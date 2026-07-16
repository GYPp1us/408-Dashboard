from datetime import datetime, timezone
from threading import Event, Thread

from .db import connect, expire_unattended_focus


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
                expire_unattended_focus(connection, datetime.now(timezone.utc), timeout_seconds)
            except Exception:
                app.logger.exception("focus_foreground_monitor_failed")
                connection.rollback()
            finally:
                connection.close()

    Thread(target=monitor, name="focus-foreground-monitor", daemon=True).start()
