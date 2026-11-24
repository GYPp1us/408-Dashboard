"""Account-scoped maintenance for the Android reminder question bank."""

import json
import secrets
from pathlib import Path

from flask import jsonify, request

from .auth import current_user_id, user_required
from .db import connect
from .focus_reporter import REPORT_BASE_URL

MAX_QUESTIONS = 128
EDITABLE_BANK_VERSION = 1


def validate_questions(value):
    if not isinstance(value, list) or len(value) > MAX_QUESTIONS:
        raise ValueError('invalid_questions')

    def text(value, limit):
        if not isinstance(value, str) or not value.strip() or len(value) > limit or '\x00' in value:
            raise ValueError('invalid_question_text')
        return value.strip()

    result = []
    for question in value:
        if not isinstance(question, dict) or not isinstance(question.get('options'), list):
            raise ValueError('invalid_question')
        body = text(question.get('body'), 560)
        options = [text(option, 80) for option in question['options']]
        answer = question.get('answer_index')
        if not 3 <= len(options) <= 5 or len(set(options)) != len(options):
            raise ValueError('invalid_options')
        if type(answer) is not int or not 0 <= answer < len(options):
            raise ValueError('invalid_answer_index')
        result.append({'body': body, 'options': options, 'answer_index': answer})
    if len({q['body'] for q in result}) != len(result):
        raise ValueError('duplicate_question')
    return result


INITIAL_QUESTIONS = validate_questions(json.loads(Path(__file__).with_name('reminder_question_seed.json').read_text(encoding='utf-8')))


def _find_bank(db, user, token):
    if token is not None:
        return db.execute('SELECT * FROM reminder_question_banks WHERE maintenance_key=?', (token,)).fetchone()
    return db.execute('SELECT * FROM reminder_question_banks WHERE user_id=?', (user,)).fetchone()


def _initialize_bank(db, user, row):
    if row is not None and row['editable_bank_version'] >= EDITABLE_BANK_VERSION:
        return row['revision'], json.loads(row['questions_json'])

    existing = json.loads(row['questions_json']) if row is not None else []
    bodies = {question['body'] for question in existing}
    questions = existing + [question for question in INITIAL_QUESTIONS if question['body'] not in bodies]
    revision = (row['revision'] if row is not None else 0) + 1
    db.execute(
        'INSERT INTO reminder_question_banks(user_id, revision, questions_json, editable_bank_version) VALUES (?,?,?,?) '
        'ON CONFLICT(user_id) DO UPDATE SET revision=excluded.revision,questions_json=excluded.questions_json,'
        'editable_bank_version=excluded.editable_bank_version',
        (user, revision, json.dumps(questions, ensure_ascii=False, separators=(',', ':')), EDITABLE_BANK_VERSION),
    )
    return revision, questions


def register_reminder_questions(app):
    def no_store(response):
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.route('/api/reminder-questions/bank', methods=['GET', 'PUT'])
    def bank():
        def handle(user=None, token=None):
            db = connect(app.config['DATABASE'])
            try:
                if request.method == 'PUT':
                    request.max_content_length = 1_600_000
                    data = request.get_json(silent=True)
                    if not isinstance(data, dict) or type(data.get('expected_revision')) is not int:
                        return jsonify(error='expected_revision_required'), 400
                    try:
                        questions = validate_questions(data.get('questions'))
                    except ValueError as error:
                        return jsonify(error=str(error)), 400
                if request.method == 'GET':
                    row = _find_bank(db, user, token)
                    if token is not None and row is None:
                        return jsonify(error='invalid_maintenance_key'), 401
                    if row is not None and row['editable_bank_version'] >= EDITABLE_BANK_VERSION:
                        return no_store(jsonify(revision=row['revision'], questions=json.loads(row['questions_json'])))
                db.execute('BEGIN IMMEDIATE')
                row = _find_bank(db, user, token)
                if token is not None:
                    if row is None:
                        return jsonify(error='invalid_maintenance_key'), 401
                    user = row['user_id']
                revision, current_questions = _initialize_bank(db, user, row)
                if request.method == 'GET':
                    db.commit()
                    return no_store(jsonify(revision=revision, questions=current_questions))
                if revision != data['expected_revision']:
                    db.commit()
                    return jsonify(error='question_bank_changed', revision=revision), 409
                db.execute('UPDATE reminder_question_banks SET revision=?, questions_json=? WHERE user_id=?',
                           (revision+1, json.dumps(questions, ensure_ascii=False, separators=(',', ':')), user))
                db.commit()
                return no_store(jsonify(revision=revision+1, questions=questions))
            finally:
                db.close()

        authorization = request.headers.get('Authorization')
        if authorization is not None:
            scheme, _, token = authorization.partition(' ')
            if scheme.lower() != 'bearer' or not 32 <= len(token) <= 100:
                return jsonify(error='invalid_maintenance_key'), 401
            return handle(token=token)
        return user_required(lambda: handle(current_user_id()))()

    @app.post('/api/reminder-questions/connection')
    @app.post('/api/reminder-questions/connection/rotate')
    @user_required
    def connection():
        db = connect(app.config['DATABASE'])
        try:
            user = current_user_id()
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT maintenance_key FROM reminder_question_banks WHERE user_id=?', (user,)).fetchone()
            token = row['maintenance_key'] if row else None
            if not token or request.path.endswith('/rotate'):
                token = secrets.token_urlsafe(32)
                db.execute('INSERT INTO reminder_question_banks(user_id, maintenance_key) VALUES (?,?) '
                           'ON CONFLICT(user_id) DO UPDATE SET maintenance_key=excluded.maintenance_key', (user, token))
            db.commit()
            url = REPORT_BASE_URL + '/api/reminder-questions/bank'
            prompt = '\n'.join([
                '维护 Mutsumi Focus 专注提醒题库。请先核算每一道题，保证只有一个正确选项。',
                f'GET {url} 读取 revision 和全部题目。先读取和合并，再 PUT 到同一地址替换题库，Content-Type: application/json。',
                f'Authorization: Bearer {token}',
                '此凭据只用于此题库，不应写进日志。',
                '提交 {"expected_revision":读取的数字,"questions":[{"body":"求极限：\\n$$\\n\\\\frac{\\\\sin x}{x}\\n$$","options":["0","1","2"],"answer_index":1}]}。',
                f'answer_index 从 0 开始，每题 3–5 个不同选项，题干最多 560 字，单选项最多 80 字，最多 {MAX_QUESTIONS} 题。支持 $$ 独占行包围的公式、$…$ 行内公式、三反引号代码块。公式使用常用 TeX 子集（lim、frac、sin、sqrt、上下标等）。',
                '所有题目均可编辑和删除。questions: [] 会清空整个题库，清空后须重新添加题目才可答题。HTTP 409 时先重读。建议提交 UTF-8 JSON。',
            ])
            return no_store(jsonify(bank_url=url, prompt=prompt))
        finally:
            db.close()
