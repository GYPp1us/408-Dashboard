"""Read-only gate for the subject/focus-item hierarchy migration.

Run this against the live SQLite file before switching a production release:

    PYTHONPATH=. python scripts/preflight_subject_migration.py /path/to/dashboard.sqlite3

It exits with 2 whenever a migration risk needs human review.  It never opens
the database for writing and does not invoke ``init_db``.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from app.db import subject_migration_report


def read_only_connection(database: Path) -> sqlite3.Connection:
    uri = f"{database.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def format_report(report: dict) -> str:
    lines = [
        "408 Dashboard subject/focus-item hierarchy migration preflight",
        f"Database: {report['database']}",
        f"SQLite: {report['sqlite_version']}",
        f"Blocking risks: {report['blocking_risk_count']}",
        f"Review risks: {report['review_risk_count']}",
    ]
    if not report["risks"]:
        lines.append("Result: no hierarchy-migration risk detected.")
        return "\n".join(lines)

    lines.append("Result: review required; do not restart the new release yet.")
    for risk in report["risks"]:
        lines.append(
            f"- [{risk['severity']}] {risk['id']}: {risk['summary']} "
            f"(affected: {risk['affected_count']})"
        )
        for sample in risk["samples"]:
            lines.append(f"  sample: {json.dumps(sample, ensure_ascii=False, sort_keys=True)}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only preflight for the subject/focus-item hierarchy migration")
    parser.add_argument("database", type=Path, help="SQLite database path")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    if not args.database.is_file():
        print(f"Database not found: {args.database}", file=sys.stderr)
        return 1
    try:
        connection = read_only_connection(args.database)
        try:
            report = subject_migration_report(connection)
            report["database"] = str(args.database.resolve())
            report["sqlite_version"] = connection.execute("SELECT sqlite_version()").fetchone()[0]
        finally:
            connection.close()
    except sqlite3.DatabaseError as error:
        print(f"Cannot inspect database: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_report(report))
    return 0 if not report["risks"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
