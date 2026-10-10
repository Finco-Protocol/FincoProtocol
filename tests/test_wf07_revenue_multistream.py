"""Explicit revenue contracts use actual production and the existing financial kernel."""
import copy
import json
from dataclasses import replace
from decimal import Decimal

import pytest

from app import project_factories as factories
from app.workbook.revenue_multistream import apply_config, canonical_json
from domain.revenue.multistream_runtime import parse_config
from financial_engine.adapters.project_inputs import from_project_inputs
from financial_engine.orchestrator import _build_period_engine
from finco_core.revenue.generation import revenue_decomposition_schedule


def contracts(pi, technology="solar", *, price=85, share=.6, merchant_price=70, strike=None, index=0):
    periods = [p for p in _build_period_engine(from_project_inputs(pi)).periods() if p.is_operation]
    common = dict(start_date=periods[0].start_date.isoformat(), end_date=periods[-1].end_date.isoformat(),
                  indexation_rate=0, settlement="SAME_PERIOD", source_ref="synthetic-executed-contract")
    rows = [dict(common, id="ppa-1", type="ppa", volume_share=share, price_eur_mwh=price, indexation_rate=index),
            dict(common, id="market-1", type="merchant", volume_share=None, price_eur_mwh=merchant_price)]
    if strike is not None:
        rows.append(dict(common, id="cfd-1", type="cfd", volume_share=1-share, price_eur_mwh=strike,
                         reference_stream_id="market-1"))
    return dict(version=1, technology=technology, indexation_basis="OPERATING_YEAR", streams=rows)


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("strike", [None, 95, 40])
def test_volume_and_signed_cfd_decimal_reconciliation(kind, strike):
    pi = getattr(factories, "create_generic_" + kind + "_reference")()
    payload = contracts(pi, kind, strike=strike, index=.02)
    active = apply_config(pi, json.dumps(payload), project_type=kind)
    axis = _build_period_engine(from_project_inputs(active))
    rows = revenue_decomposition_schedule(active, axis)
    years = {p.index: p.year_index for p in axis.periods()}
    for idx, row in rows.items():
        if not row["is_operation"]:
            continue
        streams = row["multistream_evidence"]["streams"]
        ppa = next(s for s in streams if s["type"] == "ppa")
        independently_indexed_price = Decimal(85) * Decimal("1.02") ** Decimal(str(years[idx] - 1))
        assert ppa["price_eur_mwh"] == pytest.approx(float(independently_indexed_price), abs=1e-9)
        physical = sum(s["quantity_mwh"] for s in streams if s["type"] != "cfd")
        assert physical == pytest.approx(row["generation_mwh"], abs=1e-9)
        energy = sum(Decimal.from_float(s["quantity_mwh"]) * Decimal.from_float(s["price_eur_mwh"]) / 1000
                     for s in streams if s["type"] != "cfd")
        settlement = Decimal(0)
        if strike is not None:
            cfd = next(s for s in streams if s["type"] == "cfd")
            settlement = Decimal.from_float(cfd["quantity_mwh"]) * (Decimal(str(strike)) - Decimal(70)) / 1000
            assert cfd["settlement_keur"] == pytest.approx(float(settlement), abs=1e-9)
        net = energy + settlement - Decimal.from_float(row["balancing_cost_keur"]) + Decimal.from_float(row["co2_revenue_keur"])
        assert row["revenue_keur"] == pytest.approx(float(net), abs=1e-8)


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_inactive_preserves_original_input_class_and_serialization(kind):
    from finco_core.inputs.serialization import project_inputs_to_dict as serialize_project_inputs
    pi = getattr(factories, "create_generic_" + kind + "_reference")()
    before = serialize_project_inputs(pi)
    assert apply_config(pi, "", project_type=kind) is pi
    assert "multistream_config_json" not in before["revenue"]
    assert serialize_project_inputs(apply_config(pi, None, project_type=kind)) == before
    assert type(from_project_inputs(pi).revenue).__name__ == "RevenueInput"


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_active_serialization_roundtrip_and_fingerprint(kind):
    from finco_core.inputs.serialization import project_inputs_to_dict as serialize_project_inputs, project_inputs_from_dict as deserialize_project_inputs
    from financial_engine.provenance import compute_input_fingerprint
    pi = getattr(factories, "create_generic_" + kind + "_reference")()
    active = apply_config(pi, json.dumps(contracts(pi, kind)), project_type=kind)
    encoded = serialize_project_inputs(active)
    restored = deserialize_project_inputs(encoded)
    assert restored.revenue == active.revenue
    assert from_project_inputs(restored).revenue.multistream_config_json == active.revenue.multistream_config_json
    assert compute_input_fingerprint(from_project_inputs(pi)) != compute_input_fingerprint(from_project_inputs(active))


