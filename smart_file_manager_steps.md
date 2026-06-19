# 智能文件管理系统 — 详细实现步骤

> 基于架构评审结果，已整合所有修正意见。按优先级 P0 → P1 → P2 顺序执行。

---

## 阶段零：项目初始化与环境搭建

### 步骤 0.1 — 创建项目结构

```
smart_file_manager/
├── core/
│   ├── __init__.py
│   ├── db.py              # 数据库操作层
│   ├── watcher.py         # 文件监控
│   ├── extractor.py       # 内容提取
│   ├── llm_engine.py      # LLM 标注引擎
│   ├── executor.py        # 文件操作执行器
│   └── cleaner.py         # 空间清理引擎
├── chat/
│   ├── __init__.py
│   ├── tools.py           # Function Calling 工具定义
│   └── interface.py       # 对话界面（Gradio）
├── config.py              # 全局配置
├── main.py                # 入口
└── requirements.txt
```

```bash
mkdir -p smart_file_manager/{core,chat}
cd smart_file_manager
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 步骤 0.2 — 安装依赖

```txt
# requirements.txt
watchdog>=4.0.0
python-docx>=1.1.0
pypdfium2>=4.0.0
pdfminer.six>=20221105
openpyxl>=3.1.0
python-pptx>=0.6.23
pytesseract>=0.3.10
openai>=1.30.0
gradio>=4.30.0
send2trash>=1.8.3
xxhash>=3.4.1
simhash>=2.1.0
aiofiles>=23.0.0
```

```bash
pip install -r requirements.txt
```

> **注意**：OCR 需要额外安装 Tesseract 可执行程序：
> - macOS: `brew install tesseract tesseract-lang`
> - Windows: 下载 [UB-Mannheim 安装包](https://github.com/UB-Mannheim/tesseract/wiki)
> - Linux: `sudo apt install tesseract-ocr tesseract-ocr-chi-sim`

---

## 阶段一（P0）：数据持久化层

### 步骤 1.1 — 建库与建表（含修正后的设计）

```python
# core/db.py
import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path.home() / ".smart_fm" / "index.db"

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- 核心文件表（使用自增 PK，path_hash 改为 UNIQUE 索引）
CREATE TABLE IF NOT EXISTS files (
    file_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    path_hash    TEXT    NOT NULL UNIQUE,   -- SHA256(full_path)，仅做去重索引
    full_path    TEXT    NOT NULL,
    file_name    TEXT    NOT NULL,
    size_bytes   INTEGER,
    mtime        REAL,
    atime        REAL,
    ctime        REAL,
    inode_id     TEXT,                      -- 用于追踪文件移动的真正依据
    indexed_at   REAL    NOT NULL DEFAULT (unixepoch('now'))
);

-- 标注表（改为自增 PK，支持版本追踪）
CREATE TABLE IF NOT EXISTS annotations (
    annotation_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
    remark          TEXT,
    suggested_folder TEXT,
    importance_score INTEGER CHECK (importance_score BETWEEN 1 AND 10),
    cleanup_score    INTEGER CHECK (cleanup_score BETWEEN 0 AND 10),
    raw_llm_response TEXT,
    analyzed_at      REAL NOT NULL DEFAULT (unixepoch('now')),
    content_hash     TEXT                   -- xxhash 或 SimHash，用于缓存去重
);

-- 会话表
CREATE TABLE IF NOT EXISTS conversations (
    session_id    TEXT PRIMARY KEY,
    created_at    REAL NOT NULL DEFAULT (unixepoch('now')),
    updated_at    REAL NOT NULL DEFAULT (unixepoch('now')),
    user_timezone TEXT DEFAULT 'Asia/Shanghai'
);

-- 消息表
CREATE TABLE IF NOT EXISTS messages (
    msg_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL REFERENCES conversations(session_id),
    role        TEXT    NOT NULL CHECK (role IN ('user', 'assistant', 'tool')),
    content     TEXT,
    tool_calls  TEXT,                       -- JSON
    timestamp   REAL NOT NULL DEFAULT (unixepoch('now'))
);

-- 待确认任务表
CREATE TABLE IF NOT EXISTS pending_actions (
    task_id      TEXT PRIMARY KEY,          -- UUID
    file_id      INTEGER REFERENCES files(file_id),
    action_type  TEXT NOT NULL CHECK (action_type IN ('DELETE', 'MOVE')),
    destination  TEXT,
    params       TEXT,                      -- JSON
    status       TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'confirmed', 'canceled')),
    created_at   REAL NOT NULL DEFAULT (unixepoch('now')),
    confirmed_at REAL
);

