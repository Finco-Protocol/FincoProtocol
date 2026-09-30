"""Opus H-1 — construction financing costs, IDC and DSRA in the generic product run.

The generic product run used to ignore the declared commitment fee, structuring
fee, senior rate and DSRA coverage (construction_financing=None,
dsra_support_mode=NONE). These tests pin the wired behaviour and prove it against
independent recomputations, not against the engine's own numbers.
"""
from __future__ import annotations

import dataclasses as dc

import pytest

from app import project_factories as pf
from app.services.production_financial_authority import (
    CleanProductionRunUnavailable,
    run_clean_production,
)
from financial_engine.dsra.contracts import CashDsraInput
from financial_engine.dsra.target import (
    DsraTargetPolicy,
    build_dsra_required_balance_schedule,
)
from financial_engine.financing.generic_product_policy import (
    DISABLED_GENERIC_FINANCING_POLICY,
    POLICY_AUTHORITY,
    GenericFinancingPolicyError,
    build_sources_and_uses,
    derive_construction_financing,
)
from finco_core.inputs import DebtServiceReserveSupportMode as Mode

TOL = 1e-6
PROMOTED = ("solar", "wind", "ev_charging")


def _pi(vertical: str):
    return getattr(pf, f"create_generic_{vertical}_reference")()


@pytest.fixture(scope="module")
def runs():
    return {v: run_clean_production(_pi(v), "Base", project_type=v) for v in PROMOTED}


@pytest.fixture(scope="module")
def solar_off():
    return run_clean_production(
        _pi("solar"), "Base", project_type="solar",
        financing_policy=DISABLED_GENERIC_FINANCING_POLICY)


def _fin(run):
    return run.g2c_result.financing_result


# ── 1–3. IDC and commitment fee: independent recomputation ──────────────────

def test_idc_is_zero_when_construction_debt_is_never_drawn():
    from financial_engine.construction.adapter import (
        build_construction_runtime_config,
        resolve_capex_amounts_from_capex_structure,
    )
    from finco_core.construction.stage_b2 import run_stage_b2

    pi = _pi("solar")
    construction = derive_construction_financing(pi)
    amounts = resolve_capex_amounts_from_capex_structure(construction.capex_items, pi.capex)
    total = sum(amounts.values())
    for commitment, expected_fee_positive in ((0.0, False), (20000.0, True)):
        config = build_construction_runtime_config(
            construction, senior_commitment_keur=commitment, equity_available_keur=total,
            shl_available_keur=total, capex_amounts_keur=amounts)
        costs = run_stage_b2(config).capitalized_financing_costs
        assert costs.senior_idc_keur == 0.0  # equity funds everything: nothing drawn
        assert (costs.senior_commitment_fee_keur > 0.0) is expected_fee_positive
    assert costs.structuring_fee_keur == pytest.approx(20000.0 * 0.01)


@pytest.mark.parametrize("vertical", PROMOTED)
def test_idc_and_commitment_fee_match_independent_recomputation(runs, vertical):
    run = runs[vertical]
    construction = _fin(run).construction_financing
    pi = run.project_inputs
    rate = pi.financing.senior_debt_interest_config.rate_schedule.explicit_all_in_rates[0]
    fee_rate = pi.financing.commitment_fee
    commitment = construction.final_senior_commitment_keur

    opening_drawn = 0.0
    idc_total = fee_total = 0.0
    for index, (start, end) in enumerate(zip(construction.period_start_dates,
                                             construction.period_end_dates)):
        fraction = ((end - start).days + 1) / 360.0  # ACT/360, inclusive days
        period_idc = opening_drawn * rate * fraction          # interest on drawn balance only
        period_fee = (commitment - opening_drawn) * fee_rate * fraction  # undrawn only
        assert construction.senior_idc_accrual_keur[index] == pytest.approx(period_idc, abs=TOL)
        assert construction.senior_commitment_fee_accrual_keur[index] == pytest.approx(
            period_fee, abs=TOL)
        idc_total += period_idc
        fee_total += period_fee
        opening_drawn += construction.senior_draws_keur[index]
    assert sum(construction.senior_idc_capitalized_uses_keur) == pytest.approx(idc_total, abs=TOL)
    assert construction.senior_commitment_fee_capitalized_keur == pytest.approx(fee_total, abs=TOL)
    assert idc_total > 0.0


