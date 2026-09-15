"""MVP G2B — Simple Sponsor Returns model.

Downstream-only orchestrator. Consumes G2A results and clean engine outputs.
No circular dependency back into debt sizing, tax, SHL, or construction funding.

GENERIC MVP POLICY: DISTRIBUTE_ALL_POST_SHL_CASH
  No DSRA. No MRA. No distribution account. No lock-up. No promote.
"""

from __future__ import annotations

from finco_core.engine.period_engine import map_period_vector

from datetime import date, timedelta

from finco_core.inputs import ProjectInputs, SponsorFundingMode
from finco_core.sponsor.xirr import robust_xirr

from financial_engine.financing.contracts import (
    ConstructionFundingPeriod,
    ProjectFinancingResult,
)
from financial_engine.financing.project import run_project_financing_model
from financial_engine.results import ProjectModelResult
from financial_engine.adapters.project_inputs import (
    _build_shareholder_loan_model_input_from_project_inputs,
    build_senior_debt_model_input_from_project_inputs,
)
from financial_engine.shl.contracts import ShlRepaymentMode
from financial_engine.sponsor_returns.contracts import (
    ReturnMetricStatus,
    SponsorCashFlowPeriod,
    SponsorDistributionPolicy,
    SponsorReturnResult,
)


def _add_months(d: date, months: int) -> date:
    """Add a whole number of months to a date, clamping to end-of-month."""
    month = d.month + months
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    # Clamp day to end of month
    import calendar
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _construction_period_date(
    financial_close: date,
    period_index: int,
) -> date:
    """Return the cash-draw date for a construction funding period.

    Authority: project-owned financial_close + (period_index - 1) months.
    Period 1 draw is at financial close (month 0 offset).
    Period k draw is at financial close + (k-1) months.
    """
    return _add_months(financial_close, period_index - 1)


def _xirr_status(
    cash_flows: list[float],
    rate: float | None,
) -> ReturnMetricStatus:
    has_neg = any(cf < 0 for cf in cash_flows)
    has_pos = any(cf > 0 for cf in cash_flows)
    if not has_neg:
        return ReturnMetricStatus.NO_NEGATIVE_CASHFLOW
    if not has_pos:
        return ReturnMetricStatus.NO_POSITIVE_CASHFLOW
    if rate is None:
        return ReturnMetricStatus.NON_CONVERGENT
    return ReturnMetricStatus.OK


def _moic_status(
    total_contributions: float,
    moic: float | None,
) -> ReturnMetricStatus:
    if total_contributions <= 0.0:
        return ReturnMetricStatus.ZERO_CONTRIBUTION
    if moic is None:
        return ReturnMetricStatus.UNDEFINED
    return ReturnMetricStatus.OK


def compute_gated_sponsor_return_metrics(
    cashflow_dates: list[date],
    pure_equity_cashflows: list[float],
    total_sponsor_cashflows: list[float],
    total_legal_equity_contributed_keur: float,
    total_sponsor_contributed_keur: float,
) -> tuple:
    """Compute XIRR/MOIC metrics for G2C gated cashflow vectors.

    Extracted from G2B so G2C can call it without duplicating XIRR logic.
    Returns (pe_xirr, pe_xirr_status, pe_moic, pe_moic_status,
             ts_xirr, ts_xirr_status, ts_moic, ts_moic_status).
    """
    pe_xirr = robust_xirr(pure_equity_cashflows, cashflow_dates)
    pe_xirr_status = _xirr_status(pure_equity_cashflows, pe_xirr)
    pe_moic: float | None = None
    if total_legal_equity_contributed_keur > 0.0:
        pe_moic = sum(cf for cf in pure_equity_cashflows if cf > 0) / total_legal_equity_contributed_keur
    pe_moic_status = _moic_status(total_legal_equity_contributed_keur, pe_moic)

    ts_xirr = robust_xirr(total_sponsor_cashflows, cashflow_dates)
    ts_xirr_status = _xirr_status(total_sponsor_cashflows, ts_xirr)
    ts_moic: float | None = None
    if total_sponsor_contributed_keur > 0.0:
        ts_moic = sum(cf for cf in total_sponsor_cashflows if cf > 0) / total_sponsor_contributed_keur
    ts_moic_status = _moic_status(total_sponsor_contributed_keur, ts_moic)

    return (
        pe_xirr, pe_xirr_status,
        pe_moic, pe_moic_status,
        ts_xirr, ts_xirr_status,
        ts_moic, ts_moic_status,
    )