-- 操作日志表
CREATE TABLE IF NOT EXISTS action_logs (
    log_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id       INTEGER REFERENCES files(file_id),
    action_type   TEXT NOT NULL,
    details       TEXT,
    executed_at   REAL NOT NULL DEFAULT (unixepoch('now')),
    undo_path     TEXT                      -- 回收站路径（可撤销时有值）
);

-- FTS5 全文搜索虚拟表
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    file_name,
    full_path,
    remark,
    content='',                             -- 非托管模式，手动维护
    tokenize='unicode61'
);
"""

# 索引
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_files_inode    ON files(inode_id);
CREATE INDEX IF NOT EXISTS idx_anno_file_id   ON annotations(file_id);
CREATE INDEX IF NOT EXISTS idx_anno_cleanup   ON annotations(cleanup_score, analyzed_at DESC);
CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_actions(status, created_at);
"""

def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        conn.executescript(INDEXES)
    print(f"[DB] 初始化完成：{DB_PATH}")
```

### 步骤 1.2 — FTS5 同步辅助函数

```python
# core/db.py（续）
def upsert_file(conn: sqlite3.Connection, info: dict) -> int:
    """插入或更新文件记录，返回 file_id"""
    cur = conn.execute("""
        INSERT INTO files (path_hash, full_path, file_name, size_bytes,
                           mtime, atime, ctime, inode_id)
        VALUES (:path_hash, :full_path, :file_name, :size_bytes,
                :mtime, :atime, :ctime, :inode_id)
        ON CONFLICT(path_hash) DO UPDATE SET
            full_path  = excluded.full_path,
            file_name  = excluded.file_name,
            size_bytes = excluded.size_bytes,
            mtime      = excluded.mtime,
            atime      = excluded.atime,
            inode_id   = excluded.inode_id
        RETURNING file_id
    """, info)
    file_id = cur.fetchone()[0]

    # 同步更新 FTS5
    conn.execute("DELETE FROM files_fts WHERE rowid = ?", (file_id,))
    conn.execute(
        "INSERT INTO files_fts(rowid, file_name, full_path) VALUES (?, ?, ?)",
        (file_id, info["file_name"], info["full_path"])
    )
    return file_id

