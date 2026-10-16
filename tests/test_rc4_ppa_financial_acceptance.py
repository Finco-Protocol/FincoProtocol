"""Synthetic Decimal oracle: calendar and model-year PPAs in one canonical Run."""
import copy
import json
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP

import pytest

from app.workbook.revenue_multistream import apply_config
from app.services.production_financial_authority import run_clean_production
from financial_engine.adapters.project_inputs import from_project_inputs
from financial_engine.orchestrator import _build_period_engine
from finco_core.revenue.generation import revenue_decomposition_schedule
from tests.test_ppa01_contractual_timing import terms
from tests.test_ppa01_index_series_revenue import _project, _operating, _payload, _series, _n


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_two_price_clocks_decimal_allocation_and_actual_production_run(kind):
    pi = _project(kind); operating = _operating(pi)
    raw = _payload(kind, operating, end=4, share=.35, price=60.005, rate=.02,
                   extra={"indexation_timing": terms(),
                          "price_rounding": {"enabled": True, "decimal_places": 2, "method": "HALF_EVEN"}})
    second = copy.deepcopy(raw["streams"][0])
    del second["indexation_timing"]
    second.update(id="ppa-2", price_eur_mwh=45.227, indexation_rate=0, volume_share=.25,
                  index_series=_series([100] + [105] * (_n(operating) - 1)),
                  price_rounding={"enabled": True, "decimal_places": 3, "method": "HALF_UP"})
    raw["streams"].insert(1, second)
    active = apply_config(pi, json.dumps(raw), project_type=kind)
    axis = _build_period_engine(from_project_inputs(active))
    decomposition = revenue_decomposition_schedule(active, axis)
    assert pi.revenue.balancing_cost_schedule is None and not pi.revenue.co2_enabled
    balancing_rate = Decimal(str(pi.revenue.balancing_cost_eur_per_mwh or pi.revenue.balancing_cost_wind_eur_mwh))
    max_residual = 0.0
    for index, period in enumerate(operating):
        row = decomposition[period.index]
        streams = {s["id"]: s for s in row["multistream_evidence"]["streams"]}
        generation = Decimal(str(row["generation_mwh"]))
        expected = Decimal(0)
        for stream_id, share in (("ppa-1", Decimal('.35')), ("ppa-2", Decimal('.25'))):
            actual = streams[stream_id]
            if index >= 4:
                assert actual["quantity_mwh"] == actual["revenue_keur"] == 0
                continue
            if stream_id == "ppa-1":
                count = sum(date(year, 12, 31) <= period.start_date for year in range(2029, period.start_date.year + 1))
                price = Decimal('60.005') * Decimal('1.02') ** count
                if count:
                    price = price.quantize(Decimal('.01'), rounding=ROUND_HALF_EVEN)
            else:
                price = Decimal('45.227') * (Decimal(1) if period.year_index == 1 else Decimal('1.05'))
                if period.year_index > 1:
                    price = price.quantize(Decimal('.001'), rounding=ROUND_HALF_UP)
            assert actual["price_eur_mwh"] == float(price)
            assert actual["quantity_mwh"] == pytest.approx(float(generation * share), rel=0, abs=1e-8)
            expected += generation * share * price / 1000
        residual_share = Decimal('.4') if index < 4 else Decimal(1)
        assert streams["market"]["quantity_mwh"] == pytest.approx(float(generation * residual_share), rel=0, abs=1e-8)
        merchant = generation * residual_share * Decimal(80) * Decimal('.8') / 1000
        expected += merchant - merchant * Decimal(str(pi.revenue.balancing_cost_pv)) - generation * balancing_rate / 1000
        actual_net = row["revenue_keur"]
        max_residual = max(max_residual, abs(actual_net - float(expected)))
        assert actual_net == pytest.approx(float(expected), rel=0, abs=1e-8)
    production = run_clean_production(active, "Base", project_type=kind)
    schedules = production.g2c_result.financing_result.project_model_result.operating_schedules
    for period, revenue in zip(axis.periods(), schedules.revenue_keur, strict=True):
        assert revenue == decomposition[period.index]["revenue_keur"]
    assert production.financial_statements_result is not None
    print(f"{kind}: maximum two-clock revenue residual {max_residual:.17g} kEUR")
