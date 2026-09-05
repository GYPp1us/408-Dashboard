"""Delete exactly the reviewed historical rows that an operator approved.

This is intentionally separate from the hierarchy migration.  It accepts
table/id pairs from a fresh preflight report, verifies that they are the
entire currently reported unlinked set, and refuses broad name-based deletes.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from app.db import connect, subject_migration_report


ALLOWED_TABLES = {"focus_sessions", "scores", "plans"}


def _row_reference(value: str) -> tuple[str, int]:
    table, separator, raw_id = value.partition(":")
    if separator != ":" or table not in ALLOWED_TABLES:
        raise argparse.ArgumentTypeError("row must be one of focus_sessions:<id>, scores:<id>, or plans:<id>")
    try:
        row_id = int(raw_id)
    except ValueError as error:
        raise argparse.ArgumentTypeError("row id must be a positive integer") from error
    if row_id <= 0:
        raise argparse.ArgumentTypeError("row id must be a positive integer")
    return table, row_id


def _reviewed_unlinked_rows(report: dict) -> set[tuple[str, int]]:
    risks = [risk for risk in report["risks"] if risk["id"] == "historical-subject-not-linked"]
    if len(risks) != 1:
        raise ValueError("expected exactly one historical-subject-not-linked review finding")
    risk = risks[0]
    samples = risk["samples"]
    if int(risk["affected_count"]) != len(samples):
        raise ValueError("preflight does not enumerate every unlinked history row; use a dedicated reviewed migration plan")
    try:
        return {(str(sample["table"]), int(sample["id"])) for sample in samples}
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("preflight samples are not valid table/id rows") from error


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Discard exactly the reviewed unlinked history rows after an approved migration review",
    )
    parser.add_argument("database", type=Path, help="SQLite database path")
    parser.add_argument(
        "--row",
        action="append",
        default=[],
        type=_row_reference,
        metavar="TABLE:ID",
        help="one exact row from the preflight report; repeat for every reviewed row",
    )
    parser.add_argument(
        "--expected-subject",
        action="append",
        default=[],
        help="permitted exact historical subject snapshot; repeat as needed",
    )
    parser.add_argument(
        "--confirm-discard",
        action="store_true",
        help="perform the irreversible deletion after all validations pass",
    )
    args = parser.parse_args()

    requested_rows = set(args.row)
    expected_subjects = set(args.expected_subject)
    if not args.database.is_file():
        print(f"Database not found: {args.database}", file=sys.stderr)
        return 1
    if not requested_rows or len(requested_rows) != len(args.row):
        print("Every --row must be present exactly once.", file=sys.stderr)
        return 1
    if not expected_subjects:
        print("At least one --expected-subject is required.", file=sys.stderr)
        return 1
    if not args.confirm_discard:
        print(json.dumps({"discarded": False, "error": "confirm_discard_required"}, ensure_ascii=False))
        return 2

    connection = connect(str(args.database))
    try:
        connection.execute("BEGIN IMMEDIATE")
        before = subject_migration_report(connection)
        blocking = [risk for risk in before["risks"] if risk["severity"] == "blocking"]
        if blocking:
            raise ValueError("preflight has blocking findings; no history was deleted")
        reviewed_rows = _reviewed_unlinked_rows(before)
        if requested_rows != reviewed_rows:
            raise ValueError("requested rows do not exactly match the current reviewed unlinked history rows")

        deleted_rows: list[dict] = []
        for table, row_id in sorted(requested_rows):
            row = connection.execute(
                f"SELECT id, user_id, subject FROM {table} WHERE id = ?",
                (row_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"{table}:{row_id} no longer exists")
            snapshot = dict(row)
            if snapshot["subject"] not in expected_subjects:
                raise ValueError(f"{table}:{row_id} has an unexpected subject snapshot")
            connection.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
            deleted_rows.append({"table": table, **snapshot})

        after = subject_migration_report(connection)
        connection.commit()
        print(json.dumps({
            "discarded": True,
            "deleted_rows": deleted_rows,
            "preflight_before": before,
            "preflight_after": after,
        }, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (sqlite3.DatabaseError, ValueError) as error:
        connection.rollback()
        print(f"Reviewed history discard failed: {error}", file=sys.stderr)
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
