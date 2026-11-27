"""Account-scoped, read-only access to Blockcolc's third-party friends API."""

from base64 import urlsafe_b64encode
from contextlib import closing
from datetime import date, datetime, timezone
import hmac
import json
import re
from threading import BoundedSemaphore, Thread
from time import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from cryptography.fernet import Fernet, InvalidToken
from flask import jsonify, request

from .auth import current_user_id, user_required
from .db import connect


FRIENDS_URL = "https://blockcolc.arcol.site/v1/integrations/friends"
TOKEN_PATTERN = re.compile(r"bci_[A-Za-z0-9_-]{43}")
SYNC_INTERVAL = 5
SYNC_TIMEOUT = 4
MAX_STALE = 30
MAX_RESPONSE = 8 * 1024 * 1024
PRESENCE_LIFETIME_MS = 90_000
SELECTION_KEY = "leaderboard_friend"


class SyncError(Exception):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read_friends(token):
    req = Request(FRIENDS_URL, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with build_opener(_NoRedirect).open(req, timeout=SYNC_TIMEOUT) as response:
            payload = response.read(MAX_RESPONSE + 1)
    except HTTPError as error:
        error.close()
        raise SyncError({401: "expired", 403: "scope", 429: "rate_limited"}.get(error.code, "unavailable")) from None
    except (URLError, OSError):
        raise SyncError("unavailable") from None
    if len(payload) > MAX_RESPONSE:
        raise SyncError("unavailable")
    try:
        return json.loads(payload)
    except (ValueError, UnicodeError):
        raise SyncError("unavailable") from None


def _identity(value):
    if not isinstance(value, dict):
        raise SyncError("unavailable")
    identifier = value.get("id")
    name = value.get("name")
    if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9:_-]{1,96}", identifier):
        raise SyncError("unavailable")
    if not isinstance(name, str) or not name.strip() or len(name) > 256:
        raise SyncError("unavailable")
    return identifier, name.strip()


def _iso_millis(value):
    if not isinstance(value, str):
        return None
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return round(instant.timestamp() * 1000) if instant.utcoffset() is not None else None
    except (ValueError, OverflowError, OSError):
        return None


def _focus_window(row, stamp_ms):
    if row.get("state") not in (None, "focus", "extension"):
        return None
    start = _iso_millis(row.get("startedAt"))
    if start is None or start > stamp_ms:
        return None
    if row.get("estimated") is True:
        # Beta 8's durable state can remain active past its planned end.
        return [start, None]
    # Third-party integrations are leased by their heartbeat, even for timed tasks.
    end = _iso_millis(row.get("endsAt")) if row.get("state") is None else None
    updated = _iso_millis(row.get("updatedAt"))
    limits = [value for value in (end, updated + PRESENCE_LIFETIME_MS if updated is not None else None)
              if value is not None]
    return [start, min(limits) if limits else None]


def _normalize(payload, stamp):
    if not isinstance(payload, dict) or not isinstance(payload.get("friends"), list):
        raise SyncError("unavailable")
    account_id, account_name = _identity(payload.get("account"))
    utc_day = datetime.fromtimestamp(stamp, timezone.utc).date().toordinal()
    friends = {}
    for row in payload["friends"]:
        friend_id, name = _identity(row)
        sharing = row.get("visible")
        if friend_id == account_id or not isinstance(sharing, dict):
            continue
        days = None
        if sharing.get("daily") is True and isinstance(row.get("days"), list):
            days = {}
            for record in row["days"]:
                if not isinstance(record, dict):
                    continue
                key, duration = record.get("date"), record.get("actualFocusMs")
                if not isinstance(key, str) or type(duration) is not int or not 0 <= duration <= 172_800_000:
                    continue
                try:
                    day = date.fromisoformat(key)
                except ValueError:
                    continue
                if abs(day.toordinal() - utc_day) <= 2:
                    days[day.isoformat()] = duration
        focusing = row.get("focusing")
        if sharing.get("status") is not True or row.get("stale") is True or type(focusing) is not bool:
            focusing = None
        friends[friend_id] = {
            "id": friend_id,
            "username": name,
            "source": "blockcolc",
            "key": f"blockcolc:{friend_id}",
            "days_ms": days,
            "focusing": focusing,
            "focus_window": _focus_window(row, int(stamp * 1000))
            if days is not None and focusing and sharing.get("time") is True else None,
        }
    return account_id, account_name, list(friends.values())


def clear_remote_selection(db, user_id):
    db.execute("DELETE FROM user_settings WHERE user_id=? AND key=? AND value GLOB 'blockcolc:*'", (user_id, SELECTION_KEY))