def test_idc_increases_with_construction_period_borrowing():
    def idc(gearing):
        pi = _pi("solar")
        pi = dc.replace(pi, financing=dc.replace(pi.financing, gearing_ratio=gearing))
        run = run_clean_production(pi, "Base", project_type="solar")
        return build_sources_and_uses(_fin(run)).capitalized_idc_keur

    assert idc(0.75) > idc(0.50) > 0.0


# ── 4. Structuring / arrangement fee: declared basis ────────────────────────

@pytest.mark.parametrize("vertical", PROMOTED)
def test_structuring_fee_is_declared_rate_times_committed_facility(runs, vertical):
    run = runs[vertical]
    fin = run.project_inputs.financing
    su = build_sources_and_uses(_fin(run))
    expected = (fin.structuring_fee + fin.arrangement_fee) * su.senior_debt_keur
    assert su.structuring_fee_keur == pytest.approx(expected, abs=TOL)


def test_arrangement_fee_adds_to_the_same_declared_basis():
    def fee(arrangement):
        pi = _pi("solar")
        pi = dc.replace(pi, financing=dc.replace(pi.financing, arrangement_fee=arrangement))
        su = build_sources_and_uses(_fin(run_clean_production(pi, "Base", project_type="solar")))
        return su.structuring_fee_keur / su.senior_debt_keur

    assert fee(0.0) == pytest.approx(0.01, abs=1e-9)
    assert fee(0.005) == pytest.approx(0.015, abs=1e-9)


# ── 5–6. DSRA: explicit source, asset equals funded amount, explicit release ─

@pytest.mark.parametrize("vertical", PROMOTED)
def test_initial_dsra_funding_has_an_explicit_source_and_equals_the_asset(runs, vertical):
    run = runs[vertical]
    fin = _fin(run)
    su = build_sources_and_uses(fin)
    funded = su.initial_dsra_funding_keur
    assert funded > 0.0
    assert run.authority_metadata["cash_dsra_applied"] is True
    assert run.authority_metadata["initial_dsra_funding_keur"] == pytest.approx(funded, abs=TOL)

    audit = run.financial_statements_result.funding_audit
    assert audit["non_construction_fc_uses_keur"] == pytest.approx(funded, abs=TOL)
    assert audit["non_construction_fc_sources_keur"] == pytest.approx(funded, abs=TOL)

    balance_sheet = [p for p in run.financial_statements_result.balance_sheet_periods
                     if p.balance_check_keur is not None]
    assert balance_sheet[0].dsra_balance_keur == pytest.approx(funded, abs=TOL)


@pytest.mark.parametrize("vertical", PROMOTED)
def test_dsra_is_sized_on_peak_forward_debt_service_and_released_at_maturity(runs, vertical):
    run = runs[vertical]
    fin = run.project_inputs.financing
    senior = _fin(run).project_model_result.senior_debt
    due = [x for x in senior.senior_debt_service_keur if x > 0.0]
    multiplier = fin.dsra_months * 2 / 12.0
    assert build_sources_and_uses(_fin(run)).initial_dsra_funding_keur == pytest.approx(
        max(due[1:]) * multiplier, rel=1e-6)

    cash_dsra = _fin(run).project_model_result.cash_dsra
    assert cash_dsra.total_top_up_keur == pytest.approx(0.0, abs=TOL)
    assert cash_dsra.total_release_keur == pytest.approx(
        build_sources_and_uses(_fin(run)).initial_dsra_funding_keur, abs=TOL)
    assert cash_dsra.final_closing_balance_keur == pytest.approx(0.0, abs=TOL)


# ── 7–8. Sources = Uses, no hidden funding, no unexplained negative cash ─────

