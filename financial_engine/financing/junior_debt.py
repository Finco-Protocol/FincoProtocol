"""Candidate Senior/Junior composition through existing contractual debt kernels."""
from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import timedelta
from math import fsum
import json

from finco_core.inputs import DebtServiceReserveSupportMode, PeriodFrequency, SponsorFundingMode
from finco_core.inputs.financing_instruments import FinancingCollection, FinancingError, InstrumentType, RepaymentMode
from finco_core.inputs.junior_debt import (
    AUTHORITY, JuniorProjectInputs, JuniorFundedCapex, JuniorCapitalizedCashInterest,
)
from finco_core.inputs.senior_rate_schedule import SeniorDayCountConvention
from financial_engine.financing.contracts import ConstructionFinancingResult, ProjectFinancingResult
from financial_engine.financing.multisenior import (
    FacilitySchedule, TOLERANCE_KEUR, build_aggregate_contract, build_facility_schedules,
)


@dataclass(frozen=True)
class _FacilityInputs:
    """One unchanged F3 instrument and its explicit day-count for the existing primitives."""
    info: object
    revenue: object
    capex: object
    financing: object
    financing_collection: FinancingCollection


def _facility_inputs(pi, instrument):
    day_count = (pi.junior_debt_policy.day_count if instrument.instrument_type is InstrumentType.JUNIOR_DEBT
                 else pi.financing.senior_debt_interest_config.day_count.value)
    fin = replace(pi.financing, senior_debt_interest_config=replace(
        pi.financing.senior_debt_interest_config, day_count=SeniorDayCountConvention(day_count)))
    return _FacilityInputs(pi.info, pi.revenue, pi.capex, fin, FinancingCollection((instrument,)))


def contractual_schedules(pi, periods):
    from dateutil.relativedelta import relativedelta
    op = tuple(p for p in periods if p.is_operation)
    junior = next(i for i in pi.financing_collection.instruments if i.instrument_type is InstrumentType.JUNIOR_DEBT)
    if not op:
        raise FinancingError("F35_OPERATING_AXIS_MISSING")
    if junior.repayment.mode is RepaymentMode.LEVEL_PRINCIPAL:
        grace_end = op[0].period_start + relativedelta(months=junior.repayment.grace_months)
        if grace_end not in {p.period_start for p in op if p.period_end <= junior.repayment.maturity_date}:
            raise FinancingError("F35_GRACE_NOT_ON_OPERATING_BOUNDARY")
    return tuple(build_facility_schedules(_facility_inputs(pi, instrument), periods)[0]
                 for instrument in sorted(pi.financing_collection.instruments, key=lambda i: i.seniority_rank))


def build_senior_contract(pi, periods):
    senior = next(i for i in pi.financing_collection.instruments if i.instrument_type is InstrumentType.SENIOR_TERM_LOAN)
    return build_aggregate_contract(_facility_inputs(pi, senior), periods)


def validate_capitalized_cash_interest(pi, cost):
    """Recheck the derived asset against contractual draws, not just its own digest."""
    from financial_engine.financing.generic_product_policy import derive_construction_financing
    from financial_engine.senior_debt.interest import period_day_fraction, period_interest
    from financial_engine.senior_debt.policy import DayCountConvention
    cost.validate()
    instrument = next(i for i in pi.financing_collection.instruments if i.seniority_rank == 2)
    periods = derive_construction_financing(pi).periods
    dc = DayCountConvention(pi.junior_debt_policy.day_count.upper())
    if len(cost.capitalized_cash_by_period_keur) != len(periods):
        raise FinancingError("F35_JUNIOR_IDC_PERIOD_AXIS_MISMATCH")
    opening = 0.
    mapped = []
    for p, value in zip(periods, cost.capitalized_cash_by_period_keur):
        end = p.end_date + timedelta(days=1)
        entries = [d for d in instrument.drawdowns if p.start_date <= d.draw_date < end]
        mapped.extend(entries)
        expected = period_interest(opening, instrument.interest.fixed_rate, period_day_fraction(p.start_date, end, dc))
        expected += fsum(period_interest(d.amount_keur, instrument.interest.fixed_rate,
            period_day_fraction(d.draw_date, end, dc)) for d in entries)
        if abs(value - expected) > 1e-9:
            raise FinancingError("F35_JUNIOR_IDC_CONTRACT_MISMATCH")
        opening += fsum(d.amount_keur for d in entries)
    if len(mapped) != len(instrument.drawdowns):
        raise FinancingError("F35_DRAW_OUTSIDE_CONSTRUCTION")


