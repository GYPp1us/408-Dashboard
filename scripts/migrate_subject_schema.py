"""Apply the subject/focus-item hierarchy migration after its risk review.

This is deliberately separate from the read-only preflight.  Run it only
while 408-dashboard.service is stopped and after a SQLite backup exists.
Review findings require an explicit, operator-supplied acknowledgement; a
blocking finding is never bypassed.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from app.db import SubjectMigrationBlocked, connect, init_db, subject_migration_report


def _report(connection: sqlite3.Connection, database: Path) -> dict:
    report = subject_migration_report(connection)
    report["database"] = str(database.resolve())
    report["sqlite_version"] = connection.execute("SELECT sqlite_version()").fetchone()[0]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply the reviewed subject/focus-item hierarchy SQLite migration")
    parser.add_argument("database", type=Path, help="SQLite database path")
    parser.add_argument(
        "--approve-review",
        action="store_true",
        help="acknowledge reviewed non-blocking findings; cannot bypass blocking findings",
    )
    args = parser.parse_args()

    if not args.database.is_file():
        print(f"Database not found: {args.database}", file=sys.stderr)
        return 1

    connection = connect(str(args.database))
    try:
        report = _report(connection, args.database)
        blocking = [risk for risk in report["risks"] if risk["severity"] == "blocking"]
        if blocking or (report["review_risk_count"] and not args.approve_review):
            print(json.dumps({"applied": False, "preflight": report}, ensure_ascii=False, indent=2, sort_keys=True))
            return 2

        init_db(connection, allow_subject_migration_review=args.approve_review)
        foreign_key_check = [dict(row) for row in connection.execute("PRAGMA foreign_key_check")]
        outcome = {
            "applied": not foreign_key_check,
            "preflight": report,
            "foreign_key_check": foreign_key_check,
        }
        print(json.dumps(outcome, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if not foreign_key_check else 3
    except (sqlite3.DatabaseError, SubjectMigrationBlocked) as error:
        connection.rollback()
        print(f"Migration failed: {error}", file=sys.stderr)
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
