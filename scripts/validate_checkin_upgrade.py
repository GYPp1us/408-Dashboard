"""Rehearse additive check-in schema against a read-only online database backup."""
from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
import json
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.db import init_db


def fingerprints(connection):
    result = {}
    for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        escaped = table.replace('"', '""')
        rows = connection.execute(f'SELECT * FROM "{escaped}"').fetchall()
        serialized = sorted(repr(tuple(row)) for row in rows)
        result[table] = {"rows": len(rows), "sha256": sha256('\n'.join(serialized).encode()).hexdigest()}
    return result


def rehearse(database, copy):
    if copy.exists() or database.resolve() == copy.resolve():
        raise ValueError("Rehearsal output must be a new, separate database")
    source = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
    target = sqlite3.connect(copy)
    try:
        source.backup(target)
        before = fingerprints(target)
        target.row_factory = sqlite3.Row
        init_db(target)
        after = fingerprints(target)
        assert all(after[name] == original for name, original in before.items()), "Pre-existing data changed"
        expected = {"checkin_rules", "checkin_records", "checkin_reporter_keys"}
        assert set(after) - set(before) <= expected
        assert expected <= set(after)
        assert target.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        assert target.execute('PRAGMA foreign_key_check').fetchall() == []
        return {"passed": True, "unchangedTables": len(before), "addedTables": sorted(set(after)-set(before)),
                "quickCheck": "ok", "foreignKeyViolations": 0, "sourceOpenedReadOnly": True}
    finally:
        source.close(); target.close()


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('copy', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = rehearse(args.database, args.copy)
    text = json.dumps(result, indent=2)
    if args.report:
        args.report.write_text(text+'\n', encoding='utf-8')
    print(text)
