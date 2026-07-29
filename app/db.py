import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user', 'site_owner')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invitations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    used_by INTEGER REFERENCES users(id),
    used_at TEXT
);
CREATE TABLE IF NOT EXISTS friendships (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    friend_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, friend_id),
    CHECK(user_id < friend_id)
);
CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);
CREATE TABLE IF NOT EXISTS focus_modes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    subject TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS user_focus_modes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    subject TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS focus_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    subject TEXT NOT NULL,
    mode TEXT NOT NULL,
    planned_minutes INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL,
    client_token TEXT UNIQUE,
    interruption_count INTEGER NOT NULL DEFAULT 0,
    last_foreground_at TEXT,
    focus_locked INTEGER NOT NULL DEFAULT 0,
    trusted INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS focus_pauses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES focus_sessions(id) ON DELETE CASCADE,
    started_at TEXT NOT NULL,
    ended_at TEXT
);
CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    subject TEXT NOT NULL,
    exam_date TEXT NOT NULL,
    score REAL NOT NULL,
    target REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    week_start TEXT NOT NULL,
    subject TEXT NOT NULL,
    title TEXT NOT NULL,
    target_minutes INTEGER NOT NULL,
    completed_minutes INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS daily_settlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    settlement_date TEXT NOT NULL,
    settled_at TEXT NOT NULL,
    total_seconds INTEGER NOT NULL,
    yesterday_seconds INTEGER NOT NULL,
    delta_seconds INTEGER NOT NULL,
    target_seconds INTEGER NOT NULL,
    completion REAL NOT NULL,
    session_count INTEGER NOT NULL,
    top_subject TEXT,
    top_subject_seconds INTEGER NOT NULL DEFAULT 0,
    UNIQUE(user_id, settlement_date)
);
"""

DEFAULT_FOCUS_MESSAGES = [
    {"category": "时间管理", "text": "当前只处理一个问题，剩下的交给计划。"},
    {"category": "时间管理", "text": "先完成眼前这一步，再决定下一步。"},
    {"category": "时间管理", "text": "用完整的一小时，换一个真正清晰的知识点。"},
    {"category": "时间管理", "text": "难题先标记，别让局部拖住整段节奏。"},
    {"category": "时间管理", "text": "速度不是匆忙，而是减少无意义的切换。"},
    {"category": "时间管理", "text": "给任务设边界，也给注意力留出余地。"},
    {"category": "时间管理", "text": "复习进度由完成的闭环决定，不由打开的页面决定。"},
    {"category": "时间管理", "text": "卡住五分钟，就换一种表述重新理解。"},
    {"category": "时间管理", "text": "今天的稳定投入，比临时冲刺更可靠。"},
    {"category": "时间管理", "text": "结束前留两分钟，写下清晰的下一步。"},
    {"category": "继续前进", "text": "你正在把陌生变成熟悉。"},
    {"category": "继续前进", "text": "每一次专注，都在降低考场上的不确定性。"},
    {"category": "继续前进", "text": "不必等状态完美，开始本身会制造状态。"},
    {"category": "继续前进", "text": "碰到能力边界时，慢一点也算前进。"},
    {"category": "继续前进", "text": "现在积累的确定性，会在考场上替你说话。"},
    {"category": "继续前进", "text": "把会做的做稳，把不会的逐步拆开。"},
    {"category": "继续前进", "text": "今日不求惊艳，只求比昨天更扎实。"},
    {"category": "继续前进", "text": "题目不会辜负真正理解它的人。"},
    {"category": "继续前进", "text": "长期主义不是坚持口号，而是完成这一段。"},
    {"category": "继续前进", "text": "无需一次看见终点，只需要守住当前节奏。"},
    {"category": "视线提醒", "text": "别盯着面板，回到书页和题目。"},
    {"category": "视线提醒", "text": "看远处二十秒，让眼睛也完成一次休息。"},
    {"category": "视线提醒", "text": "肩膀放松，呼吸一次，再继续。"},
    {"category": "视线提醒", "text": "喝一口水，不要用疲劳冒充努力。"},
    {"category": "视线提醒", "text": "坐姿归位，屏幕只是计时器，不是任务本身。"},
    {"category": "视线提醒", "text": "如果正在走神，写下干扰，再回到当前题。"},
    {"category": "视线提醒", "text": "面板没有新答案，答案在你的草稿纸上。"},
    {"category": "视线提醒", "text": "眼睛离开屏幕，注意力留在问题上。"},
    {"category": "视线提醒", "text": "听见自己翻页的声音，比看计时数字更重要。"},
    {"category": "视线提醒", "text": "不用频繁确认时间，计时会替你记住。"},
    {"category": "专注提醒", "text": "忽略该忽略的，专注该专注的"},
]

DEFAULT_SETTINGS = {
    "morning_start": "08:00",
    "lunch_start": "12:00",
    "library_open": "13:30",
    "library_close": "22:00",
    "exam_date": "2026-12-26",
    "timezone": "Asia/Shanghai",
    "heatmap_visible_hours": "0,2,4,6,8,10,12,14,16,18,20,22",
    "focus_messages_json": json.dumps(DEFAULT_FOCUS_MESSAGES, ensure_ascii=False, separators=(",", ":")),
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
    migrations = {
        "user_id": "INTEGER REFERENCES users(id)",
        "client_token": "TEXT",
        "last_foreground_at": "TEXT",
        "focus_locked": "INTEGER NOT NULL DEFAULT 0",
        "trusted": "INTEGER NOT NULL DEFAULT 1",
    }
    for column, definition in migrations.items():
        if column in columns:
            continue
        try:
            connection.execute(f"ALTER TABLE focus_sessions ADD COLUMN {column} {definition}")
        except sqlite3.OperationalError as error:
            if "duplicate column name" not in str(error).lower():
                raise
    for table in ("scores", "plans"):
        table_columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if "user_id" not in table_columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER REFERENCES users(id)")
    connection.execute("DROP INDEX IF EXISTS one_active_focus")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_focus_per_user ON focus_sessions(user_id) WHERE status = 'active' AND user_id IS NOT NULL")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS unique_focus_client_token ON focus_sessions(client_token) WHERE client_token IS NOT NULL")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_open_pause_per_session ON focus_pauses(session_id) WHERE ended_at IS NULL")
    connection.execute("CREATE INDEX IF NOT EXISTS daily_settlements_user_date ON daily_settlements(user_id, settlement_date)")
    for key, value in DEFAULT_SETTINGS.items():
        connection.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))
    if not connection.execute("SELECT 1 FROM focus_modes LIMIT 1").fetchone():
        connection.executemany("INSERT INTO focus_modes(name, subject, duration_minutes) VALUES (?, ?, ?)", DEFAULT_MODES)
    connection.commit()


def get_daily_settlement(connection: sqlite3.Connection, user_id: int | None, settlement_date: str) -> dict[str, Any] | None:
    if user_id is None:
        return None
    row = connection.execute(
        "SELECT * FROM daily_settlements WHERE user_id = ? AND settlement_date = ?",
        (user_id, settlement_date),
    ).fetchone()
    return dict(row) if row else None


def ensure_site_owner(connection: sqlite3.Connection, username: str, email: str, password_hash: str) -> int:
    row = connection.execute("SELECT id FROM users WHERE role = 'site_owner' ORDER BY id LIMIT 1").fetchone()
    now = datetime.now(timezone.utc).isoformat()
    if row:
        owner_id = int(row["id"])
    else:
        cursor = connection.execute(
            "INSERT INTO users(username, email, password_hash, role, created_at) VALUES (?, ?, ?, 'site_owner', ?)",
            (username, email, password_hash, now),
        )
        owner_id = int(cursor.lastrowid)
    connection.execute("UPDATE focus_sessions SET user_id = ? WHERE user_id IS NULL", (owner_id,))
    connection.execute("UPDATE scores SET user_id = ? WHERE user_id IS NULL", (owner_id,))
    connection.execute("UPDATE plans SET user_id = ? WHERE user_id IS NULL", (owner_id,))
    initialize_user_profile(connection, owner_id)
    for user in connection.execute("SELECT id FROM users WHERE id != ?", (owner_id,)).fetchall():
        initialize_user_profile(connection, int(user["id"]), owner_id)
    connection.commit()
    return owner_id


def get_user(connection: sqlite3.Connection, user_id: int | None) -> dict[str, Any] | None:
    if user_id is None:
        return None
    row = connection.execute("SELECT id, username, email, role, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_username(connection: sqlite3.Connection, username: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)).fetchone()
    return dict(row) if row else None


def get_user_by_identifier(connection: sqlite3.Connection, identifier: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE OR email = ? COLLATE NOCASE", (identifier, identifier)).fetchone()
    return dict(row) if row else None


def list_public_users(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return _rows(connection, "SELECT username, role, created_at FROM users ORDER BY username COLLATE NOCASE")


def create_user(connection: sqlite3.Connection, username: str, email: str, password_hash: str, now: str) -> int:
    cursor = connection.execute(
        "INSERT INTO users(username, email, password_hash, role, created_at) VALUES (?, ?, ?, 'user', ?)",
        (username, email, password_hash, now),
    )
    user_id = int(cursor.lastrowid)
    owner = connection.execute("SELECT id FROM users WHERE role = 'site_owner' ORDER BY id LIMIT 1").fetchone()
    initialize_user_profile(connection, user_id, int(owner["id"]) if owner else None)
    return user_id


def issue_invitation(connection: sqlite3.Connection, owner_id: int, code: str, now: str) -> dict[str, Any]:
    cursor = connection.execute(
        "INSERT INTO invitations(code, created_by, created_at) VALUES (?, ?, ?)",
        (code, owner_id, now),
    )
    row = connection.execute("SELECT * FROM invitations WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row)


def list_invitations(connection: sqlite3.Connection, owner_id: int) -> list[dict[str, Any]]:
    return _rows(connection, "SELECT id, code, created_at, used_by, used_at FROM invitations WHERE created_by = ? ORDER BY id DESC", (owner_id,))


def claim_invitation(connection: sqlite3.Connection, code: str, user_id: int, now: str) -> bool:
    cursor = connection.execute(
        "UPDATE invitations SET used_by = ?, used_at = ? WHERE code = ? AND used_by IS NULL",
        (user_id, now, code),
    )
    return cursor.rowcount == 1


def list_friends(connection: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
    return _rows(connection, """
        SELECT u.id, u.username, u.email, u.role
        FROM friendships AS f
        JOIN users AS u ON u.id = CASE WHEN f.user_id = ? THEN f.friend_id ELSE f.user_id END
        WHERE f.user_id = ? OR f.friend_id = ?
        ORDER BY u.username COLLATE NOCASE
    """, (user_id, user_id, user_id))


def add_friend(connection: sqlite3.Connection, user_id: int, friend_id: int, now: str) -> None:
    left, right = sorted((int(user_id), int(friend_id)))
    if left == right:
        raise ValueError("cannot_add_self")
    connection.execute("INSERT INTO friendships(user_id, friend_id, created_at) VALUES (?, ?, ?)", (left, right, now))


def remove_friend(connection: sqlite3.Connection, user_id: int, friend_id: int) -> None:
    left, right = sorted((int(user_id), int(friend_id)))
    connection.execute("DELETE FROM friendships WHERE user_id = ? AND friend_id = ?", (left, right))


def _rows(connection: sqlite3.Connection, query: str, params: tuple = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(query, params).fetchall()]


def initialize_user_profile(connection: sqlite3.Connection, user_id: int, template_user_id: int | None = None) -> None:
    existing = connection.execute("SELECT 1 FROM user_settings WHERE user_id = ? LIMIT 1", (user_id,)).fetchone()
    if not existing:
        if template_user_id is not None:
            source = connection.execute("SELECT key, value FROM user_settings WHERE user_id = ?", (template_user_id,)).fetchall()
        else:
            source = []
        if not source:
            source = connection.execute("SELECT key, value FROM settings").fetchall()
        connection.executemany(
            "INSERT OR IGNORE INTO user_settings(user_id, key, value) VALUES (?, ?, ?)",
            [(user_id, row["key"], row["value"]) for row in source],
        )

    if not connection.execute("SELECT 1 FROM user_focus_modes WHERE user_id = ? LIMIT 1", (user_id,)).fetchone():
        if template_user_id is not None:
            modes = connection.execute(
                "SELECT name, subject, duration_minutes FROM user_focus_modes WHERE user_id = ? ORDER BY id",
                (template_user_id,),
            ).fetchall()
        else:
            modes = []
        if not modes:
            modes = connection.execute("SELECT name, subject, duration_minutes FROM focus_modes ORDER BY id").fetchall()
        connection.executemany(
            "INSERT INTO user_focus_modes(user_id, name, subject, duration_minutes) VALUES (?, ?, ?, ?)",
            [(user_id, row["name"], row["subject"], row["duration_minutes"]) for row in modes],
        )


def get_settings(connection: sqlite3.Connection, user_id: int | None = None) -> dict[str, str]:
    table = "user_settings" if user_id is not None else "settings"
    params = (user_id,) if user_id is not None else ()
    values = {row["key"]: row["value"] for row in connection.execute(f"SELECT key, value FROM {table}" + (" WHERE user_id = ?" if user_id is not None else ""), params)}
    if user_id is not None:
        return {**DEFAULT_SETTINGS, **values}
    return values


def list_focus_modes(connection: sqlite3.Connection, user_id: int | None = None) -> list[dict[str, Any]]:
    table = "user_focus_modes" if user_id is not None else "focus_modes"
    where = " WHERE user_id = ?" if user_id is not None else ""
    params = (user_id,) if user_id is not None else ()
    return _rows(connection, f"SELECT id, name, subject, duration_minutes FROM {table}{where} ORDER BY id", params)


def replace_focus_modes(connection: sqlite3.Connection, subjects: list[str], user_id: int | None = None) -> None:
    if user_id is not None:
        connection.execute("DELETE FROM user_focus_modes WHERE user_id = ?", (user_id,))
        connection.executemany(
            "INSERT INTO user_focus_modes(user_id, name, subject, duration_minutes) VALUES (?, '专注', ?, 0)",
            [(user_id, subject) for subject in subjects],
        )
        return
    mode_ids = [row["id"] for row in connection.execute("SELECT id FROM focus_modes ORDER BY id")]
    for index, subject in enumerate(subjects):
        if index < len(mode_ids):
            connection.execute(
                "UPDATE focus_modes SET name = '专注', subject = ?, duration_minutes = 0 WHERE id = ?",
                (subject, mode_ids[index]),
            )
        else:
            connection.execute("INSERT INTO focus_modes(name, subject, duration_minutes) VALUES ('专注', ?, 0)", (subject,))
    if len(mode_ids) > len(subjects):
        placeholders = ",".join("?" for _ in mode_ids[len(subjects):])
        connection.execute(f"DELETE FROM focus_modes WHERE id IN ({placeholders})", mode_ids[len(subjects):])


def get_focus_messages(connection: sqlite3.Connection, user_id: int | None = None) -> list[dict[str, str]]:
    if user_id is None:
        row = connection.execute("SELECT value FROM settings WHERE key = 'focus_messages_json'").fetchone()
    else:
        row = connection.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = 'focus_messages_json'", (user_id,)).fetchone()
    try:
        messages = json.loads(row["value"]) if row else []
    except (TypeError, ValueError, json.JSONDecodeError):
        messages = []
    return messages if isinstance(messages, list) and messages else DEFAULT_FOCUS_MESSAGES


def save_focus_messages(connection: sqlite3.Connection, messages: list[dict[str, str]], user_id: int | None = None) -> None:
    value = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    if user_id is None:
        connection.execute(
            "INSERT INTO settings(key, value) VALUES ('focus_messages_json', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (value,),
        )
    else:
        connection.execute(
            "INSERT INTO user_settings(user_id, key, value) VALUES (?, 'focus_messages_json', ?) ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
            (user_id, value),
        )


def finish_focus_session(connection: sqlite3.Connection, session_id: int, ended_at: str) -> None:
    connection.execute(
        "UPDATE focus_pauses SET ended_at = ? WHERE session_id = ? AND ended_at IS NULL",
        (ended_at, session_id),
    )
    connection.execute(
        "UPDATE focus_sessions SET ended_at = ?, status = 'completed' WHERE id = ? AND status = 'active'",
        (ended_at, session_id),
    )


def expire_unattended_focus(connection: sqlite3.Connection, now: datetime, timeout_seconds: int = 30) -> int | None:
    cutoff = now - timedelta(seconds=timeout_seconds)
    query = """
        SELECT id, last_foreground_at
        FROM focus_sessions
        WHERE status = 'active'
          AND focus_locked = 0
          AND NOT EXISTS (
              SELECT 1 FROM focus_pauses
              WHERE focus_pauses.session_id = focus_sessions.id
                AND focus_pauses.ended_at IS NULL
          )
          AND last_foreground_at IS NOT NULL
          AND last_foreground_at <= ?
        ORDER BY id DESC
        LIMIT 1
    """
    if not connection.execute(query, (cutoff.isoformat(),)).fetchone():
        return None
    connection.execute("BEGIN IMMEDIATE")
    row = connection.execute(query, (cutoff.isoformat(),)).fetchone()
    if not row:
        connection.commit()
        return None
    last_foreground_at = datetime.fromisoformat(row["last_foreground_at"])
    ended_at = (last_foreground_at + timedelta(seconds=timeout_seconds)).isoformat()
    finish_focus_session(connection, row["id"], ended_at)
    connection.commit()
    return int(row["id"])


def list_scores(connection: sqlite3.Connection, user_id: int | None = None) -> list[dict[str, Any]]:
    return _rows(connection, "SELECT id, subject, exam_date, score, target FROM scores WHERE user_id = ? ORDER BY id", (user_id,))


def list_latest_scores(connection: sqlite3.Connection, user_id: int | None = None) -> list[dict[str, Any]]:
    return _rows(connection, """
        SELECT score.id, score.subject, score.exam_date, score.score, score.target
        FROM scores AS score
        WHERE score.user_id = ? AND score.id = (
            SELECT latest.id FROM scores AS latest
            WHERE latest.subject = score.subject AND latest.user_id = score.user_id
            ORDER BY latest.exam_date DESC, latest.id DESC
            LIMIT 1
        )
        ORDER BY score.id
    """, (user_id,))


def list_plans(connection: sqlite3.Connection, user_id: int | None = None) -> list[dict[str, Any]]:
    return _rows(connection, "SELECT id, week_start, subject, title, target_minutes, completed_minutes FROM plans WHERE user_id = ? ORDER BY week_start", (user_id,))


def clear_user_data(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN IMMEDIATE")
    connection.execute("DELETE FROM focus_sessions")
    connection.execute("DELETE FROM daily_settlements")
    connection.execute("DELETE FROM scores")
    connection.execute("DELETE FROM plans")
    connection.execute("DELETE FROM sqlite_sequence WHERE name IN ('focus_sessions', 'focus_pauses', 'scores', 'plans', 'daily_settlements')")
    connection.commit()
