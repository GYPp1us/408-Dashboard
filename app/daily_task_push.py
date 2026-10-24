"""Durable, at-least-once daily-settlement push with frozen payloads."""
from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import ssl
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from urllib.parse import urlsplit

from flask import jsonify, request

from .auth import current_user_id, user_required
from .db import connect, get_settings
from .focus_reporter import ReporterError
from .services import current_time


def stamp(now):
    return now.astimezone(timezone.utc).isoformat()


def validate_url(value):
    if not isinstance(value, str) or len(value) > 2000:
        raise ReporterError('invalid_push_url')
    if not value.strip():
        return ''
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        raise ReporterError('invalid_push_url')
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or port == 0:
        raise ReporterError('https_push_url_required')
    try:
        literal = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal = None
    if parsed.hostname.lower() == 'localhost' or literal is not None and not literal.is_global:
        raise ReporterError('public_https_push_url_required')
    return value.strip()


def settings(conn, user):
    row = conn.execute('SELECT url,token FROM daily_task_push_settings WHERE user_id=?', (user,)).fetchone()
    return {'url': row['url'] if row else '', 'has_token': bool(row and row['token']), 'configured': bool(row and row['url'])}


def status(conn, user, now):
    row = conn.execute("SELECT * FROM daily_task_outbox WHERE user_id=? AND event_type='daily_settlement.completed' ORDER BY id DESC LIMIT 1", (user,)).fetchone()
    if not row:
        return None
    data = json.loads(row['payload_json'])
    return {'event_id': row['event_id'], 'date': data['date'], 'status': 'pending' if row['status'] == 'processing' else row['status'],
            'completed': data['tasks']['completed'], 'total': data['tasks']['total'],
            'attempts': row['attempts'], 'next_attempt_at': row['next_attempt_at'], 'updated_at': row['updated_at'],
            'error': row['last_error']}


def enqueue(conn, user, settlement, snapshot, now):
    instance = get_settings(conn).get('migration_instance_id', 'dashboard')
    event_id = f"{instance}:{user}:{settlement['id']}:completed"
    payload = {'protocol': 'daily-plan.v1', 'event': 'daily_settlement.completed', 'event_id': event_id,
               'date': settlement['settlement_date'], 'settled_at': settlement['settled_at'],
               'timezone': snapshot['timezone'], 'tasks': snapshot}
    configured = settings(conn, user)['configured']
    if not configured and snapshot['total'] == 0:
        return None
    at = stamp(now)
    conn.execute('INSERT OR IGNORE INTO daily_task_outbox(user_id,settlement_id,event_id,event_type,payload_json,status,next_attempt_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
                 (user, settlement['id'], event_id, payload['event'], json.dumps(payload, ensure_ascii=False, separators=(',', ':')),
                  'pending' if configured else 'unconfigured', at if configured else None, at, at))
    return event_id


def cancel_settlement(conn, user, settlement, now):
    row = conn.execute("SELECT * FROM daily_task_outbox WHERE user_id=? AND settlement_id=? AND event_type='daily_settlement.completed'", (user, settlement['id'])).fetchone()
    if not row:
        return
    at = stamp(now)
    in_flight = row['status'] in ('processing', 'cancelling')
    conn.execute('UPDATE daily_task_outbox SET status=?,next_attempt_at=NULL,updated_at=? WHERE id=?', ('cancelling' if in_flight else 'cancelled', at, row['id']))
    if row['attempts'] == 0:
        return
    event_id = row['event_id'].rsplit(':', 1)[0] + ':cancelled'
    payload = {'protocol': 'daily-plan.v1', 'event': 'daily_settlement.cancelled', 'event_id': event_id,
               'retracts_event_id': row['event_id'], 'date': settlement['settlement_date'], 'cancelled_at': at}
    configured = settings(conn, user)['configured']
    conn.execute('INSERT OR IGNORE INTO daily_task_outbox(user_id,event_id,event_type,payload_json,status,next_attempt_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)',
                 (user, event_id, payload['event'], json.dumps(payload, ensure_ascii=False), 'pending' if configured else 'unconfigured', at if configured else None, at, at))