def upsert_annotation(conn: sqlite3.Connection, file_id: int, data: dict):
    """追加一条新标注，保留历史版本"""
    conn.execute("""
        INSERT INTO annotations
            (file_id, remark, suggested_folder, importance_score,
             cleanup_score, raw_llm_response, content_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        file_id,
        data.get("remark"),
        data.get("suggested_path"),
        data.get("importance_scale"),
        data.get("cleanup_score"),
        data.get("_raw"),
        data.get("content_hash"),
    ))

def search_files_fts(conn: sqlite3.Connection, query: str, limit: int = 20):
    """全文搜索，同时匹配文件名、路径和 LLM 备注"""
    return conn.execute("""
        SELECT f.file_id, f.full_path, f.file_name, f.size_bytes,
               a.remark, a.importance_score,
               rank
        FROM files_fts
        JOIN files f ON files_fts.rowid = f.file_id
        LEFT JOIN annotations a ON a.file_id = f.file_id
            AND a.annotation_id = (
                SELECT MAX(annotation_id) FROM annotations WHERE file_id = f.file_id
            )
        WHERE files_fts MATCH ?
        ORDER BY rank
        LIMIT ?
    """, (query, limit)).fetchall()
```

---

## 阶段二（P0）：文件监控与内容提取

### 步骤 2.1 — 文件监控（防抖去重，无需 Redis）

```python
# core/watcher.py
import asyncio
import hashlib
import os
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# 需要跳过的目录黑名单
SCAN_BLACKLIST = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".Trash", "$Recycle.Bin", "System Volume Information",
    ".ssh", ".gnupg", "AppData",
}

# 支持的文件扩展名（MVP 阶段）
SUPPORTED_EXTS = {
    ".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml",
    ".docx", ".pdf", ".xlsx", ".pptx", ".csv",
}

class _DebouncedHandler(FileSystemEventHandler):
    def __init__(self, callback, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self._pending: dict[str, float] = {}
        self._callback = callback
        self._loop = loop

    def on_created(self, event):
        if not event.is_directory:
            self._schedule(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._schedule(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            # 移动事件：注销旧路径，登记新路径
            self._pending.pop(event.src_path, None)
            self._schedule(event.dest_path)

    def _schedule(self, path: str):
        ext = Path(path).suffix.lower()
        if ext not in SUPPORTED_EXTS:
            return
        # 检查是否在黑名单目录下
        parts = set(Path(path).parts)
        if parts & SCAN_BLACKLIST:
            return
        self._pending[path] = time.monotonic()
        # 2 秒后触发，若期间再次变化则重置
        self._loop.call_soon_threadsafe(
            asyncio.ensure_future,
            self._fire_after_stable(path)
        )

    async def _fire_after_stable(self, path: str):
        await asyncio.sleep(2.0)
        last = self._pending.get(path, 0)
        if time.monotonic() - last < 1.9:
            return  # 仍在变化
        self._pending.pop(path, None)
        await self._callback(path)


def start_watcher(watch_dirs: list[str], callback, loop: asyncio.AbstractEventLoop):
    observer = Observer()
    handler = _DebouncedHandler(callback, loop)
    for d in watch_dirs:
        observer.schedule(handler, d, recursive=True)
    observer.start()
    print(f"[Watcher] 监控目录：{watch_dirs}")
    return observer
```

### 步骤 2.2 — 内容提取器（不依赖 Java/tika）

```python
# core/extractor.py
import io
from pathlib import Path

MAX_CHARS = 3000  # 传给 LLM 的最大字符数

def extract_text(path: str) -> str:
    """根据文件类型提取文本，失败时返回空字符串"""
    p = Path(path)
    ext = p.suffix.lower()
    try:
        if ext in {".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".csv"}:
            return _read_plain(p)
        elif ext == ".pdf":
            return _read_pdf(p)
        elif ext == ".docx":
            return _read_docx(p)
        elif ext == ".xlsx":
            return _read_xlsx(p)
        elif ext == ".pptx":
            return _read_pptx(p)
        elif ext in {".png", ".jpg", ".jpeg", ".bmp", ".tiff"}:
            return _read_image_ocr(p)
    except Exception as e:
        print(f"[Extractor] 提取失败 {path}: {e}")
    return ""

def _read_plain(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")[:MAX_CHARS]

def _read_pdf(p: Path) -> str:
    from pdfminer.high_level import extract_text as pdf_extract
    text = pdf_extract(str(p))
    return (text or "")[:MAX_CHARS]

def _read_docx(p: Path) -> str:
    from docx import Document
    doc = Document(str(p))
    text = "\n".join(para.text for para in doc.paragraphs)
    return text[:MAX_CHARS]

def _read_xlsx(p: Path) -> str:
    from openpyxl import load_workbook
    wb = load_workbook(str(p), read_only=True, data_only=True)
    lines = []
    for ws in wb.worksheets[:3]:  # 最多读前 3 个 sheet
        for row in ws.iter_rows(max_row=50, values_only=True):
            lines.append(" ".join(str(c) for c in row if c is not None))
    return "\n".join(lines)[:MAX_CHARS]

def _read_pptx(p: Path) -> str:
    from pptx import Presentation
    prs = Presentation(str(p))
    texts = []
    for slide in prs.slides[:10]:
        for shape in slide.shapes:
            if shape.has_text_frame:
                texts.append(shape.text_frame.text)
    return "\n".join(texts)[:MAX_CHARS]

def _read_image_ocr(p: Path) -> str:
    """OCR 提取，仅当图片较小时执行（避免耗时）"""
    import pytesseract
    from PIL import Image
    img = Image.open(str(p))
    if img.width * img.height > 4_000_000:  # 超过 400 万像素跳过
        return ""
    return pytesseract.image_to_string(img, lang="chi_sim+eng")[:MAX_CHARS]
```

### 步骤 2.3 — 内容哈希（文本用 SimHash，其他用 xxhash）

```python
# core/extractor.py（续）
import xxhash
from simhash import Simhash

def compute_content_hash(path: str, extracted_text: str) -> str:
    ext = Path(path).suffix.lower()
    text_exts = {".txt", ".md", ".py", ".js", ".ts", ".docx", ".pdf"}
    if ext in text_exts and len(extracted_text) > 100:
        # 文本类：SimHash（可检测近重复内容）
        return f"sh:{Simhash(extracted_text).value}"
    else:
        # 二进制类：xxhash（速度快）
        with open(path, "rb") as f:
            data = f.read(1 * 1024 * 1024)  # 只读前 1MB
        return f"xx:{xxhash.xxh64(data).hexdigest()}"
```

---

## 阶段三（P0）：LLM 标注引擎

### 步骤 3.1 — Prompt 模板与结构化输出

```python
# core/llm_engine.py
import json
import os
from openai import AsyncOpenAI

client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# 可用文件夹白名单（路径建议只能在这些类别下）
FOLDER_WHITELIST = [
    "Documents/Work", "Documents/Study", "Documents/Personal",
    "Downloads/Pending", "Desktop/Active",
    "Projects/Code", "Projects/Design",
    "Archive/2024", "Archive/2025", "Archive/2026",
]

SYSTEM_PROMPT = """你是一个本地文件智能标注助手。
用户会给你一段文件信息，你需要返回严格的 JSON 格式，不要包含任何额外文字。

返回格式：
{
  "remark": "一句话简短说明文件内容（20字以内）",
  "suggested_path": "建议归档的相对路径（必须是提供的白名单之一，否则填 null）",
  "importance_scale": 1到10的整数（10=非常重要，1=可以删除）,
  "cleanup_score": 0到10的整数（10=应立即清理，0=必须保留）
}

可用白名单路径：
""" + "\n".join(f"- {p}" for p in FOLDER_WHITELIST)

async def annotate_file(
    file_name: str,
    full_path: str,
    size_bytes: int,
    file_type: str,
    extracted_text: str,
    content_hash: str,
    cache_check_fn=None,  # 传入缓存查询函数
) -> dict | None:
    """调用 LLM 标注文件，带缓存和重试"""

    # 缓存检查：1小时内相同内容直接复用
    if cache_check_fn:
        cached = cache_check_fn(content_hash)
        if cached:
            print(f"[LLM] 缓存命中：{file_name}")
            return cached

    user_msg = f"""文件名：{file_name}
路径：{full_path}
类型：{file_type}
大小：{size_bytes / 1024:.1f} KB
内容摘要：
{extracted_text[:2000] if extracted_text else "（无法提取文本内容）"}"""

    for attempt in range(3):  # 最多重试 3 次
        try:
            resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_msg},
                ],
                temperature=0.2,
                timeout=20,
            )
            raw = resp.choices[0].message.content
            result = json.loads(raw)
            result["_raw"] = raw
            result["content_hash"] = content_hash

            # 路径白名单校验
            sp = result.get("suggested_path")
            if sp and sp not in FOLDER_WHITELIST:
                # 模糊匹配最近的白名单路径
                matched = _fuzzy_match_path(sp, FOLDER_WHITELIST)
                result["suggested_path"] = matched  # 若无合理匹配则为 None

            return result

        except json.JSONDecodeError:
            print(f"[LLM] JSON 解析失败（第{attempt+1}次），重试...")
            continue
        except Exception as e:
            print(f"[LLM] API 错误：{e}")
            if attempt == 2:
                return None  # fallback：只保留基础记录，不写标注

    return None

def _fuzzy_match_path(candidate: str, whitelist: list[str]) -> str | None:
    """模糊匹配：找 whitelist 中包含 candidate 关键词最多的路径"""
    candidate_parts = set(candidate.lower().replace("/", " ").split())
    scores = []
    for wp in whitelist:
        wp_parts = set(wp.lower().replace("/", " ").split())
        score = len(candidate_parts & wp_parts)
        scores.append((score, wp))
    best_score, best_path = max(scores, key=lambda x: x[0])
    return best_path if best_score > 0 else None
```

### 步骤 3.2 — 完整的写入触发流程

```python
# core/watcher.py（写入触发器，整合提取+标注+入库）
import asyncio
import hashlib
import os
import stat
from pathlib import Path
from core.db import get_conn, upsert_file, upsert_annotation, search_files_fts
from core.extractor import extract_text, compute_content_hash
from core.llm_engine import annotate_file

def _path_hash(full_path: str) -> str:
    return hashlib.sha256(full_path.encode()).hexdigest()

def _get_inode(path: str) -> str:
    try:
        st = os.stat(path)
        return f"{st.st_dev}:{st.st_ino}"
    except Exception:
        return ""

async def process_file(path: str):
    """文件稳定后的完整处理流程"""
    p = Path(path)
    if not p.exists():
        return

    print(f"[Pipeline] 处理文件：{p.name}")

    # 1. 提取基础元数据
    try:
        st = p.stat()
    except Exception:
        return

    file_info = {
        "path_hash":  _path_hash(path),
        "full_path":  str(p.resolve()),
        "file_name":  p.name,
        "size_bytes": st.st_size,
        "mtime":      st.st_mtime,
        "atime":      st.st_atime,
        "ctime":      st.st_ctime,
        "inode_id":   _get_inode(path),
    }

    # 2. 提取文本内容
    text = extract_text(path)
    content_hash = compute_content_hash(path, text)

    # 3. 入库（先写文件记录，确保 file_id 存在）
    with get_conn() as conn:
        file_id = upsert_file(conn, file_info)

    # 4. 异步调用 LLM（不阻塞监控循环）
    result = await annotate_file(
        file_name   = p.name,
        full_path   = str(p.resolve()),
        size_bytes  = st.st_size,
        file_type   = p.suffix.lstrip(".").upper() or "UNKNOWN",
        extracted_text = text,
        content_hash   = content_hash,
        cache_check_fn = lambda h: _check_cache(h),
    )

    # 5. 写入标注
    if result:
        with get_conn() as conn:
            upsert_annotation(conn, file_id, result)
        print(f"[Pipeline] 标注完成：{p.name} → {result.get('remark')}")

def _check_cache(content_hash: str) -> dict | None:
    """查询1小时内的相同内容标注"""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT remark, suggested_folder, importance_score,
                   cleanup_score, raw_llm_response, content_hash
            FROM annotations
            WHERE content_hash = ?
              AND analyzed_at > unixepoch('now') - 3600
            ORDER BY analyzed_at DESC
            LIMIT 1
        """, (content_hash,)).fetchone()
    if row:
        return {
            "remark":          row["remark"],
            "suggested_path":  row["suggested_folder"],
            "importance_scale": row["importance_score"],
            "cleanup_score":   row["cleanup_score"],
            "_raw":            row["raw_llm_response"],
            "content_hash":    row["content_hash"],
        }
    return None
