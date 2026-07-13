from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent.parent


def default_config() -> dict:
    return {
        "SECRET_KEY": os.environ.get("DASHBOARD_SECRET_KEY", "dev-only-secret"),
        "ADMIN_PASSWORD": os.environ.get("DASHBOARD_ADMIN_PASSWORD", ""),
        "DATABASE": os.environ.get("DASHBOARD_DATABASE", str(BASE_DIR / "data" / "dashboard.sqlite3")),
        "HOST": os.environ.get("DASHBOARD_HOST", "127.0.0.1"),
        "PORT": int(os.environ.get("DASHBOARD_PORT", "43127")),
        "COOKIE_SECURE": os.environ.get("COOKIE_SECURE", "0") == "1",
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
    }
