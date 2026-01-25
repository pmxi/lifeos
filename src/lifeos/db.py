import logging
import os
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

DB_PATH = Path(os.getenv("DB_PATH", "lifeos.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS task (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'pending', -- status: 'pending' or 'done'
    due_datetime TEXT, -- RFC 3339 format
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- note: information to remember, not actionable
CREATE TABLE IF NOT EXISTS note (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- reminder: scheduled prompts that wake up the agent
CREATE TABLE IF NOT EXISTS reminder (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt TEXT NOT NULL,
    trigger_at TEXT NOT NULL,  -- RFC 3339 datetime
    status TEXT DEFAULT 'pending',  -- 'pending', 'triggered', 'cancelled'
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    log.info("Initializing database at %s", DB_PATH)
    with get_connection() as conn:
        conn.executescript(SCHEMA)


def execute_sql_tool(query: str) -> list[dict]:
    log.debug("SQL: %s", query)
    with get_connection() as conn:
        cursor = conn.execute(query)
        if cursor.description:
            rows = [dict(row) for row in cursor.fetchall()]
            log.debug("Returned %d rows", len(rows))
            return rows
        conn.commit()
        log.debug("Affected %d rows", cursor.rowcount)
        return [{"rows_affected": cursor.rowcount}]