```

---

## 阶段四（P0）：对话界面与 Function Calling

### 步骤 4.1 — 定义 5 个核心工具

```python
# chat/tools.py
import os
import uuid
import json
from pathlib import Path
from core.db import get_conn, search_files_fts

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "根据关键词搜索文件，同时检索文件名、路径和 AI 生成的备注",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_details",
            "description": "获取指定文件的详细信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件绝对路径"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_file",
            "description": "用系统默认程序打开文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件绝对路径"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_file",
            "description": "将文件移动到新路径（会创建待确认任务，需用户确认后才真正执行）",
            "parameters": {
                "type": "object",
                "properties": {
                    "src":  {"type": "string", "description": "源文件路径"},
                    "dst":  {"type": "string", "description": "目标路径"},
                },
                "required": ["src", "dst"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "将文件移入回收站（会创建待确认任务，需用户确认后才真正执行）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件绝对路径"}
                },
                "required": ["path"],
            },
        },
    },
]


def execute_tool(tool_name: str, args: dict) -> str:
    """执行工具调用，返回 JSON 字符串"""
    if tool_name == "search_files":
        return _search_files(args["query"])
    elif tool_name == "get_file_details":
        return _get_file_details(args["path"])
    elif tool_name == "open_file":
        return _open_file(args["path"])
    elif tool_name == "move_file":
        return _create_pending_action("MOVE", args["src"], args.get("dst"))
    elif tool_name == "delete_file":
        return _create_pending_action("DELETE", args["path"])
    return json.dumps({"error": "未知工具"})


