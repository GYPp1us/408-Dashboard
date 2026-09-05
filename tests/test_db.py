import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def _legacy_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            email TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE user_focus_modes (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            subject TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL
        );
        CREATE TABLE focus_sessions (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            subject TEXT NOT NULL,
            mode TEXT NOT NULL,
            planned_minutes INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            status TEXT NOT NULL
        );
        CREATE TABLE scores (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            subject TEXT NOT NULL,
            exam_date TEXT NOT NULL,
            score REAL NOT NULL,
            target REAL NOT NULL
        );
        CREATE TABLE plans (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            week_start TEXT NOT NULL,
            subject TEXT NOT NULL,
            title TEXT NOT NULL,
            target_minutes INTEGER NOT NULL,
            completed_minutes INTEGER NOT NULL DEFAULT 0
        );
    """)
    connection.execute(
        "INSERT INTO users VALUES (1, 'owner', 'owner@example.com', 'hash', 'site_owner', '2026-07-01T00:00:00+00:00')"
    )
    return connection


def _insert_default_legacy_items(connection: sqlite3.Connection) -> None:
    for item_id, name in enumerate(("408二轮", "数学二轮", "英语二轮", "政治一轮", "408模拟", "数学模拟"), start=1):
        connection.execute(
            "INSERT INTO user_focus_modes VALUES (?, 1, '专注', ?, 0)",
            (item_id, name),
        )


def test_database_seeds_subjects_and_focus_items_for_a_profile(tmp_path):
    from app.db import (
        connect,
        ensure_site_owner,
        get_focus_messages,
        get_settings,
        init_db,
        list_focus_items,
        list_plans,
        list_scores,
        list_subjects,
    )

    connection = connect(str(tmp_path / "seed.sqlite3"))
    init_db(connection)
    owner_id = ensure_site_owner(connection, "owner", "owner@example.com", "hash")

    assert get_settings(connection)["morning_start"] == "08:00"
    assert get_settings(connection)["heatmap_visible_hours"] == "0,2,4,6,8,10,12,14,16,18,20,22"
    assert [row["name"] for row in list_subjects(connection, owner_id)] == ["408", "数学", "英语", "政治"]
    assert [row["label"] for row in list_focus_items(connection, owner_id)] == [
        "408 · 二轮",
        "数学 · 二轮",
        "英语 · 二轮",
        "政治 · 一轮",
        "408 · 模拟",
        "数学 · 模拟",
    ]
    assert len(get_focus_messages(connection)) == 31
    assert list_scores(connection) == []
    assert list_plans(connection) == []


def test_new_profile_clones_subjects_focus_items_and_order(tmp_path):
    from app.db import (
        connect,
        create_focus_item,
        create_subject,
        ensure_site_owner,
        get_user_by_username,
        init_db,
        list_focus_items,
        list_subjects,
        create_user,
    )

    connection = connect(str(tmp_path / "profiles.sqlite3"))
    init_db(connection)
    owner_id = ensure_site_owner(connection, "owner", "owner@example.com", "hash")
    extra = create_subject(connection, owner_id, "专业课", 150)
    create_focus_item(connection, owner_id, extra["id"], "三轮")
    connection.commit()

    create_user(connection, "alice", "alice@example.com", "hash", "2026-07-02T00:00:00+00:00")
    alice_id = get_user_by_username(connection, "alice")["id"]

    assert [row["name"] for row in list_subjects(connection, alice_id)] == [
        row["name"] for row in list_subjects(connection, owner_id)
    ]
    assert [row["label"] for row in list_focus_items(connection, alice_id)] == [
        row["label"] for row in list_focus_items(connection, owner_id)
    ]


def test_subject_and_focus_item_crud_keep_ids_and_apply_requested_order(tmp_path):
    from app.db import (
        connect,
        create_focus_item,
        create_subject,
        delete_subject,
        ensure_site_owner,
        get_focus_item,
        init_db,
        list_focus_items,
        reorder_focus_items,
        update_focus_item,
    )

    connection = connect(str(tmp_path / "crud.sqlite3"))
    init_db(connection)
    owner_id = ensure_site_owner(connection, "owner", "owner@example.com", "hash")
    subject = create_subject(connection, owner_id, "算法", 135)
    first = create_focus_item(connection, owner_id, subject["id"], "一轮")
    second = create_focus_item(connection, owner_id, subject["id"], "模拟")
    with pytest.raises(sqlite3.IntegrityError):
        create_focus_item(connection, owner_id, subject["id"], " 模拟 ")

    ordered = reorder_focus_items(
        connection,
        owner_id,
        [second["id"], *[item["id"] for item in list_focus_items(connection, owner_id) if item["id"] not in {first["id"], second["id"]}], first["id"]],
    )
    assert ordered[0]["id"] == second["id"]
    assert ordered[-1]["id"] == first["id"]
    updated = update_focus_item(connection, owner_id, first["id"], subject["id"], "二轮")
    assert updated["label"] == "算法 · 二轮"

    session = connection.execute(
        """
        INSERT INTO focus_sessions(user_id, subject_id, focus_item_id, subject, mode, planned_minutes, started_at, status)
        VALUES (?, ?, ?, '算法 · 二轮', '专注', 0, '2026-07-16T08:00:00+00:00', 'completed')
        """,
        (owner_id, subject["id"], first["id"]),
    )
    connection.execute(
        "INSERT INTO scores(user_id, subject_id, subject, exam_date, score, target) VALUES (?, ?, '算法', '2026-07-16', 120, 135)",
        (owner_id, subject["id"]),
    )
    connection.commit()
    assert delete_subject(connection, owner_id, subject["id"]) is True
    assert get_focus_item(connection, owner_id, first["id"]) is None
    assert tuple(connection.execute(
        "SELECT subject_id, focus_item_id, subject FROM focus_sessions WHERE id = ?",
        (session.lastrowid,),
    ).fetchone()) == (None, None, "算法 · 二轮")
    assert tuple(connection.execute("SELECT subject_id, subject FROM scores").fetchone()) == (None, "算法")


def test_hierarchy_migration_links_only_unambiguous_history_and_preserves_snapshots(tmp_path):
    from app.db import SubjectMigrationBlocked, init_db, subject_migration_report

    connection = _legacy_connection(tmp_path / "legacy.sqlite3")
    _insert_default_legacy_items(connection)
    connection.execute(
        "INSERT INTO focus_sessions VALUES (1, 1, '数学', '专注', 50, '2026-07-14T08:00:00+00:00', '2026-07-14T09:00:00+00:00', 'completed')"
    )
    connection.execute(
        "INSERT INTO focus_sessions VALUES (2, 1, '408二轮', '专注', 50, '2026-07-14T09:00:00+00:00', '2026-07-14T10:00:00+00:00', 'completed')"
    )
    connection.execute(
        "INSERT INTO focus_sessions VALUES (3, 1, '专业课', '专注', 50, '2026-07-14T10:00:00+00:00', '2026-07-14T11:00:00+00:00', 'completed')"
    )
    connection.execute("INSERT INTO scores VALUES (1, 1, '408', '2026-07-14', 130, 150)")
    connection.execute("INSERT INTO plans VALUES (1, 1, '2026-07-14', '数学二轮', '复盘', 60, 0)")
    connection.commit()

    report = subject_migration_report(connection)
    risk = next(risk for risk in report["risks"] if risk["id"] == "historical-subject-not-linked")
    assert risk["severity"] == "review"
    assert risk["affected_count"] == 1
    with pytest.raises(SubjectMigrationBlocked):
        init_db(connection)

    init_db(connection, allow_subject_migration_review=True)

    assert [tuple(row) for row in connection.execute(
        "SELECT name, target_score FROM user_subjects ORDER BY id"
    ).fetchall()] == [("408", 150.0), ("数学", 100.0), ("英语", 100.0), ("政治", 100.0)]
    assert connection.execute("SELECT COUNT(*) FROM user_focus_items").fetchone()[0] == 6
    assert tuple(connection.execute(
        "SELECT subject_id, focus_item_id, subject FROM focus_sessions WHERE id = 1"
    ).fetchone()) == (2, None, "数学")
    assert tuple(connection.execute(
        "SELECT subject_id, focus_item_id, subject FROM focus_sessions WHERE id = 2"
    ).fetchone()) == (1, 1, "408二轮")
    assert tuple(connection.execute(
        "SELECT subject_id, focus_item_id, subject FROM focus_sessions WHERE id = 3"
    ).fetchone()) == (None, None, "专业课")
    assert tuple(connection.execute("SELECT subject_id, subject FROM scores").fetchone()) == (1, "408")
    assert tuple(connection.execute("SELECT subject_id, subject FROM plans").fetchone()) == (2, "数学二轮")
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert subject_migration_report(connection)["risks"] == []


def test_hierarchy_migration_blocks_unsplittable_or_unowned_source_rows(tmp_path):
    from app.db import SubjectMigrationBlocked, init_db, subject_migration_report

    connection = _legacy_connection(tmp_path / "blocked.sqlite3")
    connection.execute("INSERT INTO user_focus_modes VALUES (1, 1, '专注', '数学', 0)")
    connection.execute("INSERT INTO user_focus_modes VALUES (2, 9, '专注', '408二轮', 0)")
    connection.commit()

    report = subject_migration_report(connection)
    assert report["blocking_risk_count"] >= 2
    assert {risk["id"] for risk in report["risks"]} >= {
        "legacy-focus-item-not-splittable",
        "subject-data-user-not-found",
    }
    with pytest.raises(SubjectMigrationBlocked):
        init_db(connection, allow_subject_migration_review=True)
    assert not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_subjects'"
    ).fetchone()


def test_hierarchy_migration_blocks_partial_new_schema_before_any_write(tmp_path):
    from app.db import SubjectMigrationBlocked, init_db, subject_migration_report

    connection = _legacy_connection(tmp_path / "partial.sqlite3")
    connection.execute("""
        CREATE TABLE user_subjects (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL
        )
    """)
    connection.commit()

    report = subject_migration_report(connection)
    assert {risk["id"] for risk in report["risks"]} >= {
        "partial-focus-hierarchy-schema",
        "unsupported-canonical-subject-schema",
    }
    with pytest.raises(SubjectMigrationBlocked):
        init_db(connection, allow_subject_migration_review=True)
    assert not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_focus_items'"
    ).fetchone()


def test_hierarchy_migration_reports_conflicting_score_targets_for_review(tmp_path):
    from app.db import SubjectMigrationBlocked, init_db, subject_migration_report

    connection = _legacy_connection(tmp_path / "targets.sqlite3")
    connection.execute("INSERT INTO user_focus_modes VALUES (1, 1, '专注', '数学二轮', 0)")
    connection.execute("INSERT INTO scores VALUES (1, 1, '数学', '2026-07-15', 110, 120)")
    connection.execute("INSERT INTO scores VALUES (2, 1, '数学', '2026-07-16', 130, 150)")
    connection.commit()

    report = subject_migration_report(connection)
    risk = next(risk for risk in report["risks"] if risk["id"] == "conflicting-historical-subject-targets")
    assert risk["severity"] == "review"
    with pytest.raises(SubjectMigrationBlocked):
        init_db(connection)
    init_db(connection, allow_subject_migration_review=True)
    assert connection.execute("SELECT target_score FROM user_subjects").fetchone()[0] == 150


def test_hierarchy_migration_runner_requires_explicit_review_approval(tmp_path):
    database = tmp_path / "runner.sqlite3"
    connection = _legacy_connection(database)
    connection.execute("INSERT INTO user_focus_modes VALUES (1, 1, '专注', '数学二轮', 0)")
    connection.execute(
        "INSERT INTO focus_sessions VALUES (1, 1, '历史课', '专注', 0, '2026-07-16T08:00:00+00:00', '2026-07-16T09:00:00+00:00', 'completed')"
    )
    connection.commit()
    connection.close()

    root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, "PYTHONPATH": str(root)}
    command = [sys.executable, str(root / "scripts" / "migrate_subject_schema.py"), str(database)]
    blocked = subprocess.run(command, cwd=root, env=environment, text=True, capture_output=True, check=False)
    assert blocked.returncode == 2
    assert json.loads(blocked.stdout)["applied"] is False

    approved = subprocess.run([*command, "--approve-review"], cwd=root, env=environment, text=True, capture_output=True, check=False)
    assert approved.returncode == 0
    assert json.loads(approved.stdout)["applied"] is True
    connection = sqlite3.connect(database)
    assert {"user_subjects", "user_focus_items"} <= {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    connection.close()


def test_reviewed_history_discarder_requires_an_exact_approved_row_set(tmp_path):
    database = tmp_path / "discard.sqlite3"
    connection = _legacy_connection(database)
    _insert_default_legacy_items(connection)
    connection.execute(
        "INSERT INTO focus_sessions VALUES (1, 1, '专业课', '专注', 0, '2026-07-16T08:00:00+00:00', '2026-07-16T09:00:00+00:00', 'completed')"
    )
    connection.execute(
        "INSERT INTO focus_sessions VALUES (2, 1, '自定义', '专注', 0, '2026-07-16T09:00:00+00:00', '2026-07-16T10:00:00+00:00', 'completed')"
    )
    connection.commit()
    connection.close()

    root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, "PYTHONPATH": str(root)}
    command = [
        sys.executable,
        str(root / "scripts" / "discard_review_history.py"),
        str(database),
        "--row", "focus_sessions:1",
        "--row", "focus_sessions:2",
        "--expected-subject", "专业课",
        "--expected-subject", "自定义",
    ]
    confirmation_required = subprocess.run(command, cwd=root, env=environment, text=True, capture_output=True, check=False)
    assert confirmation_required.returncode == 2

    incomplete = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "discard_review_history.py"),
            str(database),
            "--row", "focus_sessions:1",
            "--expected-subject", "专业课",
            "--expected-subject", "自定义",
            "--confirm-discard",
        ],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert incomplete.returncode == 1

    approved = subprocess.run(
        [*command, "--confirm-discard"],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert approved.returncode == 0
    result = json.loads(approved.stdout)
    assert result["discarded"] is True
    assert {(row["table"], row["id"], row["subject"]) for row in result["deleted_rows"]} == {
        ("focus_sessions", 1, "专业课"),
        ("focus_sessions", 2, "自定义"),
    }
    assert result["preflight_after"]["risks"] == []

    migration = subprocess.run(
        [sys.executable, str(root / "scripts" / "migrate_subject_schema.py"), str(database)],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert migration.returncode == 0
    assert json.loads(migration.stdout)["applied"] is True


def test_foreground_timeout_ends_running_focus_but_skips_paused_and_locked_focus(tmp_path):
    from app.db import connect, expire_unattended_focus, init_db

    connection = connect(str(tmp_path / "timeout.sqlite3"))
    init_db(connection)
    now = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
    last_foreground = now - timedelta(seconds=31)
    cursor = connection.execute(
        "INSERT INTO focus_sessions(subject, mode, planned_minutes, started_at, status, last_foreground_at) VALUES ('数学', '专注', 0, ?, 'active', ?)",
        ((now - timedelta(minutes=10)).isoformat(), last_foreground.isoformat()),
    )
    connection.commit()

    expired_id = expire_unattended_focus(connection, now, 30)
    expected_end = (last_foreground + timedelta(seconds=30)).isoformat()
    row = connection.execute("SELECT status, ended_at, trusted FROM focus_sessions WHERE id = ?", (expired_id,)).fetchone()
    assert dict(row) == {"status": "completed", "ended_at": expected_end, "trusted": 1}

    paused = connection.execute(
        "INSERT INTO focus_sessions(subject, mode, planned_minutes, started_at, status, last_foreground_at) VALUES ('数学', '专注', 0, ?, 'active', ?)",
        ((now - timedelta(minutes=5)).isoformat(), last_foreground.isoformat()),
    )
    connection.execute("INSERT INTO focus_pauses(session_id, started_at) VALUES (?, ?)", (paused.lastrowid, (now - timedelta(seconds=40)).isoformat()))
    connection.commit()
    assert expire_unattended_focus(connection, now, 30) is None

    connection.execute("UPDATE focus_pauses SET ended_at = ? WHERE session_id = ? AND ended_at IS NULL", (now.isoformat(), paused.lastrowid))
    connection.execute("UPDATE focus_sessions SET ended_at = ?, status = 'completed' WHERE id = ?", (now.isoformat(), paused.lastrowid))
    connection.execute(
        "INSERT INTO focus_sessions(subject, mode, planned_minutes, started_at, status, last_foreground_at, focus_locked, trusted) VALUES ('数学', '专注', 0, ?, 'active', ?, 1, 0)",
        ((now - timedelta(minutes=5)).isoformat(), last_foreground.isoformat()),
    )
    connection.commit()
    assert expire_unattended_focus(connection, now, 30) is None
