"""Account-scoped maintenance for the Android reminder question bank."""

import json
import secrets

from flask import jsonify, request

from .auth import current_user_id, user_required
from .db import connect
from .focus_reporter import REPORT_BASE_URL


def validate_questions(value):
    if not isinstance(value, list) or len(value) > 48:
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
                    request.max_content_length = 96_000
                    data = request.get_json(silent=True)
                    if not isinstance(data, dict) or type(data.get('expected_revision')) is not int:
                        return jsonify(error='expected_revision_required'), 400
                    try:
                        questions = validate_questions(data.get('questions'))
                    except ValueError as error:
                        return jsonify(error=str(error)), 400
                    db.execute('BEGIN IMMEDIATE')
                if token is not None:
                    row = db.execute('SELECT user_id FROM reminder_question_banks WHERE maintenance_key=?', (token,)).fetchone()
                    if row is None:
                        return jsonify(error='invalid_maintenance_key'), 401
                    user = row['user_id']
                row = db.execute('SELECT revision, questions_json FROM reminder_question_banks WHERE user_id=?', (user,)).fetchone()
                revision = row['revision'] if row else 0
                if request.method == 'GET':
                    return no_store(jsonify(revision=revision, questions=json.loads(row['questions_json']) if row else []))
                if revision != data['expected_revision']:
                    return jsonify(error='question_bank_changed', revision=revision), 409
                db.execute('INSERT INTO reminder_question_banks(user_id, revision, questions_json) VALUES (?,?,?) '
                           'ON CONFLICT(user_id) DO UPDATE SET revision=excluded.revision,questions_json=excluded.questions_json',
                           (user, revision+1, json.dumps(questions, ensure_ascii=False, separators=(',', ':'))))
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
                f'GET {url} 读取 revision 和 questions。PUT 同一地址替换自定义题库，Content-Type: application/json。',
                f'Authorization: Bearer {token}',
                '此凭据只用于此题库，不应写进日志。',
                '提交 {"expected_revision":读取的数字,"questions":[{"body":"求极限：\\n$$\\n\\\\frac{\\\\sin x}{x}\\n$$","options":["0","1","2"],"answer_index":1}]}。',
                'answer_index 从 0 开始，每题 3–5 个不同选项，最多 48 题。题干支持 $$ 独占行包围的公式、$…$ 行内公式、三反引号代码块。公式使用常用 TeX 子集（lim、frac、sin、sqrt、上下标等）。',
                '请优先编写 x→0 时可以用一两项幂级数化简的小题；删除自定义题时提交 questions: []，设备将保留内置题库。409 时先重读。',
            ])
            return no_store(jsonify(bank_url=url, prompt=prompt))
        finally:
            db.close()
