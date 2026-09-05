import hashlib
import json
import math
import secrets
import sqlite3
import unicodedata
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
CREATE TABLE IF NOT EXISTS user_subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    target_score REAL NOT NULL DEFAULT 100
);
CREATE TABLE IF NOT EXISTS user_focus_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES user_subjects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    item_key TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    legacy_mode_id INTEGER UNIQUE
);
CREATE TABLE IF NOT EXISTS focus_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    subject_id INTEGER REFERENCES user_subjects(id) ON DELETE SET NULL,
    focus_item_id INTEGER REFERENCES user_focus_items(id) ON DELETE SET NULL,
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
    subject_id INTEGER REFERENCES user_subjects(id) ON DELETE SET NULL,
    subject TEXT NOT NULL,
    exam_date TEXT NOT NULL,
    score REAL NOT NULL,
    target REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    subject_id INTEGER REFERENCES user_subjects(id) ON DELETE SET NULL,
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
CREATE TABLE IF NOT EXISTS migration_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
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

DEFAULT_SUBJECTS = [
    ("408", 100),
    ("数学", 100),
    ("英语", 100),
    ("政治", 100),
]

DEFAULT_FOCUS_ITEMS = [
    ("408", "二轮"),
    ("数学", "二轮"),
    ("英语", "二轮"),
    ("政治", "一轮"),
    ("408", "模拟"),
    ("数学", "模拟"),
]

LEGACY_FOCUS_ITEM_SUFFIXES = ("一轮", "二轮", "模拟")


def _subject_key(value: str) -> str:
    return unicodedata.normalize("NFKC", str(value)).strip().casefold()


class SubjectMigrationBlocked(RuntimeError):
    """Raised before a legacy subject migration needs human review."""

    def __init__(self, risks: list[dict[str, Any]]):
        self.risks = risks
        summaries = "; ".join(risk["summary"] for risk in risks)
        super().__init__(f"subject migration blocked: {summaries}")


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(connection, table):
        return set()
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _migration_risk(
    risk_id: str,
    severity: str,
    summary: str,
    *,
    affected_count: int = 0,
    samples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": risk_id,
        "severity": severity,
        "summary": summary,
        "affected_count": affected_count,
        "samples": samples or [],
    }


