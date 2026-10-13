"""Independent Decimal checks of candidate period products and hard boundaries."""
import copy
import json
from dataclasses import replace
from decimal import Decimal

import pytest

from app import project_factories as factories
from app.workbook.revenue_multistream import apply_config
from domain.revenue import advanced_products
from domain.revenue.multistream_runtime import parse_config
from financial_engine.adapters.project_inputs import from_project_inputs
from financial_engine.orchestrator import _build_period_engine
from finco_core.revenue.generation import revenue_decomposition_schedule
from tests.revenue_v3_cases import book


@pytest.fixture
def candidate(monkeypatch):
    # Isolated test process only. No application setting/customer switch exists.
    monkeypatch.setattr(advanced_products, "ACTIVATION_ENABLED", True)


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_release_is_closed_even_for_valid_contracts(kind):
    pi = getattr(factories, "create_generic_" + kind + "_reference")()
    raw, _ = book(pi, kind)
    assert advanced_products.ACTIVATION_ENABLED is False
    with pytest.raises(ValueError, match="RELEASE_CLOSED"):
        apply_config(pi, json.dumps(raw), project_type=kind)


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_all_period_product_math_is_independent_decimal(candidate, kind, record_property):
    pi = getattr(factories, "create_generic_" + kind + "_reference")()
    pi = replace(pi, revenue=replace(pi.revenue, co2_enabled=False))
    raw, periods = book(pi, kind)
    config = apply_config(pi, json.dumps(raw), project_type=kind)
    axis = _build_period_engine(from_project_inputs(config))
    rows = revenue_decomposition_schedule(config, axis)
    baseline = copy.deepcopy(raw)
    baseline["version"] = 2
    baseline.pop("products")
    baseline.pop("environmental_rights")
    old = apply_config(pi, json.dumps(baseline), project_type=kind)
    old_rows = revenue_decomposition_schedule(old, axis)
    worst = Decimal(0)
    for period in periods:
        row = rows[period.index]
        products = row["multistream_evidence"]["products"]
        index = Decimal("1.01") ** Decimal(str(period.year_index - 1))
        days = Decimal((period.end_date - period.start_date).days)
        expected = {"capacity_market": Decimal(2) * 20 * index * days / 365 * Decimal(".8") * Decimal(".9") * Decimal(".95"),
                    "ancillary": Decimal(2) * 800 * index * Decimal(".8") * Decimal(".9") * Decimal(".95") / 1000,
                    "rec": Decimal(100) * 3 * index / 1000}
        for product in products:
            delta = abs(Decimal(str(product["revenue_keur"])) - expected[product["type"]])
            worst = max(worst, delta)
            assert delta < Decimal("1e-9")
            assert product["settlement_date"] == period.end_date.isoformat()
            assert product["quantity_unit"] == ("CERTIFICATE_MWH" if product["type"] == "rec" else "MW")
        assert row["revenue_keur"] == pytest.approx(old_rows[period.index]["revenue_keur"] + float(sum(expected.values())), abs=1e-8)
        for field in ("ppa_generation_mwh", "merchant_generation_mwh", "balancing_cost_keur", "co2_revenue_keur"):
            assert row[field] == old_rows[period.index][field]
    record_property("maximum_product_residual_keur", str(worst))


def test_capacity_kw_and_mw_units_are_equivalent(candidate):
    pi = factories.create_generic_solar_reference()
    raw, _ = book(pi, families=("capacity_market",))
    def output(payload):
        project = apply_config(pi, json.dumps(payload), project_type="solar")
        return revenue_decomposition_schedule(project, _build_period_engine(from_project_inputs(project)))
    first = output(raw)
    raw["products"][0].update(price_eur=20000, price_unit="EUR_MW_YEAR")
    second = output(raw)
    assert [r["revenue_keur"] for r in first.values()] == [r["revenue_keur"] for r in second.values()]


@pytest.mark.parametrize("fault", ["bundled", "sold", "missing-right", "duplicate-right", "overlay-right", "volume", "duplicate-id", "duplicate-claim",
    "negative", "nan", "bool", "missing-price", "unknown-key", "dispatch", "wrong-unit", "lag", "missing-period", "bad-date", "duplicate-period",
    "pool-overlap", "pool-overcommit", "inconsistent-pool", "wrong-technology", "legacy-certificates"])
def test_missing_or_incompatible_economics_fail_closed(candidate, fault):
    pi = factories.create_generic_solar_reference()
    pi = replace(pi, revenue=replace(pi.revenue, co2_enabled=False))
    raw, _ = book(pi)
    capacity, ancillary, rec = raw["products"]
    if fault == "bundled": raw["environmental_rights"][1]["status"] = "TRANSFERRED_BUNDLED"
    elif fault == "sold": rec["ownership"] = "TRANSFERRED"
    elif fault == "missing-right": raw["environmental_rights"].pop()
    elif fault == "duplicate-right": raw["environmental_rights"].append(copy.deepcopy(raw["environmental_rights"][0]))
    elif fault == "overlay-right": raw["environmental_rights"][0]["energy_stream_id"] = "cfd-1"
    elif fault == "volume": rec["periods"][0]["certified_mwh"] = 1e10
    elif fault == "duplicate-id": rec["id"] = "ppa-1"
    elif fault == "duplicate-claim": rec["entitlement_id"] = capacity["entitlement_id"]
    elif fault == "negative": capacity["price_eur"] = -1
    elif fault == "nan": capacity["price_eur"] = float("nan")
    elif fault == "bool": capacity["eligible_mw"] = True
    elif fault == "missing-price": capacity.pop("price_eur")
    elif fault == "unknown-key": capacity["top_up"] = 10
    elif fault == "dispatch": ancillary["obligation"] = "DISPATCH"
    elif fault == "wrong-unit": ancillary["price_unit"] = "EUR_MWH"
    elif fault == "lag": capacity["periods"][0]["settlement_date"] = "2040-01-01"
    elif fault == "missing-period": capacity["periods"].pop()
    elif fault == "bad-date": capacity["start_date"] = "2030-13-01"
    elif fault == "duplicate-period": capacity["periods"].insert(0, capacity["periods"][0])
    elif fault == "pool-overlap": ancillary["pool_id"] = capacity["pool_id"]
    elif fault in ("pool-overcommit", "inconsistent-pool"):
        extra = copy.deepcopy(capacity)
        extra.update(id="extra-capacity", entitlement_id="extra-entitlement", eligible_mw=3)
        if fault == "inconsistent-pool": extra["pool_capacity_mw"] = 5
        raw["products"].append(extra)
    elif fault == "wrong-technology": raw["technology"] = "battery"
    else: pi = replace(pi, revenue=replace(pi.revenue, co2_enabled=True))
    with pytest.raises(ValueError):
        project = apply_config(pi, json.dumps(raw), project_type="solar")
        revenue_decomposition_schedule(project, _build_period_engine(from_project_inputs(project)))


def test_candidate_objects_cannot_run_after_gate_is_closed(candidate, monkeypatch):
    pi = factories.create_generic_solar_reference()
    raw, periods = book(pi, families=("capacity_market",))
    config = parse_config(json.dumps(raw))
    monkeypatch.setattr(advanced_products, "ACTIVATION_ENABLED", False)
    with pytest.raises(ValueError, match="RELEASE_CLOSED"):
        config.evaluate(periods[0], 1000)
