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
    assert [mode["duration_minutes"] for mode in modes] == [90, 50, 25, 0]
    assert len(scores) == 4
    assert len(plans) == 3
