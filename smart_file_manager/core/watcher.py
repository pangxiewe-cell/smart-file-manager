"""
文件监控系统
基于 watchdog，监控指定目录的文件创建/修改/移动事件，
通过防抖机制（file stable wait）避免重复触发，
稳定后调用内容提取 + LLM 标注流水线。
"""
import os
import time
import asyncio
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

import config
from core.db import get_conn, upsert_file, check_cache, upsert_annotation
from core.extractor import extract_text, compute_content_hash
from core.llm_engine import annotate_file


# 扫描黑名单目录
SCAN_BLACKLIST = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".trash", "$recycle.bin", "system volume information",
    ".ssh", ".gnupg", "appdata",
}


class _DebouncedHandler(FileSystemEventHandler):
    """防抖事件处理器：文件稳定后再触发处理"""

    def __init__(self, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self._pending: dict[str, float] = {}
        self._loop = loop

    # -- 事件回调 -----------------------------------------------------------

    def on_created(self, event):
        if not event.is_directory:
            self._schedule(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._schedule(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._pending.pop(event.src_path, None)
            self._schedule(event.dest_path)

    # -- 内部方法 -----------------------------------------------------------

    def _schedule(self, path: str):
        """将文件路径加入待处理队列（去重 + 过滤）"""
        ext = Path(path).suffix.lower()
        if ext not in config.SUPPORTED_EXTS:
            return
        parts = {p.lower() for p in Path(path).parts}
        if parts & SCAN_BLACKLIST:
            return
        self._pending[path] = time.monotonic()
        # 延迟 2 秒后检查文件是否稳定
        self._loop.call_soon_threadsafe(
            asyncio.ensure_future, self._fire_after_stable(path)
        )

    async def _fire_after_stable(self, path: str):
        await asyncio.sleep(config.FILE_STABLE_WAIT)
        last = self._pending.get(path, 0)
        if time.monotonic() - last < config.FILE_STABLE_WAIT - 0.1:
            return  # 文件仍在变化，跳过
        self._pending.pop(path, None)
        await _process_file_pipeline(path)


async def _process_file_pipeline(path: str):
    """完整处理流水线：提取 → 哈希 → LLM 标注 → 入库"""
    if not os.path.exists(path):
        return

    print(f"[Pipeline] 处理文件：{Path(path).name}")

    # 1. 入库文件基础信息
    with get_conn() as conn:
        file_id = upsert_file(conn, path)
    if file_id is None:
        return

    # 2. 提取文本内容
    text = extract_text(path)

    # 3. 计算内容哈希
    content_hash = compute_content_hash(path, text)

    # 4. 调用 LLM 标注（带缓存）
    with get_conn() as conn:
        cached = check_cache(conn, content_hash)

    if cached:
        print(f"[Pipeline] 缓存命中，跳过 LLM：{Path(path).name}")
        result = cached
    else:
        ext = Path(path).suffix.lower().lstrip(".")
        file_type = ext.upper() or "UNKNOWN"
        st = os.stat(path)
        result = await annotate_file(
            file_name=Path(path).name,
            full_path=path,
            size_bytes=st.st_size,
            file_type=file_type,
            extracted_text=text,
            content_hash=content_hash,
        )

    # 5. 写入标注结果
    if result:
        with get_conn() as conn:
            upsert_annotation(conn, file_id, result)
        print(f"[Pipeline] 标注完成：{Path(path).name} → {result.get('remark', '')}")


# ===== 公共接口 =========================================================

def start_watcher(loop: asyncio.AbstractEventLoop) -> Observer:
    """启动文件监控，返回 Observer（调用者需负责 observer.stop()）"""
    observer = Observer()
    handler = _DebouncedHandler(loop)

    watch_dirs = [str(Path(d).expanduser()) for d in config.WATCH_DIRS]
    for d in watch_dirs:
        if os.path.isdir(d):
            observer.schedule(handler, d, recursive=True)
            print(f"[Watcher] 监控目录：{d}")
        else:
            print(f"[Watcher] 警告：目录不存在，已跳过：{d}")

    observer.start()
    return observer
