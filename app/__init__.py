from pathlib import Path
import hashlib
from threading import Lock

from flask import Flask, url_for
from werkzeug.security import generate_password_hash

from .config import default_config
from .auth import register_auth
from .db import connect, ensure_site_owner, init_db
from .focus_monitor import start_focus_monitor
from .focus_reporter import materialize_legacy_reporter_keys
from .routes import register_routes
from .dashboard_artwork import register_dashboard_artwork


def register_static_assets(app: Flask) -> None:
    """Use content versions while rehashing only files whose metadata changed."""
    fingerprints: dict[Path, tuple[tuple[int, int], str]] = {}
    fingerprint_lock = Lock()

    def static_asset(filename: str) -> str:
        static_root = Path(app.static_folder).resolve()
        asset = (static_root / filename).resolve()
        if not asset.is_relative_to(static_root):
            raise ValueError("Static asset must stay within the static directory")
        try:
            metadata = asset.stat()
            if not asset.is_file():
                return url_for("static", filename=filename)
            signature = (metadata.st_mtime_ns, metadata.st_size)
            with fingerprint_lock:
                cached = fingerprints.get(asset)
                if cached is None or cached[0] != signature:
                    version = hashlib.sha256(asset.read_bytes()).hexdigest()[:16]
                    fingerprints[asset] = (signature, version)
                else:
                    version = cached[1]
        except OSError:
            # Missing assets keep the normal static endpoint's 404 behavior.
            return url_for("static", filename=filename)
        return url_for("static", filename=filename, v=version)

    app.jinja_env.globals["static_asset"] = static_asset


def create_app(overrides: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(default_config())
    if overrides:
        app.config.from_mapping(overrides)
    app.config["SESSION_COOKIE_SECURE"] = app.config["COOKIE_SECURE"]
    register_static_assets(app)

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    connection = connect(app.config["DATABASE"])
    init_db(connection)
    materialize_legacy_reporter_keys(connection, app.config["SECRET_KEY"])
    ensure_site_owner(
        connection,
        app.config["ADMIN_USERNAME"],
        app.config["ADMIN_EMAIL"],
        generate_password_hash(app.config["ADMIN_PASSWORD"] or "unconfigured-owner-password"),
    )
    connection.close()
    register_auth(app)
    register_routes(app)
    register_dashboard_artwork(app)
    start_focus_monitor(app)

    return app