def _search_files(query: str) -> str:
    with get_conn() as conn:
        rows = search_files_fts(conn, query, limit=10)
    results = [
        {
            "path":      row["full_path"],
            "name":      row["file_name"],
            "size_kb":   round((row["size_bytes"] or 0) / 1024, 1),
            "remark":    row["remark"],
            "importance": row["importance_score"],
        }
        for row in rows
    ]
    return json.dumps({"results": results, "count": len(results)}, ensure_ascii=False)


def _get_file_details(path: str) -> str:
    with get_conn() as conn:
        row = conn.execute("""
            SELECT f.*, a.remark, a.suggested_folder,
                   a.importance_score, a.cleanup_score
            FROM files f
            LEFT JOIN annotations a ON a.file_id = f.file_id
                AND a.annotation_id = (
                    SELECT MAX(annotation_id) FROM annotations
                    WHERE file_id = f.file_id
                )
            WHERE f.full_path = ?
        """, (path,)).fetchone()
    if not row:
        return json.dumps({"error": "文件不在索引中"})
    return json.dumps(dict(row), ensure_ascii=False, default=str)


def _open_file(path: str) -> str:
    import sys, subprocess
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])
        # 记录操作日志
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO action_logs (action_type, details, executed_at) VALUES (?, ?, unixepoch('now'))",
                ("OPEN", path)
            )
        return json.dumps({"status": "ok", "message": f"已打开：{Path(path).name}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _create_pending_action(action_type: str, src: str, dst: str = None) -> str:
    """
    重要：写操作不直接执行，创建 pending 任务返回 task_id
    前端收到 task_id 后展示确认弹窗，用户确认后再调用 /confirm/{task_id}
    """
    task_id = str(uuid.uuid4())
    with get_conn() as conn:
        row = conn.execute(
            "SELECT file_id FROM files WHERE full_path = ?", (src,)
        ).fetchone()
        file_id = row["file_id"] if row else None
        conn.execute("""
            INSERT INTO pending_actions (task_id, file_id, action_type, destination, params)
            VALUES (?, ?, ?, ?, ?)
        """, (task_id, file_id, action_type, dst,
              json.dumps({"src": src, "dst": dst})))
    return json.dumps({
        "status":    "pending_confirm",
        "task_id":   task_id,
        "action":    action_type,
        "src":       src,
        "dst":       dst,
        "message":   "已创建待确认任务，请用户确认后执行",
    }, ensure_ascii=False)
```

### 步骤 4.2 — 对话主循环（支持指代消解，最近 10 条上下文）

```python
# chat/interface.py
import json
import gradio as gr
from openai import OpenAI
from chat.tools import TOOLS, execute_tool

client = OpenAI()

SYSTEM_MSG = {
    "role": "system",
    "content": (
        "你是一个本地文件管理助手。帮助用户搜索、查看、打开、整理文件。"
        "回答要简洁自然，对于移动/删除操作必须先创建待确认任务，"
        "并明确告知用户'需要您点击确认后才会执行'。"
        "保留最近对话上下文以支持指代消解（如'就是那个''第二个'等）。"
    )
}

def chat(user_input: str, history: list) -> tuple[str, list]:
    # 构建消息列表（最近 10 轮 = 20 条消息）
    messages = [SYSTEM_MSG]
    for h in history[-10:]:
        messages.append({"role": "user",      "content": h[0]})
        messages.append({"role": "assistant", "content": h[1]})
    messages.append({"role": "user", "content": user_input})

    # 多轮 Tool 调用循环
    while True:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )
        msg = resp.choices[0].message

        if msg.tool_calls:
            messages.append(msg)
            for tc in msg.tool_calls:
                args   = json.loads(tc.function.arguments)
                result = execute_tool(tc.function.name, args)
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tc.id,
                    "content":      result,
                })
        else:
            reply = msg.content or ""
            history.append((user_input, reply))
            return reply, history

