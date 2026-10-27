"""F01 real Chromium round-trip, existing RC-M UI consumed without modification."""
import json
import os
from pathlib import Path
import pytest
from tests.test_workflow_c_browser_v1 import live_server, browser

@pytest.mark.parametrize('kind',['solar','wind','data_center','ev_charging'])
def test_low_and_standard_percent_are_distinct_after_save_and_reload(live_server,browser,monkeypatch,kind,tmp_path):
    monkeypatch.setenv('FINCO_MODEL_REACT_V1','1')
    from app.auth import COOKIE_NAME,create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.input_set import ProjectInputSet
    from app.input_adapter import senior_rate_authority,RATE_UNIT_KEY,RATE_UNIT
    owner='f01-browser-'+kind
    rec=create_reference_seeded_project(user_id=owner,template_source='generic_'+kind+'_reference',requested_name='F01 browser',capacity_mw=20.)
    context=browser.new_context(viewport={'width':1440,'height':1000})
    try:
        context.add_cookies([{'name':COOKIE_NAME,'value':create_session_token(user_id=owner,username='admin'),'url':live_server}])
        page=context.new_page();page.goto(f'{live_server}/v2/model-react/{rec.project_code}#financing')
        rows=[]
        for human,text in [(.056,'0.056'),(5.6,'5.60')]:
            field=page.get_by_label('All-in Interest Rate (%)',exact=True)
            field.fill(text)
            page.get_by_role('button',name='Save All-in Interest Rate',exact=True).click()
            page.wait_for_function("() => document.body.innerText.includes('saved and verified')")
            page.reload()
            field=page.get_by_label('All-in Interest Rate (%)',exact=True)
            assert float(field.input_value())==human
            api=context.request.get(f'{live_server}/v2/model-react/fields/debt?project={rec.project_code}').json()
            row=next(x for x in api['fields'] if x['field_id']=='debt.senior.interest_rate_pct')
            assert row['display_value']==f'{human:.12g}%'
            ws=get_workspace_state(owner,rec.project_id)
            ratio=senior_rate_authority(ProjectInputSet.from_snapshot(ws.draft_snapshot).to_projectinputs())[1]
            assert ratio==pytest.approx(human/100,abs=1e-17)
            assert ws.draft_snapshot[RATE_UNIT_KEY]==RATE_UNIT
            assert context.request.get(f'{live_server}/v2/model-react/runs?project={rec.project_code}').json()['runs']==[]
            folder=Path(os.getenv('FINVAL_BROWSER_EVIDENCE_DIR',str(tmp_path)));folder.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(folder/f'{kind}-{text}.png'),full_page=True)
            rows.append({'human_percent':human,'ratio':ratio,'display':row['display_value'],'save_created_runs':0})
        (folder/f'{kind}.json').write_text(json.dumps(rows,indent=2))
    finally:context.close()
