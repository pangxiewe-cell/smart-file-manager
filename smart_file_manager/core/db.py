"""
SQLite 数据库操作层
负责：建表、文件记录增删改查、标注记录、FTS5 全文搜索
"""
import sqlite3
import hashlib
import os
from pathlib import Path

# 延迟导入 config，避免循环导入
def _cfg():
    import config
    return config

def _db_path() -> Path:
    import config
    p = Path(config.DB_DIR).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p / "index.db"

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA encoding='UTF-8';

-- 核心文件表
CREATE TABLE IF NOT EXISTS files (
    file_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    path_hash    TEXT    NOT NULL UNIQUE,
    full_path    TEXT    NOT NULL,
    file_name    TEXT    NOT NULL,
    size_bytes   INTEGER,
    mtime        REAL,
    atime        REAL,
    ctime        REAL,
    inode_id     TEXT,
    indexed_at   REAL    NOT NULL DEFAULT (unixepoch('now'))
);

-- 标注表（支持版本追踪）
CREATE TABLE IF NOT EXISTS annotations (
    annotation_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
    remark          TEXT,
    suggested_folder TEXT,
    importance_score INTEGER CHECK (importance_score BETWEEN 1 AND 10),
    cleanup_score    INTEGER CHECK (cleanup_score BETWEEN 0 AND 10),
    raw_llm_response TEXT,
    analyzed_at      REAL NOT NULL DEFAULT (unixepoch('now')),
    content_hash     TEXT
);

-- 会话表
CREATE TABLE IF NOT EXISTS conversations (
    session_id   TEXT PRIMARY KEY,
    created_at   REAL NOT NULL DEFAULT (unixepoch('now')),
    updated_at   REAL NOT NULL DEFAULT (unixepoch('now')),
    user_timezone TEXT DEFAULT 'Asia/Shanghai'
);

-- 消息表
CREATE TABLE IF NOT EXISTS messages (
    msg_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT    NOT NULL REFERENCES conversations(session_id),
    role       TEXT    NOT NULL CHECK (role IN ('user', 'assistant', 'tool')),
    content    TEXT,
    tool_calls TEXT,
    timestamp  REAL NOT NULL DEFAULT (unixepoch('now'))
);

-- 待确认任务表
CREATE TABLE IF NOT EXISTS pending_actions (
    task_id    TEXT PRIMARY KEY,
    file_id    INTEGER REFERENCES files(file_id),
    action_type TEXT NOT NULL CHECK (action_type IN ('DELETE', 'MOVE')),
    destination TEXT,
    params      TEXT,
    status      TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'confirmed', 'canceled')),
    created_at  REAL NOT NULL DEFAULT (unixepoch('now')),
    confirmed_at REAL
);

-- 操作日志表
CREATE TABLE IF NOT EXISTS action_logs (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id     INTEGER REFERENCES files(file_id),
    action_type TEXT NOT NULL,
    details     TEXT,
    executed_at REAL NOT NULL DEFAULT (unixepoch('now')),
    undo_path   TEXT
);

