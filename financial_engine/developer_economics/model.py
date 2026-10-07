"""Developer Economics V1 — the one canonical calculator.

Pure function of the typed ``ProjectInputs.development_economics`` contract plus
the canonical Financial Close date and the canonical hard-CAPEX authority.  It
serves two consumers from ONE source so they can never disagree:

  * ``resolve_developer_project_uses``  -> the PROJECT-ledger uses
    (development cost reimbursement, developer fee) consumed by the canonical
    Sources & Uses composition point ``compute_project_uses``;
  * ``compute_developer_economics``      -> the DEVELOPER-ledger result
    (dated cash-flow vector, receipts, MOIC, XIRR).

Developer flows are NEVER inserted into sponsor contributions, sponsor
distributions, Pure Equity cash flows or the shareholder waterfall.

Metric semantics (MISSING != ZERO, no fabricated -100%/0% IRR):
  * Developer MOIC = total developer receipts / total development spend,
    receipts = reimbursement + developer fee.
      spend > 0, receipts = 0  -> 0.0   (legitimate economic zero, status OK)
      spend = 0                -> None  (ZERO_CONTRIBUTION: denominator has no
                                  economic authority)
  * Developer IRR = XIRR over the developer's own dated net cash-flow vector
    (spend negative; reimbursement and fee positive at the canonical FC date).
      valid sign change         -> value (OK)
      spend > 0, receipts = 0   -> None (NO_POSITIVE_CASHFLOW)
      no spend                  -> None (NO_NEGATIVE_CASHFLOW)
      no convergence            -> None (NON_CONVERGENT)
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import TYPE_CHECKING

from finco_core.inputs.development import (
    DeveloperFeeMode,
    DevelopmentEconomicsInput,
    DevelopmentOutcome,
)
from finco_core.sponsor.xirr import robust_xirr

from financial_engine.developer_economics.contracts import (
    DeveloperCashFlow,
    DeveloperMetricStatus,
    DeveloperEconomicsResult,
    DeveloperFeeBasisEvidence,
    DeveloperProjectUses,
)

if TYPE_CHECKING:
    from finco_core.inputs import ProjectInputs

_TOL = 1e-9

HARD_CAPEX_FEE_BASIS_AUTHORITY = (
    "CapexStructure.hard_capex_keur — pure CAPEX input, evaluated BEFORE financing "
    "costs, reserves and developer uses; contains no developer fee (non-circular)"
)
FIXED_FEE_BASIS_AUTHORITY = "FIXED_KEUR — no basis"


def _active_input(project_inputs: "ProjectInputs") -> DevelopmentEconomicsInput | None:
    config = getattr(project_inputs, "development_economics", None)
    if config is None or not config.enabled:
        return None
    return config


def _validate_spend_dates(config: DevelopmentEconomicsInput, financial_close: date) -> None:
    for entry in config.spend_schedule:
        if entry.spend_date > financial_close:
            raise ValueError(
                "DEV_ECON_SPEND_AFTER_FINANCIAL_CLOSE: development spend is pre-FC "
                f"cash; {entry.spend_date} is after the canonical Financial Close "
                f"{financial_close}"
            )


def _fee_evidence(
    config: DevelopmentEconomicsInput, project_inputs: "ProjectInputs"
) -> DeveloperFeeBasisEvidence:
    if config.outcome is DevelopmentOutcome.ABANDONED:
        fee = 0.0
        basis = None
        authority = "ABANDONED — no developer fee"
    elif config.developer_fee_mode is DeveloperFeeMode.FIXED_KEUR:
        fee = float(config.developer_fee_value)
        basis = None
        authority = FIXED_FEE_BASIS_AUTHORITY
    else:
        basis = float(project_inputs.capex.hard_capex_keur)
        fee = float(config.developer_fee_value) * basis
        authority = HARD_CAPEX_FEE_BASIS_AUTHORITY
    return DeveloperFeeBasisEvidence(
        mode=config.developer_fee_mode.value,
        fee_value=float(config.developer_fee_value),
        basis_keur=basis,
        basis_authority=authority,
        fee_keur=fee,
    )


def resolve_developer_project_uses(project_inputs: "ProjectInputs") -> DeveloperProjectUses:
    """PROJECT-ledger uses created by Developer Economics (zero when inactive)."""
    config = _active_input(project_inputs)
    if config is None:
        return DeveloperProjectUses()
    _validate_spend_dates(config, project_inputs.info.financial_close)
    if config.outcome is DevelopmentOutcome.ABANDONED:
        return DeveloperProjectUses()
    return DeveloperProjectUses(
        development_cost_reimbursement_keur=float(config.reimbursed_development_cost_keur),
        developer_fee_keur=_fee_evidence(config, project_inputs).fee_keur,
        book_basis_mode=config.book_basis_mode.value,
    )


def _status_for(values: list[float], xirr: float | None) -> DeveloperMetricStatus:
    if not any(value < -_TOL for value in values):
        return DeveloperMetricStatus.NO_NEGATIVE_CASHFLOW
    if not any(value > _TOL for value in values):
        return DeveloperMetricStatus.NO_POSITIVE_CASHFLOW
    if xirr is None:
        return DeveloperMetricStatus.NON_CONVERGENT
    return DeveloperMetricStatus.OK


def compute_developer_economics(
    project_inputs: "ProjectInputs",
) -> DeveloperEconomicsResult | None:
    """Developer-ledger result, or None when Developer Economics is inactive."""
    config = _active_input(project_inputs)
    if config is None:
        return None
    financial_close = project_inputs.info.financial_close
    _validate_spend_dates(config, financial_close)

    fee_basis = _fee_evidence(config, project_inputs)
    project_uses = resolve_developer_project_uses(project_inputs)
    reimbursement = project_uses.development_cost_reimbursement_keur
    fee = project_uses.developer_fee_keur
    total_spend = config.total_development_spend_keur
    receipts = reimbursement + fee

    by_date: dict[date, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for entry in config.spend_schedule:
        by_date[entry.spend_date][0] += entry.amount_keur
    if reimbursement > 0.0:
        by_date[financial_close][1] += reimbursement
    if fee > 0.0:
        by_date[financial_close][2] += fee

    rows = tuple(
        DeveloperCashFlow(
            cashflow_date=cash_date,
            development_spend_keur=spend,
            development_cost_reimbursement_keur=reimbursed,
            developer_fee_keur=fee_row,
            net_developer_cashflow_keur=reimbursed + fee_row - spend,
        )
        for cash_date, (spend, reimbursed, fee_row) in sorted(by_date.items())
    )

    values = [row.net_developer_cashflow_keur for row in rows]
    dates = [row.cashflow_date for row in rows]
    xirr_value = (
        robust_xirr(values, dates)
        if any(v < -_TOL for v in values) and any(v > _TOL for v in values)
        else None
    )
    xirr_status = _status_for(values, xirr_value)
    if xirr_status is not DeveloperMetricStatus.OK:
        xirr_value = None

    if total_spend > _TOL:
        moic: float | None = receipts / total_spend
        moic_status = DeveloperMetricStatus.OK
    else:
        moic = None
        moic_status = DeveloperMetricStatus.ZERO_CONTRIBUTION

    return DeveloperEconomicsResult(
        outcome=config.outcome.value,
        settlement_date=financial_close,
        cashflows=rows,
        total_development_spend_keur=total_spend,
        reimbursed_development_cost_keur=reimbursement,
        developer_fee_keur=fee,
        total_developer_receipts_keur=receipts,
        developer_moic=moic,
        developer_moic_status=moic_status,
        developer_xirr=xirr_value,
        developer_xirr_status=xirr_status,
        fee_basis=fee_basis,
    )