class BlockcolcFriends:
    def __init__(self, app):
        self.database = app.config["DATABASE"]
        secret = app.config["SECRET_KEY"]
        secret = secret if isinstance(secret, bytes) else secret.encode()
        self.cipher = Fernet(urlsafe_b64encode(hmac.digest(secret, b"408-dashboard:blockcolc-friends:v1", "sha256")))
        self.slots = BoundedSemaphore(4)

    def view(self, db, user_id, zone=None, *, refresh=True):
        row = db.execute("SELECT * FROM blockcolc_friend_links WHERE user_id=?", (user_id,)).fetchone()
        if row is None:
            return {"status": "disconnected"}, []
        stamp = time()
        if refresh and row["encrypted_token"] and row["next_sync_at"] <= stamp:
            self._schedule(db, row, stamp)
        link = {"status": row["status"], "name": row["account_name"], "synced_at": row["synced_at"]}
        age = stamp - row["synced_at"]
        if age > MAX_STALE:
            return link, []
        connected = row["status"] == "connected"
        live = connected and age <= SYNC_INTERVAL * 2
        if zone is not None:
            now = datetime.fromtimestamp(stamp, zone)
            day = now.date().isoformat()
            midnight_ms = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
            now_ms = int(stamp * 1000)
        friends = []
        for item in json.loads(row["friends_json"]):
            days = item.pop("days_ms", None)
            legacy_days = item.pop("days", None)
            window = item.pop("focus_window", None)
            item["today_seconds"] = None
            if zone is not None and connected and (days is not None or legacy_days is not None):
                confirmed_ms = days.get(day, 0) if days is not None else legacy_days.get(day, 0) * 1000
                elapsed_ms = 0
                if live and window is not None:
                    start, limit = window
                    if limit is None or now_ms < limit:
                        elapsed_ms = max(0, now_ms - max(start, midnight_ms))
                item["today_seconds"] = (confirmed_ms + elapsed_ms) // 1000
            if not live:
                item["focusing"] = None
            friends.append(item)
        return link, friends

    def _schedule(self, db, row, stamp):
        if not self.slots.acquire(blocking=False):
            return
        try:
            # The short SQLite lease also deduplicates across Gunicorn workers.
            args = row["user_id"], row["encrypted_token"]
            owns_refresh = db.execute(
                "UPDATE blockcolc_friend_links SET next_sync_at=? WHERE user_id=? AND encrypted_token=? AND next_sync_at<=?",
                (stamp + MAX_STALE, *args, stamp),
            ).rowcount
            db.commit()
            if owns_refresh:
                Thread(target=self._refresh, args=args, daemon=True, name="blockcolc-friends").start()
                return
        except BaseException:
            self.slots.release()
            raise
        self.slots.release()

    def _refresh(self, user_id, encrypted_token):
        try:
            with closing(connect(self.database)) as db, db:
                try:
                    token = self.cipher.decrypt(encrypted_token.encode()).decode()
                    account_id, name, friends = _normalize(_read_friends(token), time())
                    current = db.execute(
                        "SELECT account_id FROM blockcolc_friend_links WHERE user_id=? AND encrypted_token=?",
                        (user_id, encrypted_token),
                    ).fetchone()
                    if current is None:
                        return
                    if current["account_id"] != account_id:
                        raise SyncError("expired")
                except (SyncError, InvalidToken) as error:
                    status = str(error) if isinstance(error, SyncError) else "expired"
                    if status in {"expired", "scope"}:
                        db.execute(
                            "UPDATE blockcolc_friend_links SET status=?, encrypted_token=NULL, friends_json='[]' "
                            "WHERE user_id=? AND encrypted_token=?",
                            (status, user_id, encrypted_token),
                        )
                    else:
                        delay = 30 if status == "rate_limited" else 10
                        db.execute(
                            "UPDATE blockcolc_friend_links SET status='unavailable', next_sync_at=? "
                            "WHERE user_id=? AND encrypted_token=?",
                            (time() + delay, user_id, encrypted_token),
                        )
                else:
                    stamp = time()
                    db.execute(
                        "UPDATE blockcolc_friend_links SET account_name=?, friends_json=?, synced_at=?, "
                        "next_sync_at=?, status='connected' WHERE user_id=? AND encrypted_token=?",
                        (name, json.dumps(friends, ensure_ascii=False), stamp, stamp + SYNC_INTERVAL, user_id, encrypted_token),
                    )
        finally:
            self.slots.release()

    def link(self, db, user_id, token):
        if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token):
            raise SyncError("invalid_token")
        account_id, name, friends = _normalize(_read_friends(token), time())
        stamp = time()
        encrypted = self.cipher.encrypt(token.encode()).decode()
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute("SELECT account_id FROM blockcolc_friend_links WHERE user_id=?", (user_id,)).fetchone()
        if previous is not None and previous["account_id"] != account_id:
            clear_remote_selection(db, user_id)
        db.execute(
            "INSERT INTO blockcolc_friend_links VALUES (?,?,?,?,?,?,?,'connected') "
            "ON CONFLICT(user_id) DO UPDATE SET account_id=excluded.account_id, account_name=excluded.account_name, "
            "encrypted_token=excluded.encrypted_token, friends_json=excluded.friends_json, synced_at=excluded.synced_at, "
            "next_sync_at=excluded.next_sync_at, status=excluded.status",
            (user_id, account_id, name, encrypted, json.dumps(friends, ensure_ascii=False), stamp, stamp + SYNC_INTERVAL),
        )


def register_blockcolc_friends(app):
    service = app.extensions["blockcolc_friends"] = BlockcolcFriends(app)

    @app.route("/api/integrations/blockcolc-friends", methods=["PUT", "DELETE"])
    @user_required
    def blockcolc_link():
        try:
            with closing(connect(service.database)) as db, db:
                user_id = current_user_id()
                if request.method == "DELETE":
                    db.execute("DELETE FROM blockcolc_friend_links WHERE user_id=?", (user_id,))
                    clear_remote_selection(db, user_id)
                else:
                    request.max_content_length = 4096
                    data = request.get_json(silent=True)
                    token = data.get("token", "").strip() if isinstance(data, dict) and isinstance(data.get("token"), str) else ""
                    service.link(db, user_id, token)
        except SyncError as error:
            code = str(error)
            return jsonify(error=f"blockcolc_{code}"), (503 if code in {"unavailable", "rate_limited"} else 422)
        return jsonify(ok=True)