@pytest.mark.parametrize("vertical", PROMOTED)
def test_sources_equal_uses_without_a_plug(runs, vertical):
    fin = _fin(runs[vertical])
    su = build_sources_and_uses(fin)
    assert abs(su.difference_keur) <= TOL
    assert su.total_uses_keur == pytest.approx(
        su.base_project_capex_keur + su.capitalized_idc_keur + su.commitment_fee_keur
        + su.structuring_fee_keur + su.other_financing_costs_keur
        + su.initial_dsra_funding_keur + su.other_uses_keur, abs=TOL)
    assert su.total_sources_keur == pytest.approx(
        su.senior_debt_keur + su.junior_or_other_keur
        + su.share_capital_and_other_equity_keur + su.shareholder_loan_cash_keur, abs=TOL)
    assert all(v >= -TOL for v in (su.senior_debt_keur, su.share_capital_and_other_equity_keur,
                                   su.shareholder_loan_cash_keur))
    construction = fin.construction_financing
    assert max(abs(x) for x in construction.period_sources_uses_residual_keur) <= TOL


@pytest.mark.parametrize("vertical", PROMOTED)
def test_no_unexplained_negative_cash(runs, vertical):
    run = runs[vertical]
    post = _fin(run).project_model_result.post_senior_cash
    assert min(post.cash_after_senior_before_reserves_keur) >= -TOL
    for period in run.financial_statements_result.balance_sheet_periods:
        if period.balance_check_keur is None:
            continue
        assert period.unrestricted_cash_keur >= -TOL
        assert period.distribution_account_balance_keur >= -TOL


# ── 9. No double counting; balance sheet stays balanced ─────────────────────

@pytest.mark.parametrize("vertical", PROMOTED)
def test_financing_costs_are_capitalised_once_and_balance_sheet_balances(runs, vertical):
    run = runs[vertical]
    statements = run.financial_statements_result
    su = build_sources_and_uses(_fin(run))
    first_operating = [p for p in statements.balance_sheet_periods
                       if p.balance_check_keur is not None][0]
    capitalised = (su.base_project_capex_keur + su.capitalized_idc_keur
                   + su.commitment_fee_keur + su.structuring_fee_keur)
    assert first_operating.gross_fixed_assets_keur == pytest.approx(capitalised, abs=1e-4)
    # The DSRA is a reserve asset, not part of gross fixed assets.
    assert first_operating.dsra_balance_keur == pytest.approx(
        su.initial_dsra_funding_keur, abs=1e-4)
    # Operating P&L interest expense is the senior schedule interest only (IDC is capitalised).
    senior = _fin(run).project_model_result.senior_debt
    pnl_interest = sum(p.senior_interest_expense_keur for p in statements.income_statement_periods
                       if not p.is_construction)
    assert pnl_interest == pytest.approx(sum(senior.senior_interest_keur), rel=1e-6)
    for period in statements.balance_sheet_periods:
        if period.balance_check_keur is not None:
            assert abs(period.balance_check_keur) <= 1e-6


# ── 10. One generic finance authority across verticals ──────────────────────

def test_promoted_verticals_use_the_same_generic_authority(runs):
    for run in runs.values():
        meta = run.authority_metadata
        assert meta["financing_policy_authority"] == POLICY_AUTHORITY
        assert meta["construction_financing_applied"] is True
        assert meta["cash_dsra_applied"] is True
        assert meta["calculation_count"] == 1
        assert _fin(run).construction_financing is not None


# ── 11. Disabled policy restores the previous economics ─────────────────────

def test_disabled_policy_restores_previous_behaviour(solar_off):
    su = build_sources_and_uses(_fin(solar_off))
    assert _fin(solar_off).construction_financing is None
    assert solar_off.authority_metadata["cash_dsra_applied"] is False
    assert su.total_uses_keur == pytest.approx(33000.0)
    assert su.senior_debt_keur == pytest.approx(24750.0)
    assert su.capitalized_idc_keur == su.commitment_fee_keur == su.structuring_fee_keur == 0.0
    assert su.initial_dsra_funding_keur == 0.0
    assert solar_off.g2c_result.pure_equity_xirr == pytest.approx(0.5046761426, abs=1e-8)


def test_wired_financing_costs_reduce_returns_relative_to_disabled(runs, solar_off):
    on, off = runs["solar"].g2c_result, solar_off.g2c_result
    assert 0.0 < on.pure_equity_xirr < off.pure_equity_xirr
    assert 0.0 < on.total_sponsor_xirr < off.total_sponsor_xirr


# ── 12. Debt roll-forward identity ──────────────────────────────────────────