def launch():
    with gr.Blocks(title="智能文件管理助手") as demo:
        gr.Markdown("## 智能文件管理助手\n> 支持文件搜索、打开、整理和清理建议")
        chatbot  = gr.Chatbot(height=500)
        inp      = gr.Textbox(placeholder="说点什么…（如：帮我找上周的报告）", show_label=False)
        state    = gr.State([])
        inp.submit(chat, [inp, state], [chatbot, state])
    demo.launch(server_port=7860)
```

---

## 阶段五（P1）：文件操作执行器（安全沙箱）

### 步骤 5.1 — 确认执行器

```python
# core/executor.py
import json
import shutil
from pathlib import Path
import send2trash
from core.db import get_conn

def confirm_action(task_id: str) -> dict:
    """用户确认后，真正执行写操作"""
    with get_conn() as conn:
        task = conn.execute(
            "SELECT * FROM pending_actions WHERE task_id = ? AND status = 'pending'",
            (task_id,)
        ).fetchone()

        if not task:
            return {"status": "error", "message": "任务不存在或已过期"}

        params = json.loads(task["params"] or "{}")
        src    = params.get("src")
        dst    = params.get("dst")

        try:
            if task["action_type"] == "DELETE":
                send2trash.send2trash(src)  # 移入回收站，不直接删除
                undo_path = "（已移入回收站）"
                conn.execute(
                    "INSERT INTO action_logs (file_id, action_type, details, undo_path) VALUES (?,?,?,?)",
                    (task["file_id"], "DELETE", src, undo_path)
                )

            elif task["action_type"] == "MOVE":
                dst_path = Path(dst)
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(src, dst)
                conn.execute(
                    "INSERT INTO action_logs (file_id, action_type, details, undo_path) VALUES (?,?,?,?)",
                    (task["file_id"], "MOVE", json.dumps({"from": src, "to": dst}), src)
                )
                # 更新 FILES 表路径
                new_hash = __import__("hashlib").sha256(dst.encode()).hexdigest()
                conn.execute(
                    "UPDATE files SET full_path=?, file_name=?, path_hash=? WHERE file_id=?",
                    (dst, Path(dst).name, new_hash, task["file_id"])
                )

            # 标记任务为已确认
            conn.execute(
                "UPDATE pending_actions SET status='confirmed', confirmed_at=unixepoch('now') WHERE task_id=?",
                (task_id,)
            )
            return {"status": "ok", "message": f"{task['action_type']} 执行成功"}

        except Exception as e:
            return {"status": "error", "message": str(e)}