-- FTS5 全文搜索虚拟表（非托管模式）
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    file_name,
    full_path,
    remark,
    content='',
    tokenize='unicode61'
);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_files_inode    ON files(inode_id);
CREATE INDEX IF NOT EXISTS idx_anno_file_id   ON annotations(file_id);
CREATE INDEX IF NOT EXISTS idx_anno_cleanup   ON annotations(cleanup_score, analyzed_at DESC);
CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_actions(status, created_at);
"""


def get_conn() -> sqlite3.Connection:
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        conn.executescript(INDEXES)
    print(f"[DB] 数据库初始化完成：{_db_path()}")


def _path_hash(full_path: str) -> str:
    return hashlib.sha256(full_path.encode("utf-8")).hexdigest()


def _get_inode(path: str) -> str:
    try:
        st = os.stat(path)
        return f"{st.st_dev}:{st.st_ino}"
    except Exception:
        return ""


def upsert_file(conn: sqlite3.Connection, path: str) -> int | None:
    """插入或更新文件记录，返回 file_id"""
    import config
    if not os.path.exists(path):
        return None
    try:
        st = os.stat(path)
        p = Path(path).resolve()
        info = {
            "path_hash":  _path_hash(str(p)),
            "full_path":  str(p),
            "file_name":  p.name,
            "size_bytes": st.st_size,
            "mtime":      st.st_mtime,
            "atime":      st.st_atime,
            "ctime":      st.st_ctime,
            "inode_id":   _get_inode(str(p)),
        }
    except Exception:
        return None

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
    row = cur.fetchone()
    if row is None:
        # 旧 SQLite 不支持 RETURNING，降级处理
        row2 = conn.execute(
            "SELECT file_id FROM files WHERE path_hash = ?", (info["path_hash"],)
        ).fetchone()
        file_id = row2["file_id"] if row2 else None
    else:
        file_id = row["file_id"]

    if file_id:
        # 同步 FTS5
        conn.execute("DELETE FROM files_fts WHERE rowid = ?", (file_id,))
        try:
            conn.execute(
                "INSERT INTO files_fts(rowid, file_name, full_path) VALUES (?, ?, ?)",
                (file_id, info["file_name"], info["full_path"])
            )
        except Exception:
            pass
    return file_id


def upsert_annotation(conn: sqlite3.Connection, file_id: int, data: dict):
    """追加一条新标注（保留历史版本）"""
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


def get_latest_annotation(conn: sqlite3.Connection, file_id: int) -> dict | None:
    row = conn.execute("""
        SELECT * FROM annotations
        WHERE file_id = ?
        ORDER BY analyzed_at DESC LIMIT 1
    """, (file_id,)).fetchone()
    return dict(row) if row else None


def search_files_fts(conn: sqlite3.Connection, query: str, limit: int = 20) -> list:
    """FTS5 全文搜索，同时匹配文件名、路径和备注"""
    try:
        rows = conn.execute("""
            SELECT f.file_id, f.full_path, f.file_name, f.size_bytes,
                   a.remark, a.importance_score
            FROM files_fts
            JOIN files f ON files_fts.rowid = f.file_id
            LEFT JOIN annotations a ON a.annotation_id = (
                SELECT MAX(annotation_id) FROM annotations WHERE file_id = f.file_id
            )
            WHERE files_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit)).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        # FTS5 查询失败时降级为 LIKE 搜索
        like_q = f"%{query}%"
        rows = conn.execute("""
            SELECT f.file_id, f.full_path, f.file_name, f.size_bytes,
                   a.remark, a.importance_score
            FROM files f
            LEFT JOIN annotations a ON a.annotation_id = (
                SELECT MAX(annotation_id) FROM annotations WHERE file_id = f.file_id
            )
            WHERE f.file_name LIKE ? OR f.full_path LIKE ?
            LIMIT ?
        """, (like_q, like_q, limit)).fetchall()
        return [dict(r) for r in rows]


def check_cache(conn: sqlite3.Connection, content_hash: str) -> dict | None:
    """查询缓存（1小时内相同内容）"""
    import config
    rows = conn.execute("""
        SELECT remark, suggested_folder, importance_score,
               cleanup_score, raw_llm_response, content_hash
        FROM annotations
        WHERE content_hash = ?
          AND analyzed_at > unixepoch('now') - ?
        ORDER BY analyzed_at DESC LIMIT 1
    """, (content_hash, config.LLM_CACHE_SECONDS)).fetchone()
    if rows:
        return {
            "remark":           rows["remark"],
            "suggested_path":   rows["suggested_folder"],
            "importance_scale":  rows["importance_score"],
            "cleanup_score":    rows["cleanup_score"],
            "_raw":             rows["raw_llm_response"],
            "content_hash":     rows["content_hash"],
        }
    return None


def file_path_by_id(conn: sqlite3.Connection, file_id: int) -> str | None:
    row = conn.execute("SELECT full_path FROM files WHERE file_id = ?", (file_id,)).fetchone()
    return row["full_path"] if row else None


def cleanup_expired_tasks(conn: sqlite3.Connection):
    """清理超过 30 分钟未确认的任务"""
    conn.execute("""
        UPDATE pending_actions SET status='canceled'
        WHERE status='pending'
          AND created_at < unixepoch('now') - 1800
    """)