@pytest.mark.parametrize("vertical", PROMOTED)
def test_senior_debt_rollforward_identity(runs, vertical):
    fin = _fin(runs[vertical])
    senior = fin.project_model_result.senior_debt
    construction = fin.construction_financing
    first_operating_opening = senior.senior_debt_opening_keur[
        next(i for i, x in enumerate(senior.senior_debt_opening_keur) if x > 0.0)]
    assert first_operating_opening == pytest.approx(fin.final_senior_commitment_keur, abs=1e-4)
    # Construction draws plus the COD-funded reserve draw make up the commitment.
    assert sum(construction.senior_draws_keur) <= fin.final_senior_commitment_keur + TOL
    for opening, principal, closing in zip(
            senior.senior_debt_opening_keur, senior.senior_principal_keur,
            senior.senior_debt_closing_keur):
        assert opening - principal == pytest.approx(closing, abs=TOL)
    assert senior.senior_debt_closing_keur[-1] == pytest.approx(0.0, abs=1e-4)


# ── Guards: explicit typed inputs win; inconsistent timing fails closed ─────

def test_explicit_typed_inputs_are_not_overridden():
    pi = _pi("solar")
    explicit = derive_construction_financing(pi)
    pi = dc.replace(pi, financing=dc.replace(
        pi.financing, construction_financing=explicit,
        dsra_support_mode=Mode.CASH_DSRA, debt_service_reserve_requirement_keur=500.0))
    run = run_clean_production(pi, "Base", project_type="solar")
    assert run.authority_metadata["construction_financing_applied"] is False
    assert run.authority_metadata["cash_dsra_applied"] is False
    assert build_sources_and_uses(_fin(run)).initial_dsra_funding_keur == pytest.approx(500.0)


def test_capex_timing_beyond_construction_fails_closed():
    pi = _pi("solar")
    epc = pi.capex.epc_contract
    long_profile = dc.replace(epc, spending_profile=(0.25, 0.25, 0.25, 0.25))
    pi = dc.replace(pi, capex=dc.replace(pi.capex, epc_contract=long_profile))
    with pytest.raises(GenericFinancingPolicyError, match="H1_CAPEX_TIMING_EXCEEDS_CONSTRUCTION"):
        derive_construction_financing(pi)
    with pytest.raises(CleanProductionRunUnavailable):
        run_clean_production(pi, "Base", project_type="solar")


# ── DSRA target policy unit tests ───────────────────────────────────────────

def _schedule(policy, ds):
    n = len(ds)
    from datetime import date, timedelta
    starts = tuple(date(2030, 1, 1) + timedelta(days=180 * i) for i in range(n))
    ends = tuple(s + timedelta(days=179) for s in starts)
    return build_dsra_required_balance_schedule(
        period_indices=tuple(range(n)), period_start_dates=starts, period_end_dates=ends,
        is_construction=tuple([True] + [False] * (n - 1)), senior_debt_service_keur=tuple(ds),
        coverage_months=6, periods_per_year=2, policy=policy)


def test_peak_policy_holds_the_peak_while_debt_is_due_then_releases():
    ds = [0.0, 100.0, 140.0, 110.0, 130.0, 0.0, 0.0]
    forward = _schedule(DsraTargetPolicy.FORWARD_DEBT_SERVICE_MONTHS, ds)
    peak = _schedule(DsraTargetPolicy.PEAK_FORWARD_DEBT_SERVICE_MONTHS, ds)
    assert forward == (0.0, 140.0, 110.0, 130.0, 0.0, 0.0, 0.0)
    assert peak == (0.0, 140.0, 140.0, 140.0, 0.0, 0.0, 0.0)


def test_peak_policy_requires_cash_dsra_and_positive_coverage():
    with pytest.raises(ValueError, match="requires mode=CASH_DSRA"):
        CashDsraInput(mode=Mode.NONE, target_policy=DsraTargetPolicy.PEAK_FORWARD_DEBT_SERVICE_MONTHS)
    with pytest.raises(ValueError, match="requires dsra_months > 0"):
        CashDsraInput(mode=Mode.CASH_DSRA, dsra_months=0,
                      target_policy=DsraTargetPolicy.PEAK_FORWARD_DEBT_SERVICE_MONTHS)