@dataclass(frozen=True, kw_only=True)
class JuniorConstructionFinancingResult(ConstructionFinancingResult):
    junior_cash_idc: JuniorCapitalizedCashInterest


@dataclass(frozen=True, kw_only=True)
class JuniorFinancingResult(ProjectFinancingResult):
    dscr_debt_capacity_keur: float | None
    senior_facility: FacilitySchedule
    junior_facility: FacilitySchedule
    financing_collection_digest: str
    financing_authority: str = AUTHORITY

    def junior_values(self, index):
        f = self.junior_facility
        if index not in f.period_indices:
            return dict(junior_opening_keur=0., junior_interest_keur=0., junior_principal_keur=0.,
                        junior_debt_service_keur=0., junior_closing_keur=0.)
        i = f.period_indices.index(index)
        return {f"junior_{name}_keur": getattr(f, f"{name}_keur")[i]
                for name in ("opening", "interest", "principal", "debt_service", "closing")}


def validate_project_boundary(pi):
    fin = pi.financing
    if not isinstance(pi, JuniorProjectInputs):
        raise FinancingError("F35_TYPED_INPUT_REQUIRED")
    if pi.info.period_frequency is not PeriodFrequency.SEMESTRIAL:
        raise FinancingError("F35_PERIOD_FREQUENCY_UNSUPPORTED")
    if fin.sponsor_funding_mode is not SponsorFundingMode.EQUITY_ONLY:
        raise FinancingError("F35_ACTIVE_SHL_NOT_RELEASED")
    if fin.junior_or_other_project_funding_keur or fin.other_equity_funding_before_shl_keur:
        raise FinancingError("F35_COMPETING_FUNDING_AUTHORITY")
    if (fin.dsra_support_mode is not DebtServiceReserveSupportMode.NONE or fin.dsra_months
            or fin.debt_service_reserve_requirement_keur or fin.dsra_target_policy is not None
            or fin.dsrf_commitment_keur or fin.dsrf_commitment_fee_rate_pa
            or pi.capex.reserve_accounts_keur or pi.cash_reserve_interest_policy is not None):
        raise FinancingError("F35_RESERVES_NOT_RELEASED")
    if fin.construction_period_uses_keur or fin.construction_financing is not None:
        raise FinancingError("F35_CONSTRUCTION_AUTHORITY_CONFLICT")
    if isinstance(pi.capex, JuniorFundedCapex) or any(getattr(pi.capex, k) for k in (
        "idc_keur", "commitment_fees_keur", "bank_fees_keur", "other_financial_keur", "vat_costs_keur",
        "vat_facility_idc_keur", "vat_facility_commitment_fee_keur")):
        raise FinancingError("F35_MANUAL_FINANCING_COST_CONFLICT")
    if pi.development_economics is not None:
        raise FinancingError("F35_DEVELOPER_USES_NOT_RELEASED")
    if fin.senior_debt_interest_config.day_count.value not in ("act_360", "act_365"):
        raise FinancingError("F35_SENIOR_DAY_COUNT_UNSUPPORTED")
    tax = pi.tax
    if tax.thin_cap_enabled or tax.atad_enabled or (tax.interest_limitation_policy is not None and tax.interest_limitation_policy.enabled):
        raise FinancingError("F35_INTEREST_LIMITATION_NOT_RELEASED")
    book_tax = pi.junior_debt_policy.idc_tax_treatment == "BOOK_BASED_POLICY"
    if book_tax != tax.tax_dep_basis_source_owned:
        raise FinancingError("F35_IDC_TAX_POLICY_CONFLICT")
    if book_tax and (tax.tax_depreciation_mode.value != "book_based_percentage" or tax.tax_deductible_book_dep_pct != 1.):
        raise FinancingError("F35_BOOK_BASED_TAX_POLICY_REQUIRED")


