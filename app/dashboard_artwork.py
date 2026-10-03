"""Account artwork stored verbatim in SQLite; no image resizing or transcoding."""

from io import BytesIO
import secrets
import struct
import zlib

from flask import jsonify, request, send_file, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from .auth import current_user_id, login_required, user_required
from .db import connect
from .routes import _viewer_user_id

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_IMAGE_BYTES + 64 * 1024
DEFAULT_MOTTO = "放弃幻想，准备斗争"
MAX_MOTTO_LENGTH = 80
DEFAULT_ARTWORK = {"url": "/static/current-time-art.jpg", "is_custom": False, "motto": DEFAULT_MOTTO}


def _png(data):
    position = 8
    image_bytes = 0
    zlib_header = b""
    first = True
    while position + 12 <= len(data):
        length = int.from_bytes(data[position:position + 4], "big")
        kind = data[position + 4:position + 8]
        finish = position + 12 + length
        if finish > len(data):
            return False
        content = data[position + 8:finish - 4]
        if zlib.crc32(kind + content) & 0xffffffff != int.from_bytes(data[finish - 4:finish], "big"):
            return False
        if first:
            if kind != b"IHDR" or length != 13:
                return False
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", content)
            valid_depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
            if not width or not height or depth not in valid_depths.get(color, ()) or compression or filtering or interlace > 1:
                return False
            first = False
        elif kind == b"IHDR":
            return False
        if kind == b"IDAT":
            image_bytes += length
            zlib_header = (zlib_header + content[:2])[:2]
        if kind == b"IEND":
            return (length == 0 and image_bytes >= 6 and finish == len(data) and len(zlib_header) == 2
                    and zlib_header[0] & 15 == 8 and zlib_header[0] >> 4 <= 7
                    and not zlib_header[1] & 32 and int.from_bytes(zlib_header, "big") % 31 == 0)
        position = finish
    return False


def _jpeg(data):
    position = 2
    frame = scan = False
    while position < len(data):
        if data[position] != 0xff:
            return False
        while position < len(data) and data[position] == 0xff:
            position += 1
        if position >= len(data):
            return False
        marker = data[position]
        position += 1
        if marker == 0xd9:
            return frame and scan and position == len(data)
        if marker in (0x00, 0xd8) or 0xd0 <= marker <= 0xd7:
            return False
        if marker == 0x01:
            continue
        if position + 2 > len(data):
            return False
        length = int.from_bytes(data[position:position + 2], "big")
        if length < 2 or position + length > len(data):
            return False
        segment = data[position + 2:position + length]
        if marker in (0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf):
            if len(segment) < 6 or not int.from_bytes(segment[1:3], "big") or not int.from_bytes(segment[3:5], "big"):
                return False
            if len(segment) != 6 + segment[5] * 3:
                return False
            frame = True
        position += length
        if marker == 0xda:
            if not frame or len(segment) < 4 or len(segment) != 1 + segment[0] * 2 + 3:
                return False
            scan = True
            scan_start = position
            while position < len(data):
                next_marker = data.find(b"\xff", position)
                if next_marker < 0 or next_marker + 1 >= len(data):
                    return False
                value = data[next_marker + 1]
                if value == 0x00 or 0xd0 <= value <= 0xd7:
                    position = next_marker + 2
                else:
                    if next_marker == scan_start:
                        return False
                    position = next_marker
                    break
    return False


def _gif(data):
    if len(data) < 14 or not int.from_bytes(data[6:8], "little") or not int.from_bytes(data[8:10], "little"):
        return False
    position = 13 + (3 * (2 ** ((data[10] & 7) + 1)) if data[10] & 0x80 else 0)
    frame = False
    while position < len(data):
        marker = data[position]
        position += 1
        if marker == 0x3b:
            return frame and position == len(data)
        image_block = marker == 0x2c
        if marker == 0x21:
            position += 1  # Extension label precedes data sub-blocks.
        elif marker == 0x2c:
            if position + 9 > len(data):
                return False
            if not int.from_bytes(data[position + 4:position + 6], "little") or not int.from_bytes(data[position + 6:position + 8], "little"):
                return False
            flags = data[position + 8]
            position += 9 + (3 * 2 ** ((flags & 7) + 1) if flags & 0x80 else 0)
            if position >= len(data) or not 2 <= data[position] <= 8:
                return False
            position += 1
            frame = True
        else:
            return False
        block_bytes = 0
        while position < len(data):
            length = data[position]
            position += 1
            if not length:
                break
            block_bytes += length
            position += length
        else:
            return False
        if image_block and not block_bytes:
            return False
    return False


def _webp_frame(kind, content):
    if kind == b"VP8 ":
        return (len(content) > 10 and not content[0] & 1 and content[3:6] == b"\x9d\x01\x2a"
                and int.from_bytes(content[6:8], "little") & 0x3fff
                and int.from_bytes(content[8:10], "little") & 0x3fff)
    if kind == b"VP8L":
        return len(content) > 5 and content[0] == 0x2f and content[4] & 0xe0 == 0
    return False