def connect(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _hierarchy_parts(value: str) -> tuple[str, str] | None:
    label = unicodedata.normalize("NFKC", str(value)).strip()
    for item_name in LEGACY_FOCUS_ITEM_SUFFIXES:
        if not label.endswith(item_name):
            continue
        subject_name = label[:-len(item_name)].strip(" ·-_")
        if _subject_key(subject_name):
            return subject_name, item_name
    return None


def _hierarchy_target(value: Any) -> float | None:
    try:
        target = float(value)
    except (TypeError, ValueError):
        return None
    return target if math.isfinite(target) and 0 < target <= 199 else None


def _hierarchy_mode_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    columns = _table_columns(connection, "user_focus_modes")
    if not {"id", "user_id", "subject"}.issubset(columns):
        return []
    target_column = "target_score" if "target_score" in columns else "NULL"
    return [
        dict(row)
        for row in connection.execute(f"""
            SELECT id, user_id, subject, {target_column} AS target_score
            FROM user_focus_modes
            ORDER BY id
        """).fetchall()
    ]


def _hierarchy_mode_status(connection: sqlite3.Connection) -> str:
    modes = _hierarchy_mode_rows(connection)
    if not modes:
        return "none"
    if not _table_exists(connection, "user_focus_items"):
        return "required"
    linked = {
        int(row["legacy_mode_id"])
        for row in connection.execute(
            "SELECT legacy_mode_id FROM user_focus_items WHERE legacy_mode_id IS NOT NULL"
        ).fetchall()
    }
    source = {int(row["id"]) for row in modes}
    if source.issubset(linked):
        return "complete"
    return "partial" if source & linked else "required"


def _hierarchy_owner_risks(
    connection: sqlite3.Connection,
    risks: list[dict[str, Any]],
    tables: tuple[str, ...],
) -> None:
    user_columns = _table_columns(connection, "users")
    invalid: list[dict[str, Any]] = []
    if "id" not in user_columns:
        for table in tables:
            if {"id", "user_id"}.issubset(_table_columns(connection, table)):
                invalid.extend(
                    {"table": table, "id": int(row["id"]), "user_id": row["user_id"]}
                    for row in connection.execute(
                        f"SELECT id, user_id FROM {table} WHERE user_id IS NOT NULL ORDER BY id"
                    ).fetchall()
                )
        if invalid:
            risks.append(_migration_risk(
                "unsupported-user-schema",
                "blocking",
                "存在带 user_id 的学习数据，但 users 表缺少 id；无法验证账户归属。",
                affected_count=len(invalid),
                samples=invalid[:10],
            ))
        return
    for table in tables:
        if not {"id", "user_id"}.issubset(_table_columns(connection, table)):
            continue
        invalid.extend(
            {"table": table, "id": int(row["id"]), "user_id": row["user_id"]}
            for row in connection.execute(f"""
                SELECT record.id, record.user_id
                FROM {table} AS record
                LEFT JOIN users AS owner ON owner.id = record.user_id
                WHERE record.user_id IS NOT NULL AND owner.id IS NULL
                ORDER BY record.id
            """).fetchall()
        )
    if invalid:
        risks.append(_migration_risk(
            "subject-data-user-not-found",
            "blocking",
            "存在 user_id 指向不存在账户的数据；不能安全建立稳定关联。",
            affected_count=len(invalid),
            samples=invalid[:10],
        ))


def _hierarchy_canonical_risks(connection: sqlite3.Connection, risks: list[dict[str, Any]]) -> None:
    subject_rows = connection.execute(
        "SELECT id, user_id, name, subject_key, target_score FROM user_subjects ORDER BY id"
    ).fetchall()
    invalid_subjects: list[dict[str, Any]] = []
    groups: dict[tuple[int, str], list[sqlite3.Row]] = {}
    for row in subject_rows:
        key = _subject_key(row["name"])
        if not key or row["subject_key"] != key or _hierarchy_target(row["target_score"]) is None:
            invalid_subjects.append(dict(row))
        else:
            groups.setdefault((int(row["user_id"]), key), []).append(row)
    duplicates = [rows for rows in groups.values() if len(rows) > 1]
    if invalid_subjects:
        risks.append(_migration_risk(
            "invalid-canonical-subject",
            "blocking",
            "新科目表存在空名称、错误稳定键或无效目标分。",
            affected_count=len(invalid_subjects),
            samples=invalid_subjects[:10],
        ))
    if duplicates:
        risks.append(_migration_risk(
            "duplicate-canonical-subject",
            "blocking",
            "同一账户的新科目名称归一化后重复。",
            affected_count=len(duplicates),
            samples=[
                {"user_id": rows[0]["user_id"], "subject_ids": [row["id"] for row in rows]}
                for rows in duplicates[:10]
            ],
        ))

    item_rows = connection.execute("""
        SELECT item.id, item.user_id, item.subject_id, item.name, item.item_key,
               subject.user_id AS subject_user_id
        FROM user_focus_items AS item
        LEFT JOIN user_subjects AS subject ON subject.id = item.subject_id
        ORDER BY item.id
    """).fetchall()
    invalid_items: list[dict[str, Any]] = []
    item_groups: dict[tuple[int, int, str], list[sqlite3.Row]] = {}
    for row in item_rows:
        key = _subject_key(row["name"])
        if (
            row["subject_user_id"] is None
            or row["subject_user_id"] != row["user_id"]
            or not key
            or row["item_key"] != key
        ):
            invalid_items.append(dict(row))
        else:
            item_groups.setdefault((int(row["user_id"]), int(row["subject_id"]), key), []).append(row)
    duplicates = [rows for rows in item_groups.values() if len(rows) > 1]
    if invalid_items:
        risks.append(_migration_risk(
            "invalid-canonical-focus-item",
            "blocking",
            "新专注事项存在错误稳定键、空名称或跨账户科目引用。",
            affected_count=len(invalid_items),
            samples=invalid_items[:10],
        ))
    if duplicates:
        risks.append(_migration_risk(
            "duplicate-canonical-focus-item",
            "blocking",
            "同一科目下存在归一化后重复的专注事项。",
            affected_count=len(duplicates),
            samples=[
                {
                    "user_id": rows[0]["user_id"],
                    "subject_id": rows[0]["subject_id"],
                    "focus_item_ids": [row["id"] for row in rows],
                }
                for rows in duplicates[:10]
            ],
        ))

    for table in ("focus_sessions", "scores", "plans"):
        columns = _table_columns(connection, table)
        if not {"id", "user_id", "subject_id"}.issubset(columns):
            continue
        rows = connection.execute(f"""
            SELECT record.id, record.user_id, record.subject_id, subject.user_id AS subject_user_id
            FROM {table} AS record
            JOIN user_subjects AS subject ON subject.id = record.subject_id
            WHERE record.user_id IS NOT NULL AND record.user_id != subject.user_id
            ORDER BY record.id
        """).fetchall()
        if rows:
            risks.append(_migration_risk(
                f"cross-account-subject-link-{table}",
                "blocking",
                f"{table} 存在跨账户 subject_id 关联。",
                affected_count=len(rows),
                samples=[dict(row) for row in rows[:10]],
            ))
    if {"id", "user_id", "focus_item_id"}.issubset(_table_columns(connection, "focus_sessions")):
        rows = connection.execute("""
            SELECT session.id, session.user_id, session.focus_item_id, item.user_id AS item_user_id
            FROM focus_sessions AS session
            JOIN user_focus_items AS item ON item.id = session.focus_item_id
            WHERE session.user_id IS NOT NULL AND session.user_id != item.user_id
            ORDER BY session.id
        """).fetchall()
        if rows:
            risks.append(_migration_risk(
                "cross-account-focus-item-link",
                "blocking",
                "focus_sessions 存在跨账户 focus_item_id 关联。",
                affected_count=len(rows),
                samples=[dict(row) for row in rows[:10]],
            ))


def _focus_hierarchy_report(connection: sqlite3.Connection) -> dict[str, Any]:
    history_tables = ("focus_sessions", "scores", "plans")
    risks: list[dict[str, Any]] = []
    legacy_columns = _table_columns(connection, "user_focus_modes")
    subject_columns = _table_columns(connection, "user_subjects")
    item_columns = _table_columns(connection, "user_focus_items")
    has_subject_table = bool(subject_columns)
    has_item_table = bool(item_columns)
    legacy_columns_required = {"id", "user_id", "subject"}
    subject_columns_required = {"id", "user_id", "name", "subject_key", "target_score"}
    item_columns_required = {"id", "user_id", "subject_id", "name", "item_key", "sort_order", "legacy_mode_id"}
    legacy_source_supported = not legacy_columns or legacy_columns_required.issubset(legacy_columns)
    canonical_ready = (
        has_subject_table
        and has_item_table
        and subject_columns_required.issubset(subject_columns)
        and item_columns_required.issubset(item_columns)
    )
    report: dict[str, Any] = {
        "schema": {
            "user_focus_modes": sorted(legacy_columns),
            "user_subjects": sorted(subject_columns),
            "user_focus_items": sorted(item_columns),
            "users": sorted(_table_columns(connection, "users")),
            **{table: sorted(_table_columns(connection, table)) for table in history_tables},
        },
        "risks": risks,
    }
    if has_subject_table != has_item_table:
        risks.append(_migration_risk(
            "partial-focus-hierarchy-schema",
            "blocking",
            "新两层表只创建了一部分；不能判断中断前已写入的数据，必须从完整备份恢复或人工修复。",
        ))
    if legacy_columns and not legacy_source_supported:
        risks.append(_migration_risk(
            "unsupported-legacy-focus-schema",
            "blocking",
            "旧专注事项表缺少 id、user_id 或 subject，无法安全转换。",
            samples=[{"missing_columns": sorted(legacy_columns_required - legacy_columns)}],
        ))
    if has_subject_table and not subject_columns_required.issubset(subject_columns):
        risks.append(_migration_risk(
            "unsupported-canonical-subject-schema",
            "blocking",
            "新科目表缺少层级迁移所需列，不能继续写入。",
            samples=[{"missing_columns": sorted(subject_columns_required - subject_columns)}],
        ))
    if has_item_table and not item_columns_required.issubset(item_columns):
        risks.append(_migration_risk(
            "unsupported-canonical-focus-item-schema",
            "blocking",
            "新专注事项表缺少层级迁移所需列，不能继续写入。",
            samples=[{"missing_columns": sorted(item_columns_required - item_columns)}],
        ))
    _hierarchy_owner_risks(
        connection,
        risks,
        ("user_focus_modes", "user_subjects", "user_focus_items", *history_tables),
    )
    modes = _hierarchy_mode_rows(connection) if legacy_source_supported else []
    status = (
        _hierarchy_mode_status(connection)
        if not has_item_table or "legacy_mode_id" in item_columns
        else "unsupported"
    )
    if canonical_ready:
        _hierarchy_canonical_risks(connection, risks)
        if status == "partial":
            risks.append(_migration_risk(
                "partial-focus-hierarchy-migration",
                "blocking",
                "旧专注事项只有一部分完成了两层转换；不会猜测剩余映射。",
            ))
        elif status == "required":
            risks.append(_migration_risk(
                "unapplied-focus-hierarchy-migration",
                "blocking",
                "新两层表已存在，但旧专注事项尚未转换；必须从完整备份重试。",
            ))
    elif not has_subject_table and not has_item_table and modes:
        parsed: dict[int, tuple[str, str]] = {}
        unsplittable: list[dict[str, Any]] = []
        item_groups: dict[tuple[int, str, str], list[dict[str, Any]]] = {}
        invalid_item_targets: list[dict[str, Any]] = []
        for mode in modes:
            parts = _hierarchy_parts(mode["subject"])
            if mode["user_id"] is None or parts is None:
                unsplittable.append({"id": mode["id"], "user_id": mode["user_id"], "subject": mode["subject"]})
                continue
            parsed[int(mode["id"])] = parts
            item_groups.setdefault(
                (int(mode["user_id"]), _subject_key(parts[0]), _subject_key(parts[1])),
                [],
            ).append(mode)
            if mode["target_score"] is not None and _hierarchy_target(mode["target_score"]) is None:
                invalid_item_targets.append({
                    "mode_id": mode["id"],
                    "user_id": mode["user_id"],
                    "subject": mode["subject"],
                    "target": mode["target_score"],
                })
        if unsplittable:
            risks.append(_migration_risk(
                "legacy-focus-item-not-splittable",
                "blocking",
                "旧专注名称不能明确拆为“科目 + 一轮/二轮/模拟事项”；不会猜测。",
                affected_count=len(unsplittable),
                samples=unsplittable[:10],
            ))
        duplicates = [rows for rows in item_groups.values() if len(rows) > 1]
        if duplicates:
            risks.append(_migration_risk(
                "duplicate-legacy-focus-item",
                "blocking",
                "同一账户中存在重复的“科目 + 专注事项”组合，不能自动合并。",
                affected_count=len(duplicates),
                samples=[
                    {"user_id": rows[0]["user_id"], "mode_ids": [row["id"] for row in rows]}
                    for rows in duplicates[:10]
                ],
            ))
        if invalid_item_targets:
            risks.append(_migration_risk(
                "invalid-focus-item-target",
                "blocking",
                "旧专注事项的目标分不在 1–199 内，无法安全迁移到科目。",
                affected_count=len(invalid_item_targets),
                samples=invalid_item_targets[:10],
            ))

        subject_keys = {
            (int(mode["user_id"]), _subject_key(parts[0]))
            for mode in modes
            if mode["user_id"] is not None
            for parts in [_hierarchy_parts(mode["subject"])]
            if parts is not None
        }
        item_keys = {
            (int(mode["user_id"]), _subject_key(mode["subject"]))
            for mode in modes
            if mode["user_id"] is not None and _hierarchy_parts(mode["subject"]) is not None
        }
        unlinked: list[dict[str, Any]] = []
        unowned: list[dict[str, Any]] = []
        for table in history_tables:
            columns = _table_columns(connection, table)
            if not {"id", "user_id", "subject"}.issubset(columns):
                continue
            if "subject_id" in columns:
                risks.append(_migration_risk(
                    f"unexpected-subject-id-{table}",
                    "blocking",
                    f"{table} 已有 subject_id，无法确认它是否指向新的科目表。",
                ))
                continue
            for row in connection.execute(
                f"SELECT id, user_id, subject FROM {table} ORDER BY id"
            ).fetchall():
                if row["user_id"] is None:
                    unowned.append({"table": table, "id": int(row["id"]), "subject": row["subject"]})
                    continue
                key = (int(row["user_id"]), _subject_key(row["subject"]))
                if key not in subject_keys and key not in item_keys:
                    unlinked.append({
                        "table": table,
                        "id": int(row["id"]),
                        "user_id": int(row["user_id"]),
                        "subject": row["subject"],
                    })
        if unlinked:
            risks.append(_migration_risk(
                "historical-subject-not-linked",
                "review",
                "部分历史文本无法匹配新科目或专注事项；原文本会保留，稳定 ID 保持为空。",
                affected_count=len(unlinked),
                samples=unlinked[:10],
            ))
        if unowned:
            risks.append(_migration_risk(
                "historical-row-without-owner",
                "review",
                "部分历史记录没有 user_id，无法安全绑定到当前账户的科目。",
                affected_count=len(unowned),
                samples=unowned[:10],
            ))

        score_columns = _table_columns(connection, "scores")
        if {"id", "user_id", "subject", "exam_date", "target"}.issubset(score_columns):
            target_conflicts: list[dict[str, Any]] = []
            invalid_targets: list[dict[str, Any]] = []
            for user_id, subject_key in subject_keys:
                rows = connection.execute("""
                    SELECT id, subject, exam_date, target
                    FROM scores
                    WHERE user_id = ?
                    ORDER BY exam_date DESC, id DESC
                """, (user_id,)).fetchall()
                matching = [row for row in rows if _subject_key(row["subject"]) == subject_key]
                values = {_hierarchy_target(row["target"]) for row in matching}
                if None in values:
                    invalid_targets.extend(
                        {
                            "score_id": row["id"],
                            "user_id": user_id,
                            "subject": row["subject"],
                            "target": row["target"],
                        }
                        for row in matching
                        if _hierarchy_target(row["target"]) is None
                    )
                valid_values = sorted(value for value in values if value is not None)
                if len(valid_values) > 1:
                    target_conflicts.append({
                        "user_id": user_id,
                        "subject": matching[0]["subject"],
                        "values": valid_values,
                        "chosen_by_migration": _hierarchy_target(matching[0]["target"]) or 100,
                    })
            if invalid_targets:
                risks.append(_migration_risk(
                    "invalid-historical-target",
                    "review",
                    "部分历史成绩目标分不在成绩纸带范围内；历史值保留，当前科目使用有效值或默认 100。",
                    affected_count=len(invalid_targets),
                    samples=invalid_targets[:10],
                ))
            if target_conflicts:
                risks.append(_migration_risk(
                    "conflicting-historical-subject-targets",
                    "review",
                    "同一科目的历史成绩有多个目标分；迁移会采用日期最新且有效的值。",
                    affected_count=len(target_conflicts),
                    samples=target_conflicts[:10],
                ))

    try:
        foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
    except sqlite3.DatabaseError:
        foreign_key_rows = []
    if foreign_key_rows:
        risks.append(_migration_risk(
            "existing-foreign-key-violations",
            "blocking",
            "数据库已有外键违规；迁移前必须先修复。",
            affected_count=len(foreign_key_rows),
            samples=[dict(row) for row in foreign_key_rows[:10]],
        ))
    report["blocking_risk_count"] = sum(risk["severity"] == "blocking" for risk in risks)
    report["review_risk_count"] = sum(risk["severity"] == "review" for risk in risks)
    report["ready_without_review"] = not risks
    return report


def subject_migration_report(connection: sqlite3.Connection) -> dict[str, Any]:
    return _focus_hierarchy_report(connection)


def _raise_if_subject_migration_is_unsafe(connection: sqlite3.Connection, *, allow_review: bool = False) -> None:
    report = subject_migration_report(connection)
    prohibited = [
        risk for risk in report["risks"]
        if risk["severity"] == "blocking" or not allow_review
    ]
    if prohibited:
        raise SubjectMigrationBlocked(prohibited)


def _hierarchy_add_columns(connection: sqlite3.Connection, table: str, definitions: dict[str, str]) -> None:
    columns = _table_columns(connection, table)
    for column, definition in definitions.items():
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _hierarchy_ensure_history_columns(connection: sqlite3.Connection) -> None:
    _hierarchy_add_columns(connection, "focus_sessions", {
        "user_id": "INTEGER REFERENCES users(id)",
        "subject_id": "INTEGER REFERENCES user_subjects(id) ON DELETE SET NULL",
        "focus_item_id": "INTEGER REFERENCES user_focus_items(id) ON DELETE SET NULL",
        "client_token": "TEXT",
        "last_foreground_at": "TEXT",
        "focus_locked": "INTEGER NOT NULL DEFAULT 0",
        "trusted": "INTEGER NOT NULL DEFAULT 1",
        "ended_reason": "TEXT",
    })
    for table in ("scores", "plans"):
        _hierarchy_add_columns(connection, table, {
            "user_id": "INTEGER REFERENCES users(id)",
            "subject_id": "INTEGER REFERENCES user_subjects(id) ON DELETE SET NULL",
        })


def _hierarchy_subject_target(
    connection: sqlite3.Connection,
    user_id: int,
    subject_name: str,
    modes: list[dict[str, Any]],
) -> float:
    score_columns = _table_columns(connection, "scores")
    if {"user_id", "subject", "exam_date", "target"}.issubset(score_columns):
        for row in connection.execute("""
            SELECT subject, target
            FROM scores
            WHERE user_id = ?
            ORDER BY exam_date DESC, id DESC
        """, (user_id,)).fetchall():
            if _subject_key(row["subject"]) == _subject_key(subject_name):
                target = _hierarchy_target(row["target"])
                if target is not None:
                    return target
    targets = {_hierarchy_target(mode["target_score"]) for mode in modes}
    targets.discard(None)
    return next(iter(targets)) if len(targets) == 1 else 100


def _migrate_focus_hierarchy(connection: sqlite3.Connection) -> None:
    modes = _hierarchy_mode_rows(connection)
    if not modes or _hierarchy_mode_status(connection) == "complete":
        return
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = {}
    parts_by_id: dict[int, tuple[str, str]] = {}
    for mode in modes:
        parts = _hierarchy_parts(mode["subject"])
        if mode["user_id"] is None or parts is None:
            raise SubjectMigrationBlocked([_migration_risk(
                "legacy-focus-item-not-splittable",
                "blocking",
                "旧专注事项不能安全转换。",
            )])
        parts_by_id[int(mode["id"])] = parts
        grouped.setdefault((int(mode["user_id"]), _subject_key(parts[0])), []).append(mode)

    subject_ids: dict[tuple[int, str], int] = {}
    for (user_id, subject_key), source_modes in grouped.items():
        subject_name = parts_by_id[int(source_modes[0]["id"])][0]
        cursor = connection.execute("""
            INSERT INTO user_subjects(user_id, name, subject_key, target_score)
            VALUES (?, ?, ?, ?)
        """, (
            user_id,
            subject_name,
            subject_key,
            _hierarchy_subject_target(connection, user_id, subject_name, source_modes),
        ))
        subject_ids[(user_id, subject_key)] = int(cursor.lastrowid)

    item_ids: dict[tuple[int, str], tuple[int, int]] = {}
    user_orders: dict[int, int] = {}
    for mode in modes:
        user_id = int(mode["user_id"])
        subject_name, item_name = parts_by_id[int(mode["id"])]
        subject_id = subject_ids[(user_id, _subject_key(subject_name))]
        user_orders[user_id] = user_orders.get(user_id, 0) + 1
        cursor = connection.execute("""
            INSERT INTO user_focus_items(
                user_id, subject_id, name, item_key, sort_order, legacy_mode_id
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            subject_id,
            item_name,
            _subject_key(item_name),
            user_orders[user_id],
            int(mode["id"]),
        ))
        item_ids[(user_id, _subject_key(mode["subject"]))] = (subject_id, int(cursor.lastrowid))

    for table in ("focus_sessions", "scores", "plans"):
        columns = _table_columns(connection, table)
        if not {"id", "user_id", "subject", "subject_id"}.issubset(columns):
            continue
        rows = connection.execute(
            f"SELECT id, user_id, subject FROM {table} WHERE user_id IS NOT NULL AND subject_id IS NULL ORDER BY id"
        ).fetchall()
        for row in rows:
            user_id = int(row["user_id"])
            key = _subject_key(row["subject"])
            item = item_ids.get((user_id, key))
            subject_id = item[0] if item else subject_ids.get((user_id, key))
            if subject_id is None:
                continue
            if table == "focus_sessions" and "focus_item_id" in columns:
                connection.execute(
                    "UPDATE focus_sessions SET subject_id = ?, focus_item_id = ? WHERE id = ?",
                    (subject_id, item[1] if item else None, row["id"]),
                )
            else:
                connection.execute(
                    f"UPDATE {table} SET subject_id = ? WHERE id = ?",
                    (subject_id, row["id"]),
                )


def init_db(connection: sqlite3.Connection, *, allow_subject_migration_review: bool = False) -> None:
    _raise_if_subject_migration_is_unsafe(
        connection,
        allow_review=allow_subject_migration_review,
    )
    connection.executescript(SCHEMA)
    _hierarchy_ensure_history_columns(connection)
    _migrate_focus_hierarchy(connection)
    connection.execute("DROP INDEX IF EXISTS one_active_focus")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_focus_per_user ON focus_sessions(user_id) WHERE status = 'active' AND user_id IS NOT NULL")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS unique_focus_client_token ON focus_sessions(client_token) WHERE client_token IS NOT NULL")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_open_pause_per_session ON focus_pauses(session_id) WHERE ended_at IS NULL")
    connection.execute("CREATE INDEX IF NOT EXISTS daily_settlements_user_date ON daily_settlements(user_id, settlement_date)")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS unique_user_subject_key ON user_subjects(user_id, subject_key)")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS unique_user_focus_item_key ON user_focus_items(user_id, subject_id, item_key)")
    connection.execute("CREATE INDEX IF NOT EXISTS user_focus_item_order ON user_focus_items(user_id, sort_order, id)")
    for key, value in DEFAULT_SETTINGS.items():
        connection.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))
    connection.execute(
        "INSERT OR IGNORE INTO settings(key, value) VALUES ('migration_instance_id', ?)",
        (secrets.token_hex(16),),
    )
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

    if connection.execute("SELECT 1 FROM user_subjects WHERE user_id = ? LIMIT 1", (user_id,)).fetchone():
        return

    source_subjects: list[sqlite3.Row] = []
    source_items: list[sqlite3.Row] = []
    if template_user_id is not None:
        source_subjects = connection.execute("""
            SELECT id, name, target_score
            FROM user_subjects
            WHERE user_id = ?
            ORDER BY id
        """, (template_user_id,)).fetchall()
        source_items = connection.execute("""
            SELECT id, subject_id, name, sort_order
            FROM user_focus_items
            WHERE user_id = ?
            ORDER BY sort_order, id
        """, (template_user_id,)).fetchall()

    subject_ids: dict[object, int] = {}
    if source_subjects:
        for row in source_subjects:
            cursor = connection.execute("""
                INSERT INTO user_subjects(user_id, name, subject_key, target_score)
                VALUES (?, ?, ?, ?)
            """, (user_id, row["name"], _subject_key(row["name"]), row["target_score"]))
            subject_ids[row["id"]] = int(cursor.lastrowid)
    else:
        for name, target in DEFAULT_SUBJECTS:
            cursor = connection.execute("""
                INSERT INTO user_subjects(user_id, name, subject_key, target_score)
                VALUES (?, ?, ?, ?)
            """, (user_id, name, _subject_key(name), target))
            subject_ids[name] = int(cursor.lastrowid)

    if source_items:
        for row in source_items:
            connection.execute("""
                INSERT INTO user_focus_items(user_id, subject_id, name, item_key, sort_order)
                VALUES (?, ?, ?, ?, ?)
            """, (
                user_id,
                subject_ids[row["subject_id"]],
                row["name"],
                _subject_key(row["name"]),
                row["sort_order"],
            ))
    else:
        for order, (subject_name, item_name) in enumerate(DEFAULT_FOCUS_ITEMS, start=1):
            connection.execute("""
                INSERT INTO user_focus_items(user_id, subject_id, name, item_key, sort_order)
                VALUES (?, ?, ?, ?, ?)
            """, (
                user_id,
                subject_ids[subject_name],
                item_name,
                _subject_key(item_name),
                order,
            ))


def get_settings(connection: sqlite3.Connection, user_id: int | None = None) -> dict[str, str]:
    table = "user_settings" if user_id is not None else "settings"
    params = (user_id,) if user_id is not None else ()
    values = {row["key"]: row["value"] for row in connection.execute(f"SELECT key, value FROM {table}" + (" WHERE user_id = ?" if user_id is not None else ""), params)}
    if user_id is not None:
        return {**DEFAULT_SETTINGS, **values}
    return values


def list_focus_modes(connection: sqlite3.Connection, user_id: int | None = None) -> list[dict[str, Any]]:
    if user_id is None:
        return []
    return [
        {**item, "subject": f"{item['subject']}{item['name']}"}
        for item in list_focus_items(connection, user_id)
    ]


def list_focus_items(connection: sqlite3.Connection, user_id: int | None) -> list[dict[str, Any]]:
    where = "WHERE item.user_id = ?" if user_id is not None else ""
    params = (user_id,) if user_id is not None else ()
    return _rows(connection, f"""
        SELECT item.id, item.subject_id, item.name, item.sort_order,
               subject.name AS subject,
               subject.name || ' · ' || item.name AS label
        FROM user_focus_items AS item
        JOIN user_subjects AS subject ON subject.id = item.subject_id
        {where}
        ORDER BY item.sort_order, item.id
    """, params)


def list_subjects(connection: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
    return _rows(connection, """
        SELECT id, name, target_score AS target
        FROM user_subjects
        WHERE user_id = ?
        ORDER BY id
    """, (user_id,))


def get_subject(connection: sqlite3.Connection, user_id: int, subject_id: int) -> dict[str, Any] | None:
    row = connection.execute("""
        SELECT id, name, target_score
        FROM user_subjects
        WHERE user_id = ? AND id = ?
    """, (user_id, subject_id)).fetchone()
    return dict(row) if row else None


def get_subject_by_name(connection: sqlite3.Connection, user_id: int, subject: str) -> dict[str, Any] | None:
    row = connection.execute("""
        SELECT id, name, target_score
        FROM user_subjects
        WHERE user_id = ? AND subject_key = ?
    """, (user_id, _subject_key(subject))).fetchone()
    if row:
        return dict(row)
    item = get_focus_item_by_name(connection, user_id, subject)
    return get_subject(connection, user_id, int(item["subject_id"])) if item else None


def _subject_values(name: str, target_score: float) -> tuple[str, str, float]:
    subject = unicodedata.normalize("NFKC", str(name)).strip()
    key = _subject_key(subject)
    try:
        target = float(target_score)
    except (TypeError, ValueError) as error:
        raise ValueError("invalid_subject") from error
    if not key or len(subject) > 24 or not math.isfinite(target) or target <= 0 or target > 199:
        raise ValueError("invalid_subject")
    return subject, key, target


def create_subject(connection: sqlite3.Connection, user_id: int, name: str, target_score: float) -> dict[str, Any]:
    subject, key, target = _subject_values(name, target_score)
    cursor = connection.execute("""
        INSERT INTO user_subjects(user_id, name, subject_key, target_score)
        VALUES (?, ?, ?, ?)
    """, (user_id, subject, key, target))
    return get_subject(connection, user_id, int(cursor.lastrowid)) or {}


def update_subject(connection: sqlite3.Connection, user_id: int, subject_id: int, name: str, target_score: float) -> dict[str, Any] | None:
    if not get_subject(connection, user_id, subject_id):
        return None
    subject, key, target = _subject_values(name, target_score)
    connection.execute("""
        UPDATE user_subjects
        SET name = ?, subject_key = ?, target_score = ?
        WHERE user_id = ? AND id = ?
    """, (subject, key, target, user_id, subject_id))
    return get_subject(connection, user_id, subject_id)


def delete_subject(connection: sqlite3.Connection, user_id: int, subject_id: int) -> bool:
    cursor = connection.execute("DELETE FROM user_subjects WHERE user_id = ? AND id = ?", (user_id, subject_id))
    return cursor.rowcount == 1


def _focus_item_values(name: str) -> tuple[str, str]:
    item_name = unicodedata.normalize("NFKC", str(name)).strip()
    item_key = _subject_key(item_name)
    if not item_key or len(item_name) > 24:
        raise ValueError("invalid_focus_item")
    return item_name, item_key


def get_focus_item(connection: sqlite3.Connection, user_id: int, focus_item_id: int) -> dict[str, Any] | None:
    row = connection.execute("""
        SELECT item.id, item.subject_id, item.name, item.sort_order,
               subject.name AS subject,
               subject.name || ' · ' || item.name AS label
        FROM user_focus_items AS item
        JOIN user_subjects AS subject ON subject.id = item.subject_id
        WHERE item.user_id = ? AND item.id = ?
    """, (user_id, focus_item_id)).fetchone()
    return dict(row) if row else None


def get_focus_item_by_name(connection: sqlite3.Connection, user_id: int, name: str) -> dict[str, Any] | None:
    key = _subject_key(name)
    matches = [
        item
        for item in list_focus_items(connection, user_id)
        if key in {_subject_key(item["label"]), _subject_key(f"{item['subject']}{item['name']}")}
    ]
    return matches[0] if len(matches) == 1 else None


def create_focus_item(
    connection: sqlite3.Connection,
    user_id: int,
    subject_id: int,
    name: str,
) -> dict[str, Any]:
    if not get_subject(connection, user_id, subject_id):
        raise ValueError("subject_not_found")
    item_name, item_key = _focus_item_values(name)
    next_order = connection.execute(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM user_focus_items WHERE user_id = ?",
        (user_id,),
    ).fetchone()[0]
    cursor = connection.execute("""
        INSERT INTO user_focus_items(user_id, subject_id, name, item_key, sort_order)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, subject_id, item_name, item_key, next_order))
    return get_focus_item(connection, user_id, int(cursor.lastrowid)) or {}


