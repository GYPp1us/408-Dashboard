from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil

from app.db import clear_user_data, connect, init_db


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up and clear seeded study data")
    parser.add_argument("--database", required=True)
    parser.add_argument("--backup-dir", required=True)
    args = parser.parse_args()

    database = Path(args.database)
    backup_dir = Path(args.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    connection = connect(str(database))
    init_db(connection)
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()

    backup = backup_dir / f"dashboard-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.sqlite3"
    shutil.copy2(database, backup)

    connection = connect(str(database))
    clear_user_data(connection)
    counts = {
        "focus_sessions": connection.execute("SELECT COUNT(*) FROM focus_sessions").fetchone()[0],
        "scores": connection.execute("SELECT COUNT(*) FROM scores").fetchone()[0],
        "plans": connection.execute("SELECT COUNT(*) FROM plans").fetchone()[0],
        "focus_modes": connection.execute("SELECT COUNT(*) FROM focus_modes").fetchone()[0],
    }
    connection.close()
    print({"backup": str(backup), "counts": counts})


if __name__ == "__main__":
    main()
