def test_database_seeds_default_settings_and_modes(tmp_path):
    from app.db import connect, get_focus_messages, init_db, list_focus_modes, get_settings, list_scores, list_plans

    connection = connect(str(tmp_path / "seed.sqlite3"))
    init_db(connection)

    settings = get_settings(connection)
    modes = list_focus_modes(connection)
    scores = list_scores(connection)
    plans = list_plans(connection)

    assert settings["morning_start"] == "08:00"
    assert settings["lunch_start"] == "12:00"
    assert settings["library_open"] == "13:30"
    assert settings["library_close"] == "22:00"
    assert settings["heatmap_visible_hours"] == "0,2,4,6,8,10,12,14,16,18,20,22"
    assert [mode["subject"] for mode in modes] == ["408二轮", "数学二轮", "英语二轮", "政治一轮", "408模拟", "数学模拟"]
    assert [mode["duration_minutes"] for mode in modes] == [0, 0, 0, 0, 0, 0]
    assert {mode["name"] for mode in modes} == {"专注"}
    assert len(get_focus_messages(connection)) == 31
    assert get_focus_messages(connection)[-1]["text"] == "忽略该忽略的，专注该专注的"
    assert len(scores) == 0
    assert len(plans) == 0


def test_database_initialization_is_idempotent(tmp_path):
    from app.db import connect, init_db, list_focus_modes, list_scores, list_plans

    connection = connect(str(tmp_path / "repeat.sqlite3"))
    init_db(connection)
    init_db(connection)

    assert len(list_focus_modes(connection)) == 6
    assert list_scores(connection) == []
    assert list_plans(connection) == []


def test_clear_user_data_preserves_modes_and_settings(tmp_path):
    from app.db import clear_user_data, connect, init_db, list_focus_modes, list_plans, list_scores

    connection = connect(str(tmp_path / "clear.sqlite3"))
    init_db(connection)
    connection.execute("INSERT INTO scores(subject, exam_date, score, target) VALUES ('数学', '2026-07-14', 100, 130)")
    connection.execute("INSERT INTO plans(week_start, subject, title, target_minutes, completed_minutes) VALUES ('2026-07-14', '数学', '测试', 100, 0)")
    connection.commit()

    clear_user_data(connection)

    assert list_scores(connection) == []
    assert list_plans(connection) == []
    assert len(list_focus_modes(connection)) == 6


def test_database_preserves_custom_focus_content_on_reinitialization(tmp_path):
    from app.db import connect, get_focus_messages, init_db, list_focus_modes, replace_focus_modes, save_focus_messages

    connection = connect(str(tmp_path / "legacy-modes.sqlite3"))
    init_db(connection)
    replace_focus_modes(connection, ["专业课", "数学", "自定义"])
    save_focus_messages(connection, [{"category": "提醒", "text": "只做当前题"}])
    connection.commit()

    init_db(connection)

    modes = list_focus_modes(connection)
    assert [mode["subject"] for mode in modes] == ["专业课", "数学", "自定义"]
    assert {mode["name"] for mode in modes} == {"专注"}
    assert {mode["duration_minutes"] for mode in modes} == {0}
    assert get_focus_messages(connection) == [{"category": "提醒", "text": "只做当前题"}]


def test_database_migrates_existing_focus_rows_as_trusted(tmp_path):
    import sqlite3

    from app.db import init_db

    connection = sqlite3.connect(tmp_path / "legacy.sqlite3")
    connection.row_factory = sqlite3.Row
    connection.execute("""
        CREATE TABLE focus_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            mode TEXT NOT NULL,
            planned_minutes INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            status TEXT NOT NULL,
            client_token TEXT UNIQUE,
            interruption_count INTEGER NOT NULL DEFAULT 0
        )
    """)
    connection.execute("INSERT INTO focus_sessions(subject, mode, planned_minutes, started_at, ended_at, status) VALUES ('数学', '专注', 0, '2026-07-16T08:00:00+00:00', '2026-07-16T09:00:00+00:00', 'completed')")
    connection.commit()

    init_db(connection)

    row = connection.execute("SELECT trusted, focus_locked, last_foreground_at FROM focus_sessions").fetchone()
    assert dict(row) == {"trusted": 1, "focus_locked": 0, "last_foreground_at": None}
    assert connection.execute("SELECT COUNT(*) FROM focus_pauses").fetchone()[0] == 0


def test_foreground_timeout_ends_running_focus_but_skips_paused_and_locked_focus(tmp_path):
    from datetime import datetime, timedelta, timezone

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
