import json

import pytest

from app import create_app
from app.db import connect


@pytest.fixture
def clients(tmp_path):
    app = create_app({'TESTING': True, 'DATABASE': str(tmp_path / 'bank.sqlite3'), 'ADMIN_PASSWORD': 'test'})
    owner = app.test_client()
    assert owner.post('/login', data={'password': 'test'}).status_code in (302, 303)
    outsider = app.test_client()
    return owner, outsider


PATH = '/api/reminder-questions/bank'
CONNECTION = '/api/reminder-questions/connection'
QUESTION = {'body': '求极限\n$$\n\\frac{\\sin x}{x}\n$$\n```python\nx = 0\n```', 'options': ['0', '1', '2'], 'answer_index': 1}


def test_owner_can_manage_question_bank_with_optimistic_revision(clients):
    owner, outsider = clients
    assert outsider.get(PATH).status_code == 401
    initial = owner.get(PATH).get_json()
    assert initial['revision'] == 1
    assert len(initial['questions']) == 50
    assert len({question['body'] for question in initial['questions']}) == 50
    assert all(any(category in question['body'] for question in initial['questions']) for category in ('极限', '定积分', '级数', '口算'))
    edited = {**initial['questions'][0], 'options': ['1', '0', '-1']}
    put = {'expected_revision': 1, 'questions': [edited]}
    assert owner.put(PATH, json=put).get_json() == {'questions': [edited], 'revision': 2}
    assert owner.get(PATH).headers['Cache-Control'] == 'no-store'
    assert owner.put(PATH, json=put).status_code == 409
    assert owner.put(PATH, json={'expected_revision': 2, 'questions': []}).get_json()['questions'] == []
    assert owner.get(PATH).get_json() == {'questions': [], 'revision': 3}
    owner.post(CONNECTION + '/rotate')
    assert owner.get(PATH).get_json() == {'questions': [], 'revision': 3}
    outsider.get('/guest')
    assert outsider.get(PATH).status_code == 403
    assert outsider.post(CONNECTION).status_code == 403


def test_maintenance_prompt_key_rotates_without_changing_bank_or_allowing_other_api(clients):
    owner, outsider = clients
    prompt = owner.post(CONNECTION).get_json()['prompt']
    token = prompt.split('Authorization: Bearer ', 1)[1].splitlines()[0]
    assert token and 'answer_index' in prompt
    headers = {'Authorization': f'Bearer {token}'}
    assert len(outsider.get(PATH, headers=headers).get_json()['questions']) == 50
    assert outsider.put(PATH, headers=headers, json={'expected_revision': 1, 'questions': [QUESTION]}).status_code == 200
    assert outsider.get('/api/dashboard', headers=headers).status_code == 401
    assert outsider.get(PATH, headers={'Authorization': 'Bearer invalid-example-key'}).status_code == 401
    assert token not in owner.post(CONNECTION + '/rotate').get_json()['prompt']
    assert outsider.get(PATH, headers=headers).status_code == 401
    assert owner.get(PATH).get_json() == {'questions': [QUESTION], 'revision': 2}


def test_question_bank_accepts_512_max_length_questions_and_rejects_513(clients):
    owner, _ = clients
    revision = owner.get(PATH).get_json()['revision']
    questions = [
        {'body': str(index).ljust(560, '🧮'), 'options': [symbol * 80 for symbol in '🤔😐🫠🤓🤯'], 'answer_index': 0}
        for index in range(512)
    ]
    payload = json.dumps({'expected_revision': revision, 'questions': questions}, ensure_ascii=True)
    saved = owner.put(PATH, data=payload, content_type='application/json')
    assert saved.status_code == 200
    assert saved.get_json() == {'revision': revision + 1, 'questions': questions}

    rejected = owner.put(PATH, json={'expected_revision': revision + 1, 'questions': [*questions, QUESTION]})
    assert rejected.status_code == 400
    assert rejected.get_json() == {'error': 'invalid_questions'}


def test_upgrade_preserves_custom_questions_key_and_overrides(clients):
    owner, outsider = clients
    initial = owner.get(PATH).get_json()['questions']
    override = {**initial[0], 'options': ['2', '1', '0'], 'answer_index': 1}
    legacy = [override] + [{**QUESTION, 'body': f'已有题 {index}'} for index in range(47)]
    token = 'legacy-maintenance-token-0123456789'
    with connect(owner.application.config['DATABASE']) as db:
        db.execute('UPDATE reminder_question_banks SET revision=7, questions_json=?, maintenance_key=?, editable_bank_version=0',
                   (json.dumps(legacy), token))
    headers = {'Authorization': f'Bearer {token}'}
    conflict = outsider.put(PATH, headers=headers, json={'expected_revision': 7, 'questions': []})
    assert conflict.status_code == 409
    assert conflict.get_json()['revision'] == 8
    expected = {'revision': 8, 'questions': legacy + initial[1:]}
    assert outsider.get(PATH, headers=headers).get_json() == expected
    assert owner.get(PATH).get_json() == expected
    assert outsider.put(PATH, headers=headers, json={'expected_revision': 8, 'questions': expected['questions']}).status_code == 200


@pytest.mark.parametrize('question', [
    {**QUESTION, 'answer_index': True},
    {**QUESTION, 'answer_index': 3},
    {**QUESTION, 'options': ['0', '0', '1']},
    {**QUESTION, 'body': ' '},
])
def test_invalid_questions_cannot_replace_good_bank(clients, question):
    owner, _ = clients
    revision = owner.get(PATH).get_json()['revision']
    assert owner.put(PATH, json={'expected_revision': revision, 'questions': [QUESTION]}).status_code == 200
    assert owner.put(PATH, json={'expected_revision': revision + 1, 'questions': [question]}).status_code == 400
    assert owner.get(PATH).get_json() == {'questions': [QUESTION], 'revision': revision + 1}