def run_junior_financing(pi, *, source_id="", baseline_commit_sha="", period_financing_income=None):
    from finco_core.construction.allocator import allocate_construction_sources_per_period
    from finco_core.construction.stage_b2 import CapitalizedFinancingCosts, apply_capitalized_financing_costs
    from financial_engine.adapters.project_inputs import from_project_inputs, build_senior_debt_model_input_from_project_inputs
    from financial_engine.book_basis import build_book_depreciable_asset_basis
    from financial_engine.financing.generic_product_policy import derive_construction_financing
    from financial_engine.financing.project_uses import compute_project_uses
    from financial_engine.financing.stack import build_construction_funding_schedule, reconcile_financing_stack
    from financial_engine.inputs import PeriodInterestInput
    from financial_engine.orchestrator import run_operating_model, run_senior_debt_model

    validate_project_boundary(pi)
    periods = run_operating_model(from_project_inputs(pi, source_id=source_id, baseline_commit_sha=baseline_commit_sha)).periods
    senior_facility, junior_facility = contractual_schedules(pi, periods)
    construction = derive_construction_financing(pi)
    n = len(construction.periods)
    s, j = senior_facility, junior_facility
    cost = JuniorCapitalizedCashInterest.from_funded_ledger(j.instrument_id,
        pi.financing_collection.content_digest(), j.construction_idc_keur, pi.junior_debt_policy.idc_book_life_years)
    senior_cost = CapitalizedFinancingCosts(senior_idc_keur=fsum(s.construction_idc_keur),
        senior_commitment_fee_keur=fsum(s.construction_commitment_fees_keur),
        structuring_fee_keur=fsum(s.upfront_fees_keur), vat_idc_keur=0., vat_commitment_fee_keur=0.)
    capex = apply_capitalized_financing_costs(pi.capex, senior_cost)
    capex = JuniorFundedCapex(**{f.name: getattr(capex, f.name) for f in fields(type(pi.capex))}, junior_cash_idc=cost)
    working = replace(pi, capex=capex, financing=replace(pi.financing, clean_shl_principal_keur=0.))
    uses = compute_project_uses(working)
    senior_capacity = uses.total_project_uses_keur * pi.financing.gearing_ratio
    if s.commitment_keur > senior_capacity + TOLERANCE_KEUR:
        raise FinancingError("F35_SENIOR_GEARING_CAP_EXCEEDED")
    total_debt = s.commitment_keur + j.commitment_keur
    if total_debt > uses.total_project_uses_keur * pi.junior_debt_policy.maximum_total_debt_gearing + TOLERANCE_KEUR:
        raise FinancingError("F35_TOTAL_DEBT_GEARING_CAP_EXCEEDED")
    _, equity = reconcile_financing_stack(total_project_uses_keur=uses.total_project_uses_keur,
        final_senior_commitment_keur=s.commitment_keur, junior_or_other_main_project_funding_keur=j.commitment_keur,
        share_capital_keur=pi.financing.share_capital_keur, share_premium_keur=pi.financing.share_premium_keur,
        other_equity_funding_before_shl_keur=0., sponsor_funding_mode=SponsorFundingMode.EQUITY_ONLY)
    hard = tuple(fsum(getattr(pi.capex, item.code).amount_keur * item.payment_weights[i]
        for item in construction.capex_items) for i in range(n))
    total_uses = tuple(hard[i] + s.construction_idc_keur[i] + j.construction_idc_keur[i]
        + s.construction_commitment_fees_keur[i] + s.upfront_fees_keur[i] for i in range(n))
    if abs(fsum(total_uses) - uses.total_project_uses_keur) > TOLERANCE_KEUR:
        raise FinancingError("F35_CONSTRUCTION_USES_MISMATCH")
    residual = tuple(total_uses[i] - s.construction_draws_keur[i] - j.construction_draws_keur[i] for i in range(n))
    if any(v < -TOLERANCE_KEUR for v in residual):
        raise FinancingError("F35_PERIOD_OVERFUNDING")
    rows = allocate_construction_sources_per_period(period_uses=tuple(max(0., v) for v in residual),
        share_capital_keur=pi.financing.share_capital_keur, share_premium_keur=pi.financing.share_premium_keur,
        other_committed_equity_keur=0., additional_equity_keur=equity, shl_cash_keur=0., junior_keur=0., senior_commitment_keur=0.)
    rows = tuple(replace(r, period_uses_keur=total_uses[i], senior_draw_keur=s.construction_draws_keur[i],
        junior_draw_keur=j.construction_draws_keur[i], total_sources_keur=r.total_sources_keur
        + s.construction_draws_keur[i] + j.construction_draws_keur[i]) for i, r in enumerate(rows))
    dates = tuple((p.start_date, p.end_date + timedelta(days=1), p.end_date + timedelta(days=1)) for p in construction.periods)
    funding = build_construction_funding_schedule(construction_period_count=n, total_project_uses_keur=uses.total_project_uses_keur,
        senior_keur=s.commitment_keur, junior_keur=j.commitment_keur, share_capital_keur=pi.financing.share_capital_keur,
        share_premium_keur=pi.financing.share_premium_keur, other_committed_equity_keur=0., additional_equity_keur=equity,
        shl_cash_keur=0., period_dates=dates, canonical_economic_allocations=rows)
    model_input = build_senior_debt_model_input_from_project_inputs(working, source_id=source_id, baseline_commit_sha=baseline_commit_sha)
    junior_interest = dict(zip(j.period_indices, j.interest_keur))
    existing = {r.period_index: r for r in model_input.tax.period_interest}
    if any(r.other_interest_keur or r.shl_interest_keur for r in existing.values()):
        raise FinancingError("F35_COMPETING_OTHER_INTEREST")
    interest = tuple(replace(existing.get(p.period_index, PeriodInterestInput(p.period_index)),
        other_interest_keur=junior_interest.get(p.period_index, 0.)) for p in periods if p.is_operation)
    tax = replace(model_input.tax, period_interest=interest)
    if period_financing_income:
        tax = replace(tax, period_financing_income=period_financing_income)
    model = run_senior_debt_model(replace(model_input, tax=tax))
    senior = model.senior_debt
    if senior is None or not senior.diagnostics.get("is_authoritative", False):
        raise FinancingError("F35_SENIOR_NOT_AUTHORITATIVE")
    for output, field in (("senior_debt_opening_keur", "opening_keur"), ("senior_interest_keur", "interest_keur"),
        ("senior_principal_keur", "principal_keur"), ("senior_debt_service_keur", "debt_service_keur"),
        ("senior_debt_closing_keur", "closing_keur")):
        expected = dict(zip(s.period_indices, getattr(s, field)))
        if any(abs(v - expected.get(i, 0.)) > TOLERANCE_KEUR for i, v in zip(senior.period_indices, getattr(senior, output))):
            raise FinancingError("F35_SENIOR_HANDSHAKE_FAILED", output)
    cfads = dict(zip(model.tax_and_cfads.period_indices, model.tax_and_cfads.cfads_keur))
    service_s, service_j = dict(zip(s.period_indices, s.debt_service_keur)), dict(zip(j.period_indices, j.debt_service_keur))
    for p in periods:
        if p.is_operation and cfads[p.period_index] + TOLERANCE_KEUR < service_s.get(p.period_index, 0.) + service_j.get(p.period_index, 0.):
            i = p.period_index
            available = cfads[i] - service_s.get(i, 0.)
            due = service_j.get(i, 0.)
            raise FinancingError("F35_CONTRACTUAL_SERVICE_CASH_SHORTFALL", json.dumps({
                "period_index": i, "base_cfads_keur": cfads[i], "senior_due_keur": service_s.get(i, 0.),
                "junior_due_keur": due, "post_senior_available_keur": available,
                "contractual_shortfall_keur": service_s.get(i, 0.) + due - cfads[i],
                "junior_unpaid_opening_balance_keur": dict(zip(j.period_indices, j.opening_keur)).get(i, 0.),
            }, sort_keys=True))
    zero = (0.,) * n
    cfr = JuniorConstructionFinancingResult(period_start_dates=tuple(d[0] for d in dates),
        period_end_dates=tuple(p.end_date for p in construction.periods), hard_capex_uses_keur=hard,
        total_period_uses_keur=total_uses, senior_draws_keur=s.construction_draws_keur,
        cumulative_senior_keur=tuple(fsum(s.construction_draws_keur[:i+1]) for i in range(n)),
        senior_idc_accrual_keur=s.construction_idc_keur, senior_commitment_fee_accrual_keur=s.construction_commitment_fees_keur,
        structuring_fee_keur=s.upfront_fees_keur, shl_allocation_keur=zero, shl_cash_contribution_keur=zero,
        shl_day_count_fraction=zero, shl_pik_accrual_keur=zero,
        total_capitalized_financing_keur=senior_cost.total_keur + cost.amount_keur,
        shl_construction_pik_keur=0., opening_operating_shl_keur=0., final_total_project_uses_keur=uses.total_project_uses_keur,
        final_senior_commitment_keur=s.commitment_keur, sources_uses_residual_keur=funding.total_audit_residual_keur,
        outer_iterations=1, outer_residual_keur=0., stage_b2_iterations=0, stage_b2_residual_keur=0.,
        share_capital_draws_keur=tuple(r.share_capital_draw_keur for r in rows), share_premium_draws_keur=tuple(r.share_premium_draw_keur for r in rows),
        other_committed_equity_draws_keur=zero, additional_equity_draws_keur=tuple(r.additional_equity_draw_keur for r in rows),
        junior_draws_keur=j.construction_draws_keur, period_sources_uses_residual_keur=tuple(r.residual_keur for r in rows),
        senior_idc_capitalized_uses_keur=s.construction_idc_keur, senior_commitment_fee_capitalized_keur=fsum(s.construction_commitment_fees_keur),
        authority=AUTHORITY, junior_cash_idc=cost)
    return JuniorFinancingResult(project_model_result=model, project_uses=uses, dscr_debt_capacity_keur=None,
        gearing_basis_keur=uses.total_project_uses_keur, gearing_ratio=pi.financing.gearing_ratio,
        gearing_debt_capacity_keur=senior_capacity, final_senior_commitment_keur=s.commitment_keur,
        binding_senior_constraint="EXPLICIT_SENIOR_COMMITMENT", junior_or_other_main_project_funding_keur=j.commitment_keur,
        share_capital_keur=pi.financing.share_capital_keur, share_premium_keur=pi.financing.share_premium_keur,
        other_equity_funding_before_shl_keur=0., additional_equity_keur=equity, derived_shl_cash_principal_keur=0.,
        shl_construction_pik_keur=0., opening_operating_shl_balance_keur=0., construction_funding=funding,
        fixed_point_iteration_count=1, fixed_point_maximum_difference_keur=0., construction_financing=cfr,
        book_depreciable_asset_basis=build_book_depreciable_asset_basis(pi.capex, cfr),
        senior_facility=s, junior_facility=j, financing_collection_digest=pi.financing_collection.content_digest())
