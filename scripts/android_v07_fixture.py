"""Loopback-only APK asset preview; never import or deploy into production."""
from pathlib import Path
import sys

from flask import request, send_file

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.android_fixture_server import fixture_app

ASSETS = ROOT / "android/app/src/main/assets/dashboard"
app = fixture_app(ROOT / ".tmp/android-v07-preview.sqlite3", testing=True)


@app.before_request
def apk_assets():
    overrides = {"/static/app.js": "app.js", "/static/viewport-scale.css": "viewport-scale.css",
                 "/static/dashboard-details.js": "dashboard-details.js",
                 "/static/viewport-scale.js": "viewport-scale.js"}
    asset = overrides.get(request.path)
    if asset:
        response = send_file(ASSETS / asset, max_age=0)
        response.headers["Cache-Control"] = "no-store"
        return response


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=43130, use_reloader=False)
