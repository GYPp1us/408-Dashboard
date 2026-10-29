from datetime import datetime, timedelta, timezone

import pytest
from app import create_app
from app.db import connect, expire_unattended_focus, record_foreground_heartbeat


@pytest.fixture
def owner(tmp_path):
    app = create_app({'TESTING': True, 'DATABASE': str(tmp_path/'focus.sqlite3'),
                      'SECRET_KEY': 'test', 'ADMIN_PASSWORD': 'test'})
    client = app.test_client()
    client.post('/login', data={'password': 'test'})
    session = client.post('/api/focus/start', json={'subject': '数学二轮', 'mode': '专注'}).get_json()['session']
    db = connect(app.config['DATABASE'])
    yield client, db, session
    db.close()


def old_heartbeat(db, session, seconds=31):
    at = datetime.now(timezone.utc)-timedelta(seconds=seconds)
    db.execute('UPDATE focus_sessions SET last_foreground_at=? WHERE id=?', (at.isoformat(), session['id']))
    db.commit()
    return at


def test_native_background_polls_and_legacy_heartbeats_cannot_keep_unlocked_focus_alive(owner):
    client, db, session = owner
    at = old_heartbeat(db, session)
    for _ in range(3):
        assert client.get('/api/dashboard', headers={'User-Agent': 'MutsumiFocus/0.9.0'}).status_code == 200
        client.post('/api/focus/heartbeat', json={'session_id': session['id'], 'allow_recovery': True},
                    headers={'User-Agent': 'MutsumiFocus/0.9.0'})
    assert db.execute('SELECT last_foreground_at FROM focus_sessions WHERE id=?', (session['id'],)).fetchone()[0] == at.isoformat()
    assert expire_unattended_focus(db, at+timedelta(seconds=31)) == session['id']
    result = client.post('/api/focus/heartbeat', json={'session_id': session['id'], 'allow_recovery': True},
                         headers={'User-Agent': 'MutsumiFocus/0.9.0'}).get_json()
    assert not result['recovered'] and result['status'] == 'completed'


def test_visible_native_heartbeat_attests_presence_but_hidden_keepalive_does_not(owner):
    client, db, session = owner
    at = old_heartbeat(db, session, 20)
    client.post('/api/focus/heartbeat', json={'session_id': session['id'], 'foreground': False},
                headers={'User-Agent': 'MutsumiFocus/0.9.1'})
    assert db.execute('SELECT last_foreground_at FROM focus_sessions WHERE id=?', (session['id'],)).fetchone()[0] == at.isoformat()
    client.post('/api/focus/heartbeat', json={'session_id': session['id'], 'foreground': True},
                headers={'User-Agent': 'MutsumiFocus/0.9.1'})
    assert expire_unattended_focus(db, datetime.now(timezone.utc)) is None


def test_old_timeout_cannot_be_resurrected_after_long_background_absence(owner):
    client, db, session = owner
    at = old_heartbeat(db, session, 16*3600)
    expire_unattended_focus(db, datetime.now(timezone.utc))
    result = client.post('/api/focus/heartbeat', json={'session_id': session['id'], 'foreground': True,
                                                     'allow_recovery': True}).get_json()
    assert not result['recovered'] and result['status'] == 'completed'
    assert datetime.fromisoformat(db.execute('SELECT ended_at FROM focus_sessions WHERE id=?', (session['id'],)).fetchone()[0]) == at+timedelta(seconds=30)


def test_locked_background_focus_and_long_lunch_pause_remain_active(owner):
    client, db, session = owner
    at = old_heartbeat(db, session, 5*3600)
    client.post('/api/focus/pause', json={'session_id': session['id'], 'paused': True})
    old_heartbeat(db, session, 5*3600)
    assert expire_unattended_focus(db, datetime.now(timezone.utc)) is None
    client.post('/api/focus/pause', json={'session_id': session['id'], 'paused': False})
    old_heartbeat(db, session, 5*3600)
    client.post('/api/focus/lock', json={'session_id': session['id']})
    assert expire_unattended_focus(db, datetime.now(timezone.utc)) is None
    row = db.execute('SELECT focus_locked,trusted FROM focus_sessions WHERE id=?', (session['id'],)).fetchone()
    assert tuple(row) == (1, 0)


def test_stale_session_heartbeat_cannot_keep_new_session_alive(owner):
    client, db, session = owner
    client.post('/api/focus/end', json={'session_id': session['id']})
    new = client.post('/api/focus/start', json={'subject': '英语二轮', 'mode': '专注'}).get_json()['session']
    at = old_heartbeat(db, new)
    result = record_foreground_heartbeat(db, datetime.now(timezone.utc), session['user_id'], session['id'], True)
    assert result['status'] == 'completed'
    assert expire_unattended_focus(db, at+timedelta(seconds=31)) == new['id']
