import json
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pytest
from app import create_app
from app.db import connect, create_user
from app.daily_task_push import deliver_due, post_https
from app.focus_reporter import ReporterError
from werkzeug.security import generate_password_hash


@pytest.fixture
def env(tmp_path, monkeypatch):
    now = datetime.fromisoformat('2026-10-24T20:00:00+08:00')
    for module in ['app.routes', 'app.daily_tasks', 'app.daily_task_push']:
        attr = '_now' if module == 'app.routes' else 'current_time'
        monkeypatch.setattr(module + '.' + attr, lambda zone='UTC': now.astimezone(ZoneInfo(zone)))
    app = create_app({'TESTING': True, 'DATABASE': str(tmp_path/'daily.sqlite3'), 'SECRET_KEY':'test', 'ADMIN_PASSWORD':'test-password', 'COOKIE_SECURE':False})
    client = app.test_client()
    assert client.post('/login', data={'password':'test-password'}).status_code == 302
    details = client.post('/api/daily-plan-reporter/connection').get_json()
    paths = {k:urlsplit(v).path for k,v in details.items() if k.endswith('_url')}
    return app, client, paths, now


def database(app):
    return connect(app.config['DATABASE'])


def task(client, paths, title='数学模拟', **extra):
    response = client.post(paths['report_url'], json={'tasks':[{'title':title, **extra}]})
    assert response.status_code == 200, response.get_json()
    return response.get_json()['tasks'][0]


def test_minimal_upsert_is_idempotent_and_completion_is_not_reset(env):
    app, client, paths, now = env
    first = task(client, paths)
    again = client.post(paths['report_url'], json={'tasks':[{'title':'数学模拟'}]}).get_json()
    assert not again['changed'] and again['total'] == 1
    response = client.post(paths['completion_url'], json={'task_id':first['id'], 'completed':True})
    assert response.status_code == 200
    assert task(client, paths)['completed']
    repeated = client.post(paths['completion_url'], json={'task_id':first['id'], 'completed':True}).get_json()
    assert not repeated['changed'] and len(repeated['completion_records']) == 1
    undone = client.post(paths['completion_url'], json={'task_id':first['id'], 'completed':False}).get_json()
    assert undone['completed'] == 0 and len(undone['completion_records']) == 2


def test_daily_key_rotation_authentication_and_prompt_contract(env):
    app, client, paths, now = env
    details = client.post('/api/daily-plan-reporter/connection').get_json()
    assert 'daily_settlement.cancelled' in details['prompt']
    assert 'Idempotency-Key' in details['prompt'] and details['today_url'] in details['prompt']
    assert client.get(paths['today_url']).status_code == 200
    rotated = client.post('/api/daily-plan-reporter/connection/rotate').get_json()
    assert client.get(paths['today_url']).status_code == 401
    assert client.get(urlsplit(rotated['today_url']).path).status_code == 200
    anonymous = app.test_client()
    assert anonymous.get('/api/daily-tasks').status_code == 401
    assert anonymous.post('/api/daily-plan-reporter/connection').status_code == 401
    guest = app.test_client(); guest.get('/guest')
    assert guest.post('/api/daily-plan-reporter/connection').status_code == 403


def test_agent_updates_are_atomic_and_keep_stable_ids_across_renames(env):
    app, client, paths, now = env
    first = task(client, paths, external_id='paper-1')
    updated = task(client, paths, title='模拟与订正', external_id='paper-1', target_minutes=90)
    assert updated['id'] == first['id'] and updated['target_minutes'] == 90
    failed = client.post(paths['report_url'], json={'tasks':[{'title':'可用任务'}, {'title':''}]})
    assert failed.status_code == 400
    assert client.get(paths['today_url']).get_json()['total'] == 1
    assert client.post(paths['report_url'], json={'tasks':[{'title':'坏值', 'completed':1}]}).status_code == 400
    assert client.post(paths['report_url'], json={'tasks':[{'title':'坏值', 'target_minutes':True}]}).status_code == 400
    assert client.get(paths['today_url']+'?date=bad').status_code == 400


def test_task_dates_and_sources_are_independent(env):
    app, client, paths, now = env
    task(client, paths)
    assert client.post(paths['report_url'], json={'source':'another_agent', 'tasks':[{'title':'数学模拟'}]}).get_json()['total'] == 2
    tomorrow = client.post(paths['report_url'], json={'date':'2026-10-25', 'tasks':[{'title':'数学模拟'}]}).get_json()
    assert tomorrow['total'] == 1 and tomorrow['date'] == '2026-10-25'
    assert client.get(paths['today_url']).get_json()['date'] == '2026-10-24'


