"""Actual FINCO calendar aggregation and honest unreleased financial boundary."""
import json
from dataclasses import replace
from datetime import datetime, time, timezone
from decimal import Decimal

import pytest

from app.project_factories import create_generic_storage_reference, create_default_solar_bess_project
from app.services import m7_bess_authority as authority
from domain.bess.contracts import parse_configuration, BessInputError
from domain.bess.dispatch import evaluate
from domain.bess.settlement import aggregate_to_financial_periods
from domain.bess.synthetic import example
from finco_core.engine.period_engine import PeriodEngine


def utc(day):
    return datetime.combine(day, time(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compatible():
    from datetime import date
    source = create_generic_storage_reference()
    source = replace(source, info=replace(source.info, financial_close=date(2027, 1, 1), construction_months=12,
                                          cod_date=date(2028, 1, 1), horizon_years=2))
    axis = PeriodEngine(source.info.financial_close, 12, 2, 0, cod_date=source.info.cod_date)
    operating = [p for p in axis.periods() if p.is_operation]
    raw = example(utc(operating[0].start_date), utc(operating[-1].end_date))
    config = parse_configuration(json.dumps(raw))
    return source, axis, raw, config, evaluate(config)


def test_full_canonical_period_aggregation_has_no_calendar_year_shortcut():
    source, axis, raw, config, result = compatible()
    periods = aggregate_to_financial_periods(result, axis.periods())
    assert len(periods) == 4
    for proposal, meta in zip(periods, (p for p in axis.periods() if p.is_operation)):
        assert proposal.hours == (meta.end_date - meta.start_date).days * 24
        assert proposal.period_index == meta.index
        assert proposal.cash_date == meta.end_date.isoformat()
        assert proposal.gross_sale_revenue_keur == Decimal(".081") * (proposal.hours // 24)
        assert proposal.charging_purchase_cost_keur == Decimal(".04") * (proposal.hours // 24)
    assert sum(p.grid_import_mwh for p in periods) == result.purchased_import_mwh
    assert sum(p.grid_export_mwh for p in periods) == result.delivered_export_mwh
    assert periods[0].hours != periods[1].hours
    assert periods[0].canonical_accrual_days == periods[0].hours // 24 + 1
    assert authority.propose_financial_handoff(source, config, result).periods == periods


def test_post_cod_augmentation_cost_is_dated_capex_not_revenue_or_opex():
    source, axis, raw, _config, _result = compatible()
    from tests.test_m7_bess_physics import event
    raw["events"] = [event(at="2028-07-01T00:00:00Z")]
    config = parse_configuration(json.dumps(raw))
    result = evaluate(config)
    handoff = authority.propose_financial_handoff(source, config, result)
    assert sum(p.lifecycle_capex_keur for p in handoff.periods) == 100
    assert sum(p.lifecycle_capex_keur > 0 for p in handoff.periods) == 1
    assert "BESS_POST_COD_ASSET_COMMISSIONING_BOOK_TAX_AND_FUNDING_UNRESOLVED" in handoff.blockers
    assert not handoff.released


def test_source_storage_reference_exposes_cod_and_clean_tax_gaps_without_modification():
    inputs = create_generic_storage_reference()
    before = repr(inputs)
    config = parse_configuration(json.dumps(example()))
    result = evaluate(config)
    handoff = authority.propose_financial_handoff(inputs, config, result)
    assert not handoff.periods and not handoff.released
    assert any("PERIOD_AXIS_COD_MISMATCH" in reason for reason in handoff.blockers)
    assert "CLEAN_RUNTIME_TAX_POLICY_NOT_READY" in handoff.blockers
    assert "BESS_SAVED_PHYSICAL_INPUT_MISMATCH" in handoff.blockers
    assert repr(inputs) == before
    assert any(row[1] == "bess_cells" for row in handoff.initial_capex_categories)
    assert handoff.opex_categories


def test_financial_release_cannot_be_forged_and_no_finance_engine_is_called(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Candidate must not calculate finance or write a Run")
    monkeypatch.setattr("app.services.production_financial_authority.run_clean_production", forbidden)
    monkeypatch.setattr("app.runtime.model_execution.run_model_process", forbidden)
    config = parse_configuration(json.dumps(example()))
    handoff = authority.propose_financial_handoff(create_generic_storage_reference(), config, evaluate(config))
    monkeypatch.setattr(authority, "ACTIVATION_ENABLED", True)
    with pytest.raises(authority.BessFinancialIntegrationUnavailable, match="RELEASE_CLOSED"):
        authority.require_canonical_financial_run(replace(handoff, released=True, blockers=()))


def test_hybrid_and_mismatched_physical_result_fail_closed():
    config = parse_configuration(json.dumps(example()))
    result = evaluate(config)
    with pytest.raises(BessInputError, match="hybrid"):
        authority.propose_financial_handoff(create_default_solar_bess_project(), config, result)
    other = example()
    other["dispatch"][20]["sell_price_eur_mwh"] = 120
    with pytest.raises(BessInputError, match="BINDING"):
        authority.propose_financial_handoff(create_generic_storage_reference(), parse_configuration(json.dumps(other)), result)


def test_incomplete_dispatch_or_broken_finance_axis_cannot_be_padded():
    source, axis, raw, config, result = compatible()
    with pytest.raises(BessInputError, match="FINANCE_AXIS"):
        aggregate_to_financial_periods(result, axis.periods()[:-1])
    operating = [p for p in axis.periods() if p.is_operation]
    bad = [replace(operating[1], start_date=operating[0].start_date), *operating[2:]]
    with pytest.raises(BessInputError, match="FINANCE_AXIS"):
        aggregate_to_financial_periods(result, bad)


def test_all_candidate_activations_remain_closed():
    from domain.revenue.advanced_products import ACTIVATION_ENABLED as revenue_enabled
    from app.workbook.junior_debt_config import ACTIVATION_ENABLED as junior_enabled
    assert not authority.ACTIVATION_ENABLED
    assert not revenue_enabled
    assert not junior_enabled
