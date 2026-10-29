"""Back up and discard one fingerprint-verified, completed abnormal focus record.

Dry run prints only the target ID, duration and fingerprint. No historical
record dump or business content leaves the database host.
"""
from argparse import ArgumentParser
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import connect, get_settings
from app.focus_kline import build_focus_kline
from app.routes import _session_payload
from scripts.validate_checkin_upgrade import fingerprints


def reviewed_target(db, session_id):
    row = db.execute('SELECT * FROM focus_sessions WHERE id=?', (session_id,)).fetchone()
    if not row:
        raise ValueError('Target no longer exists')
    row = dict(row)
    pauses = [dict(p) for p in db.execute('SELECT * FROM focus_pauses WHERE session_id=? ORDER BY id', (session_id,))]
    if row['status'] != 'completed' or not row['ended_at'] or row['focus_locked'] or row['reporter_source']:
        raise ValueError('Only an unlocked, completed application record is eligible')
    if any(not p['ended_at'] for p in pauses):
        raise ValueError('Target still has an open pause')
    seconds = _session_payload(row, pauses, datetime.now(timezone.utc))['effective_seconds']
    if seconds < 12*3600:
        raise ValueError('Target is not the reviewed long-running anomaly')
    settings = get_settings(db, row['user_id'])
    zone = ZoneInfo(settings.get('timezone', 'Asia/Shanghai'))
    start = datetime.fromisoformat(row['started_at']).astimezone(zone).date().isoformat()
    end = datetime.fromisoformat(row['ended_at']).astimezone(zone).date().isoformat()
    if db.execute('SELECT 1 FROM daily_task_focus_links WHERE session_id=?', (session_id,)).fetchone():
        raise ValueError('Target has a task attribution requiring separate review')
    if db.execute('SELECT 1 FROM daily_settlements WHERE user_id=? AND settlement_date BETWEEN ? AND ?',
                  (row['user_id'], start, end)).fetchone():
        raise ValueError('Target overlaps a frozen daily settlement')
    digest = sha256(json.dumps({'session':row,'pauses':pauses}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return row, {'sessionId':session_id,'effectiveSeconds':seconds,'pauseRows':len(pauses),
                 'fingerprint':digest,'affectedFrom':start}


def protected_source(db, session_id, user_id, first_day):
    statements = [
        ('SELECT * FROM focus_sessions WHERE id<>? ORDER BY id', (session_id,)),
        ('SELECT * FROM focus_pauses WHERE session_id<>? ORDER BY id', (session_id,)),
        ('SELECT * FROM focus_klines WHERE user_id<>? OR trading_date<? ORDER BY user_id,trading_date', (user_id,first_day)),
    ]
    return [sha256(repr([tuple(r) for r in db.execute(sql, params)]).encode()).hexdigest() for sql,params in statements]


def discard(db, session_id, expected):
    db.execute('BEGIN IMMEDIATE')
    try:
        row, report = reviewed_target(db, session_id)
        if report['fingerprint'] != expected:
            raise ValueError('Target changed since review')
        before = fingerprints(db)
        protected = protected_source(db, session_id, row['user_id'], report['affectedFrom'])
        db.execute('DELETE FROM focus_pauses WHERE session_id=?', (session_id,))
        db.execute('DELETE FROM focus_sessions WHERE id=?', (session_id,))
        db.execute('DELETE FROM focus_klines WHERE user_id=? AND trading_date>=?', (row['user_id'],report['affectedFrom']))
        settings = get_settings(db, row['user_id'])
        build_focus_kline(db, row['user_id'], settings.get('timezone','Asia/Shanghai'), settings)
        after = fingerprints(db)
        allowed = {'focus_sessions','focus_pauses','focus_klines'}
        assert all(after[t] == value for t,value in before.items() if t not in allowed)
        assert protected_source(db, session_id, row['user_id'], report['affectedFrom']) == protected
        assert after['focus_sessions']['rows'] == before['focus_sessions']['rows']-1
        assert after['focus_pauses']['rows'] == before['focus_pauses']['rows']-report['pauseRows']
        assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        db.commit()
        return dict(report, discarded=True, unrelatedTablesVerified=len(before)-3,
                    unrelatedFocusAndEarlierIndexUnchanged=True, quickCheck='ok')
    except Exception:
        db.rollback()
        raise


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--session', type=int, required=True)
    parser.add_argument('--expected-fingerprint')
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        db = sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
        try:
            print(json.dumps(dict(reviewed_target(db, args.session)[1], discarded=False)))
        finally:
            db.close()
        return
    if not args.backup or not args.expected_fingerprint or args.backup.exists():
        raise ValueError('Apply requires a new backup path and the reviewed target fingerprint')
    if args.database.resolve() == args.backup.resolve():
        raise ValueError('Backup must be separate')
    args.backup.open('xb').close()
    source = sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro', uri=True)
    target = sqlite3.connect(args.backup)
    try:
        source.backup(target)
        assert target.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
    finally:
        source.close()
        target.close()
    db = connect(str(args.database))
    try:
        report = dict(discard(db, args.session, args.expected_fingerprint), backup=str(args.backup))
        args.backup.with_suffix(args.backup.suffix+'.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report))
    finally:
        db.close()


if __name__ == '__main__':
    main()
