from datetime import datetime, timezone
from threading import Event, Thread

from .db import connect, expire_unattended_focus, get_settings
from .focus_kline import build_focus_kline


def start_focus_monitor(app) -> None:
    if app.config.get("TESTING"):
        return

    database = app.config["DATABASE"]
    timeout_seconds = int(app.config["FOREGROUND_TIMEOUT_SECONDS"])
    interval_seconds = float(app.config["FOREGROUND_MONITOR_INTERVAL"])
    stop_event = Event()

    def monitor() -> None:
        while not stop_event.wait(interval_seconds):
            connection = connect(database)
            try:
                expired_session_id = expire_unattended_focus(connection, datetime.now(timezone.utc), timeout_seconds)
                if expired_session_id is not None:
                    row = connection.execute(
                        "SELECT user_id FROM focus_sessions WHERE id = ?", (expired_session_id,)
                    ).fetchone()
                    if row and row["user_id"] is not None:
                        user_id = int(row["user_id"])
                        settings = get_settings(connection, user_id)
                        build_focus_kline(connection, user_id, settings.get("timezone", "Asia/Shanghai"), settings)
            except Exception:
                app.logger.exception("focus_foreground_monitor_failed")
                connection.rollback()
            finally:
                connection.close()

    Thread(target=monitor, name="focus-foreground-monitor", daemon=True).start()
