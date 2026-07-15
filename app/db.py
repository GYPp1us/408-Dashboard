import sqlite3
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS focus_modes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    subject TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS focus_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    mode TEXT NOT NULL,
    planned_minutes INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL,
    client_token TEXT UNIQUE,
    interruption_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    exam_date TEXT NOT NULL,
    score REAL NOT NULL,
    target REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start TEXT NOT NULL,
    subject TEXT NOT NULL,
    title TEXT NOT NULL,
    target_minutes INTEGER NOT NULL,
    completed_minutes INTEGER NOT NULL DEFAULT 0
);
"""

DEFAULT_SETTINGS = {
    "morning_start": "08:00",
    "lunch_start": "12:00",
    "library_open": "13:30",
    "library_close": "22:00",
    "exam_date": "2026-12-26",
    "timezone": "Asia/Shanghai",
    "heatmap_visible_hours": "0,2,4,6,8,10,12,14,16,18,20,22",
}

DEFAULT_MODES = [
    ("专注", "408二轮", 0),
    ("专注", "数学二轮", 0),
    ("专注", "英语二轮", 0),
    ("专注", "政治一轮", 0),
    ("专注", "408模拟", 0),
    ("专注", "数学模拟", 0),
]

def connect(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(focus_sessions)")}
    if "client_token" not in columns:
        try:
            connection.execute("ALTER TABLE focus_sessions ADD COLUMN client_token TEXT")
        except sqlite3.OperationalError as error:
            if "duplicate column name" not in str(error).lower():
                raise
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_focus ON focus_sessions(status) WHERE status = 'active'")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS unique_focus_client_token ON focus_sessions(client_token) WHERE client_token IS NOT NULL")
    for key, value in DEFAULT_SETTINGS.items():
        connection.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))
    mode_ids = [row["id"] for row in connection.execute("SELECT id FROM focus_modes ORDER BY id")]
    for index, mode in enumerate(DEFAULT_MODES):
        if index < len(mode_ids):
            connection.execute(
                "UPDATE focus_modes SET name = ?, subject = ?, duration_minutes = ? WHERE id = ?",
                (*mode, mode_ids[index]),
            )
        else:
            connection.execute("INSERT INTO focus_modes(name, subject, duration_minutes) VALUES (?, ?, ?)", mode)
    if len(mode_ids) > len(DEFAULT_MODES):
        placeholders = ",".join("?" for _ in mode_ids[len(DEFAULT_MODES):])
        connection.execute(f"DELETE FROM focus_modes WHERE id IN ({placeholders})", mode_ids[len(DEFAULT_MODES):])
    connection.commit()


def _rows(connection: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(query).fetchall()]


def get_settings(connection: sqlite3.Connection) -> dict[str, str]:
    return {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM settings")}


def list_focus_modes(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return _rows(connection, "SELECT id, name, subject, duration_minutes FROM focus_modes ORDER BY id")


def list_scores(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return _rows(connection, "SELECT id, subject, exam_date, score, target FROM scores ORDER BY id")


def list_latest_scores(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return _rows(connection, """
        SELECT score.id, score.subject, score.exam_date, score.score, score.target
        FROM scores AS score
        WHERE score.id = (
            SELECT latest.id FROM scores AS latest
            WHERE latest.subject = score.subject
            ORDER BY latest.exam_date DESC, latest.id DESC
            LIMIT 1
        )
        ORDER BY score.id
    """)


def list_plans(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return _rows(connection, "SELECT id, week_start, subject, title, target_minutes, completed_minutes FROM plans ORDER BY week_start")


def clear_user_data(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN IMMEDIATE")
    connection.execute("DELETE FROM focus_sessions")
    connection.execute("DELETE FROM scores")
    connection.execute("DELETE FROM plans")
    connection.execute("DELETE FROM sqlite_sequence WHERE name IN ('focus_sessions', 'scores', 'plans')")
    connection.commit()