def post_https(url, token, payload, event_id):
    """Validate and pin public addresses while preserving TLS SNI/cert checks."""
    parsed = urlsplit(validate_url(url))
    host, port = parsed.hostname, parsed.port or 443
    addresses = list(dict.fromkeys(info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ReporterError('public_https_push_url_required')

    class PinnedHTTPS(http.client.HTTPSConnection):
        def connect(self):
            raw = socket.create_connection((addresses[0], port), timeout=self.timeout)
            try:
                self.sock = self._context.wrap_socket(raw, server_hostname=host)
            except Exception:
                raw.close()
                raise

    connection = PinnedHTTPS(host, port, timeout=8, context=ssl.create_default_context())
    try:
        headers = {'Content-Type': 'application/json; charset=utf-8', 'Idempotency-Key': event_id,
                   'User-Agent': 'MutsumiFocus-DailyPlan/1'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        path = parsed.path or '/'
        if parsed.query:
            path += '?' + parsed.query
        connection.request('POST', path, body=payload.encode('utf-8'), headers=headers)
        code = connection.getresponse().status
        # Redirects are never followed, particularly to a private target.
        return 200 <= code < 300
    finally:
        connection.close()


def deliver_due(app, now=None):
    now = now or current_time('UTC')
    at = stamp(now)
    conn = connect(app.config['DATABASE'])
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("UPDATE daily_task_outbox SET status='cancelled',lease_until=NULL WHERE status='cancelling' AND lease_until<=?", (at,))
        row = conn.execute("""SELECT q.* FROM daily_task_outbox q WHERE
            ((q.status IN ('pending','failed') AND q.next_attempt_at<=?) OR (q.status='processing' AND q.lease_until<=?))
            AND NOT EXISTS (SELECT 1 FROM daily_task_outbox active WHERE active.user_id=q.user_id AND active.id<>q.id
              AND active.status IN ('processing','cancelling') AND active.lease_until>?)
            ORDER BY q.id LIMIT 1""", (at, at, at)).fetchone()
        if not row:
            conn.commit()
            return False
        config = conn.execute('SELECT url,token FROM daily_task_push_settings WHERE user_id=?', (row['user_id'],)).fetchone()
        if not config or not config['url']:
            conn.execute("UPDATE daily_task_outbox SET status='unconfigured',next_attempt_at=NULL,updated_at=? WHERE id=?", (at, row['id']))
            conn.commit()
            return True
        attempts = row['attempts'] + 1
        lease = stamp(now + timedelta(seconds=60))
        conn.execute("UPDATE daily_task_outbox SET status='processing',attempts=?,lease_until=?,updated_at=? WHERE id=?", (attempts, lease, at, row['id']))
        conn.commit()
        transport = app.config.get('DAILY_TASK_PUSH_TRANSPORT') or post_https
        try:
            accepted = bool(transport(config['url'], config['token'], row['payload_json'], row['event_id']))
            error = '' if accepted else 'receiver_not_confirmed'
        except Exception:
            accepted, error = False, 'receiver_unreachable'
        finished = current_time('UTC') if not app.config.get('TESTING') else now
        delay = [15, 60, 180, 600, 1800][min(attempts - 1, 4)]
        retry_at = stamp(finished + timedelta(seconds=delay)) if not accepted and attempts < 5 else None
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("UPDATE daily_task_outbox SET status=?,next_attempt_at=?,lease_until=NULL,updated_at=?,last_error=? WHERE id=? AND status='processing' AND attempts=? AND lease_until=?", ('sent' if accepted else 'failed', retry_at, stamp(finished), error, row['id'], attempts, lease))
        conn.execute("UPDATE daily_task_outbox SET status='cancelled',lease_until=NULL,updated_at=? WHERE id=? AND status='cancelling' AND attempts=? AND lease_until=?", (stamp(finished), row['id'], attempts, lease))
        conn.commit()
        return True
    finally:
        conn.close()


def start_push_worker(app):
    if app.config.get('TESTING'):
        return
    stop = Event()
    def work():
        while not stop.wait(3):
            try:
                deliver_due(app)
            except Exception:
                # Do not log payloads, endpoint addresses or bearer credentials.
                app.logger.error('daily_task_delivery_worker_failed')
    Thread(target=work, name='daily-task-delivery', daemon=True).start()
    app.extensions['daily_task_delivery_stop'] = stop


def register_push_routes(app, run, payload):
    @app.route('/api/daily-tasks/push', methods=['GET', 'PUT'])
    @user_required
    def push_settings():
        def handle(conn):
            user, now = current_user_id(), current_time('UTC')
            if request.method == 'PUT':
                data = payload()
                url = validate_url(data.get('url', ''))
                row = conn.execute('SELECT token FROM daily_task_push_settings WHERE user_id=?', (user,)).fetchone()
                token = row['token'] if row else ''
                if 'token' in data:
                    token = data['token']
                    if not isinstance(token, str) or len(token) > 2048 or '\r' in token or '\n' in token:
                        raise ReporterError('invalid_push_token')
                conn.execute('BEGIN IMMEDIATE')
                conn.execute('INSERT INTO daily_task_push_settings(user_id,url,token,updated_at) VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET url=excluded.url,token=excluded.token,updated_at=excluded.updated_at', (user, url, token, stamp(now)))
                if url:
                    conn.execute("UPDATE daily_task_outbox SET status='pending',next_attempt_at=?,updated_at=? WHERE user_id=? AND status='unconfigured'", (stamp(now), stamp(now), user))
                conn.commit()
            return jsonify(**settings(conn, user), sync=status(conn, user, now))
        return run(handle)

    @app.post('/api/daily-tasks/push/retry')
    @user_required
    def retry_push():
        def handle(conn):
            user, now = current_user_id(), current_time('UTC')
            if not settings(conn, user)['configured']:
                raise ReporterError('push_not_configured', 409)
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute("SELECT id FROM daily_task_outbox WHERE user_id=? AND status IN ('failed','unconfigured') ORDER BY id LIMIT 1", (user,)).fetchone()
            if row:
                conn.execute("UPDATE daily_task_outbox SET status='pending',attempts=0,next_attempt_at=?,updated_at=?,last_error='' WHERE id=?", (stamp(now), stamp(now), row['id']))
            conn.commit()
            return jsonify(ok=True, changed=bool(row), sync=status(conn, user, now))
        return run(handle)