def test_assignment_counts_existing_pause_aware_seconds_once_and_enforces_revisions(env):
    app, client, paths, now = env
    current = task(client, paths)
    conn = database(app)
    cursor = conn.execute("INSERT INTO focus_sessions(user_id,subject,mode,planned_minutes,started_at,ended_at,status) VALUES (1,'数学','学习',0,?,?,'completed')", ((now-timedelta(minutes=30)).isoformat(), now.isoformat()))
    session_id = cursor.lastrowid
    conn.execute('INSERT INTO focus_pauses(session_id,started_at,ended_at) VALUES (?,?,?)', (session_id, (now-timedelta(minutes=15)).isoformat(), (now-timedelta(minutes=10)).isoformat()))
    conn.commit(); conn.close()
    url = f'/api/focus/{session_id}/daily-task'
    assigned = client.put(url, json={'task_id':current['id'], 'completed':True, 'expected_revision':current['revision']})
    assert assigned.status_code == 200
    assert not client.put(url, json={'task_id':current['id'], 'completed':True}).get_json()['changed']
    catalog = client.get(paths['today_url']).get_json()
    assert catalog['focus_seconds'] == 1500 and catalog['completed'] == 1
    assert len(catalog['tasks'][0]['focus_records']) == 1
    assert client.put(url, json={'task_id':current['id'], 'completed':False, 'expected_revision':current['revision']}).status_code == 409
    assert client.get(url).get_json()['task_id'] == current['id']
    assert client.put(url, json={'task_id':None}).status_code == 200
    assert client.get(paths['today_url']).get_json()['focus_seconds'] == 0


def test_other_accounts_cannot_read_or_assign_tasks(env):
    app, client, paths, now = env
    current = task(client, paths)
    conn = database(app)
    create_user(conn, 'second', 'second@example.invalid', generate_password_hash('second-pass'), now.isoformat())
    conn.commit(); conn.close()
    second = app.test_client(); second.post('/login', data={'identifier':'second','password':'second-pass'})
    assert second.get('/api/daily-tasks').get_json()['tasks'] == []
    assert second.post('/api/daily-tasks/complete', json={'task_id':current['id'], 'completed':True}).status_code == 404
    assert client.get('/api/dashboard').get_json()['daily_plan']['total'] == 1


def settle(client):
    response = client.post('/api/daily-settlement', json={'expected_date':'2026-10-24'})
    assert response.status_code in (200,201), response.get_json()
    return response.get_json()


def test_settlement_freezes_tasks_and_unconfigured_push_is_truthful(env):
    app, client, paths, now = env
    current = task(client, paths)
    first = settle(client)
    assert first['report']['daily_tasks']['total'] == 1
    assert not first['report']['daily_tasks']['tasks'][0]['completed']
    assert client.get('/api/daily-tasks/push').get_json()['sync']['status'] == 'unconfigured'
    assert not deliver_due(app, now)
    client.post(paths['completion_url'], json={'task_id':current['id'], 'completed':True})
    repeat = settle(client)
    assert repeat['report'] == first['report'] and repeat['idempotent']
    assert client.get(paths['today_url']).get_json()['completed'] == 1
    conn=database(app)
    assert conn.execute('SELECT count(*) FROM daily_task_outbox').fetchone()[0] == 1
    conn.close()


def test_push_retries_use_the_same_event_and_never_return_saved_credentials(env):
    app, client, paths, now = env
    task(client, paths)
    settings = client.put('/api/daily-tasks/push', json={'url':'https://example.com/receive', 'token':'private-token'})
    assert settings.status_code == 200 and 'private-token' not in settings.get_data(as_text=True)
    settle(client)
    calls=[]
    app.config['DAILY_TASK_PUSH_TRANSPORT'] = lambda *args: calls.append(args) or False
    assert deliver_due(app, now)
    status = client.get('/api/daily-tasks/push').get_json()['sync']
    assert status['status'] == 'failed' and status['attempts'] == 1
    assert not deliver_due(app, now+timedelta(seconds=14))
    app.config['DAILY_TASK_PUSH_TRANSPORT'] = lambda *args: calls.append(args) or True
    assert deliver_due(app, now+timedelta(seconds=15))
    assert client.get('/api/daily-tasks/push').get_json()['sync']['status'] == 'sent'
    assert calls[0] == calls[1]
    assert calls[0][1] == 'private-token'
    assert json.loads(calls[0][2])['event_id'] == calls[0][3]


def test_cancel_after_delivery_sends_a_deduplicated_retraction(env):
    app, client, paths, now = env
    task(client, paths)
    client.put('/api/daily-tasks/push', json={'url':'https://example.com/receive'})
    settled = settle(client)
    calls=[]; app.config['DAILY_TASK_PUSH_TRANSPORT'] = lambda *args: calls.append(json.loads(args[2])) or True
    deliver_due(app, now)
    response = client.delete('/api/daily-settlement', json={'expected_date':'2026-10-24','settlement_id':settled['settlement']['id']})
    assert response.status_code == 200
    deliver_due(app, now)
    assert [row['event'] for row in calls] == ['daily_settlement.completed','daily_settlement.cancelled']
    assert calls[1]['retracts_event_id'] == calls[0]['event_id']
    assert not deliver_due(app, now)


