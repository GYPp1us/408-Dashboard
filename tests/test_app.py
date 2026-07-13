def test_app_factory_uses_test_database(tmp_path):
    from app import create_app

    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "test.sqlite3"),
        "SECRET_KEY": "test-secret",
        "ADMIN_PASSWORD": "test-password",
    })

    assert app.config["TESTING"] is True
    assert app.config["DATABASE"].endswith("test.sqlite3")
