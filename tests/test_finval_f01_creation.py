"""Existing standalone Solar/Wind creation adapter establishes canonical units."""
import json
import pytest
from tests.test_qa_create_project_country_capacity import client,_login
from app.input_adapter import RATE_UNIT_KEY,RATE_UNIT,senior_rate_authority
from app.workbook.input_set import ProjectInputSet

@pytest.mark.parametrize('kind,project_type',[('solar','Solar'),('wind','Wind')])
def test_standalone_create_persists_four_true_human_rates(client,kind,project_type):
    import main_web
    from app.persistence import db
    _login(client)
    for human in [.056,.56,5.6,9.]:
        data=main_web._generic_prefill_values('generic_'+kind)
        data.update(project_name=f'F01 standalone {kind} {human}',country_market='HR',interest_rate_pct=str(human))
        response=client.post('/projects/create',data=data,follow_redirects=False)
        assert response.status_code in (200,303),response.text[:500]
        with db.get_connection() as c:
            row=c.execute('SELECT * FROM projects WHERE project_name=?',(data['project_name'],)).fetchone()
            ws=c.execute('SELECT * FROM workspace_states WHERE project_id=?',(row['project_id'],)).fetchone()
        for raw in [row['baseline_snapshot_json'],ws['draft_snapshot_json'],ws['saved_snapshot_json']]:
            snap=json.loads(raw)
            assert snap[RATE_UNIT_KEY]==RATE_UNIT
            assert float(snap['interest_rate_pct'])==human
            assert senior_rate_authority(ProjectInputSet.from_snapshot(snap).to_projectinputs())[1]==pytest.approx(human/100,abs=1e-17)
