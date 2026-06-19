"""
文件操作执行器（安全沙箱）
所有写操作（移动/删除）不直接执行，先创建 pending 任务，
用户确认后才真正执行。支持撤销（通过回收站）。
"""
import json
import os
import shutil
import uuid
from pathlib import Path

import config
from core.db import get_conn, file_path_by_id


# ===== 公共接口 =============================================================

def create_pending_action(action_type: str, src: str, dst: str = None) -> dict:
    """
    创建待确认任务，返回 task_id。
    前端收到 task_id 后展示确认弹窗。
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
              json.dumps({"src": src, "dst": dst}, ensure_ascii=False)))
    return {
        "status":     "pending_confirm",
        "task_id":    task_id,
        "action":     action_type,
        "src":        src,
        "dst":        dst,
        "message":    "操作已创建，等待用户确认",
    }


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
        src    = params.get("src", "")
        dst    = task["destination"]

        try:
            if task["action_type"] == "DELETE":
                result = _do_delete(conn, task, src)

            elif task["action_type"] == "MOVE":
                result = _do_move(conn, task, src, dst)

            else:
                return {"status": "error", "message": f"未知操作类型：{task['action_type']}"}

            # 标记任务为已确认
            conn.execute(
                "UPDATE pending_actions SET status='confirmed', confirmed_at=unixepoch('now') WHERE task_id=?",
                (task_id,)
            )
            return result

        except Exception as e:
            return {"status": "error", "message": str(e)}


def cancel_action(task_id: str) -> dict:
    with get_conn() as conn:
        conn.execute(
            "UPDATE pending_actions SET status='canceled' WHERE task_id=?",
            (task_id,)
        )
    return {"status": "ok", "message": "操作已取消"}


def get_pending_actions() -> list[dict]:
    """获取所有待确认任务（供前端展示）"""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT pa.*, f.full_path AS src_path
            FROM pending_actions pa
            LEFT JOIN files f ON pa.file_id = f.file_id
            WHERE pa.status = 'pending'
            ORDER BY pa.created_at DESC
        """).fetchall()
    return [dict(r) for r in rows]


# ===== 内部方法 =============================================================

def _do_delete(conn, task, src: str) -> dict:
    if not os.path.exists(src):
        return {"status": "ok", "message": "文件已不存在（可能已被删除）"}
    import send2trash
    send2trash.send2trash(src)
    undo_info = f"已移入回收站：{Path(src).name}"
    conn.execute(
        "INSERT INTO action_logs (file_id, action_type, details, undo_path) VALUES (?,?,?,?)",
        (task["file_id"], "DELETE", src, undo_info)
    )
    # 从索引中移除
    conn.execute("DELETE FROM files WHERE file_id = ?", (task["file_id"],))
    return {"status": "ok", "message": f"已移入回收站：{Path(src).name}"}


def _do_move(conn, task, src: str, dst: str) -> dict:
    if not dst:
        return {"status": "error", "message": "目标路径不能为空"}
    dst_path = Path(dst)
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    if not os.path.exists(src):
        return {"status": "error", "message": "源文件不存在"}
    shutil.move(src, str(dst_path))
    # 更新数据库路径
    import core.db as db_mod
    new_path = str(dst_path.resolve())
    with get_conn() as conn2:
        db_mod.upsert_file(conn2, new_path)
    conn.execute(
        "INSERT INTO action_logs (file_id, action_type, details, undo_path) VALUES (?,?,?,?)",
        (task["file_id"], "MOVE", json.dumps({"from": src, "to": dst}, ensure_ascii=False), src)
    )
    return {"status": "ok", "message": f"已移动到：{dst}"}
