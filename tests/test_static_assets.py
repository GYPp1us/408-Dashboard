import hashlib
import os
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

import pytest

from app import create_app


@pytest.fixture()
def app(tmp_path):
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "assets.sqlite3"),
                       "SECRET_KEY": "test", "ADMIN_PASSWORD": "password", "COOKIE_SECURE": False})


def test_static_asset_fingerprints_change_after_live_edit_and_cache_unchanged_files(app, tmp_path, monkeypatch):
    folder = tmp_path / "static"
    folder.mkdir()
    asset = folder / "sample.js"
    asset.write_bytes(b"const value = 1;")
    app.static_folder = str(folder)
    read_bytes = Path.read_bytes
    reads = []

    def record_read(path):
        reads.append(path)
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", record_read)
    helper = app.jinja_env.globals["static_asset"]
    with app.test_request_context():
        original = helper("sample.js")
        assert helper("sample.js") == original
        assert reads == [asset]
        assert parse_qs(urlsplit(original).query)["v"] == [hashlib.sha256(b"const value = 1;").hexdigest()[:16]]
        first_stat = asset.stat()
        asset.write_bytes(b"const value = 2;")
        os.utime(asset, ns=(first_stat.st_atime_ns, first_stat.st_mtime_ns + 1_000_000_000))
        changed = helper("sample.js")
        assert changed != original
        assert helper("sample.js") == changed
        assert len(reads) == 2
        assert parse_qs(urlsplit(changed).query)["v"] == [hashlib.sha256(b"const value = 2;").hexdigest()[:16]]
    assert app.test_client().get(changed).data == b"const value = 2;"


def test_content_version_survives_mtime_only_change_and_missing_assets_are_normal_404(app, tmp_path):
    folder = tmp_path / "static"
    folder.mkdir()
    asset = folder / "sample.css"
    asset.write_bytes(b"body { color: red; }")
    app.static_folder = str(folder)
    helper = app.jinja_env.globals["static_asset"]
    with app.test_request_context():
        first = helper("sample.css")
        metadata = asset.stat()
        os.utime(asset, ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 1_000_000_000))
        assert helper("sample.css") == first
        assert helper("missing.css") == "/static/missing.css"
        with pytest.raises(ValueError):
            helper("../outside.css")
    assert app.test_client().get("/static/missing.css").status_code == 404


def test_rendered_dashboard_and_index_version_all_css_and_javascript(app):
    client = app.test_client()
    client.get("/guest")
    for path in ("/guest", "/focus-kline"):
        response = client.get(path)
        assert response.status_code == 200
        assets = re.findall(r'(?:href|src)="(/static/[^" ]+\.(?:css|js)(?:\?[^" ]*)?)"', response.get_data(as_text=True))
        assert assets
        for url in assets:
            assert re.fullmatch(r"[0-9a-f]{16}", parse_qs(urlsplit(url).query)["v"][0])
            assert client.get(url).status_code == 200
