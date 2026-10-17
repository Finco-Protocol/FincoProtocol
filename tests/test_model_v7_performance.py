"""Opt-in measurement/privacy and compact Diagnostics consumer contract."""
from copy import deepcopy
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.model_performance import ModelPerformanceMiddleware, span, _current
from app.v2.diagnostics_client import diagnostics_client_payload, diagnostics_client_json


def test_instrumentation_default_off_and_request_local(monkeypatch, caplog):
    app = FastAPI()
    app.add_middleware(ModelPerformanceMiddleware)
    @app.get('/v2/workbook')
    def route():
        with span('diagnostics'):
            pass
        with span('PRIVATE_UNAPPROVED_LABEL'):
            pass
        return {'ok':True}
    client = TestClient(app)
    monkeypatch.delenv('FINCO_MODEL_PERF_ENABLED', raising=False)
    assert 'server-timing' not in client.get('/v2/workbook?project=PRIVATE_ACCOUNT').headers
    assert _current.get() is None
    monkeypatch.setenv('FINCO_MODEL_PERF_ENABLED', '1')
    with caplog.at_level('INFO', logger='finco.model_performance'):
        response = client.get('/v2/workbook?project=PRIVATE_ACCOUNT&token=PRIVATE_TOKEN')
    assert response.json() == {'ok':True}
    assert 'diagnostics;dur=' in response.headers['server-timing']
    assert 'server;dur=' in response.headers['server-timing']
    for forbidden in ('PRIVATE_ACCOUNT', 'PRIVATE_TOKEN', 'PRIVATE_UNAPPROVED_LABEL', '/v2/workbook'):
        assert forbidden not in caplog.text + response.headers['server-timing']
    assert _current.get() is None


def test_metrics_reset_after_failure(monkeypatch):
    monkeypatch.setenv('FINCO_MODEL_PERF_ENABLED', '1')
    app = FastAPI()
    app.add_middleware(ModelPerformanceMiddleware)
    @app.get('/v2/workbook/failure')
    async def route():
        with span('diagnostics'):
            raise ValueError('not logged')
    with pytest.raises(ValueError):
        TestClient(app).get('/v2/workbook/failure')
    assert _current.get() is None


def test_concurrent_requests_do_not_share_timing_state(monkeypatch):
    import asyncio
    import httpx
    monkeypatch.setenv('FINCO_MODEL_PERF_ENABLED', '1')
    app = FastAPI()
    arrived = asyncio.Event()
    @app.get('/v2/workbook/first')
    async def first():
        with span('diagnostics'):
            arrived.set()
            await asyncio.sleep(.02)
        return {'ok': True}
    @app.get('/v2/workbook/second')
    async def second():
        await arrived.wait()
        with span('statements'):
            await asyncio.sleep(.01)
        return {'ok': True}
    wrapped = ModelPerformanceMiddleware(app)
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=wrapped), base_url='http://test') as client:
            return await asyncio.gather(client.get('/v2/workbook/first'), client.get('/v2/workbook/second'))
    first_response, second_response = asyncio.run(exercise())
    assert 'diagnostics;dur=' in first_response.headers['server-timing']
    assert 'statements;dur=' not in first_response.headers['server-timing']
    assert 'statements;dur=' in second_response.headers['server-timing']
    assert 'diagnostics;dur=' not in second_response.headers['server-timing']
    assert _current.get() is None


def test_compact_payload_inherits_only_exact_redundant_identity_and_is_html_safe():
    identity = {'snapshot_id':'run', 'composite_hash':'hash', 'scenario_id':'scenario'}
    period = {'check_id':'QM-TEST', 'snapshot_id':'run', 'run_identity':identity,
              'period_index':1, 'date':'2030-01-01', 'status':'FAIL', 'residual':1e-12,
              'evidence_source':'source', 'reason':'</script><script>unsafe</script>'}
    check = {'check_id':'QM-TEST', 'evidence_source':'source', 'periods':[period]}
    data = {'identity':identity, 'checks':[check], 'groups':[{'checks':[check]}],
            'top_issues':[check], 'waterfall':[1], 'state':'STALE', 'score':{'counts':{'fail':1}},
            'v2':{'advanced_checks':[], 'actions':{}, 'root_causes':[], 'heatmap':{'cells':[]},
                  'advanced_summary':{'registered':9}, 'inventory':[1], 'run_comparison':{'rows':[1]}, 'bankability':{}}}
    before = deepcopy(data)
    out = diagnostics_client_payload(data)
    assert data == before
    assert out['state'] == 'STALE' and out['score'] == data['score']
    assert not {'groups','top_issues','waterfall'} & out.keys()
    assert 'inventory' not in out['v2']
    assert out['v2']['run_comparison'] == data['v2']['run_comparison']
    assert out['v2']['bankability'] == data['v2']['bankability']
    compact = out['checks'][0]['periods'][0]
    assert {**{'check_id':'QM-TEST', 'snapshot_id':identity['snapshot_id'],
                'run_identity':identity, 'evidence_source':'source'}, **compact} == period
    encoded = str(diagnostics_client_json(data))
    assert '</script>' not in encoded
    assert json.loads(encoded) == out
    data['checks'][0]['periods'][0]['snapshot_id'] = 'unexpected-identity'
    assert diagnostics_client_payload(data)['checks'][0]['periods'][0]['snapshot_id'] == 'unexpected-identity'
