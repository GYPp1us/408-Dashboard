from datetime import datetime, timedelta, timezone

import pytest
from app import create_app
from app.db import connect
from app.focus_kline import build_focus_kline
from scripts.discard_abnormal_focus import discard, reviewed_target
from scripts.validate_checkin_upgrade import fingerprints


@pytest.fixture
def anomaly(tmp_path):
    app = create_app({'TESTING':True, 'DATABASE':str(tmp_path/'cleanup.sqlite3'), 'ADMIN_PASSWORD':'test'})
    db = connect(app.config['DATABASE'])
    user = db.execute('SELECT id FROM users LIMIT 1').fetchone()[0]
    now = datetime.now(timezone.utc)
    cursor = db.execute("INSERT INTO focus_sessions(user_id,subject,mode,planned_minutes,started_at,ended_at,status,last_foreground_at) VALUES (?,'数学','专注',0,?,?,'completed',?)",
                        (user,(now-timedelta(hours=20)).isoformat(),now.isoformat(),now.isoformat()))
    target = cursor.lastrowid
    db.execute('INSERT INTO focus_pauses(session_id,started_at,ended_at) VALUES (?,?,?)',
               (target,(now-timedelta(hours=19)).isoformat(),(now-timedelta(hours=15)).isoformat()))
    db.execute("INSERT INTO focus_sessions(user_id,subject,mode,planned_minutes,started_at,ended_at,status) VALUES (?,'英语','专注',0,?,?,'completed')",
               (user,(now-timedelta(days=3)).isoformat(),(now-timedelta(days=3)+timedelta(minutes=30)).isoformat()))
    db.commit()
    build_focus_kline(db, user)
    yield db, target
    db.close()


def test_discards_only_reviewed_row_and_pause_and_preserves_older_history(anomaly):
    db, target = anomaly
    _, review = reviewed_target(db, target)
    assert review['effectiveSeconds'] == 16*3600
    result = discard(db, target, review['fingerprint'])
    assert result['discarded'] and result['unrelatedFocusAndEarlierIndexUnchanged']
    assert db.execute('SELECT count(*) FROM focus_sessions').fetchone()[0] == 1
    assert db.execute('SELECT count(*) FROM focus_pauses').fetchone()[0] == 0


def test_changed_fingerprint_rolls_back_without_mutation(anomaly):
    db, target = anomaly
    before = fingerprints(db)
    with pytest.raises(ValueError, match='changed since review'):
        discard(db, target, '0'*64)
    assert fingerprints(db) == before


def test_frozen_settlement_prevents_discard(anomaly):
    db, target = anomaly
    row, review = reviewed_target(db, target)
    db.execute('INSERT INTO daily_settlements(user_id,settlement_date,settled_at,total_seconds,yesterday_seconds,delta_seconds,target_seconds,completion,session_count) VALUES (?,?,?,0,0,0,28800,0,1)',
               (row['user_id'],review['affectedFrom'],row['ended_at']))
    db.commit()
    with pytest.raises(ValueError, match='frozen daily settlement'):
        reviewed_target(db, target)
    assert db.execute('SELECT 1 FROM focus_sessions WHERE id=?', (target,)).fetchone()
