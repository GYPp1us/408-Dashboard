from pathlib import Path

from flask import Flask

from .config import default_config
from .auth import register_auth
from .db import connect, init_db
from .focus_monitor import start_focus_monitor
from .routes import register_routes


def create_app(overrides: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(default_config())
    if overrides:
        app.config.from_mapping(overrides)
    app.config["SESSION_COOKIE_SECURE"] = app.config["COOKIE_SECURE"]

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    connection = connect(app.config["DATABASE"])
    init_db(connection)
    connection.close()
    register_auth(app)
    register_routes(app)
    start_focus_monitor(app)

    return app
