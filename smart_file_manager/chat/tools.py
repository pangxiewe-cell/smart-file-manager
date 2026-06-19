"""
Function Calling 工具定义与执行器
定义 5 个核心工具（search_files / get_file_details / open_file / move_file / delete_file），
由 LLM 调用，返回 JSON 结果给对话界面。
"""
import json
import os
import sys
import subprocess
from pathlib import Path

import config
from core.db import get_conn, search_files_fts, file_path_by_id
from core.executor import create_pending_action


# ===== 工具定义（供 OpenAI 使用）=====
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "根据关键词搜索文件，同时检索文件名、路径和 AI 生成的备注",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_details",
            "description": "获取指定文件的详细信息（大小、路径、AI 备注等）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件绝对路径"},
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
                    "path": {"type": "string", "description": "文件绝对路径"},
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
                    "src": {"type": "string", "description": "源文件绝对路径"},
                    "dst": {"type": "string", "description": "目标绝对路径"},
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
                    "path": {"type": "string", "description": "文件绝对路径"},
                },
                "required": ["path"],
            },
        },
    },
]


# ===== 工具执行 =============================================================

def execute_tool(tool_name: str, args: dict) -> str:
    """执行工具调用，返回 JSON 字符串"""
    dispatch = {
        "search_files":     _search_files,
        "get_file_details": _get_file_details,
        "open_file":        _open_file,
        "move_file":        _move_file,
        "delete_file":      _delete_file,
    }
    handler = dispatch.get(tool_name)
    if not handler:
        return json.dumps({"error": f"未知工具：{tool_name}"}, ensure_ascii=False)
    try:
        result = handler(args)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ===== 各工具实现 ===========================================================

def _search_files(args: dict) -> dict:
    query = args.get("query", "")
    if not query:
        return {"results": [], "count": 0}
    with get_conn() as conn:
        rows = search_files_fts(conn, query, limit=10)
    return {
        "results": rows,
        "count": len(rows),
    }


def _get_file_details(args: dict) -> dict:
    path = args.get("path", "")
    if not path:
        return {"error": "路径不能为空"}
    with get_conn() as conn:
        row = conn.execute("""
            SELECT f.*, a.remark, a.suggested_folder,
                   a.importance_score, a.cleanup_score, a.analyzed_at
            FROM files f
            LEFT JOIN annotations a ON a.file_id = f.file_id
                AND a.annotation_id = (
                    SELECT MAX(annotation_id) FROM annotations WHERE file_id = f.file_id
                )
            WHERE f.full_path = ?
        """, (path,)).fetchone()
    if not row:
        return {"error": "文件不在索引中"}
    return dict(row)


def _open_file(args: dict) -> dict:
    path = args.get("path", "")
    if not path or not os.path.exists(path):
        return {"error": "文件不存在"}
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
                "INSERT INTO action_logs (action_type, details) VALUES (?, ?)",
                ("OPEN", path),
            )
        return {"status": "ok", "message": f"已打开：{Path(path).name}"}
    except Exception as e:
        return {"error": str(e)}


def _move_file(args: dict) -> dict:
    src = args.get("src", "")
    dst = args.get("dst", "")
    if not src or not dst:
        return {"error": "src 和 dst 均不能为空"}
    return create_pending_action("MOVE", src, dst)


def _delete_file(args: dict) -> dict:
    path = args.get("path", "")
    if not path:
        return {"error": "路径不能为空"}
    return create_pending_action("DELETE", path)
