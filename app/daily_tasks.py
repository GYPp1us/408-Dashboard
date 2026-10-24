"""Account-scoped daily plans, focus attribution, completion history and Agent keys."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import unicodedata
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from flask import jsonify, request

from .auth import current_user_id, user_required
from .db import connect, get_focus_item, get_settings, get_subject, list_focus_items, list_subjects
from .focus_reporter import KEY_PATTERN, SOURCE_PATTERN, REPORT_BASE_URL, ReporterError
from .services import current_time


def local_day(conn, user, now):
    return now.astimezone(ZoneInfo(get_settings(conn, user).get('timezone', 'Asia/Shanghai'))).date().isoformat()


def plan_day(value, fallback):
    if value is None:
        return fallback
    if not isinstance(value, str) or len(value) != 10:
        raise ReporterError('invalid_plan_date')
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ReporterError('invalid_plan_date')


def source_name(value):
    if not isinstance(value, str) or not SOURCE_PATTERN.fullmatch(value):
        raise ReporterError('invalid_source')
    return value


def text(value, limit, code, required=False):
    if not isinstance(value, str) or len(value.strip()) > limit or required and not value.strip():
        raise ReporterError(code)
    return value.strip()


def completion(conn, user, task, value, source, now):
    if type(value) is not bool:
        raise ReporterError('invalid_completed')
    if bool(task['completed']) == value:
        return False
    at = now.astimezone(timezone.utc).isoformat()
    conn.execute('UPDATE daily_tasks SET completed=?,completed_at=?,revision=revision+1,updated_at=? WHERE id=? AND user_id=?',
                 (int(value), at if value else None, at, task['id'], user))
    conn.execute('INSERT INTO daily_task_events(user_id,task_id,completed,source,accepted_at) VALUES (?,?,?,?,?)',
                 (user, task['id'], int(value), source, at))
    return True


def catalog(conn, user, now, day=None):
    day = plan_day(day, local_day(conn, user, now))
    rows = conn.execute('SELECT * FROM daily_tasks WHERE user_id=? AND plan_date=? AND archived=0 ORDER BY sort_order,id', (user, day)).fetchall()
    tasks = []
    # Reuse the established pause-aware, per-session calculation rather than
    # maintaining a second duration formula for plan completion.
    from .routes import _row
    for row in rows:
        item = dict(row)
        ids = [r['session_id'] for r in conn.execute('SELECT session_id FROM daily_task_focus_links WHERE user_id=? AND task_id=? ORDER BY session_id', (user, row['id']))]
        records = []
        for session_id in ids:
            session = _row(conn, session_id, now)
            if session and session['user_id'] == user:
                records.append({key: session[key] for key in ('id', 'subject', 'started_at', 'ended_at', 'effective_seconds')})
        item.update(completed=bool(item['completed']), archived=bool(item['archived']), focus_seconds=sum(r['effective_seconds'] for r in records), focus_records=records)
        tasks.append(item)
    events = [dict(r, completed=bool(r['completed'])) for r in conn.execute('SELECT e.id,e.task_id,e.completed,e.source,e.accepted_at FROM daily_task_events e JOIN daily_tasks t ON t.id=e.task_id WHERE e.user_id=? AND t.plan_date=? ORDER BY e.id', (user, day))]
    return {'date': day, 'timezone': get_settings(conn, user).get('timezone', 'Asia/Shanghai'), 'tasks': tasks,
            'total': len(tasks), 'completed': sum(t['completed'] for t in tasks), 'focus_seconds': sum(t['focus_seconds'] for t in tasks),
            'completion_records': events}


def summary(conn, user, now):
    day = local_day(conn, user, now)
    row = conn.execute('SELECT count(*) AS total,coalesce(sum(completed),0) AS completed,coalesce(sum(revision),0) AS revisions,coalesce(max(updated_at),\'\') AS updated FROM daily_tasks WHERE user_id=? AND plan_date=? AND archived=0', (user, day)).fetchone()
    return {'date': day, 'total': row['total'], 'completed': row['completed'], 'revision': f"{day}:{row['total']}:{row['completed']}:{row['revisions']}:{row['updated']}"}


def upsert(conn, user, payload, now):
    source = source_name(payload.get('source', 'agent'))
    day = plan_day(payload.get('date'), local_day(conn, user, now))
    entries = payload.get('tasks')
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise ReporterError('tasks_array_required')
    at = now.astimezone(timezone.utc).isoformat()
    conn.execute('BEGIN IMMEDIATE')
    changed = False
    try:
        seen = set()
        for position, data in enumerate(entries):
            if not isinstance(data, dict):
                raise ReporterError('invalid_task')
            title = text(data.get('title'), 120, 'invalid_task_title', True)
            identity = data.get('external_id')
            if identity is None:
                normalized = ' '.join(unicodedata.normalize('NFKC', title).casefold().split())
                identity = 'name:' + hashlib.sha256(normalized.encode()).hexdigest()[:24]
            identity = text(identity, 128, 'invalid_external_id', True)
            if identity in seen:
                raise ReporterError('duplicate_external_id')
            seen.add(identity)
            existing = conn.execute('SELECT * FROM daily_tasks WHERE user_id=? AND plan_date=? AND source=? AND external_id=?', (user, day, source, identity)).fetchone()
            values = dict(existing) if existing else {'note': '', 'subject_id': None, 'focus_item_id': None, 'target_minutes': None, 'archived': 0, 'sort_order': position}
            note = text(data.get('note', values['note']), 2000, 'invalid_task_note')
            target = data.get('target_minutes', values['target_minutes'])
            if target is not None and (type(target) is not int or not 0 <= target <= 1440):
                raise ReporterError('invalid_target_minutes')
            subject_id, item_id = data.get('subject_id', values['subject_id']), data.get('focus_item_id', values['focus_item_id'])
            if item_id is not None:
                item = get_focus_item(conn, user, item_id) if type(item_id) is int else None
                if not item or subject_id is not None and item['subject_id'] != subject_id:
                    raise ReporterError('focus_item_not_found', 404)
                subject_id = item['subject_id']
            if subject_id is not None and (type(subject_id) is not int or not get_subject(conn, user, subject_id)):
                raise ReporterError('subject_not_found', 404)
            archived = data.get('archived', bool(values['archived']))
            order = data.get('sort_order', values['sort_order'])
            if type(archived) is not bool or type(order) is not int or not -10000 <= order <= 10000:
                raise ReporterError('invalid_task_order_or_archive')
            fields = (title, note, subject_id, item_id, target, order, int(archived))
            if existing:
                previous = tuple(existing[k] for k in ('title','note','subject_id','focus_item_id','target_minutes','sort_order','archived'))
                if fields != previous:
                    conn.execute('UPDATE daily_tasks SET title=?,note=?,subject_id=?,focus_item_id=?,target_minutes=?,sort_order=?,archived=?,revision=revision+1,updated_at=? WHERE id=?', (*fields, at, existing['id']))
                    changed = True
                task_id = existing['id']
            else:
                cursor = conn.execute('INSERT INTO daily_tasks(user_id,plan_date,source,external_id,title,note,subject_id,focus_item_id,target_minutes,sort_order,archived,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', (user, day, source, identity, *fields, at, at))
                task_id = cursor.lastrowid
                changed = True
            if 'completed' in data:
                task = conn.execute('SELECT * FROM daily_tasks WHERE id=?', (task_id,)).fetchone()
                changed = completion(conn, user, task, data['completed'], source, now) or changed
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {'ok': True, 'changed': changed, **catalog(conn, user, now, day)}


def connection_details(conn, user, now, rotate=False):
    conn.execute('BEGIN IMMEDIATE')
    try:
        row = conn.execute('SELECT token FROM daily_task_reporter_keys WHERE user_id=?', (user,)).fetchone()
        if row is None or rotate:
            token = f'{user}.{secrets.token_hex(32)}'
            conn.execute('INSERT INTO daily_task_reporter_keys(user_id,token,created_at) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET token=excluded.token,created_at=excluded.created_at', (user, token, now.isoformat()))
        else:
            token = row['token']
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    base = f'{REPORT_BASE_URL}/api/daily-plan-reporter/{token}'
    details = {'report_url': base + '/frame', 'today_url': base + '/today', 'catalog_url': base + '/today', 'completion_url': base + '/complete', 'protocol': 'daily-plan.v1'}
    details['prompt'] = agent_prompt(details)
    return details



def agent_prompt(details):
    return "\n".join([
        "请按 daily-plan.v1 协议接入 Mutsumi Focus，每日计划以本端数据口径为准。",
        f"1. GET {details['today_url']} 读取账户时区下的今日 tasks、completed/total、focus_seconds、completion_records，以及 subjects/focus_items 目录。可选 ?date=YYYY-MM-DD 读取指定计划日。",
        f"2. POST {details['report_url']}，Content-Type: application/json。最简 JSON：" + '{"tasks":[{"title":"完成一套数学模拟"}]}。',
        '完整示例：{"source":"my_agent","date":"2026-10-24","tasks":[{"external_id":"math-paper-01","title":"完成一套数学模拟","note":"先限时，再订正","target_minutes":120,"subject_id":1,"focus_item_id":2}]}。',
        "source 可省略，默认 agent，建议每个系统固定一个英文标识。date 可省略，使用服务端账户今日。external_id 可省略，按规范化任务名生成；需要改名时应固定 external_id。相同来源、日期及外部 ID 幂等更新，省略项不会删除旧任务。",
        "subject_id/focus_item_id 使用 GET 返回的本账户目录 ID，可省略；有项目时科目需匹配。target_minutes 为 0–1440 整数，可省略；note 可省略。archived=true 移出任务但保留历史；省略 completed 不会重置完成状态。",
        f"3. GET {details['today_url']} 可随时查看用户在 APP 中归类的真实专注记录与完成状态。一个任务可关联多段专注，focus_seconds 自动扣除暂停，重复保存不重复计时。",
        f"确需主动更正完成状态时，POST {details['completion_url']}，JSON " + '{"task_id":目录中的数字ID,"completed":true,"expected_revision":读取到的revision}。false 可撤销完成；409 daily_task_changed 时重新读取，不盲目覆盖。',
        "4. 准备一个公网 HTTPS JSON 接收接口，在 APP 每日计划接入设置中填写地址，以及可选的双方约定鉴权密钥。结算后本端主动 POST，不要求接收方轮询等待。",
        '推送示例：{"protocol":"daily-plan.v1","event":"daily_settlement.completed","event_id":"稳定事件ID","date":"2026-10-24","settled_at":"ISO时间","timezone":"Asia/Shanghai","tasks":{"date":"2026-10-24","total":2,"completed":1,"focus_seconds":7200,"tasks":[...],"completion_records":[...]}}。',
        "请求头 Idempotency-Key 与 event_id 相同；配置密钥时带 Authorization: Bearer <双方约定密钥>。校验并持久保存后返回任意 2xx，勿依赖响应正文。",
        "推送至少一次，可能重试；同一 event_id 的结算快照保持不变，接收端必须按 event_id 去重。不得因重复推送重复累加时长或完成次数。结算后的任务修改可通过今日接口读取，不会改写已结算快照。",
        '用户取消已推送或结果不确定的结算时，还会收到 {"protocol":"daily-plan.v1","event":"daily_settlement.cancelled","event_id":"撤销事件ID","retracts_event_id":"原结算事件ID","date":"YYYY-MM-DD","cancelled_at":"ISO时间"}，请按 retracts_event_id 撤销对应快照。新的重新结算使用新事件 ID。',
        "5. key 长期有效，只有在 APP 手动更换后旧链接失效；与专注上报、打卡 key 独立。链接含密钥，按密码保护，不写公开仓库或日志。401 表示 key 无效；404 表示任务/项目不属于本账户；409 表示状态冲突。不要用模拟数据回报真实任务已完成。",
    ])


def authenticate(conn, key):
    match = KEY_PATTERN.fullmatch(key)
    if not match:
        return None
    user = int(match.group(1))
    row = conn.execute('SELECT token FROM daily_task_reporter_keys WHERE user_id=?', (user,)).fetchone()
    return user if row and hmac.compare_digest(row['token'], key) else None


def complete_task(conn, user, data, now, source='app'):
    task_id = data.get('task_id')
    if type(task_id) is not int:
        raise ReporterError('task_id_required')
    conn.execute('BEGIN IMMEDIATE')
    try:
        task = conn.execute('SELECT * FROM daily_tasks WHERE id=? AND user_id=?', (task_id, user)).fetchone()
        if not task:
            raise ReporterError('daily_task_not_found', 404)
        if 'expected_revision' in data and (type(data['expected_revision']) is not int or data['expected_revision'] != task['revision']):
            raise ReporterError('daily_task_changed', 409)
        changed = completion(conn, user, task, data.get('completed'), source, now)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {'ok': True, 'changed': changed, **catalog(conn, user, now, task['plan_date'])}


def assign_focus(conn, user, session_id, data, now):
    conn.execute('BEGIN IMMEDIATE')
    try:
        session = conn.execute('SELECT * FROM focus_sessions WHERE id=? AND user_id=?', (session_id, user)).fetchone()
        if not session:
            raise ReporterError('focus_session_not_found', 404)
        if session['status'] == 'active' or not session['ended_at']:
            raise ReporterError('focus_session_not_ended', 409)
        task_id = data.get('task_id')
        task = None
        if task_id is not None:
            if type(task_id) is not int:
                raise ReporterError('invalid_task_id')
            task = conn.execute('SELECT * FROM daily_tasks WHERE id=? AND user_id=? AND archived=0', (task_id, user)).fetchone()
            if not task:
                raise ReporterError('daily_task_not_found', 404)
            if 'expected_revision' in data and (type(data['expected_revision']) is not int or data['expected_revision'] != task['revision']):
                raise ReporterError('daily_task_changed', 409)
        elif 'completed' in data:
            raise ReporterError('task_required_for_completion')
        before = conn.execute('SELECT task_id FROM daily_task_focus_links WHERE session_id=? AND user_id=?', (session_id, user)).fetchone()
        changed = (before['task_id'] if before else None) != task_id
        at = now.astimezone(timezone.utc).isoformat()
        if changed:
            conn.execute('DELETE FROM daily_task_focus_links WHERE session_id=? AND user_id=?', (session_id, user))
            if task_id is not None:
                conn.execute('INSERT INTO daily_task_focus_links(session_id,task_id,user_id,updated_at) VALUES (?,?,?,?)', (session_id, task_id, user, at))
            for affected in {before['task_id'] if before else None, task_id} - {None}:
                conn.execute('UPDATE daily_tasks SET revision=revision+1,updated_at=? WHERE id=? AND user_id=?', (at, affected, user))
        if task is not None and 'completed' in data:
            changed = completion(conn, user, task, data['completed'], 'app', now) or changed
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {'ok': True, 'changed': changed, 'session_id': session_id, 'task_id': task_id}


def register_daily_tasks(app):
    def run(callback):
        conn = connect(app.config['DATABASE'])
        try:
            return callback(conn)
        except ReporterError as error:
            conn.rollback()
            return jsonify(error=error.code), error.status
        finally:
            conn.close()

    def payload():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ReporterError('json_object_required')
        return data

    @app.get('/api/daily-tasks')
    @user_required
    def daily_tasks_catalog():
        return run(lambda c: jsonify(catalog(c, current_user_id(), current_time('UTC'), request.args.get('date'))))

    @app.post('/api/daily-tasks/complete')
    @user_required
    def daily_task_complete():
        return run(lambda c: jsonify(complete_task(c, current_user_id(), payload(), current_time('UTC'))))

    @app.route('/api/focus/<int:session_id>/daily-task', methods=['GET', 'PUT'])
    @user_required
    def daily_task_focus(session_id):
        def handle(c):
            user, now = current_user_id(), current_time('UTC')
            if request.method == 'PUT':
                return jsonify(assign_focus(c, user, session_id, payload(), now))
            from .routes import _row
            session = _row(c, session_id, now)
            if not session or session['user_id'] != user:
                raise ReporterError('focus_session_not_found', 404)
            row = c.execute('SELECT task_id FROM daily_task_focus_links WHERE session_id=? AND user_id=?', (session_id, user)).fetchone()
            return jsonify(session=session, task_id=row['task_id'] if row else None)
        return run(handle)

    @app.post('/api/daily-plan-reporter/connection')
    @app.post('/api/daily-plan-reporter/connection/rotate')
    @user_required
    def daily_plan_connection():
        return run(lambda c: jsonify(connection_details(c, current_user_id(), current_time('UTC'), request.path.endswith('/rotate'))))

    def external(key, callback):
        def handle(c):
            user = authenticate(c, key)
            if user is None:
                raise ReporterError('invalid_reporter_key', 401)
            return callback(c, user, current_time('UTC'))
        return run(handle)

    @app.get('/api/daily-plan-reporter/<key>/today')
    def daily_plan_external_today(key):
        return external(key, lambda c, u, n: jsonify(**catalog(c, u, n, request.args.get('date')), subjects=list_subjects(c, u), focus_items=list_focus_items(c, u)))

    @app.post('/api/daily-plan-reporter/<key>/frame')
    def daily_plan_external_frame(key):
        return external(key, lambda c, u, n: jsonify(upsert(c, u, payload(), n)))

    @app.post('/api/daily-plan-reporter/<key>/complete')
    def daily_plan_external_complete(key):
        return external(key, lambda c, u, n: jsonify(complete_task(c, u, payload(), n, 'agent')))

    from .daily_task_push import register_push_routes
    register_push_routes(app, run, payload)
