"""financial_engine.financing.generic_product_policy — H-1 generic product financing policy.

The product's FinancingParams already declare a commitment fee, a structuring /
arrangement fee, the senior all-in rate and a DSRA coverage (dsra_months), but the
generic product run historically ignored them (construction_financing=None,
dsra_support_mode=NONE), so IDC, lender fees and the DSRA were excluded from the
Sources & Uses, debt sizing, financial statements and returns.

This module wires those declared assumptions into the engine's existing typed
authorities — it adds no new economics:

* Construction financing: derives ``ConstructionFinancingInput`` (IDC, commitment
  fee, structuring/arrangement fee) from the project's own calendar, CAPEX timing
  and financing assumptions. IDC is computed by Stage B2 on actual senior draws.
* DSRA: enables ``CASH_DSRA`` with the PEAK_FORWARD_DEBT_SERVICE_MONTHS target: the
  peak debt service due over any ``dsra_months`` window ahead, held while senior
  debt is outstanding and released when it is repaid. The initial (COD) funding
  equals that peak, resolved by a fixed point on the actual senior schedule. It is a
  Project Use inside Total Project Uses, funded by the same construction sources
  waterfall as every other use (equity first, senior residual up to the gearing
  cap), so there is no unexplained funding source.

Explicit typed inputs always win: if a project already carries typed construction
financing, a DSRA mode, or manual IDC/fee CAPEX, the policy does not override it.
"""
from __future__ import annotations

import dataclasses as dc
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from finco_core.engine.period_engine import PeriodEngine
from finco_core.engine.period_engine import PeriodFrequency as EnginePeriodFrequency
from finco_core.inputs import DebtServiceReserveSupportMode, ProjectInputs
from finco_core.inputs import PeriodFrequency as InputPeriodFrequency
from finco_core.inputs.construction_financing import (
    ConstructionCapexTimingInput,
    ConstructionCommitmentFeeInput,
    ConstructionFinancingInput,
    ConstructionPeriodSpec,
    ConstructionSeniorPricingInput,
    ConstructionStructuringFeeBasisMode,
    ConstructionStructuringFeeInput,
)
from finco_core.inputs.senior_rate_schedule import SeniorRateMode

POLICY_AUTHORITY = "GENERIC_PRODUCT_FINANCING_POLICY_H1_V1"
_PERIODS_PER_YEAR = 2  # the clean senior-debt contract supports SEMESTRIAL only


class GenericFinancingPolicyError(ValueError):
    """Typed fail-closed error; the message starts with an ``H1_*`` reason code."""


@dataclass(frozen=True)
class GenericFinancingPolicy:
    """Which declared financing assumptions the generic product run applies."""

    apply_construction_financing: bool = True
    apply_cash_dsra: bool = True
    dsra_tolerance_keur: float = 1e-6
    dsra_max_iterations: int = 25


DEFAULT_GENERIC_FINANCING_POLICY = GenericFinancingPolicy()
DISABLED_GENERIC_FINANCING_POLICY = GenericFinancingPolicy(False, False)


@dataclass(frozen=True)
class FinancingPolicyEvidence:
    """What the policy applied; attached to the production run for traceability."""

    authority: str
    construction_financing_applied: bool
    cash_dsra_applied: bool
    initial_dsra_funding_keur: float
    dsra_iterations: int
    dsra_residual_keur: float


@dataclass(frozen=True)
class SourcesAndUses:
    """Explicit Sources & Uses at financial close / COD (kEUR); no residual plug."""

    base_project_capex_keur: float
    capitalized_idc_keur: float
    commitment_fee_keur: float
    structuring_fee_keur: float
    other_financing_costs_keur: float
    initial_dsra_funding_keur: float
    other_uses_keur: float
    total_uses_keur: float
    senior_debt_keur: float
    junior_or_other_keur: float
    share_capital_and_other_equity_keur: float
    shareholder_loan_cash_keur: float
    total_sources_keur: float
    difference_keur: float  # total_sources - total_uses; must be ~0
    # Developer Economics V1 typed project uses (part of total_uses_keur; 0.0 = inactive).
    development_cost_reimbursement_keur: float = 0.0
    developer_fee_keur: float = 0.0


def _is_untouched(pi: ProjectInputs) -> tuple[bool, bool]:
    """(construction financing may be derived, DSRA may be derived)."""
    fin, capex = pi.financing, pi.capex
    manual_costs = any(
        getattr(capex, name, 0.0)
        for name in (
            "idc_keur", "commitment_fees_keur", "bank_fees_keur", "other_financial_keur",
            "vat_costs_keur", "vat_facility_idc_keur", "vat_facility_commitment_fee_keur",
        )
    )
    construction_free = fin.construction_financing is None and not manual_costs and not (
        fin.construction_period_uses_keur
    )
    dsra_free = (
        fin.dsra_support_mode == DebtServiceReserveSupportMode.NONE
        and not fin.debt_service_reserve_requirement_keur
        and not capex.reserve_accounts_keur
        and fin.dsra_target_policy is None
        and int(fin.dsra_months or 0) > 0
    )
    return construction_free, dsra_free


