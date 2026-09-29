import base64
from io import BytesIO
from pathlib import Path
import struct
import zlib

from flask import render_template_string, session, template_rendered
import pytest

from app import create_app
from app.dashboard_artwork import DEFAULT_ARTWORK, MAX_IMAGE_BYTES
from app.db import connect, create_user


def png(width=1, height=1, padding=0):
    def chunk(kind, content):
        return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content) & 0xffffffff)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    if padding:
        data += chunk(b"tEXt", b"note\0" + b"x" * padding)
    pixels = (b"\0" + b"\x80\x90\xa0" * width) * height
    return data + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")


GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==")
WEBP = base64.b64decode("UklGRiIAAABXRUJQVlA4IBYAAAAwAQCdASoBAAEADsD+JaQAA3AAAAAA")


@pytest.fixture()
def setup(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "artwork.sqlite3"), "SECRET_KEY": "test",
                      "ADMIN_PASSWORD": "password", "COOKIE_SECURE": False})
    connection = connect(app.config["DATABASE"])
    owner = connection.execute("SELECT id FROM users WHERE role = 'site_owner'").fetchone()["id"]
    other = create_user(connection, "other", "other@example.com", "unused", "2026-09-28T00:00:00+00:00")
    connection.commit()
    connection.close()

    def client(user_id, guest=False, viewing=None):
        result = app.test_client()
        with result.session_transaction() as state:
            state.update(authenticated=True, role="guest" if guest else "user")
            state["profile_user_id" if guest else "user_id"] = user_id
            if viewing is not None:
                state.update(viewing_as_guest=True, profile_user_id=viewing)
        return result

    return app, client, owner, other


def upload(client, data, filename="custom.bin", mime="application/octet-stream"):
    return client.post("/api/dashboard/artwork", data={"image": (BytesIO(data), filename, mime)}, content_type="multipart/form-data")


@pytest.mark.parametrize("data,mime", [(png(), "image/png"),
    (Path("app/static/current-time-art.jpg").read_bytes(), "image/jpeg"), (GIF, "image/gif"), (WEBP, "image/webp")],
    ids=["png", "jpeg", "gif", "webp"])
def test_four_formats_preserve_bytes_and_use_trusted_content_type(setup, data, mime):
    app, client, owner, _ = setup
    response = upload(client(owner), data, "untrusted.svg", "image/svg+xml")
    assert response.status_code == 200
    artwork = response.get_json()["artwork"]
    assert artwork["is_custom"] is True
    assert artwork["url"].startswith(f"/dashboard/artwork/{owner}/")
    image = app.test_client().get(artwork["url"])
    assert image.data == data
    assert image.headers["Content-Type"] == mime
    assert image.headers["X-Content-Type-Options"] == "nosniff"
    assert "immutable" in image.headers["Cache-Control"]
    assert app.test_client().get(artwork["url"], headers={"If-None-Match": image.headers["ETag"]}).status_code == 304


def test_artwork_account_isolation_guest_scope_and_read_only_access(setup):
    app, client, owner, other = setup
    owner_art = upload(client(owner), png()).get_json()["artwork"]
    other_art = upload(client(other), GIF).get_json()["artwork"]
    assert client(owner).get("/api/dashboard/artwork").get_json()["artwork"] == owner_art
    assert client(other).get("/api/dashboard/artwork").get_json()["artwork"] == other_art
    assert client(owner, guest=True).get("/api/dashboard/artwork").get_json()["artwork"] == owner_art
    assert client(other, viewing=owner).get("/api/dashboard/artwork").get_json()["artwork"] == owner_art
    for denied in (app.test_client(), client(owner, guest=True), client(other, viewing=owner)):
        expected = 401 if denied.get("/api/dashboard/artwork").status_code == 401 else 403
        assert upload(denied, png()).status_code == expected
        assert denied.delete("/api/dashboard/artwork").status_code == expected
    assert client(owner).get("/api/dashboard/artwork").get_json()["artwork"] == owner_art
    assert client(other).get("/api/dashboard/artwork").get_json()["artwork"] == other_art


