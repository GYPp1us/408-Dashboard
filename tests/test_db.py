def test_database_seeds_default_settings_and_modes(tmp_path):
    from app.db import connect, init_db, list_focus_modes, get_settings, list_scores, list_plans

    connection = connect(str(tmp_path / "seed.sqlite3"))
    init_db(connection)

    settings = get_settings(connection)
    modes = list_focus_modes(connection)
    scores = list_scores(connection)
    plans = list_plans(connection)

    assert settings["morning_start"] == "08:00"
    assert settings["lunch_start"] == "12:00"
    assert settings["library_close"] == "22:00"
    assert [mode["duration_minutes"] for mode in modes] == [0, 0, 0, 0]
    assert {mode["name"] for mode in modes} == {"专注"}
    assert len(scores) == 0
    assert len(plans) == 0


def test_database_initialization_is_idempotent(tmp_path):
    from app.db import connect, init_db, list_focus_modes, list_scores, list_plans

    connection = connect(str(tmp_path / "repeat.sqlite3"))
    init_db(connection)
    init_db(connection)

    assert len(list_focus_modes(connection)) == 4
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
    assert len(list_focus_modes(connection)) == 4
