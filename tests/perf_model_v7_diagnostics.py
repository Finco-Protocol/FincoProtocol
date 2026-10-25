"""Opt-in local benchmark: five authenticated synthetic Solar/Wind samples per action."""
import hashlib
import json
import os
from pathlib import Path
import time
import pytest
from tests.test_rcux2_ppa_quick_add_browser import Session, live_server, browser, _run
from tests.model_workspace_navigation import activate_destination


FETCH = """async ({url, method, body, isJson}) => {
  const options = {method:method || 'GET', credentials:'same-origin', headers:{'HX-Request':'true'}};
  if (body) { options.body = isJson ? JSON.stringify(body) : new URLSearchParams(body).toString();
    options.headers['Content-Type'] = isJson ? 'application/json' : 'application/x-www-form-urlencoded'; }
  const start = performance.now(); const response = await fetch(url, options); const headers = performance.now();
  const text = await response.text(); const end = performance.now();
  const metric = performance.getEntriesByName(response.url).slice(-1)[0];
  return {status:response.status, wall_ms:end-start, ttfb_ms:headers-start,
    decoded_bytes:new TextEncoder().encode(text).length, encoded_bytes:metric?.encodedBodySize || null,
    server_timing:response.headers.get('Server-Timing'), content_encoding:response.headers.get('Content-Encoding')};
}"""


def _tokens(s):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get
    ws = get_workspace_state(s.uid, s.rec.project_id)
    identity = assemble_consistent_for_get(s.uid, s.rec.project_id, WORKBOOK.version)
    return dict(project=s.rec.project_code, content_hash=identity.composite_hash,
                workbook_version=WORKBOOK.version), ws


def _fetch(page, path, body=None, is_json=False):
    result = page.evaluate(FETCH, dict(url=path, method='POST' if body else 'GET', body=body, isJson=is_json))
    assert result['status'] == 200, (path, result)
    return result


def _nav(page, url, reload=False):
    response = page.reload(wait_until='load') if reload else page.goto(url, wait_until='load')
    result = page.evaluate("""() => { const n=performance.getEntriesByType('navigation')[0]; return {
      wall_ms:n.loadEventEnd-n.startTime, ttfb_ms:n.responseStart-n.requestStart,
      decoded_bytes:n.decodedBodySize, encoded_bytes:n.encodedBodySize,
      dom_elements:document.querySelectorAll('*').length, dom_content_loaded_ms:n.domContentLoadedEventEnd,
      response_end_ms:n.responseEnd, requests:performance.getEntriesByType('resource').length}; }""")
    result['server_timing'] = response.headers.get('server-timing')
    return result


@pytest.mark.parametrize('template', ['generic_solar_reference', 'generic_wind_reference'])
def test_measurements(live_server, browser, template):
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence.db import get_cursor
    from app.persistence.workspace_repository import get_workspace_state
    s = Session(live_server, browser, 'v7-benchmark-' + template, template=template)
    s.page.set_default_timeout(120000)
    _run(s)  # committed fixture warm-up, excluded from the five measured Runs
    samples = []
    for index in range(5):
        ctx = browser.new_context(viewport={'width':1440, 'height':900})
        ctx.add_cookies([{'name':COOKIE_NAME, 'value':create_session_token(user_id=s.uid, username='admin'), 'url':live_server}])
        page = ctx.new_page(); page.set_default_timeout(120000)
        row = {'sample':index}
        url = f'{live_server}/v2/workbook?project={s.rec.project_code}'
        row['initial_open'] = _nav(page, url)
        row['repeated_open'] = _nav(page, url, reload=True)
        fields, ws = _tokens(s)
        csrf = page.locator('[data-csrf][data-project]').first.get_attribute('data-csrf')
        row['scalar_save'] = _fetch(page, '/v2/workbook/grid/save', {
            **fields, 'csrf_token':csrf, 'scenario_id':ws.active_scenario_id,
            'cells':[{'field_id':'revenue.ppa.base_tariff','value':str(61 + index)}]}, True)
        row['diagnostics'] = _fetch(page, '/v2/workbook/diagnostics?project=' + s.rec.project_code)
        row['statements'] = _fetch(page, '/v2/workbook/outputs?project=' + s.rec.project_code)
        with get_cursor() as cur:
            cur.execute('SELECT * FROM capex_sub_lines WHERE project_id=? AND is_active=1 ORDER BY display_order LIMIT 1', (s.rec.project_id,))
            line = dict(cur.fetchone())
        fields, _ = _tokens(s)
        row['capex_save'] = _fetch(page, '/v2/capex/line/update', {
            **fields, 'sub_line_id':line['sub_line_id'], 'label':line['label'],
            'amount_keur':str(100 + index), 'notes':'', 'row_version':line['updated_at']})
        fields, _ = _tokens(s)
        row['committed_run'] = _fetch(page, '/v2/workbook/run', {**fields, 'csrf_token': page.locator('#v2-canonical-run-form [name=run_csrf_token]').input_value()})
        ws = get_workspace_state(s.uid, s.rec.project_id)
        assert ws.last_runtime_snapshot_id
        finance = {key:getattr(ws,key) for key in ('last_runtime_summary','last_debt_schedule',
            'last_financial_statements','last_sponsor_schedule','last_integrity_evidence')}
        row['financial_sha256'] = hashlib.sha256(json.dumps(finance,sort_keys=True,default=str).encode()).hexdigest()
        # Load the newly committed snapshot, then time actual destination selection.
        page.goto(url)
        start = time.perf_counter()
        activate_destination(page, 'tab-diagnostics')
        page.locator('[data-md-payload]').wait_for(state='attached')
        row['navigation'] = {'wall_ms':(time.perf_counter()-start)*1000}
        row['diagnostics_json_bytes'] = len(page.locator('[data-md-payload]').text_content().encode())
        samples.append(row)
        ctx.close()
        print(template, index, {k:round(v.get('wall_ms',0)) for k,v in row.items() if isinstance(v,dict)}, flush=True)
    out = Path(os.environ['V7_BENCH_DIR']); out.mkdir(parents=True, exist_ok=True)
    (out / (template + '.json')).write_text(json.dumps(samples,indent=2), encoding='utf-8')
    s.close()


@pytest.fixture(scope='module', autouse=True)
def _cleanup():
    yield
    from app.runtime import model_execution
    model_execution.reset_model_executor_for_tests(None)
