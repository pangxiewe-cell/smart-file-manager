"""
空间清理建议引擎
第一层：规则筛选（> 100MB 且 30 天未访问，排除黑名单目录）
第二层：LLM 批量重排序，给出每条的清理建议
"""
import os
import time
import json
import asyncio
from pathlib import Path

import config
from core.db import get_conn, file_path_by_id
from core.llm_engine import _get_client


# 扫描黑名单（必须跳过，避免扫 node_modules 等巨型目录）
SCAN_BLACKLIST = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".trash", "$recycle.bin", "system volume information",
    ".ssh", ".gnupg", "appdata", "library", "application support",
}


# ===== 公共接口 =============================================================

async def generate_cleanup_report() -> list[dict]:
    """生成清理报告：规则筛选 + LLM 批量重排序"""
    # 第一层：规则筛选
    candidates = _rule_filter()

    if not candidates:
        return []

    # 查询已有 LLM 备注
    with get_conn() as conn:
        for c in candidates:
            row = conn.execute("""
                SELECT a.remark, a.cleanup_score
                FROM files f JOIN annotations a ON a.file_id = f.file_id
                WHERE f.full_path = ?
                ORDER BY a.analyzed_at DESC LIMIT 1
            """, (c["path"],)).fetchone()
            if row:
                c["remark"]       = row["remark"]
                c["cleanup_score"] = row["cleanup_score"]

    # 第二层：LLM 批量重排序（每批 20 个）
    results = []
    for i in range(0, len(candidates), 20):
        batch  = candidates[i:i+20]
        ranked = await _llm_rank_batch(batch)
        results.extend(ranked)

    # 按释放空间降序
    results.sort(key=lambda x: x.get("size_mb", 0), reverse=True)
    return results


# ===== 内部方法 =============================================================

def _rule_filter() -> list[dict]:
    """递归扫描监控目录，筛选 > 100MB 且 30 天未访问的文件"""
    candidates = []
    now = time.time()
    THIRTY_DAYS = 30 * 86400
    watch_dirs = [str(Path(d).expanduser()) for d in config.WATCH_DIRS]

    for root in watch_dirs:
        if not os.path.isdir(root):
            continue
        for entry in _safe_scandir(root):
            try:
                st = entry.stat()
                if (st.st_size > 100 * 1024 * 1024
                        and (now - st.st_atime) > THIRTY_DAYS):
                    candidates.append({
                        "path":      entry.path,
                        "name":      entry.name,
                        "size_mb":   round(st.st_size / 1024 / 1024, 1),
                        "days_ago":  int((now - st.st_atime) / 86400),
                        "remark":     None,
                        "cleanup_score": None,
                    })
            except (PermissionError, OSError):
                continue
    return candidates


def _safe_scandir(root: str):
    """递归扫描，跳过黑名单目录"""
    try:
        with os.scandir(root) as it:
            for entry in it:
                if entry.name.startswith("."):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in SCAN_BLACKLIST:
                        yield from _safe_scandir(entry.path)
                elif entry.is_file():
                    yield entry
    except (PermissionError, OSError):
        pass


async def _llm_rank_batch(batch: list[dict]) -> list[dict]:
    """用 LLM 对候选文件批量打分"""
    items_text = "\n".join(
        f"{i+1}. 文件名：{c['name']}，大小：{c['size_mb']}MB，"
        f"{c['days_ago']}天未访问"
        + (f"，备注：{c['remark']}" if c.get("remark") else "")
        for i, c in enumerate(batch)
    )
    prompt = (
        "以下是本地文件的候选清理列表，请对每项给出处理建议。\n"
        "严格返回 JSON 数组，每项包含：\n"
        '  index（原序号，整数）, action（"立即清理" / "可压缩归档" / "建议保留"）, reason（10字以内理由）\n\n'
        f"{items_text}"
    )

    try:
        client = _get_client()
        model = config.OLLAMA_MODEL if config.USE_LOCAL_LLM else config.OPENAI_MODEL
        resp = await client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            timeout=30,
        )
        raw = resp.choices[0].message.content
        data = json.loads(raw)
        # 兼容两种返回格式
        items = data if isinstance(data, list) else data.get("items", data.get("results", []))
        rank_map = {it["index"]: it for it in items if isinstance(it, dict) and "index" in it}
        for i, c in enumerate(batch):
            r = rank_map.get(i + 1, {})
            c["llm_action"] = r.get("action", "未知")
            c["llm_reason"] = r.get("reason", "")
    except Exception as e:
        print(f"[Cleaner] LLM 重排失败：{e}")
        for c in batch:
            c["llm_action"] = "未评估"
            c["llm_reason"] = ""

    return batch
