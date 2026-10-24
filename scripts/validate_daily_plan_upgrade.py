"""Rehearse the additive daily-plan upgrade on a new SQLite online backup."""
from argparse import ArgumentParser
from pathlib import Path
import json
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app
from app.db import FOCUS_EXCHANGE_EFFECTIVE_KEY, init_db
from scripts.validate_checkin_upgrade import fingerprints

DAILY_TABLES = {
    'daily_tasks', 'daily_task_focus_links', 'daily_task_events',
    'daily_task_reporter_keys', 'daily_task_push_settings', 'daily_task_outbox',
}


def rehearse(database, copy):
    if not database.is_file() or copy.exists() or database.resolve() == copy.resolve():
        raise ValueError('Use an existing source and a new, separate rehearsal database')
    source = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
    target = sqlite3.connect(copy)
    try:
        source.backup(target)
        target.row_factory = sqlite3.Row
        before = fingerprints(target)
        cutover = target.execute('SELECT value FROM settings WHERE key=?', (FOCUS_EXCHANGE_EFFECTIVE_KEY,)).fetchone()[0]
        init_db(target)
        after = fingerprints(target)
        assert all(after[name] == value for name, value in before.items()), 'Pre-existing data changed'
        assert set(after) - set(before) <= DAILY_TABLES
        assert DAILY_TABLES <= set(after)
        assert target.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        assert target.execute('PRAGMA foreign_key_check').fetchall() == []
        assert target.execute('SELECT value FROM settings WHERE key=?', (FOCUS_EXCHANGE_EFFECTIVE_KEY,)).fetchone()[0] == cutover
        owner = target.execute("SELECT id,username,role FROM users WHERE role='site_owner' ORDER BY id LIMIT 1").fetchone()
        assert owner is not None
    finally:
        source.close()
        target.close()

    # All API probes below run on the clone. Never start monitor/delivery workers
    # or send callbacks while rehearsing production data.
    app = create_app({'TESTING': True, 'DATABASE': str(copy), 'SECRET_KEY': 'upgrade-rehearsal-only', 'COOKIE_SECURE': False})
    connection = sqlite3.connect(copy)
    try:
        startup = fingerprints(connection)
        assert all(startup[name] == value for name, value in before.items()), 'Application startup rewrote existing data'
    finally:
        connection.close()
    client = app.test_client()
    with client.session_transaction() as session:
        session.update(authenticated=True, user_id=owner['id'], role=owner['role'], username=owner['username'])
    assert client.get('/api/daily-tasks').status_code == 200
    assert client.get('/api/daily-tasks/push').status_code == 200
    details = client.post('/api/daily-plan-reporter/connection').get_json()
    from urllib.parse import urlsplit
    today, report = (urlsplit(details[name]).path for name in ('today_url', 'report_url'))
    assert client.get(today).status_code == 200
    response = client.post(report, json={'source': 'release_rehearsal', 'tasks': [{'external_id': 'schema-smoke', 'title': 'Upgrade rehearsal only'}]})
    assert response.status_code == 200
    task = next(task for task in response.get_json()['tasks'] if task['source'] == 'release_rehearsal')
    assert client.post('/api/daily-tasks/complete', json={'task_id': task['id'], 'completed': True, 'expected_revision': task['revision']}).status_code == 200
    anonymous = app.test_client()
    assert anonymous.get('/api/daily-tasks').status_code == 401
    assert anonymous.get('/api/daily-tasks/push').status_code == 401
    guest = app.test_client()
    guest.get('/guest')
    assert guest.get('/api/dashboard').get_json()['daily_plan'] is None
    assert guest.get('/api/daily-tasks').status_code == 403
    return {'passed': True, 'unchangedTables': len(before), 'addedTables': sorted(set(after)-set(before)),
            'quickCheck': 'ok', 'foreignKeyViolations': 0, 'sourceOpenedReadOnly': True,
            'existingStartupDataUnchanged': True, 'exchangeEffectiveAt': cutover,
            'authenticatedApiSmoke': True, 'guestAndAnonymousDenied': True, 'outboundCallbacks': False}


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
