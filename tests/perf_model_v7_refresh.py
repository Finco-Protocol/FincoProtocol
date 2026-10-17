"""Opt-in synthetic V7 Phase 2 browser benchmarks; set V7P2_BENCH_DIR outside the checkout."""
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlparse
sys.path.insert(0, str(Path.cwd()))
import pytest
from tests.test_rcux2_ppa_quick_add_browser import Session, live_server, browser, _run
from tests.model_workspace_navigation import activate_destination


def settle(page, pending, completed):
    deadline=time.perf_counter()+60
    while pending or time.perf_counter()-completed[0] < .5:
        assert time.perf_counter()<deadline, ('Browser network failed to settle',
            [(request.method, urlparse(request.url).path, request.failure) for request in pending])
        page.wait_for_timeout(20)
    page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')


@pytest.mark.parametrize('template',['generic_solar_reference','generic_wind_reference'])
def test_journey(live_server,browser,template):
    assert os.environ.get('FINCO_MODEL_EXECUTION_MODE') == 'process', 'Benchmark requires the production process executor'
    from app.persistence.workspace_repository import get_workspace_state
    s=Session(live_server,browser,'v7p2-'+template,template=template)
    page=s.page
    page.set_default_timeout(120000)
    pending=set(); completed=[time.perf_counter()]; responses=[]
    page.on('request',lambda request:pending.add(request))
    def done(request):
        pending.discard(request);completed[0]=time.perf_counter()
    page.on('requestfinished',done);page.on('requestfailed',done)
    page.on('response',lambda response:responses.append(response))
    _run(s)
    settle(page,pending,completed)
    result=[]
    for sample in range(5):
        page.goto(f'{live_server}/v2/workbook?project={s.rec.project_code}&sheet=overview')
        settle(page,pending,completed)
        initial=page.evaluate('''() => ({bytes:performance.getEntriesByType('navigation')[0].decodedBodySize,
          dom:document.querySelectorAll('*').length, fs_bytes:new TextEncoder().encode(document.querySelector('#v2-sheet-financial-statements').outerHTML).length,
          fs_dom:document.querySelector('#v2-sheet-financial-statements').querySelectorAll('*').length})''')
        activate_destination(page,'tab-input-grid');settle(page,pending,completed)
        cell=page.locator('.ig-input[data-ig-field="project_setup.technical.p50_hours"]')
        # Small upward production edit preserves each vertical's own viable financing case.
        cell.fill(str(float(cell.input_value().replace(',','')) + 1));cell.press('Enter')
        page.wait_for_function('() => window.FincoInputGrid.stagedCount() === 1')
        settle(page,pending,completed)
        responses.clear()
        page.evaluate('''() => {
          performance.clearResourceTimings();window.__p2Long=[];window.__p2Swaps=[];window.__p2SwapStart=new WeakMap();
          if(!window.__p2Observed){window.__p2Observed=true;
            new PerformanceObserver(list => window.__p2Long.push(...list.getEntries().map(e=>({start:e.startTime,duration:e.duration}))))
              .observe({type:'longtask',buffered:false});
            document.addEventListener('htmx:beforeSwap',e=>window.__p2SwapStart.set(e.detail.xhr,performance.now()));
            document.addEventListener('htmx:afterSwap',e=>{const start=window.__p2SwapStart.get(e.detail.xhr);
              if(start!==undefined)window.__p2Swaps.push(performance.now()-start);});
          }
          window.__p2Start=performance.now();
        }''')
        started=time.perf_counter()
        saved=page.evaluate('() => window.FincoInputGrid.save()')
        assert saved
        promise_ms=(time.perf_counter()-started)*1000
        settle(page,pending,completed)
        elapsed=(time.perf_counter()-started)*1000
        resources=page.evaluate('''() => ({resources:performance.getEntriesByType('resource').map(e=>({path:new URL(e.name).pathname,
          duration_ms:e.duration,ttfb_ms:e.responseStart-e.requestStart,decoded_bytes:e.decodedBodySize,encoded_bytes:e.encodedBodySize})),
          long_tasks:window.__p2Long.filter(e=>e.start>=window.__p2Start),swap_durations_ms:window.__p2Swaps,
          feedback_ms:window.__igLastSaveMs,focused_field:document.activeElement?.dataset.igField})''')
        oob=0; save_ms=None; timings={}
        for response in list(responses):
            if response.request.resource_type not in ('fetch','xhr'):continue
            text=response.text();oob+=text.count('hx-swap-oob=')
            if response.request.method=='POST' and '/grid/save' in response.url:save_ms=response.request.timing['responseEnd']
            timings[urlparse(response.url).path]=response.headers.get('server-timing')
        assert get_workspace_state(s.uid,s.rec.project_id).dirty
        save={'promise_ms':promise_ms,'usable_ui_ms':elapsed,'save_http_ms':save_ms,'oob_fragments':oob,
              'resources':resources,'timings':timings}
        responses.clear()
        run_started=time.perf_counter();_run(s);settle(page,pending,completed)
        run={'usable_ui_ms':(time.perf_counter()-run_started)*1000}
        for response in list(responses):
            if response.request.method=='POST' and '/workbook/run' in response.url:
                run.update(http_ms=response.request.timing['responseEnd'],bytes=len(response.body()),
                           server_timing=response.headers.get('server-timing'))
        result.append({'sample':sample,'initial':initial,'save':save,'run':run})
        output=Path(os.environ['V7P2_BENCH_DIR']);output.mkdir(parents=True,exist_ok=True)
        (output/(template+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(template,sample,round(elapsed),len(resources['resources']),flush=True)
    output=Path(os.environ['V7P2_BENCH_DIR']);output.mkdir(parents=True,exist_ok=True)
    (output/(template+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
    s.close()


@pytest.fixture(scope='module',autouse=True)
def cleanup():
    yield
    from app.runtime.model_execution import reset_model_executor_for_tests
    reset_model_executor_for_tests(None)