def derive_construction_financing(pi: ProjectInputs) -> ConstructionFinancingInput:
    """Derive the typed construction-financing input from the project's own inputs."""
    info, fin = pi.info, pi.financing
    if info.period_frequency != InputPeriodFrequency.SEMESTRIAL:
        raise GenericFinancingPolicyError(
            "H1_UNSUPPORTED_PERIOD_FREQUENCY: generic construction financing "
            f"supports SEMESTRIAL only, got {info.period_frequency!r}"
        )
    engine = PeriodEngine(
        financial_close=info.financial_close,
        construction_months=info.construction_months,
        horizon_years=info.horizon_years,
        ppa_years=pi.revenue.ppa_term_years,
        frequency=EnginePeriodFrequency.SEMESTRIAL,
        cod_date=info.cod_date,
        period_axis_convention=getattr(
            info.period_axis_convention, "value", info.period_axis_convention),
    )
    construction = [p for p in engine.periods() if p.is_construction]
    n = len(construction)
    if n == 0:
        raise GenericFinancingPolicyError("H1_NO_CONSTRUCTION_PERIODS")
    periods = tuple(
        ConstructionPeriodSpec(start_date=p.start_date, end_date=p.end_date - timedelta(days=1))
        for p in construction
    )

    items = []
    for code in pi.capex._CAPEX_ITEM_FIELDS:
        item = getattr(pi.capex, code)
        if item.amount_keur <= 0.0:
            continue
        if len(item.spending_profile) > n:
            raise GenericFinancingPolicyError(
                f"H1_CAPEX_TIMING_EXCEEDS_CONSTRUCTION: {code} has "
                f"{len(item.spending_profile)} spending periods for {n} construction periods"
            )
        weights = [0.0] * n
        weights[0] += item.y0_share  # paid at financial close
        for index, share in enumerate(item.spending_profile):
            weights[index] += share  # paid at the end of construction period ``index``
        items.append(ConstructionCapexTimingInput(
            code=code, name=item.name, payment_weights=tuple(weights)))

    rate_cfg = fin.senior_debt_interest_config
    schedule = rate_cfg.rate_schedule
    if schedule.mode == SeniorRateMode.EXPLICIT_ALL_IN_SCHEDULE and schedule.explicit_all_in_rates:
        all_in = schedule.explicit_all_in_rates[0]
    elif schedule.mode == SeniorRateMode.FLAT_ALL_IN:
        all_in = schedule.flat_all_in_rate
    else:
        all_in = fin.all_in_rate
    pricing = ConstructionSeniorPricingInput(
        mode=SeniorRateMode.FLAT_ALL_IN, flat_all_in_rate=all_in, day_count=rate_cfg.day_count)

    return ConstructionFinancingInput(
        enabled=True,
        periods=periods,
        capex_items=tuple(items),
        senior_pricing=pricing,
        commitment_fee=ConstructionCommitmentFeeInput(rate=fin.commitment_fee),
        structuring_fee=ConstructionStructuringFeeInput(
            rate=fin.structuring_fee + fin.arrangement_fee,
            basis_mode=ConstructionStructuringFeeBasisMode.SENIOR_PLUS_VAT_COMMITMENTS,
            payment_weights=tuple([1.0] + [0.0] * (n - 1)),  # paid at financial close
        ),
    )


def apply_generic_financing_policy(
    pi: ProjectInputs, policy: GenericFinancingPolicy, *, initial_dsra_keur: float = 0.0,
) -> tuple[ProjectInputs, bool, bool]:
    """Return inputs with the policy applied, plus (construction applied, dsra applied)."""
    from finco_core.inputs.multisenior import MultiSeniorProjectInputs
    if isinstance(pi, MultiSeniorProjectInputs):
        from financial_engine.financing.multisenior import validate_project_boundary
        validate_project_boundary(pi)
        return pi, False, False
    construction_free, dsra_free = _is_untouched(pi)
    fin = pi.financing
    construction_on = policy.apply_construction_financing and construction_free
    dsra_on = policy.apply_cash_dsra and dsra_free
    if construction_on:
        fin = dc.replace(fin, construction_financing=derive_construction_financing(pi))
    if dsra_on:
        fin = dc.replace(
            fin,
            dsra_support_mode=DebtServiceReserveSupportMode.CASH_DSRA,
            dsra_target_policy="peak_forward_debt_service_months",
            debt_service_reserve_requirement_keur=float(initial_dsra_keur),
        )
    return dc.replace(pi, financing=fin), construction_on, dsra_on