def update_focus_item(
    connection: sqlite3.Connection,
    user_id: int,
    focus_item_id: int,
    subject_id: int,
    name: str,
) -> dict[str, Any] | None:
    if not get_focus_item(connection, user_id, focus_item_id):
        return None
    if not get_subject(connection, user_id, subject_id):
        raise ValueError("subject_not_found")
    item_name, item_key = _focus_item_values(name)
    connection.execute("""
        UPDATE user_focus_items
        SET subject_id = ?, name = ?, item_key = ?
        WHERE user_id = ? AND id = ?
    """, (subject_id, item_name, item_key, user_id, focus_item_id))
    return get_focus_item(connection, user_id, focus_item_id)


def delete_focus_item(connection: sqlite3.Connection, user_id: int, focus_item_id: int) -> bool:
    cursor = connection.execute(
        "DELETE FROM user_focus_items WHERE user_id = ? AND id = ?",
        (user_id, focus_item_id),
    )
    return cursor.rowcount == 1


def reorder_focus_items(
    connection: sqlite3.Connection,
    user_id: int,
    focus_item_ids: list[int],
) -> list[dict[str, Any]]:
    current_ids = {
        int(row["id"])
        for row in connection.execute(
            "SELECT id FROM user_focus_items WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    }
    requested_ids = [int(item_id) for item_id in focus_item_ids]
    if len(requested_ids) != len(set(requested_ids)) or set(requested_ids) != current_ids:
        raise ValueError("invalid_focus_item_order")
    for order, focus_item_id in enumerate(requested_ids, start=1):
        connection.execute(
            "UPDATE user_focus_items SET sort_order = ? WHERE user_id = ? AND id = ?",
            (order, user_id, focus_item_id),
        )
    return list_focus_items(connection, user_id)


def replace_focus_modes(connection: sqlite3.Connection, subjects: list[str], user_id: int | None = None) -> None:
    raise ValueError("focus_item_crud_required")


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


def finish_focus_session(connection: sqlite3.Connection, session_id: int, ended_at: str, reason: str = "manual") -> None:
    connection.execute(
        "UPDATE focus_pauses SET ended_at = ? WHERE session_id = ? AND ended_at IS NULL",
        (ended_at, session_id),
    )
    connection.execute(
        "UPDATE focus_sessions SET ended_at = ?, status = 'completed', ended_reason = ? WHERE id = ? AND status = 'active'",
        (ended_at, reason, session_id),
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
    finish_focus_session(connection, row["id"], ended_at, "foreground_timeout")
    connection.commit()
    return int(row["id"])


def record_foreground_heartbeat(
    connection: sqlite3.Connection,
    now: datetime,
    session_id: int | None = None,
    allow_recovery: bool = False,
) -> dict[str, Any]:
    now_value = now.isoformat()
    connection.execute("BEGIN IMMEDIATE")
    active = connection.execute(
        "SELECT id FROM focus_sessions WHERE status = 'active' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    recovered = False
    if active:
        connection.execute(
            "UPDATE focus_sessions SET last_foreground_at = ? WHERE id = ?",
            (now_value, active["id"]),
        )
        session_id = int(active["id"])
    elif session_id is not None and allow_recovery:
        row = connection.execute(
            "SELECT id FROM focus_sessions WHERE id = ? AND status = 'completed' AND ended_reason = 'foreground_timeout'",
            (session_id,),
        ).fetchone()
        if row:
            connection.execute(
                "UPDATE focus_sessions SET status = 'active', ended_at = NULL, ended_reason = NULL, last_foreground_at = ? WHERE id = ?",
                (now_value, session_id),
            )
            recovered = True
    row = connection.execute(
        "SELECT id, status, ended_reason FROM focus_sessions WHERE id = ?",
        (session_id,),
    ).fetchone() if session_id is not None else None
    connection.commit()
    return {
        "ok": True,
        "session_id": int(row["id"]) if row else None,
        "status": row["status"] if row else None,
        "ended_reason": row["ended_reason"] if row else None,
        "recovered": recovered,
    }


def create_migration_code(connection: sqlite3.Connection, now: datetime, lifetime_seconds: int = 900) -> dict[str, str]:
    code = secrets.token_urlsafe(24)
    expires_at = now + timedelta(seconds=lifetime_seconds)
    connection.execute(
        "INSERT INTO migration_tokens(code_hash, created_at, expires_at) VALUES (?, ?, ?)",
        (hashlib.sha256(code.encode("utf-8")).hexdigest(), now.isoformat(), expires_at.isoformat()),
    )
    connection.commit()
    return {"code": code, "expires_at": expires_at.isoformat()}


def consume_migration_code(connection: sqlite3.Connection, code: str, now: datetime) -> bool:
    code_hash = hashlib.sha256(code.strip().encode("utf-8")).hexdigest()
    connection.execute("BEGIN IMMEDIATE")
    row = connection.execute(
        "SELECT id FROM migration_tokens WHERE code_hash = ? AND used_at IS NULL AND expires_at > ?",
        (code_hash, now.isoformat()),
    ).fetchone()
    if not row:
        connection.rollback()
        return False
    connection.execute("UPDATE migration_tokens SET used_at = ? WHERE id = ?", (now.isoformat(), row["id"]))
    connection.commit()
    return True


def export_migration_data(connection: sqlite3.Connection, now: datetime) -> dict[str, Any]:
    connection.execute("BEGIN")
    try:
        settings = get_settings(connection)
        instance_id = settings.pop("migration_instance_id")
        package = {
            "format": "408-dashboard-migration",
            "version": 3,
            "source_instance_id": instance_id,
            "exported_at": now.isoformat(),
            "settings": settings,
            "focus_items": list_focus_items(connection, None),
            "user_subjects": _rows(connection, "SELECT * FROM user_subjects ORDER BY id"),
            "user_focus_items": _rows(connection, "SELECT * FROM user_focus_items ORDER BY id"),
            "focus_sessions": _rows(connection, "SELECT * FROM focus_sessions ORDER BY id"),
            "focus_pauses": _rows(connection, "SELECT * FROM focus_pauses ORDER BY id"),
            "scores": list_scores(connection),
            "plans": list_plans(connection),
        }
        if _table_exists(connection, "user_focus_modes"):
            package["legacy_user_focus_modes"] = _rows(
                connection,
                "SELECT * FROM user_focus_modes ORDER BY id",
            )
        connection.commit()
        return package
    except Exception:
        connection.rollback()
        raise


def list_scores(connection: sqlite3.Connection, user_id: int | None = None) -> list[dict[str, Any]]:
    if user_id is None:
        return _rows(connection, "SELECT id, subject_id, subject, exam_date, score, target FROM scores ORDER BY id")
    return _rows(connection, "SELECT id, subject_id, subject, exam_date, score, target FROM scores WHERE user_id = ? ORDER BY id", (user_id,))


def list_latest_scores(connection: sqlite3.Connection, user_id: int | None = None) -> list[dict[str, Any]]:
    return _rows(connection, """
        SELECT score.id, score.subject_id, score.subject, score.exam_date, score.score, score.target
        FROM scores AS score
        WHERE score.user_id = ? AND score.id = (
            SELECT latest.id FROM scores AS latest
            WHERE latest.user_id = score.user_id
              AND (
                  (latest.subject_id IS NOT NULL AND latest.subject_id = score.subject_id)
                  OR (latest.subject_id IS NULL AND score.subject_id IS NULL AND latest.subject = score.subject)
              )
            ORDER BY latest.exam_date DESC, latest.id DESC
            LIMIT 1
        )
        ORDER BY score.id
    """, (user_id,))


def list_plans(connection: sqlite3.Connection, user_id: int | None = None) -> list[dict[str, Any]]:
    if user_id is None:
        return _rows(connection, "SELECT id, subject_id, week_start, subject, title, target_minutes, completed_minutes FROM plans ORDER BY week_start")
    return _rows(connection, "SELECT id, subject_id, week_start, subject, title, target_minutes, completed_minutes FROM plans WHERE user_id = ? ORDER BY week_start", (user_id,))


def clear_user_data(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN IMMEDIATE")
    connection.execute("DELETE FROM focus_sessions")
    connection.execute("DELETE FROM daily_settlements")
    connection.execute("DELETE FROM scores")
    connection.execute("DELETE FROM plans")
    connection.execute("DELETE FROM sqlite_sequence WHERE name IN ('focus_sessions', 'focus_pauses', 'scores', 'plans', 'daily_settlements')")
    connection.commit()
