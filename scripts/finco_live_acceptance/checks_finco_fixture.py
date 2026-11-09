"""MANUAL explicit pytest path only; filename/location are NOT auto-discovered.

Reuse the existing canonical local server/session helpers and its unchanged
Save/CSRF/CAS/unknown-outcome browser cases. No deployment or production account.
"""
import hashlib
import os
import json
from pathlib import Path
import time
import pytest
from tests.test_workflow_c_browser_v1 import live_server,browser
from tests.model_react_rcm_support import rcm_react_flag
from tests.model_react_rcm_financing_acceptance import fin_session
from tests.model_react_pr3b2_acceptance import test_pr3b2_stale_csrf_and_retry_keep_draft,test_pr3b2_unknown_outcome_replays_identical_request
from scripts.finco_live_acceptance.browser import Browser,deployment
from scripts.finco_live_acceptance.policy import Session,NetworkPolicy,digest,PREFIX
from scripts.finco_live_acceptance.lifecycle import run_project

@pytest.mark.parametrize('technology',['solar','wind'])
def test_runner_local_canonical_lifecycle(live_server,browser,rcm_react_flag,tmp_path,technology,monkeypatch):
    from app.auth import COOKIE_NAME,create_session_token
    from scripts.finco_live_acceptance.runner import expected_artifacts
    from types import SimpleNamespace
    monkeypatch.setenv('FINCO_SAVE_ALL_PROFILE_ENABLED','0')
    uid='onaccept-fixture-'+technology
    context=browser.new_context();context.add_cookies([{'name':COOKIE_NAME,'value':create_session_token(user_id=uid,username='admin'),'url':live_server}])
    state=tmp_path/'session.json';context.storage_state(path=str(state));context.close()
    policy=NetworkPolicy(live_server,'synthetic-writable');ledger={}
    with Browser(live_server,policy,30,time.monotonic()+180,state,borrowed_browser=browser) as b:
        scope=b.json_get('/v2/model-react/setup-drafts?technology=solar')
        assert scope['scope']==digest(uid)
        policy.authenticated=True
        assert deployment(b,expected_artifacts(SimpleNamespace(expected_js_sha256=None,expected_css_sha256=None)))['frontend']=='FRONTEND_EXACT_MATCH'
        result=run_project(b,technology,PREFIX+'local-fixture-'+technology,ledger,lambda:None)
    diagnostic=next((row for row in result if row['operation']=='lifecycle'),None)
    assert diagnostic is None,(diagnostic,policy.blocked)
    evidence=os.environ.get('ONACCEPT_FIXTURE_EVIDENCE_DIR')
    if evidence:
        out=Path(evidence);out.mkdir(parents=True,exist_ok=True)
        (out/(technology+'.json')).write_text(json.dumps({'technology':technology,'environment':'CONTROLLED_LOCAL_CANONICAL_FIXTURE','operations':result,'sent_mutations':policy.sent_mutations,'explicit_run_requests':sum(x['path']=='/v2/workbook/run' for x in policy.posts),'profile_flag':os.environ.get('FINCO_SAVE_ALL_PROFILE_ENABLED'),'network_body_digests_only':policy.posts},indent=2)+'\n')
    indexed={row['operation']:row for row in result}
    assert indexed['create']['status']=='PASS',result
    assert indexed['save_reload_no_run']['status']=='PASS',result
    assert indexed['explicit_run']['status']=='PASS',result
    assert indexed['save_makes_outdated']['status']=='PASS',result
    assert indexed['stale_second_tab']['status']=='PASS',result
    assert policy.sent_mutations==4  # Create + Save14 + explicit Run + Save15; stale refuses before wire; see canonical writer counts below.