def cancel_action(task_id: str) -> dict:
    with get_conn() as conn:
        conn.execute(
            "UPDATE pending_actions SET status='canceled' WHERE task_id=?",
            (task_id,)
        )
    return {"status": "ok", "message": "操作已取消"}


def cleanup_expired_tasks():
    """清理超过 30 分钟未确认的任务"""
    with get_conn() as conn:
        conn.execute("""
            UPDATE pending_actions SET status='canceled'
            WHERE status='pending'
              AND created_at < unixepoch('now') - 1800
        """)
```

---

## 阶段六（P1）：空间清理引擎

### 步骤 6.1 — 分级扫描 + LLM 重排序

```python
# core/cleaner.py
import os
import asyncio
import json
from pathlib import Path
from core.db import get_conn
from core.llm_engine import client

# 扫描黑名单（必须跳过）
SCAN_BLACKLIST = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".Trash", "$Recycle.Bin", "System Volume Information",
    ".ssh", ".gnupg",
}

async def generate_cleanup_report(scan_roots: list[str]) -> list[dict]:
    """生成清理报告：规则筛选 + LLM 批量重排"""

    # 第一层：规则筛选（> 100MB 且 30 天未访问）
    candidates = []
    now = __import__("time").time()
    THIRTY_DAYS = 30 * 86400

    for root in scan_roots:
        for entry in _safe_scandir(root):
            try:
                st = entry.stat()
                if st.st_size > 100 * 1024 * 1024 and (now - st.st_atime) > THIRTY_DAYS:
                    candidates.append({
                        "path":     entry.path,
                        "name":     entry.name,
                        "size_mb":  round(st.st_size / 1024 / 1024, 1),
                        "days_ago": int((now - st.st_atime) / 86400),
                    })
            except (PermissionError, OSError):
                continue

    # 查询已有的 LLM 备注
    with get_conn() as conn:
        for c in candidates:
            row = conn.execute("""
                SELECT a.remark, a.cleanup_score
                FROM files f JOIN annotations a ON a.file_id = f.file_id
                WHERE f.full_path = ?
                ORDER BY a.analyzed_at DESC LIMIT 1
            """, (c["path"],)).fetchone()
            if row:
                c["remark"]        = row["remark"]
                c["cleanup_score"] = row["cleanup_score"]

    # 第二层：LLM 批量重排序（每批 20 个）
    results = []
    for i in range(0, len(candidates), 20):
        batch  = candidates[i:i+20]
        ranked = await _llm_rank_batch(batch)
        results.extend(ranked)

    # 按释放空间降序排列
    results.sort(key=lambda x: x.get("size_mb", 0), reverse=True)
    return results


def _safe_scandir(root: str):
    """递归扫描，跳过黑名单目录"""
    try:
        with os.scandir(root) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in SCAN_BLACKLIST and not entry.name.startswith("."):
                        yield from _safe_scandir(entry.path)
                elif entry.is_file():
                    yield entry
    except PermissionError:
        pass


