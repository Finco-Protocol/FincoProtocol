"""Contract rounding through authorized Save, actual Run and immutable history."""
from tests.model_mutation_csrf import post_valid_mutation

import copy
import json
from decimal import Decimal, ROUND_HALF_UP

import pytest

from tests.test_developer_economics_persistence_v1 import OWNER, Flow, env  # noqa: F401
from tests.test_rc2_integration_acceptance import _save_revenue
from tests.test_ppa01_save_scenario_run_chain import _book, _levels, _years, _page


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_rounding_save_scenario_run_and_immutable_history(env, kind):
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.scenarios_repository import list_scenarios, get_scenario
    flow = Flow(env, kind)
    original = _book(flow, _levels(flow, 100, 2.5), price=62.345)
    assert _save_revenue(flow, original).status_code == 200
    before = flow.run()
    history = copy.deepcopy(get_run_history(OWNER, flow.record.project_id))
    assert post_valid_mutation(env.client, '/v2/workbook/scenarios/create', data={**flow.project, 'scenario_name': 'Rounded'}).status_code == 200
    child = next(s for s in list_scenarios(OWNER, flow.record.project_id) if not s.is_base_case)
    assert post_valid_mutation(env.client, '/v2/workbook/scenarios/select', data={**flow.project, 'scenario_id': child.scenario_id}).status_code == 200
    selected = copy.deepcopy(original)
    selected['streams'][0]['price_rounding'] = dict(enabled=True, decimal_places=2, method='HALF_UP')
    assert _save_revenue(flow, selected).status_code == 200
    assert flow.ws().dirty and 'STALE' in _page(flow)
    assert json.loads(flow.ws().draft_snapshot['rev_multistream_config_json']) == original
    assert json.loads(get_scenario(child.scenario_id, OWNER).overrides['rev_multistream_config_json']) == selected
    assert 'data-rounding-preview' in _page(flow)
    result = flow.run()
    assert not flow.ws().dirty and 'CURRENT' in _page(flow)
    assert json.loads(result['scenario_revenue_input']['multistream_config_json']) == selected
    years = _years(flow)
    max_residual = 0.0
    for period in result['revenue_multistream_audit']:
        row = next(s for s in period['streams'] if s['id'] == 'ppa-1')
        year = years[period['period_index']]
        indexed = Decimal('62.345') * Decimal(str(selected['streams'][0]['index_series'][year-1]['level'])) / 100
        price = indexed if year == 1 else indexed.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        assert row['price_eur_mwh'] == float(price)
        expected = float(Decimal(str(row['quantity_mwh'])) * price / 1000)
        max_residual = max(max_residual, abs(row['revenue_keur'] - expected))
        assert row['revenue_keur'] == pytest.approx(expected, rel=0, abs=1e-8)
    assert result['total_revenue_keur'] != before['total_revenue_keur']
    now = get_run_history(OWNER, flow.record.project_id)
    assert len(now) == 2
    assert next(h for h in now if h.history_id == history[0].history_id).runtime_summary == history[0].runtime_summary
    frozen = copy.deepcopy(flow.ws().last_runtime_summary)
    invalid = copy.deepcopy(selected); invalid['streams'][0]['price_rounding']['decimal_places'] = 5
    assert _save_revenue(flow, invalid).status_code == 422
    assert flow.ws().last_runtime_summary == frozen and not flow.ws().dirty
    base = next(s for s in list_scenarios(OWNER, flow.record.project_id) if s.is_base_case)
    for sid in (base.scenario_id, child.scenario_id):
        assert post_valid_mutation(env.client, '/v2/workbook/scenarios/select', data={**flow.project, 'scenario_id': sid}).status_code == 200
        assert 'CURRENT' in _page(flow)
    assert flow.ws().last_runtime_summary == frozen
    print(f'{kind}: maximum rounded revenue residual={max_residual:.17g} kEUR')