def _webp(data):
    if len(data) < 20 or int.from_bytes(data[4:8], "little") + 8 != len(data):
        return False
    position = 12
    frame = False
    while position + 8 <= len(data):
        kind = data[position:position + 4]
        length = int.from_bytes(data[position + 4:position + 8], "little")
        finish = position + 8 + length
        if finish + length % 2 > len(data):
            return False
        content = data[position + 8:finish]
        if kind in (b"VP8 ", b"VP8L"):
            if not _webp_frame(kind, content):
                return False
            frame = True
        elif kind == b"VP8X" and (length != 10 or content[0] & 0xc1 or content[1:4] != b"\0\0\0"):
            return False
        elif kind == b"ANMF":
            # Animated frames contain their own ALPH/VP8/VP8L sub-chunks.
            if length < 24:
                return False
            inner = 16
            inner_frame = False
            while inner + 8 <= len(content):
                inner_kind = content[inner:inner + 4]
                inner_length = int.from_bytes(content[inner + 4:inner + 8], "little")
                inner_end = inner + 8 + inner_length
                if inner_end + inner_length % 2 > len(content):
                    return False
                if inner_kind in (b"VP8 ", b"VP8L"):
                    if not _webp_frame(inner_kind, content[inner + 8:inner_end]):
                        return False
                    inner_frame = True
                inner = inner_end + inner_length % 2
            if inner != len(content) or not inner_frame:
                return False
            frame = True
        position = finish + length % 2
    return frame and position == len(data)


def image_mime(data):
    """Check image signatures and bounded container structure without decoding pixels."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and _png(data):
        return "image/png"
    if data.startswith(b"\xff\xd8") and _jpeg(data):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a") and _gif(data):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP" and _webp(data):
        return "image/webp"
    return None


def register_dashboard_artwork(app):
    def artwork_for(connection, user_id):
        row = connection.execute("SELECT version FROM dashboard_artwork WHERE user_id = ?", (user_id,)).fetchone()
        artwork = {"url": url_for("dashboard_artwork_image", user_id=user_id, version=row["version"]), "is_custom": True} if row else dict(DEFAULT_ARTWORK)
        motto = connection.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = 'dashboard_motto'", (user_id,)).fetchone()
        artwork["motto"] = motto["value"] if motto else DEFAULT_MOTTO
        return artwork

    @app.context_processor
    def inject_dashboard_artwork():
        connection = connect(app.config["DATABASE"])
        try:
            return {"dashboard_artwork": artwork_for(connection, _viewer_user_id(connection))}
        finally:
            connection.close()

    @app.get("/api/dashboard/artwork")
    @login_required
    def dashboard_artwork_get():
        connection = connect(app.config["DATABASE"])
        try:
            return jsonify(artwork=artwork_for(connection, _viewer_user_id(connection)))
        finally:
            connection.close()

    @app.post("/api/dashboard/artwork")
    @user_required
    def dashboard_artwork_post():
        request.max_content_length = MAX_REQUEST_BYTES
        request.max_form_memory_size = 256 * 1024
        request.max_form_parts = 4
        try:
            uploaded = request.files.get("image")
            motto_values = request.form.getlist("motto")
            if request.is_json:
                payload = request.get_json(silent=True)
                if not isinstance(payload, dict):
                    return jsonify(error="invalid_motto"), 400
                motto_values = [payload["motto"]] if "motto" in payload else []
            if "motto" in request.files or len(motto_values) > 1:
                return jsonify(error="invalid_motto"), 400
            motto = motto_values[0] if motto_values else None
            if motto_values and (not isinstance(motto, str) or len(motto) > MAX_MOTTO_LENGTH):
                return jsonify(error="invalid_motto"), 400
            if uploaded is None and not motto_values:
                return jsonify(error="image_required"), 400
            data = uploaded.stream.read(MAX_IMAGE_BYTES + 1) if uploaded is not None else None
        except RequestEntityTooLarge:
            return jsonify(error="image_too_large"), 413
        if data is not None and len(data) > MAX_IMAGE_BYTES:
            return jsonify(error="image_too_large"), 413
        mime = image_mime(data) if data is not None else None
        if data is not None and mime is None:
            return jsonify(error="invalid_image"), 400
        connection = connect(app.config["DATABASE"])
        try:
            user_id = current_user_id()
            if data is not None:
                connection.execute("""INSERT INTO dashboard_artwork(user_id, version, mime_type, image) VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET version=excluded.version, mime_type=excluded.mime_type, image=excluded.image""",
                    (user_id, secrets.token_hex(16), mime, data))
            if motto_values:
                connection.execute("""INSERT INTO user_settings(user_id, key, value) VALUES (?, 'dashboard_motto', ?)
                    ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value""", (user_id, motto.strip()))
            connection.commit()
            return jsonify(artwork=artwork_for(connection, user_id))
        finally:
            connection.close()

    @app.delete("/api/dashboard/artwork")
    @user_required
    def dashboard_artwork_delete():
        connection = connect(app.config["DATABASE"])
        try:
            user_id = current_user_id()
            connection.execute("DELETE FROM dashboard_artwork WHERE user_id = ?", (user_id,))
            connection.commit()
            return jsonify(artwork=artwork_for(connection, user_id))
        finally:
            connection.close()

    @app.get("/dashboard/artwork/<int:user_id>/<version>")
    def dashboard_artwork_image(user_id, version):
        connection = connect(app.config["DATABASE"])
        try:
            row = connection.execute("SELECT image, mime_type FROM dashboard_artwork WHERE user_id = ? AND version = ?", (user_id, version)).fetchone()
        finally:
            connection.close()
        if row is None:
            return jsonify(error="artwork_not_found"), 404
        response = send_file(BytesIO(row["image"]), mimetype=row["mime_type"], max_age=31536000,
                             etag=version, conditional=True)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