async def _llm_rank_batch(batch: list[dict]) -> list[dict]:
    items_text = "\n".join(
        f"{i+1}. 文件名：{c['name']}，大小：{c['size_mb']}MB，"
        f"{c['days_ago']}天未访问，备注：{c.get('remark','无')}"
        for i, c in enumerate(batch)
    )
    prompt = f"""以下是本地文件的候选清理列表，请对每项给出建议。
返回严格的 JSON 数组，每项包含：index（原序号）, action（"立即清理"/"可压缩归档"/"建议保留"）, reason（10字以内）

{items_text}"""

    try:
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        rankings = json.loads(resp.choices[0].message.content)
        rank_map = {r["index"]: r for r in rankings.get("items", rankings if isinstance(rankings, list) else [])}
        for i, c in enumerate(batch):
            r = rank_map.get(i + 1, {})
            c["llm_action"] = r.get("action", "未知")
            c["llm_reason"] = r.get("reason", "")
    except Exception as e:
        print(f"[Cleaner] LLM 重排失败：{e}")

    return batch
```

---

## 阶段七（P2）：扩展属性缓存（可选）

> **定位**：扩展属性是 SQLite 的冗余备份，不是主存储。
> ADS 在 ZIP/OneDrive/FAT32 场景会静默丢失，这是已知限制。

```python
# core/xattr_cache.py
import sys
import json

def write_remark_xattr(path: str, remark: str):
    """将 LLM 备注写入扩展属性（best-effort，失败不报错）"""
    try:
        data = json.dumps({"remark": remark}, ensure_ascii=False).encode()
        if sys.platform in ("linux", "darwin"):
            import xattr
            xattr.setxattr(path, "user.llm.remark", data)
        elif sys.platform == "win32":
            # ADS: 写入 filename:llm_remark 备用数据流
            ads_path = path + ":llm_remark"
            with open(ads_path, "wb") as f:
                f.write(data)
    except Exception:
        pass  # 静默失败，SQLite 是主存储

def read_remark_xattr(path: str) -> str | None:
    try:
        if sys.platform in ("linux", "darwin"):
            import xattr
            data = xattr.getxattr(path, "user.llm.remark")
            return json.loads(data).get("remark")
        elif sys.platform == "win32":
            ads_path = path + ":llm_remark"
            with open(ads_path, "rb") as f:
                return json.loads(f.read()).get("remark")
    except Exception:
        return None
```

---

## 阶段八：入口与整合

```python
# main.py
import asyncio
import os
from pathlib import Path
from core.db import init_db
from core.watcher import start_watcher, process_file
from chat.interface import launch

WATCH_DIRS = [
    str(Path.home() / "Desktop"),
    str(Path.home() / "Documents"),
    str(Path.home() / "Downloads"),
]

async def main():
    # 初始化数据库
    init_db()

    # 启动文件监控
    loop = asyncio.get_event_loop()
    observer = start_watcher(WATCH_DIRS, process_file, loop)

    print("[Main] 系统启动完成。访问 http://localhost:7860 打开对话界面")

    # 启动 Gradio（在主线程）
    launch()

    # 等待监控线程
    try:
        observer.join()
    except KeyboardInterrupt:
        observer.stop()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 快速验证清单

在开始编码前，用以下命令验证关键依赖可用：

```bash
# 验证 Python 依赖
python -c "import watchdog, openai, gradio, send2trash, xxhash; print('OK')"

# 验证 OCR（可选）
python -c "import pytesseract; print(pytesseract.get_tesseract_version())"

# 验证 SQLite FTS5 支持
python -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute('CREATE VIRTUAL TABLE t USING fts5(x)'); print('FTS5 OK')"

# 启动系统
python main.py
```

---

## 修正清单汇总（相对原方案）

| 原方案 | 修正后 | 原因 |
|--------|--------|------|
| `path_hash` 做 PK | 改为 `file_id INTEGER AUTOINCREMENT` + `path_hash UNIQUE` | 支持路径更新，避免移动时记录丢失 |
| `ANNOTATIONS.path_hash PK` | 改为 `annotation_id AUTOINCREMENT` | 支持版本追踪 |
| Redis 去重队列 | `asyncio` + 内存字典防抖 | 消除进程依赖，桌面场景已够用 |
| tika-python | 按类型分用 `python-docx / pdfminer / openpyxl / python-pptx` | 消除 Java 依赖 |
| 全用 SimHash | 文本用 SimHash，其他用 xxhash | SimHash 不适合二进制文件 |
| ADS 作主存储 | ADS 降为 best-effort 备份 | ZIP/OneDrive/FAT32 会静默丢失 |
| FTS5 视为普通索引 | 改为独立虚拟表 + 手动同步 | FTS5 是虚拟表，不是索引 |
| Tool 层直接执行写操作 | 返回 `task_id`，前端二次确认后执行 | 避免 LLM 误判为"已完成" |