def run_project_sponsor_returns_model(
    project_inputs: ProjectInputs,
    *,
    source_id: str = "",
    baseline_commit_sha: str = "",
) -> SponsorReturnResult:
    """Compute G2B simple sponsor returns from G2A financing results.

    Calls run_project_financing_model internally once. The G2A result is
    not mutated. Return calculation is observational/downstream only.

    Raises ValueError if sponsor_funding_mode or gearing_basis_mode are
    not explicitly set (same guard as G2A).
    """
    # ── Run G2A financing model ───────────────────────────────────────────────
    financing: ProjectFinancingResult = run_project_financing_model(
        project_inputs,
        source_id=source_id,
        baseline_commit_sha=baseline_commit_sha,
    )

    model_result: ProjectModelResult = financing.project_model_result  # type: ignore[assignment]
    fin = project_inputs.financing
    info = project_inputs.info

    # ── Construction contribution schedule from G2A ───────────────────────────
    # Dates: financial_close is the project-owned canonical anchor.
    # Period k draws on financial_close + (k-1) months.
    financial_close: date = info.financial_close

    construction_periods_by_index: dict[int, ConstructionFundingPeriod] = {
        p.period_index: p for p in financing.construction_funding.periods
    }

    # ── Map model periods ─────────────────────────────────────────────────────
    # Construction period draw dates
    construction_draw_periods = sorted(construction_periods_by_index.keys())

    # SHL schedule (may be None for EQUITY_ONLY)
    shl = model_result.shareholder_loan

    shl_cash_interest_by_idx: dict[int, float] = {}
    shl_principal_by_idx: dict[int, float] = {}
    shl_debt_service_by_idx: dict[int, float] = {}
    shl_opening_by_idx: dict[int, float] = {}
    shl_pik_by_idx: dict[int, float] = {}

    is_bullet = False
    shl_maturity_idx: int | None = None

    # Independently-derived canonical axes (Correction C / TASK 1):
    #   expected_full_axis — all model period indices from model_result.periods
    expected_full_axis: tuple[int, ...] = tuple(
        p.period_index for p in model_result.periods
    )

    if shl is not None:
        senior_contract = build_senior_debt_model_input_from_project_inputs(
            project_inputs
        )
        senior_last_period_index = (
            senior_contract.senior_debt_policy.maturity_period_index
        )
        shl_contract = _build_shareholder_loan_model_input_from_project_inputs(
            project_inputs,
            model_result.periods,
            senior_debt_maturity_period_index=senior_last_period_index,
        )
        if shl_contract is None:
            raise ValueError("G2B: canonical SHL schedule exists without typed SHL contract")
        is_bullet = shl_contract.repayment_mode == ShlRepaymentMode.BULLET
        shl_maturity_idx = shl_contract.maturity_period_index if is_bullet else None
        # SHL schedule axis must match the full canonical period axis (Rule 4).
        # shl.period_indices was validated against full_axis by the orchestrator.
        shl_cash_interest_by_idx = map_period_vector(
            shl.period_indices, shl.shl_cash_interest_keur,
            label="sponsor_returns.shl_cash_interest",
            expected_indices=expected_full_axis,
        )
        shl_principal_by_idx = map_period_vector(
            shl.period_indices, shl.shl_principal_keur,
            label="sponsor_returns.shl_principal",
            expected_indices=expected_full_axis,
        )
        shl_debt_service_by_idx = map_period_vector(
            shl.period_indices, shl.shl_debt_service_keur,
            label="sponsor_returns.shl_debt_service",
            expected_indices=expected_full_axis,
        )
        shl_opening_by_idx = map_period_vector(
            shl.period_indices, shl.shl_opening_keur,
            label="sponsor_returns.shl_opening",
            expected_indices=expected_full_axis,
        )
        shl_pik_by_idx = map_period_vector(
            shl.period_indices, shl.shl_pik_interest_keur,
            label="sponsor_returns.shl_pik",
            expected_indices=expected_full_axis,
        )

    # Signed post-Senior cash authority (G2B uses the SIGNED field, not the floored one).
    # Negative = CFADS insufficient to cover Senior debt service.
    # This preserves cash deficits so shortfall remains visible rather than silently zeroed.
    if model_result.post_senior_cash is None:
        raise ValueError("G2B requires post_senior_cash; clean engine did not produce it")
    signed_post_senior_by_idx: dict[int, float] = map_period_vector(
        model_result.post_senior_cash.period_indices,
        model_result.post_senior_cash.cash_after_senior_before_reserves_keur,
        label="sponsor_returns.post_senior_cash",
        expected_indices=expected_full_axis,
    )

    # Dates for operating periods
    period_date_by_idx: dict[int, date] = {
        p.period_index: p.period_end
        for p in model_result.periods
    }

    # ── Build per-period cashflow records ─────────────────────────────────────
    cashflow_periods: list[SponsorCashFlowPeriod] = []

    # BULLET fail-closed state: once the contractual balloon is underfunded at
    # maturity this flag latches True. Subsequent periods: distribution = 0.
    # No default interest, no sponsor top-up, no post-maturity SHL terms invented.
    bullet_unpaid_active: bool = False

    # --- Construction periods (contributions only) ---
    for k in construction_draw_periods:
        cp = construction_periods_by_index[k]
        # Fix 3 / Step 9: use canonical cashflow_date from ConstructionFundingPeriod when
        # available (populated in explicit mode from model period dates). Fall back to the
        # legacy FC + (k-1) months formula only when cashflow_date is None.
        if cp.cashflow_date is not None:
            cf_date = cp.cashflow_date
        else:
            cf_date = _construction_period_date(financial_close, k)

        share_cap = cp.share_capital_draw_keur
        share_prem = cp.share_premium_draw_keur
        other_committed = cp.other_committed_equity_draw_keur
        add_eq = cp.additional_equity_draw_keur
        # Fix 3 / BLOCKER 1: always use Layer B (sponsor_shl_cash_contribution_keur) for G2B
        # sponsor cashflows. In stack.py this is always populated:
        #   - Legacy/PRO_RATA: contribution == allocation (shl_cash_draw_keur).
        #   - ALL_AT_FC explicit: contribution = [principal, 0, 0]; allocation = [alloc0, alloc1, ...].
        # Using the contribution field directly gives correct sponsor cashflow timing for all paths.
        shl_draw = cp.sponsor_shl_cash_contribution_keur

        pure_equity_net = -(share_cap + share_prem + other_committed + add_eq)
        total_sponsor_net = pure_equity_net - shl_draw

        cashflow_periods.append(SponsorCashFlowPeriod(
            period_index=k,
            cashflow_date=cf_date,
            is_construction=True,
            share_capital_contribution_keur=share_cap,
            share_premium_contribution_keur=share_prem,
            other_committed_equity_contribution_keur=other_committed,
            additional_equity_contribution_keur=add_eq,
            shl_cash_contribution_keur=shl_draw,
            shl_cash_interest_receipt_keur=0.0,
            shl_principal_receipt_keur=0.0,
            post_shl_cash_available_keur=0.0,
            legal_equity_distribution_keur=0.0,
            cash_shortfall_keur=0.0,
            pure_equity_net_cashflow_keur=pure_equity_net,
            total_sponsor_net_cashflow_keur=total_sponsor_net,
        ))

    # --- Operating periods (receipts and distributions) ---
    for period in model_result.periods:
        if not period.is_operation:
            continue
        idx = period.period_index
        cf_date = period_date_by_idx[idx]

        # Signed post-Senior cash — fail closed if the period is missing.
        # The post_senior_cash schedule must cover all operating periods.
        if idx not in signed_post_senior_by_idx:
            raise ValueError(
                f"G2B: operating period {idx} absent from post_senior_cash schedule; "
                "clean engine output is incomplete"
            )
        signed_post_senior = signed_post_senior_by_idx[idx]

        # Canonical SHL vectors are actual cash payments. Contractual BULLET due is
        # a separate reporting/gating concept derived at the typed maturity only.
        #
        # SHL handshake (non-negative post-Senior, non-bullet case):
        #   When signed_post_senior >= 0 and shl_service_due <= available cash,
        #   signed_post_shl == cash_remaining_after_shl_before_reserves (within tolerance).
        #
        # Negative post-Senior case:
        #   SHL engine received max(0, post_senior) = 0, so shl_debt_service = 0.
        #   G2B retains the full negative signed_post_senior as the project cash deficit.
        if shl is not None:
            if idx not in shl_debt_service_by_idx:
                raise ValueError(
                    f"G2B: SHL schedule exists but operating period {idx} absent "
                    "from shl_debt_service; SHL engine output is incomplete"
                )
            actual_shl_cash_int = shl_cash_interest_by_idx.get(idx, 0.0)
            actual_shl_principal = shl_principal_by_idx.get(idx, 0.0)
            is_at_maturity = shl_maturity_idx is not None and idx == shl_maturity_idx
            contractual_principal_due = (
                shl_opening_by_idx.get(idx, 0.0) + shl_pik_by_idx.get(idx, 0.0)
                if is_bullet and is_at_maturity
                else actual_shl_principal
            )
            contractual_shl_service_due = actual_shl_cash_int + contractual_principal_due
        else:
            # EQUITY_ONLY: no SHL debt service or receipts
            contractual_shl_service_due = 0.0
            contractual_principal_due = 0.0
            actual_shl_cash_int = 0.0
            actual_shl_principal = 0.0
            is_at_maturity = False

        # Contractual signed_post_shl drives distribution and shortfall.
        # No equity distribution while contractual SHL service is unpaid.
        signed_post_shl = signed_post_senior - contractual_shl_service_due
        post_shl_available = max(0.0, signed_post_shl)
        cash_shortfall = max(0.0, -signed_post_shl)

        # BULLET fail-closed: detect underfunded balloon at contractual maturity.
        if is_at_maturity and shl is not None:
            unpaid_principal = contractual_principal_due - actual_shl_principal
            if unpaid_principal > 1e-6:
                bullet_unpaid_active = True

        # Post-maturity legal-equity distributions are zero when balloon was
        # underfunded. The SHL liability is NOT extinguished; no terms invented.
        if bullet_unpaid_active and not is_at_maturity:
            distribution = 0.0
        else:
            distribution = post_shl_available  # DISTRIBUTE_ALL_POST_SHL_CASH

        pure_equity_net = distribution
        total_sponsor_net = (
            pure_equity_net
            + actual_shl_cash_int
            + actual_shl_principal
        )

        cashflow_periods.append(SponsorCashFlowPeriod(
            period_index=idx,
            cashflow_date=cf_date,
            is_construction=False,
            share_capital_contribution_keur=0.0,
            share_premium_contribution_keur=0.0,
            other_committed_equity_contribution_keur=0.0,
            additional_equity_contribution_keur=0.0,
            shl_cash_contribution_keur=0.0,
            shl_cash_interest_receipt_keur=actual_shl_cash_int,
            shl_principal_receipt_keur=actual_shl_principal,
            post_shl_cash_available_keur=post_shl_available,
            legal_equity_distribution_keur=distribution,
            cash_shortfall_keur=cash_shortfall,
            pure_equity_net_cashflow_keur=pure_equity_net,
            total_sponsor_net_cashflow_keur=total_sponsor_net,
        ))

    # ── Aggregate totals ──────────────────────────────────────────────────────
    total_sc = sum(p.share_capital_contribution_keur for p in cashflow_periods)
    total_sp = sum(p.share_premium_contribution_keur for p in cashflow_periods)
    total_oce = sum(p.other_committed_equity_contribution_keur for p in cashflow_periods)
    total_ae = sum(p.additional_equity_contribution_keur for p in cashflow_periods)
    total_le = total_sc + total_sp + total_oce + total_ae
    total_shl_contrib = sum(p.shl_cash_contribution_keur for p in cashflow_periods)
    total_sponsor_contrib = total_le + total_shl_contrib

    total_shl_int_recd = sum(p.shl_cash_interest_receipt_keur for p in cashflow_periods)
    total_shl_prin_recd = sum(p.shl_principal_receipt_keur for p in cashflow_periods)
    total_distributions = sum(p.legal_equity_distribution_keur for p in cashflow_periods)
    total_sponsor_receipts = total_distributions + total_shl_int_recd + total_shl_prin_recd

    # ── Pure Equity XIRR / MOIC ───────────────────────────────────────────────
    pe_xirr: float | None
    pe_xirr_status: ReturnMetricStatus
    pe_moic: float | None
    pe_moic_status: ReturnMetricStatus
    ts_xirr: float | None
    ts_xirr_status: ReturnMetricStatus
    ts_moic: float | None
    ts_moic_status: ReturnMetricStatus

    if bullet_unpaid_active:
        # BULLET fail-closed: SHL liability not extinguished at maturity.
        # Metrics are undefined — unpaid principal means the project cannot be
        # valued as a going concern under this structure.
        pe_xirr = None
        pe_xirr_status = ReturnMetricStatus.UNPAID_SHL_AT_CONTRACTUAL_MATURITY
        pe_moic = None
        pe_moic_status = ReturnMetricStatus.UNPAID_SHL_AT_CONTRACTUAL_MATURITY
        ts_xirr = None
        ts_xirr_status = ReturnMetricStatus.UNPAID_SHL_AT_CONTRACTUAL_MATURITY
        ts_moic = None
        ts_moic_status = ReturnMetricStatus.UNPAID_SHL_AT_CONTRACTUAL_MATURITY
    else:
        pe_cfs = [p.pure_equity_net_cashflow_keur for p in cashflow_periods]
        pe_dates = [p.cashflow_date for p in cashflow_periods]

        pe_xirr = robust_xirr(pe_cfs, pe_dates)
        pe_xirr_status = _xirr_status(pe_cfs, pe_xirr)

        if total_le > 0.0:
            pos_pe = sum(cf for cf in pe_cfs if cf > 0)
            pe_moic = pos_pe / total_le
            pe_moic_status = ReturnMetricStatus.OK
        else:
            pe_moic = None
            pe_moic_status = ReturnMetricStatus.ZERO_CONTRIBUTION

        # ── Total Sponsor XIRR / MOIC ─────────────────────────────────────────
        ts_cfs = [p.total_sponsor_net_cashflow_keur for p in cashflow_periods]
        ts_dates = pe_dates  # same period dates

        ts_xirr = robust_xirr(ts_cfs, ts_dates)
        ts_xirr_status = _xirr_status(ts_cfs, ts_xirr)

        if total_sponsor_contrib > 0.0:
            pos_ts = sum(cf for cf in ts_cfs if cf > 0)
            ts_moic = pos_ts / total_sponsor_contrib
            ts_moic_status = ReturnMetricStatus.OK
        else:
            ts_moic = None
            ts_moic_status = ReturnMetricStatus.ZERO_CONTRIBUTION

    return SponsorReturnResult(
        financing_result=financing,
        distribution_policy=SponsorDistributionPolicy.DISTRIBUTE_ALL_POST_SHL_CASH,
        cashflow_periods=tuple(cashflow_periods),
        total_share_capital_contributed_keur=total_sc,
        total_share_premium_contributed_keur=total_sp,
        total_other_committed_equity_contributed_keur=total_oce,
        total_additional_equity_contributed_keur=total_ae,
        total_legal_equity_contributed_keur=total_le,
        total_shl_cash_contributed_keur=total_shl_contrib,
        total_sponsor_contributed_keur=total_sponsor_contrib,
        total_shl_cash_interest_received_keur=total_shl_int_recd,
        total_shl_principal_received_keur=total_shl_prin_recd,
        total_legal_equity_distributions_keur=total_distributions,
        total_sponsor_receipts_keur=total_sponsor_receipts,
        pure_equity_xirr=pe_xirr,
        pure_equity_xirr_status=pe_xirr_status,
        pure_equity_moic=pe_moic,
        pure_equity_moic_status=pe_moic_status,
        total_sponsor_xirr=ts_xirr,
        total_sponsor_xirr_status=ts_xirr_status,
        total_sponsor_moic=ts_moic,
        total_sponsor_moic_status=ts_moic_status,
        shl_bullet_unpaid_at_maturity=bullet_unpaid_active,
    )
