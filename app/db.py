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
    "library_open": "15:00",
    "library_close": "22:00",
    "exam_date": "2026-12-26",
    "timezone": "Asia/Shanghai",
}

DEFAULT_MODES = [
    ("深度专注", "专业课", 90),
    ("标准专注", "数学", 50),
    ("短时冲刺", "英语", 25),
    ("自由计时", "自定义", 0),
]

DEFAULT_SCORES = [
    ("数学", "2026-07-12", 118, 130),
    ("英语", "2026-07-12", 72, 80),
    ("政治", "2026-07-12", 68, 75),
    ("专业课", "2026-07-12", 214, 240),
]

DEFAULT_PLANS = [
    ("2026-07-14", "专业课", "图论、查找、排序", 900, 558),
    ("2026-07-21", "数学", "概率论与线代错题二刷", 720, 252),
    ("2026-07-28", "英语", "真题阅读与作文模板", 600, 108),
]


def connect(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    for key, value in DEFAULT_SETTINGS.items():
        connection.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))
    if connection.execute("SELECT COUNT(*) FROM focus_modes").fetchone()[0] == 0:
        connection.executemany("INSERT INTO focus_modes(name, subject, duration_minutes) VALUES (?, ?, ?)", DEFAULT_MODES)
    if connection.execute("SELECT COUNT(*) FROM scores").fetchone()[0] == 0:
        connection.executemany("INSERT INTO scores(subject, exam_date, score, target) VALUES (?, ?, ?, ?)", DEFAULT_SCORES)
    if connection.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 0:
        connection.executemany("INSERT INTO plans(week_start, subject, title, target_minutes, completed_minutes) VALUES (?, ?, ?, ?, ?)", DEFAULT_PLANS)
    connection.commit()


def _rows(connection: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(query).fetchall()]


def get_settings(connection: sqlite3.Connection) -> dict[str, str]:
    return {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM settings")}


def list_focus_modes(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return _rows(connection, "SELECT id, name, subject, duration_minutes FROM focus_modes ORDER BY id")


def list_scores(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return _rows(connection, "SELECT id, subject, exam_date, score, target FROM scores ORDER BY id")


def list_plans(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return _rows(connection, "SELECT id, week_start, subject, title, target_minutes, completed_minutes FROM plans ORDER BY week_start")
