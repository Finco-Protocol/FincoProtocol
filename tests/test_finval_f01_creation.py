"""Existing standalone Solar/Wind creation adapter establishes canonical units."""
import json
import pytest
from tests.model_react_test_helpers import react_fields_save_contract
from tests.test_qa_create_project_country_capacity import client, _login
from app.input_adapter import RATE_UNIT_KEY, RATE_UNIT, senior_rate_authority
from app.workbook.input_set import ProjectInputSet


@pytest.mark.parametrize('kind,project_type', [('solar', 'Solar'), ('wind', 'Wind')])
def test_standalone_create_persists_four_true_human_rates(client, kind, project_type):
    from app.persistence import db
    _login(client)
    for human in (.056, .56, 5.6, 9.):
        opts = client.get('/v2/model-react/new-project/options').json()
        name = f'F01 standalone {kind} {human}'
        created = client.post('/v2/model-react/new-project/create', json={
            'request_id': opts['request_id'], 'csrf_token': opts['csrf_token'],
            'name': name, 'technology': kind, 'country': 'HR', 'capacity_mw': 20.0,
            'acknowledge_preview': True,
        })
        assert created.status_code in (200, 201), created.text[:500]
        code = created.json()['project']['code']
        save = react_fields_save_contract(client, code, 'debt')
        upd = client.post('/v2/workbook/update', data={
            'project': code, 'sheet_id': 'debt', 'field_id': 'debt.senior.interest_rate_pct',
            'value': str(human), 'workbook_version': save['workbook_version'],
            'content_hash': save['content_hash'], 'csrf_token': save['csrf_token'],
        }, follow_redirects=False)
        assert upd.status_code in (200, 303), upd.text[:500]
        with db.get_connection() as c:
            row = c.execute('SELECT * FROM projects WHERE project_name=?', (name,)).fetchone()
            ws = c.execute('SELECT * FROM workspace_states WHERE project_id=?', (row['project_id'],)).fetchone()
        base_snap = json.loads(row['baseline_snapshot_json'])
        assert base_snap[RATE_UNIT_KEY] == RATE_UNIT
        saved_snap = json.loads(ws['saved_snapshot_json'])
        assert saved_snap[RATE_UNIT_KEY] == RATE_UNIT
        snap = json.loads(ws['draft_snapshot_json'])
        assert snap[RATE_UNIT_KEY] == RATE_UNIT
        assert float(snap['interest_rate_pct']) == human
        assert senior_rate_authority(ProjectInputSet.from_snapshot(snap).to_projectinputs())[1] == pytest.approx(human / 100, abs=1e-17)