@pytest.mark.parametrize("value", [None, "", False, 0, "{}", "[]"])
def test_explicit_malformed_serialized_authority_never_falls_back(value):
    from finco_core.inputs.serialization import project_inputs_to_dict as serialize_project_inputs, project_inputs_from_dict as deserialize_project_inputs
    encoded = serialize_project_inputs(factories.create_generic_solar_reference())
    encoded["revenue"]["multistream_config_json"] = value
    with pytest.raises(ValueError):
        deserialize_project_inputs(encoded)


@pytest.mark.parametrize("kind", ["capacity_market", "ancillary", "rec", "battery", "unknown"])
def test_unproven_streams_fail_closed(kind):
    payload = contracts(factories.create_generic_solar_reference())
    payload["streams"][0]["type"] = kind
    with pytest.raises(ValueError, match="UNSUPPORTED_STREAM"):
        parse_config(json.dumps(payload))


@pytest.mark.parametrize("kind", ["data_center", "ev_charging", "storage", "wind"])
def test_unsupported_sector_or_technology_mismatch(kind):
    pi = factories.create_generic_solar_reference()
    with pytest.raises(ValueError, match="TECHNOLOGY"):
        apply_config(pi, json.dumps(contracts(pi)), project_type=kind)


@pytest.mark.parametrize("key,value", [("volume_share", 1.1), ("volume_share", True), ("price_eur_mwh", -1),
    ("price_eur_mwh", float("nan")), ("price_eur_mwh", float("inf")), ("indexation_rate", -1),
    ("settlement", "NEXT_PERIOD"), ("start_date", "bad"), ("source_ref", ""), ("id", ""), ("extra", 1)])
def test_invalid_contracts_cannot_reach_runtime(key, value):
    pi = factories.create_generic_solar_reference()
    payload = contracts(pi)
    payload["streams"][0][key] = value
    with pytest.raises(ValueError):
        apply_config(pi, json.dumps(payload), project_type="solar")


@pytest.mark.parametrize("problem", ["oversubscribed", "duplicate", "missing-ref", "cfd-exceeds-volume", "indexed-cfd", "inactive-ref", "partial-period"])
def test_overlap_reference_and_axis_fail_closed(problem):
    pi = factories.create_generic_solar_reference()
    payload = contracts(pi, strike=90)
    rows = payload["streams"]
    if problem == "oversubscribed":
        rows[1]["volume_share"] = .6
    elif problem == "duplicate":
        rows[1]["id"] = rows[0]["id"]
    elif problem == "missing-ref":
        rows[-1]["reference_stream_id"] = "nonexistent"
    elif problem == "cfd-exceeds-volume":
        rows[-1]["volume_share"] = .5
    elif problem == "indexed-cfd":
        rows[-1]["indexation_rate"] = .02
    elif problem == "inactive-ref":
        rows[1]["start_date"] = "2032-06-30"
    else:
        rows[0]["start_date"] = "2031-03-02"
    with pytest.raises(ValueError):
        apply_config(pi, json.dumps(payload), project_type="solar")


def test_unallocated_volume_is_not_hidden_merchant_backfill_and_dates_are_authoritative():
    pi = factories.create_generic_solar_reference()
    payload = contracts(pi)
    payload["streams"] = payload["streams"][:1]
    payload["streams"][0]["end_date"] = "2031-12-31"
    active = apply_config(pi, json.dumps(payload), project_type="solar")
    rows = revenue_decomposition_schedule(active, _build_period_engine(from_project_inputs(active)))
    for row in rows.values():
        if not row["is_operation"]:
            continue
        evidence = row["multistream_evidence"]
        assert row["gross_merchant_revenue_keur"] == 0
        assert evidence["unallocated_generation_mwh"] == pytest.approx(row["generation_mwh"] - row["ppa_generation_mwh"])
    assert any(r.get("multistream_evidence", {}).get("streams", [{}])[0].get("status") == "expired" for r in rows.values())


def test_canonicalization_is_deterministic_and_rejects_duplicate_keys():
    raw = json.dumps(contracts(factories.create_generic_solar_reference()))
    assert canonical_json(raw) == canonical_json(json.dumps(json.loads(raw), indent=2))
    with pytest.raises(ValueError, match="duplicate key"):
        parse_config('{"version":1,"version":1}')