def _peak_forward_debt_service_keur(result) -> float:
    """Peak next-period senior debt service over the tenor (before the coverage multiplier).

    Operating period i's DSRA target references the debt service of period i + 1, so
    the peak requirement is the maximum debt service from the second debt period on.
    """
    senior = result.financing_result.project_model_result.senior_debt
    due = [float(x) for x in senior.senior_debt_service_keur if x > 0.0]
    return max(due[1:], default=0.0)


def run_with_generic_financing_policy(
    pi: ProjectInputs,
    run: Callable[[ProjectInputs], object],
    policy: GenericFinancingPolicy = DEFAULT_GENERIC_FINANCING_POLICY,
) -> tuple[object, ProjectInputs, FinancingPolicyEvidence]:
    """Run the engine with the policy applied; returns (result, applied inputs, evidence).

    The initial DSRA funding is the peak forward debt service over ``dsra_months``,
    a fixed point because the reserve is itself a Project Use that moves the debt.
    """
    applied, construction_on, dsra_on = apply_generic_financing_policy(pi, policy)
    if not dsra_on:
        result = run(applied)
        return result, applied, FinancingPolicyEvidence(
            POLICY_AUTHORITY, construction_on, False, 0.0, 0, 0.0)

    multiplier = int(pi.financing.dsra_months) * _PERIODS_PER_YEAR / 12.0
    # Seed only (never the authority): the peak debt service of the plain run is within
    # a few percent of the final answer, and the target barely depends on the reserve
    # itself, so the fixed point below converges in two engine evaluations.
    try:
        funding = _peak_forward_debt_service_keur(run(pi)) * multiplier
    except Exception:  # noqa: BLE001 - a failed seed only costs iterations
        funding = 0.0
    residual = float("inf")
    for iteration in range(1, policy.dsra_max_iterations + 1):
        applied, _, _ = apply_generic_financing_policy(pi, policy, initial_dsra_keur=funding)
        result = run(applied)
        target = _peak_forward_debt_service_keur(result) * multiplier
        residual = abs(target - funding)
        if residual <= policy.dsra_tolerance_keur:
            return result, applied, FinancingPolicyEvidence(
                POLICY_AUTHORITY, construction_on, True, funding, iteration, residual)
        funding = target
    raise GenericFinancingPolicyError(
        "H1_DSRA_INITIAL_FUNDING_NOT_CONVERGED: residual "
        f"{residual:.6f} kEUR after {policy.dsra_max_iterations} iterations")


def build_sources_and_uses(financing_result) -> SourcesAndUses:
    """Explicit Sources & Uses view from the engine's own audited financing result."""
    fin = financing_result
    uses = fin.project_uses
    construction = fin.construction_financing
    if construction is not None:
        idc = float(sum(construction.senior_idc_capitalized_uses_keur)) + float(construction.vat_idc_keur)
        commitment = float(construction.senior_commitment_fee_capitalized_keur) + float(
            construction.vat_commitment_fee_keur)
        structuring = float(sum(construction.structuring_fee_keur))
    else:
        idc = commitment = structuring = 0.0
    financing_costs = float(uses.explicit_financing_cost_uses_keur)
    other_financing = financing_costs - idc - commitment - structuring
    other_financing = 0.0 if abs(other_financing) < 1e-9 else other_financing
    funding = fin.construction_funding
    equity = float(fin.share_capital_keur) + float(fin.share_premium_keur) + float(
        fin.other_equity_funding_before_shl_keur) + float(fin.additional_equity_keur)
    total_uses = float(uses.total_project_uses_keur)
    total_sources = float(funding.total_audit_sources_keur)
    return SourcesAndUses(
        base_project_capex_keur=float(uses.hard_project_capex_keur),
        capitalized_idc_keur=idc,
        commitment_fee_keur=commitment,
        structuring_fee_keur=structuring,
        other_financing_costs_keur=other_financing,
        initial_dsra_funding_keur=float(uses.reserve_account_funding_keur),
        other_uses_keur=float(uses.other_explicit_project_uses_keur),
        total_uses_keur=total_uses,
        senior_debt_keur=float(fin.final_senior_commitment_keur),
        junior_or_other_keur=float(fin.junior_or_other_main_project_funding_keur),
        share_capital_and_other_equity_keur=equity,
        shareholder_loan_cash_keur=float(fin.derived_shl_cash_principal_keur),
        total_sources_keur=total_sources,
        difference_keur=(0.0 if abs(total_sources - total_uses) < 1e-9 else total_sources - total_uses),
        development_cost_reimbursement_keur=float(uses.development_cost_reimbursement_keur),
        developer_fee_keur=float(uses.developer_fee_keur),
    )


__all__ = [
    "POLICY_AUTHORITY", "GenericFinancingPolicy", "GenericFinancingPolicyError",
    "DEFAULT_GENERIC_FINANCING_POLICY", "DISABLED_GENERIC_FINANCING_POLICY",
    "FinancingPolicyEvidence", "SourcesAndUses", "derive_construction_financing",
    "apply_generic_financing_policy", "run_with_generic_financing_policy",
    "build_sources_and_uses",
]
