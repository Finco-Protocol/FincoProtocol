"""Two explicit pari-passu Seniors, composed through existing financing kernels.

Facility commitments are contractual inputs, not DSCR sizing outputs. This V1
supports fixed cash interest, construction-only dated draws and level/bullet
repayment. Aggregate rates are derived from facility balances solely to hand
the summed interest to the existing tax/CFADS solver; they are never user inputs.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from math import fsum

from dateutil.relativedelta import relativedelta

from finco_core.inputs import DebtServiceReserveSupportMode, PeriodFrequency, SponsorFundingMode
from finco_core.inputs.financing_instruments import FinancingError, RepaymentMode
from finco_core.inputs.multisenior import MultiSeniorProjectInputs
from financial_engine.financing.contracts import ProjectFinancingResult
from financial_engine.senior_debt.inputs import PeriodPrincipal, PeriodRate, SeniorDebtInputs
from financial_engine.senior_debt.interest import period_day_fraction, period_interest
from financial_engine.senior_debt.policy import DayCountConvention, SeniorDebtPolicy, SeniorDebtSizingMode
from financial_engine.senior_debt.sculpting import build_explicit_schedule, build_level_principal_schedule

TOLERANCE_KEUR = 1e-7


@dataclass(frozen=True)
class FacilitySchedule:
    instrument_id: str
    commitment_keur: float
    maturity_period_index: int
    period_indices: tuple[int, ...]
    opening_keur: tuple[float, ...]
    interest_keur: tuple[float, ...]
    principal_keur: tuple[float, ...]
    debt_service_keur: tuple[float, ...]
    closing_keur: tuple[float, ...]
    construction_draws_keur: tuple[float, ...]
    construction_idc_keur: tuple[float, ...]
    construction_commitment_fees_keur: tuple[float, ...]
    upfront_fees_keur: tuple[float, ...]


@dataclass(frozen=True, kw_only=True)
class MultiSeniorFinancingResult(ProjectFinancingResult):
    dscr_debt_capacity_keur: float | None
    facility_schedules: tuple[FacilitySchedule, ...]
    financing_collection_digest: str
    aggregate_period_rates: tuple[PeriodRate, ...]


def _day_count(pi):
    value = pi.financing.senior_debt_interest_config.day_count.value
    if value not in ("act_365", "act_360"):
        raise FinancingError("F3_DAY_COUNT_UNSUPPORTED", value)
    return {"act_365": DayCountConvention.ACT_365, "act_360": DayCountConvention.ACT_360}[value]


def validate_project_boundary(pi):
    """Reject competing economic authorities instead of silently ignoring them."""
    fin = pi.financing
    if pi.info.period_frequency is not PeriodFrequency.SEMESTRIAL:
        raise FinancingError("F3_PERIOD_FREQUENCY_UNSUPPORTED")
    if fin.sponsor_funding_mode is not SponsorFundingMode.EQUITY_ONLY:
        raise FinancingError("F3_ACTIVE_SHL_INTEGRATION_NOT_RELEASED")
    if fin.junior_or_other_project_funding_keur:
        raise FinancingError("F3_JUNIOR_FINANCING_UNSUPPORTED")
    if fin.other_equity_funding_before_shl_keur:
        raise FinancingError("F3_OTHER_EQUITY_ACCOUNTING_NOT_RELEASED")
    if fin.dsra_support_mode is not DebtServiceReserveSupportMode.NONE or fin.debt_service_reserve_requirement_keur or fin.dsra_months:
        raise FinancingError("F3_RESERVE_INTEGRATION_NOT_RELEASED")
    if pi.capex.reserve_accounts_keur or pi.cash_reserve_interest_policy is not None:
        raise FinancingError("F3_RESERVE_INTEGRATION_NOT_RELEASED")
    if any(getattr(pi.capex, key, 0.) for key in ("idc_keur", "commitment_fees_keur", "bank_fees_keur",
            "other_financial_keur", "vat_costs_keur", "vat_facility_idc_keur", "vat_facility_commitment_fee_keur")):
        raise FinancingError("F3_MANUAL_FINANCING_COST_CONFLICT")
    if fin.construction_period_uses_keur or fin.construction_financing is not None:
        raise FinancingError("F3_CONSTRUCTION_AUTHORITY_CONFLICT")
    _day_count(pi)


def _construction(pi):
    from financial_engine.financing.generic_product_policy import derive_construction_financing
    return derive_construction_financing(pi)


def build_facility_schedules(pi, periods):
    """Produce contractual facility ledgers using canonical calendar and primitives."""
    construction = _construction(pi)
    op = tuple(p for p in periods if p.is_operation)
    if not op:
        raise FinancingError("F3_OPERATING_AXIS_MISSING")
    dc = _day_count(pi)
    results = []
    for instrument in pi.financing_collection.instruments:
        matching = [p for p in op if p.period_end == instrument.repayment.maturity_date]
        if len(matching) != 1:
            raise FinancingError("F3_MATURITY_NOT_ON_OPERATING_BOUNDARY", instrument.instrument_id)
        maturity = matching[0].period_index
        debt_periods = tuple(p for p in op if p.period_index <= maturity)
        grace_end = op[0].period_start + relativedelta(months=instrument.repayment.grace_months)
        eligible = [p for p in debt_periods if p.period_start >= grace_end]
        if not eligible:
            raise FinancingError("F3_GRACE_EXCEEDS_MATURITY", instrument.instrument_id)
        indices = tuple(p.period_index for p in debt_periods)
        if instrument.repayment.mode is RepaymentMode.LEVEL_PRINCIPAL:
            rows = build_level_principal_schedule(opening_debt_keur=instrument.commitment_keur,
                period_indices=indices, interest_by_period={}, cfads_by_period={},
                repayment_start_index=eligible[0].period_index, maturity_index=maturity)
            principal = {r.period_index: r.principal_keur for r in rows}
        else:
            principal = {maturity: instrument.commitment_keur}
        raw = build_explicit_schedule(opening_debt_keur=instrument.commitment_keur,
            period_indices=indices, interest_by_period={}, cfads_by_period={}, explicit_principal_by_period=principal)
        interest = {p.period_index: period_interest(r.opening_keur, instrument.interest.fixed_rate,
                    period_day_fraction(p.period_start, p.period_end, dc)) for p, r in zip(debt_periods, raw)}
        rows = build_explicit_schedule(opening_debt_keur=instrument.commitment_keur,
            period_indices=indices, interest_by_period=interest, cfads_by_period={}, explicit_principal_by_period=principal)
        if abs(rows[-1].closing_keur) > TOLERANCE_KEUR:
            raise FinancingError("F3_FACILITY_MATURITY_UNSETTLED", instrument.instrument_id)
        draws, idc, fees, upfront = [], [], [], []
        opening = 0.
        mapped_dates = set()
        for i, p in enumerate(construction.periods):
            end_exclusive = p.end_date + timedelta(days=1)
            entries = [d for d in instrument.drawdowns if p.start_date <= d.draw_date < end_exclusive]
            mapped_dates.update(d.draw_date for d in entries)
            drawn = fsum(d.amount_keur for d in entries)
            dcf = period_day_fraction(p.start_date, end_exclusive, dc)
            # Each dated cash draw accrues from its own date, never the whole
            # period by an averaged construction rate or funding-profile replay.
            accrued = period_interest(opening, instrument.interest.fixed_rate, dcf) + fsum(
                period_interest(d.amount_keur, instrument.interest.fixed_rate,
                    period_day_fraction(d.draw_date, end_exclusive, dc)) for d in entries)
            commitment_rate = next((f.rate for f in instrument.fees if f.kind == "COMMITMENT"), 0.)
            undrawn_integral = (instrument.commitment_keur - opening) * dcf - fsum(
                d.amount_keur * period_day_fraction(d.draw_date, end_exclusive, dc) for d in entries)
            draws.append(drawn)
            idc.append(accrued)
            fees.append(commitment_rate * undrawn_integral)
            upfront.append(fsum(f.rate * instrument.commitment_keur for f in instrument.fees
                               if f.kind == "UPFRONT") if i == 0 else 0.)
            opening += drawn
        if mapped_dates != {d.draw_date for d in instrument.drawdowns}:
            raise FinancingError("F3_DRAW_OUTSIDE_CONSTRUCTION", instrument.instrument_id)
        results.append(FacilitySchedule(instrument.instrument_id, instrument.commitment_keur, maturity, indices,
            tuple(r.opening_keur for r in rows), tuple(r.interest_keur for r in rows),
            tuple(r.principal_keur for r in rows), tuple(r.debt_service_keur for r in rows),
            tuple(r.closing_keur for r in rows), tuple(draws), tuple(idc), tuple(fees), tuple(upfront)))
    return tuple(results)


def build_aggregate_contract(pi, periods):
    facilities = build_facility_schedules(pi, periods)
    maturity = max(f.maturity_period_index for f in facilities)
    op = tuple(p for p in periods if p.is_operation and p.period_index <= maturity)
    maps = [{i: (o, p, interest) for i, o, p, interest in zip(f.period_indices,
        f.opening_keur, f.principal_keur, f.interest_keur)} for f in facilities]
    rates, principal = [], []
    for period in op:
        values = [m.get(period.period_index, (0., 0., 0.)) for m in maps]
        opening = fsum(v[0] for v in values)
        interest = fsum(v[2] for v in values)
        fraction = period_day_fraction(period.period_start, period.period_end, _day_count(pi))
        rates.append(PeriodRate(period.period_index, interest / opening / fraction if opening > 0 else 0.))
        principal.append(PeriodPrincipal(period.period_index, fsum(v[1] for v in values)))
    total = fsum(f.commitment_keur for f in facilities)
    policy = SeniorDebtPolicy(policy_id="f3-explicit-aggregate-senior-v1", policy_version="1.0",
        sizing_mode=SeniorDebtSizingMode.EXPLICIT_SCHEDULE, target_dscr=pi.financing.target_dscr,
        maximum_gearing=None, annual_fixed_rate=None, periods_per_year=2, day_count_convention=_day_count(pi),
        repayment_start_period_index=op[0].period_index, maturity_period_index=maturity,
        convergence_tolerance_keur=TOLERANCE_KEUR, convergence_relative_tolerance=1e-9,
        maximum_iterations=50, permit_terminal_balloon=False)
    return policy, SeniorDebtInputs(eligible_project_cost_keur=0., initial_debt_guess_keur=total,
        opening_debt_balance_keur=total, period_rates=tuple(rates), explicit_principal_schedule=tuple(principal))


def run_multisenior_financing(pi, *, source_id="", baseline_commit_sha="", period_financing_income=None):
    """Compose facilities before tax/CFADS, funding, statements and sponsor returns.

    V1 has explicit commitments and no active SHL/reserve facility. Consequently
    no debt-sizing/SHL/IDC circular solve is needed: construction cash interest
    is calculated from contractual dated draws, then funded once as project uses.
    """
    from finco_core.construction.allocator import allocate_construction_sources_per_period
    from finco_core.construction.stage_b2 import CapitalizedFinancingCosts, apply_capitalized_financing_costs
    from financial_engine.adapters.project_inputs import from_project_inputs, build_senior_debt_model_input_from_project_inputs
    from financial_engine.financing.contracts import ConstructionFinancingResult
    from financial_engine.financing.project import _build_generic_book_basis, _developer_uses
    from financial_engine.financing.project_uses import compute_project_uses
    from financial_engine.financing.stack import build_construction_funding_schedule, reconcile_financing_stack
    from financial_engine.orchestrator import run_operating_model, run_senior_debt_model

    validate_project_boundary(pi)
    if pi.development_economics is not None:
        raise FinancingError("F3_NON_CONSTRUCTION_USES_INTEGRATION_NOT_RELEASED")
    periods = run_operating_model(from_project_inputs(pi, source_id=source_id,
        baseline_commit_sha=baseline_commit_sha)).periods
    facilities = build_facility_schedules(pi, periods)
    construction = _construction(pi)
    n = len(construction.periods)

    def summed(field):
        return tuple(fsum(getattr(f, field)[i] for f in facilities) for i in range(n))

    idc, commitment, upfront = summed("construction_idc_keur"), summed("construction_commitment_fees_keur"), summed("upfront_fees_keur")
    draws = summed("construction_draws_keur")
    capitalized = CapitalizedFinancingCosts(senior_idc_keur=fsum(idc),
        senior_commitment_fee_keur=fsum(commitment), structuring_fee_keur=fsum(upfront),
        vat_idc_keur=0., vat_commitment_fee_keur=0.)
    capex = apply_capitalized_financing_costs(pi.capex, capitalized)
    # EQUITY_ONLY has no SHL obligation. As in the canonical financing stack,
    # the factory's legacy SHL seed is not an effective financing input.
    working = replace(pi, capex=capex,
        financing=replace(pi.financing, clean_shl_principal_keur=0.))
    uses = compute_project_uses(working)
    senior_total = fsum(f.commitment_keur for f in facilities)
    gearing_capacity = uses.total_project_uses_keur * pi.financing.gearing_ratio
    if senior_total > gearing_capacity + TOLERANCE_KEUR:
        raise FinancingError("F3_AGGREGATE_GEARING_CAP_EXCEEDED")
    _, additional_equity = reconcile_financing_stack(total_project_uses_keur=uses.total_project_uses_keur,
        final_senior_commitment_keur=senior_total, junior_or_other_main_project_funding_keur=0.,
        share_capital_keur=pi.financing.share_capital_keur, share_premium_keur=pi.financing.share_premium_keur,
        other_equity_funding_before_shl_keur=pi.financing.other_equity_funding_before_shl_keur,
        sponsor_funding_mode=pi.financing.sponsor_funding_mode)
    amounts = {item.code: getattr(pi.capex, item.code).amount_keur for item in construction.capex_items}
    hard = tuple(fsum(amounts[item.code] * item.payment_weights[i] for item in construction.capex_items) for i in range(n))
    total_uses = tuple(hard[i] + idc[i] + commitment[i] + upfront[i] for i in range(n))
    if abs(fsum(total_uses) - uses.total_project_uses_keur) > TOLERANCE_KEUR:
        raise FinancingError("F3_CONSTRUCTION_USES_DO_NOT_RECONCILE")
    residual_uses = tuple(total_uses[i] - draws[i] for i in range(n))
    if any(value < -TOLERANCE_KEUR for value in residual_uses):
        raise FinancingError("F3_PERIOD_OVERFUNDING", "Dated Senior draws exceed that period's funded uses.")
    equity_rows = allocate_construction_sources_per_period(period_uses=tuple(max(0., v) for v in residual_uses),
        share_capital_keur=pi.financing.share_capital_keur, share_premium_keur=pi.financing.share_premium_keur,
        other_committed_equity_keur=pi.financing.other_equity_funding_before_shl_keur,
        additional_equity_keur=additional_equity, shl_cash_keur=0., junior_keur=0., senior_commitment_keur=0.)
    allocations = tuple(replace(row, period_uses_keur=total_uses[i], senior_draw_keur=draws[i],
        total_sources_keur=row.total_sources_keur + draws[i]) for i, row in enumerate(equity_rows))
    dates = tuple((p.start_date, p.end_date + timedelta(days=1), p.end_date + timedelta(days=1)) for p in construction.periods)
    funding = build_construction_funding_schedule(construction_period_count=n,
        total_project_uses_keur=uses.total_project_uses_keur, senior_keur=senior_total, junior_keur=0.,
        share_capital_keur=pi.financing.share_capital_keur, share_premium_keur=pi.financing.share_premium_keur,
        other_committed_equity_keur=pi.financing.other_equity_funding_before_shl_keur,
        additional_equity_keur=additional_equity, shl_cash_keur=0., period_dates=dates,
        canonical_economic_allocations=allocations)
    model_input = build_senior_debt_model_input_from_project_inputs(working,
        source_id=source_id, baseline_commit_sha=baseline_commit_sha)
    if period_financing_income and model_input.tax is not None:
        model_input = replace(model_input, tax=replace(model_input.tax, period_financing_income=period_financing_income))
    model = run_senior_debt_model(model_input)
    senior = model.senior_debt
    if senior is None or not senior.diagnostics.get("is_authoritative", False):
        raise FinancingError("F3_AGGREGATE_SENIOR_SOLVER_NOT_AUTHORITATIVE")
    fields = (("senior_debt_opening_keur", "opening_keur"), ("senior_interest_keur", "interest_keur"),
              ("senior_principal_keur", "principal_keur"), ("senior_debt_service_keur", "debt_service_keur"),
              ("senior_debt_closing_keur", "closing_keur"))
    for aggregate_field, facility_field in fields:
        maps = [dict(zip(f.period_indices, getattr(f, facility_field))) for f in facilities]
        for index, value in zip(senior.period_indices, getattr(senior, aggregate_field)):
            if abs(value - fsum(m.get(index, 0.) for m in maps)) > TOLERANCE_KEUR:
                raise FinancingError("F3_FACILITY_AGGREGATE_HANDSHAKE_FAILED", f"{aggregate_field}:{index}")
    cfads = dict(zip(model.tax_and_cfads.period_indices, model.tax_and_cfads.cfads_keur))
    for index, service in zip(senior.period_indices, senior.senior_debt_service_keur):
        if service > cfads[index] + TOLERANCE_KEUR:
            raise FinancingError("F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL", str(index))
    zero = tuple(0. for _ in range(n))
    cumulative = tuple(fsum(draws[:i + 1]) for i in range(n))
    financing = ConstructionFinancingResult(period_start_dates=tuple(d[0] for d in dates),
        period_end_dates=tuple(p.end_date for p in construction.periods), hard_capex_uses_keur=hard,
        total_period_uses_keur=total_uses, senior_draws_keur=draws, cumulative_senior_keur=cumulative,
        senior_idc_accrual_keur=idc, senior_commitment_fee_accrual_keur=commitment,
        structuring_fee_keur=upfront, shl_allocation_keur=zero, shl_cash_contribution_keur=zero,
        shl_day_count_fraction=zero, shl_pik_accrual_keur=zero,
        total_capitalized_financing_keur=capitalized.total_keur, shl_construction_pik_keur=0.,
        opening_operating_shl_keur=0., final_total_project_uses_keur=uses.total_project_uses_keur,
        final_senior_commitment_keur=senior_total, sources_uses_residual_keur=funding.total_audit_residual_keur,
        outer_iterations=1, outer_residual_keur=0., stage_b2_iterations=0, stage_b2_residual_keur=0.,
        share_capital_draws_keur=tuple(a.share_capital_draw_keur for a in allocations),
        share_premium_draws_keur=tuple(a.share_premium_draw_keur for a in allocations),
        other_committed_equity_draws_keur=tuple(a.other_committed_equity_draw_keur for a in allocations),
        additional_equity_draws_keur=tuple(a.additional_equity_draw_keur for a in allocations), junior_draws_keur=zero,
        period_sources_uses_residual_keur=tuple(a.residual_keur for a in allocations),
        senior_idc_capitalized_uses_keur=idc, senior_commitment_fee_capitalized_keur=fsum(commitment),
        authority="F3_DATED_FACILITY_CONSTRUCTION_FINANCING_V1")
    return MultiSeniorFinancingResult(project_model_result=model, project_uses=uses,
        dscr_debt_capacity_keur=None, gearing_basis_keur=uses.total_project_uses_keur,
        gearing_ratio=pi.financing.gearing_ratio, gearing_debt_capacity_keur=gearing_capacity,
        final_senior_commitment_keur=senior_total, binding_senior_constraint="EXPLICIT_FACILITY_COMMITMENTS",
        junior_or_other_main_project_funding_keur=0., share_capital_keur=pi.financing.share_capital_keur,
        share_premium_keur=pi.financing.share_premium_keur,
        other_equity_funding_before_shl_keur=pi.financing.other_equity_funding_before_shl_keur,
        additional_equity_keur=additional_equity, derived_shl_cash_principal_keur=0.,
        shl_construction_pik_keur=0., opening_operating_shl_balance_keur=0., construction_funding=funding,
        fixed_point_iteration_count=1, fixed_point_maximum_difference_keur=0., construction_financing=financing,
        book_depreciable_asset_basis=_build_generic_book_basis(capex, developer_uses=_developer_uses(pi)),
        facility_schedules=facilities, financing_collection_digest=pi.financing_collection.content_digest(),
        aggregate_period_rates=model_input.senior_debt_inputs.period_rates)