@pytest.mark.parametrize("invalid", [b"", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", b"not an image",
    b"\x89PNG\r\n\x1a\n", png()[:-1], png() + b"extra", b"\xff\xd8\xff\xd9",
    b"GIF89a", GIF[:-1], b"RIFF\x04\0\0\0WEBP", WEBP[:-1]])
def test_invalid_image_leaves_existing_artwork_unchanged(setup, invalid):
    _, client, owner, _ = setup
    result = client(owner)
    artwork = upload(result, png()).get_json()["artwork"]
    response = upload(result, invalid, "valid.png", "image/png")
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_image"
    assert result.get("/api/dashboard/artwork").get_json()["artwork"] == artwork


def test_missing_and_oversized_images_and_multipart_limits_are_atomic(setup):
    _, client, owner, _ = setup
    result = client(owner)
    artwork = upload(result, png()).get_json()["artwork"]
    assert result.post("/api/dashboard/artwork", data={}).get_json()["error"] == "image_required"
    for oversized in (b"x" * (MAX_IMAGE_BYTES + 1), b"x" * (MAX_IMAGE_BYTES + 100000)):
        response = upload(result, oversized)
        assert response.status_code == 413
        assert response.get_json()["error"] == "image_too_large"
    response = result.post("/api/dashboard/artwork", data={"image": (BytesIO(png()), "a.png"), "huge_field": "x" * 300000})
    assert response.status_code == 413
    assert result.get("/api/dashboard/artwork").get_json()["artwork"] == artwork


def test_no_width_limit_large_valid_upload_and_version_replacement_delete(setup):
    app, client, owner, other = setup
    result = client(owner)
    assert result.get("/api/dashboard/artwork").get_json()["artwork"] == DEFAULT_ARTWORK
    # Beyond common screen widths; no resizing, and multipart parser accepts >64 KiB files.
    original = png(width=20000, padding=200000)
    first = upload(result, original).get_json()["artwork"]
    assert app.test_client().get(first["url"]).data == original
    second = upload(result, original).get_json()["artwork"]
    assert first["url"] != second["url"]
    assert app.test_client().get(first["url"]).status_code == 404
    assert app.test_client().get(second["url"].replace(f"/{owner}/", f"/{other}/")).status_code == 404
    assert result.delete("/api/dashboard/artwork").get_json()["artwork"] == DEFAULT_ARTWORK
    assert app.test_client().get(second["url"]).status_code == 404
    assert result.delete("/api/dashboard/artwork").status_code == 200


def test_template_initial_context_and_reads_do_not_change_database(setup):
    app, client, owner, other = setup
    artwork = upload(client(owner), png()).get_json()["artwork"]
    connection = connect(app.config["DATABASE"])
    before = list(connection.iterdump())
    connection.close()
    viewer = client(owner, guest=True)
    assert viewer.get("/api/dashboard/artwork").get_json()["artwork"] == artwork
    contexts = []
    def record(sender, template, context, **extra):
        contexts.append(context)
    template_rendered.connect(record, app)
    try:
        assert viewer.get("/owner/guest").status_code == 200
    finally:
        template_rendered.disconnect(record, app)
    assert contexts[0]["dashboard_artwork"] == artwork
    with app.test_request_context():
        session.update(authenticated=True, role="user", user_id=other, viewing_as_guest=True, profile_user_id=owner)
        assert render_template_string("{{ dashboard_artwork.url }}") == artwork["url"]
    assert app.test_client().get(artwork["url"]).status_code == 200
    assert client(other).get("/api/settings").get_json()["settings"].get("artwork") is None
    connection = connect(app.config["DATABASE"])
    assert list(connection.iterdump()) == before
    connection.close()
