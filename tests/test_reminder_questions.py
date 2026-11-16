import pytest

from app import create_app


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
    assert owner.get(PATH).get_json() == {'questions': [], 'revision': 0}
    put = {'expected_revision': 0, 'questions': [QUESTION]}
    assert owner.put(PATH, json=put).get_json() == {'questions': [QUESTION], 'revision': 1}
    assert owner.get(PATH).headers['Cache-Control'] == 'no-store'
    assert owner.put(PATH, json=put).status_code == 409
    assert owner.put(PATH, json={'expected_revision': 1, 'questions': []}).get_json()['questions'] == []
    outsider.get('/guest')
    assert outsider.get(PATH).status_code == 403
    assert outsider.post(CONNECTION).status_code == 403


def test_maintenance_prompt_key_rotates_without_changing_bank_or_allowing_other_api(clients):
    owner, outsider = clients
    prompt = owner.post(CONNECTION).get_json()['prompt']
    token = prompt.split('Authorization: Bearer ', 1)[1].splitlines()[0]
    assert token and 'answer_index' in prompt
    headers = {'Authorization': f'Bearer {token}'}
    assert outsider.put(PATH, headers=headers, json={'expected_revision': 0, 'questions': [QUESTION]}).status_code == 200
    assert outsider.get('/api/dashboard', headers=headers).status_code == 401
    assert outsider.get(PATH, headers={'Authorization': 'Bearer invalid-example-key'}).status_code == 401
    assert token not in owner.post(CONNECTION + '/rotate').get_json()['prompt']
    assert outsider.get(PATH, headers=headers).status_code == 401
    assert owner.get(PATH).get_json() == {'questions': [QUESTION], 'revision': 1}


@pytest.mark.parametrize('question', [
    {**QUESTION, 'answer_index': True},
    {**QUESTION, 'answer_index': 3},
    {**QUESTION, 'options': ['0', '0', '1']},
    {**QUESTION, 'body': ' '},
])
def test_invalid_questions_cannot_replace_good_bank(clients, question):
    owner, _ = clients
    assert owner.put(PATH, json={'expected_revision': 0, 'questions': [QUESTION]}).status_code == 200
    assert owner.put(PATH, json={'expected_revision': 1, 'questions': [question]}).status_code == 400
    assert owner.get(PATH).get_json() == {'questions': [QUESTION], 'revision': 1}