def test_public_https_validation_and_dns_pinning_block_private_targets(env, monkeypatch):
    app, client, paths, now = env
    for url in ['http://example.com/a', 'https://127.0.0.1/a', 'https://localhost/a', 'https://user:pass@example.com/a', 'https://[::1]/a']:
        assert client.put('/api/daily-tasks/push', json={'url':url}).status_code == 400
    monkeypatch.setattr('socket.getaddrinfo', lambda *a,**k:[(0,0,0,'',('10.0.0.5',443))])
    with pytest.raises(ReporterError):
        post_https('https://example.com/a','','{}','event')


def test_no_task_or_configuration_does_not_create_a_false_sync_notice(env):
    app, client, paths, now = env
    settle(client)
    assert client.get('/api/daily-tasks/push').get_json()['sync'] is None
    assert client.get('/api/dashboard').get_json()['island_context']['task_sync'] is None


def test_saved_configuration_resumes_frozen_unconfigured_reports(env):
    app, client, paths, now = env
    current = task(client, paths)
    settle(client)
    client.post(paths['completion_url'], json={'task_id':current['id'], 'completed':True})
    configured = client.put('/api/daily-tasks/push', json={'url':'https://example.com/receive','token':'test-token'}).get_json()
    assert configured['sync']['status'] == 'pending'
    # Updating the URL without a token preserves the stored credential.
    client.put('/api/daily-tasks/push', json={'url':'https://example.com/receive'})
    calls=[]
    app.config['DAILY_TASK_PUSH_TRANSPORT'] = lambda *args: calls.append(args) or True
    assert deliver_due(app, now)
    assert calls[0][1] == 'test-token'
    assert json.loads(calls[0][2])['tasks']['completed'] == 0


def test_cancelling_before_delivery_never_sends_the_original_or_a_retraction(env):
    app, client, paths, now = env
    task(client, paths)
    client.put('/api/daily-tasks/push', json={'url':'https://example.com/receive'})
    settled=settle(client)
    assert client.delete('/api/daily-settlement', json={'expected_date':'2026-10-24','settlement_id':settled['settlement']['id']}).status_code == 200
    app.config['DAILY_TASK_PUSH_TRANSPORT'] = lambda *args: pytest.fail('Cancelled event was sent')
    assert not deliver_due(app, now)


def test_cancellation_in_flight_waits_then_sends_compensation(env):
    app, client, paths, now = env
    task(client, paths)
    client.put('/api/daily-tasks/push', json={'url':'https://example.com/receive'})
    settled=settle(client)
    calls=[]
    def transport(*args):
        calls.append(json.loads(args[2]))
        if len(calls) == 1:
            assert client.delete('/api/daily-settlement', json={'expected_date':'2026-10-24','settlement_id':settled['settlement']['id']}).status_code == 200
            assert not deliver_due(app, now), 'An in-flight request still owns its lease'
        return True
    app.config['DAILY_TASK_PUSH_TRANSPORT'] = transport
    assert deliver_due(app, now)
    assert deliver_due(app, now)
    assert [p['event'] for p in calls] == ['daily_settlement.completed', 'daily_settlement.cancelled']
    assert calls[1]['retracts_event_id'] == calls[0]['event_id']


def test_an_active_focus_cannot_be_classified_as_completed(env):
    app, client, paths, now = env
    current=task(client, paths)
    conn=database(app)
    sid=conn.execute("INSERT INTO focus_sessions(user_id,subject,mode,planned_minutes,started_at,status) VALUES (1,'数学','学习',0,?,'active')", (now.isoformat(),)).lastrowid
    conn.commit();conn.close()
    assert client.put(f'/api/focus/{sid}/daily-task',json={'task_id':current['id'],'completed':True}).status_code == 409
    assert client.get(paths['today_url']).get_json()['completed'] == 0


def test_guest_reports_preserve_public_focus_stats_but_do_not_expose_agent_tasks(env):
    app, client, paths, now = env
    task(client, paths, title='private-agent-plan', note='private-task-note')
    settle(client)
    guest=app.test_client();guest.get('/guest')
    for response in [guest.get('/api/dashboard'),guest.get('/api/daily-settlement/report?date=2026-10-24')]:
        assert response.status_code == 200
        assert 'private-agent-plan' not in response.get_data(as_text=True)
        assert 'private-task-note' not in response.get_data(as_text=True)
        assert 'total_seconds' in response.get_data(as_text=True)
    assert client.get('/api/daily-settlement/report?date=2026-10-24').get_json()['report']['daily_tasks']['total'] == 1


def test_an_expired_delivery_cannot_overwrite_the_recovered_worker_result(env):
    app, client, paths, now = env
    task(client, paths)
    client.put('/api/daily-tasks/push', json={'url':'https://example.com/receive'})
    settle(client)
    calls=[]
    def transport(*args):
        calls.append(args)
        if len(calls)==1:
            assert deliver_due(app, now+timedelta(seconds=61))
            return False
        return True
    app.config['DAILY_TASK_PUSH_TRANSPORT']=transport
    assert deliver_due(app,now)
    sync=client.get('/api/daily-tasks/push').get_json()['sync']
    assert sync['status']=='sent' and sync['attempts']==2
    assert calls[0]==calls[1], 'Lease recovery preserves the same immutable event'