def test_bank_price_override_cannot_be_silently_ignored():
    from financial_engine.orchestrator import derive_debt_sizing_operating_input
    pi = factories.create_generic_solar_reference()
    active = apply_config(pi, json.dumps(contracts(pi)), project_type="solar")
    clean = from_project_inputs(active)
    with pytest.raises(ValueError, match="BANK_PRICE_OVERRIDE_UNSUPPORTED"):
        from financial_engine.inputs import DebtSizingCaseInput
        from finco_core.inputs import YieldScenario
        derive_debt_sizing_operating_input(clean, DebtSizingCaseInput(production_yield_scenario=YieldScenario.P90_10Y,
                                                                    market_prices_curve_eur_mwh=(60.0,)))


def test_merchant_capture_and_cfd_market_reference_are_not_conflated():
    pi = factories.create_generic_solar_reference()
    payload = contracts(pi, strike=90)
    payload["streams"][1]["capture_rate"] = .8
    active = apply_config(pi, json.dumps(payload), project_type="solar")
    rows = revenue_decomposition_schedule(active, _build_period_engine(from_project_inputs(active)))
    for row in rows.values():
        if not row["is_operation"]:
            continue
        streams = row["multistream_evidence"]["streams"]
        merchant = next(s for s in streams if s["type"] == "merchant")
        cfd = next(s for s in streams if s["type"] == "cfd")
        assert merchant["capture_rate"] == .8
        assert merchant["revenue_keur"] == pytest.approx(merchant["quantity_mwh"] * 70 * .8 / 1000)
        assert cfd["settlement_keur"] == pytest.approx(cfd["quantity_mwh"] * (90-70) / 1000)


@pytest.mark.parametrize("driver", ["ppa_price", "merchant_price"])
def test_legacy_scalar_sensitivity_cannot_ignore_contract_prices(driver):
    from app.services.sensitivity_service import _apply_shock
    pi = factories.create_generic_solar_reference()
    active = apply_config(pi, json.dumps(contracts(pi)), project_type="solar")
    with pytest.raises(ValueError, match="REVENUE_V2_SENSITIVITY_UNSUPPORTED"):
        _apply_shock(active, driver, 10)


def test_later_contract_start_and_end_change_actual_period_status():
    from financial_engine.orchestrator import run_operating_model
    pi = factories.create_generic_solar_reference()
    periods = [p for p in _build_period_engine(from_project_inputs(pi)).periods() if p.is_operation]
    payload = contracts(pi)
    payload["streams"][0]["start_date"] = periods[2].start_date.isoformat()
    payload["streams"][0]["end_date"] = periods[4].end_date.isoformat()
    active = apply_config(pi, json.dumps(payload), project_type="solar")
    operating = run_operating_model(from_project_inputs(active))
    assert [p.is_ppa_active for p in operating.periods if p.is_operation] == [2 <= i <= 4 for i in range(len(periods))]


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_f3_two_senior_debt_and_financial_statements_integrate_real_contract_revenue(kind):
    from tests.test_financing_f3_multisenior import case
    from app.services.production_financial_authority import run_clean_production
    from app.run_integrity import build_run_integrity_evidence, run_integrity_checks
    pi, _ = case(kind)
    active = apply_config(pi, json.dumps(contracts(pi, kind, price=95, merchant_price=90, strike=100)), project_type=kind)
    run = run_clean_production(active, "Base", project_type=kind)
    baseline = run_clean_production(pi, "Base", project_type=kind)
    financing = run.g2c_result.financing_result
    assert len(financing.facility_schedules) == 2
    senior = financing.project_model_result.senior_debt
    assert sum(senior.senior_principal_keur) == pytest.approx(senior.debt_size_keur, abs=1e-9)
    assert run_integrity_checks(build_run_integrity_evidence(run)).to_dict()["overall"] == "PASS"
    evidence = next(e for e in financing.project_model_result.provenance.derivation_evidence
                    if e.output_path == "operating_schedules.revenue_keur")
    assert evidence.notes
    base_financing = baseline.g2c_result.financing_result
    assert financing.project_model_result.operating_schedules.revenue_keur != base_financing.project_model_result.operating_schedules.revenue_keur
    assert run.g2c_result.total_sponsor_xirr != baseline.g2c_result.total_sponsor_xirr
    for row in run.financial_statements_result.income_statement_periods:
        if not row.is_construction:
            assert row.ebitda_keur == pytest.approx(row.revenue_keur - row.opex_keur, abs=1e-9)
