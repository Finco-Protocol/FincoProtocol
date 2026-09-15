"""financial_engine.dsra.model — Canonical CASH_DSRA roll-forward engine.

Pure computation. No imports from app, legacy waterfall, project factories,
Excel fixtures, or diagnostic scripts. No project-name dispatch.

Ordering (CASH_DSRA, per operating period):
    opening  = requirement_keur at first operating period (COD handshake)
               or prior closing_balance for subsequent periods
    top_up   = min(max(0, target - opening), max(0, cash_before))
    release  = max(0, opening - target)
    draw     = min(opening - release, max(0, -cash_before)) [when cash_before < 0]
    closing  = opening + top_up - draw - release
    cash_after = cash_before - top_up + draw + release

Cash conservation:  cash_before - top_up + draw + release == cash_after
Balance conservation: opening + top_up - draw - release == closing
"""
from __future__ import annotations

from finco_core.inputs import DebtServiceReserveSupportMode

from financial_engine.dsra.contracts import (
    CashDsraInput,
    CashDsraPeriodResult,
    CashDsraSchedules,
)
from financial_engine.results import OperatingPeriodResult, PostSeniorCashSchedules

_FLOAT_TOLERANCE = 1e-9


def run_cash_dsra_model(
    post_senior_cash: PostSeniorCashSchedules,
    dsra_input: CashDsraInput | None,
    periods: tuple[OperatingPeriodResult, ...],
) -> CashDsraSchedules:
    """Compute CASH_DSRA roll-forward from signed post-Senior cash.

    Parameters
    ----------
    post_senior_cash:
        Pre-reserve Phase 2C output. cash_after_senior_before_reserves_keur
        is the signed per-period cash BEFORE any DSRA adjustment.
    dsra_input:
        Typed reserve policy. None treated as NONE mode (neutral).
    periods:
        All model periods (construction + operating) from Phase 2B result.
        Used to identify is_construction per period_index.

    Returns
    -------
    CashDsraSchedules with per-period roll-forward and aggregate diagnostics.
    """
    if dsra_input is None:
        dsra_input = CashDsraInput(mode=DebtServiceReserveSupportMode.NONE, requirement_keur=0.0)

    from financial_engine.dsra.target import DsraTargetPolicy
    mode = dsra_input.mode
    req = dsra_input.requirement_keur
    balance_schedule = dsra_input.required_balance_schedule
    policy = dsra_input.target_policy

    # Policy / schedule authority enforcement — fail closed on mismatches.
    n_periods = len(post_senior_cash.period_indices)
    if policy == DsraTargetPolicy.FORWARD_DEBT_SERVICE_MONTHS:
        if balance_schedule is None:
            raise ValueError(
                "CASH_DSRA_DYNAMIC_TARGET_SCHEDULE_REQUIRED: "
                "target_policy=FORWARD_DEBT_SERVICE_MONTHS but required_balance_schedule is None. "
                "The orchestrator must build the dynamic schedule from the final Senior DS "
                "schedule before calling run_cash_dsra_model()."
            )
    elif policy == DsraTargetPolicy.FIXED_AMOUNT:
        if balance_schedule is not None:
            raise ValueError(
                "CASH_DSRA_FIXED_AMOUNT_AUTHORITY_CONFLICT: "
                "target_policy=FIXED_AMOUNT but required_balance_schedule is also provided. "
                "Exactly one target authority is allowed. "
                "Either set target_policy=FORWARD_DEBT_SERVICE_MONTHS or clear the schedule."
            )
    if balance_schedule is not None and len(balance_schedule) != n_periods:
        raise ValueError(
            f"CASH_DSRA_SCHEDULE_LENGTH_MISMATCH: required_balance_schedule length "
            f"{len(balance_schedule)} != period_indices length {n_periods}."
        )

    if mode == DebtServiceReserveSupportMode.NONE and req > _FLOAT_TOLERANCE:
        raise ValueError(
            "CASH_DSRA_NONE_MODE_WITH_POSITIVE_REQUIREMENT: "
            f"dsra_input.mode=NONE but requirement_keur={req}. "
            "Set requirement_keur=0.0 or change mode to CASH_DSRA."
        )

    is_constr_by_idx: dict[int, bool] = {p.period_index: p.is_construction for p in periods}
    period_indices = post_senior_cash.period_indices
    cash_before_all = post_senior_cash.cash_after_senior_before_reserves_keur

    period_results: list[CashDsraPeriodResult] = []
    total_top_up = 0.0
    total_draw = 0.0
    total_release = 0.0

    if mode in (DebtServiceReserveSupportMode.NONE, DebtServiceReserveSupportMode.DSRF):
        # Neutral pass-through for all periods — no reserve movements.
        for idx, cash_before in zip(period_indices, cash_before_all):
            is_constr = is_constr_by_idx.get(idx, False)
            period_results.append(_neutral_period(idx, is_constr, cash_before, 0.0))
    else:
        # CASH_DSRA: roll-forward for operating periods, neutral for construction.
        prev_closing = 0.0
        first_op_seen = False

        for period_pos, (idx, cash_before) in enumerate(zip(period_indices, cash_before_all)):
            is_constr = is_constr_by_idx.get(idx, False)

            if is_constr:
                # Construction: reserve not yet funded; all movements zero.
                # required_balance shown as 0 (construction target is always 0).
                period_results.append(CashDsraPeriodResult(
                    period_index=idx,
                    is_construction=True,
                    opening_balance_keur=0.0,
                    required_balance_keur=0.0,
                    cash_before_dsra_keur=cash_before,
                    draw_to_cover_shortfall_keur=0.0,
                    top_up_keur=0.0,
                    release_keur=0.0,
                    closing_balance_keur=0.0,
                    cash_after_dsra_keur=cash_before,
                    shortfall_keur=0.0,
                    target_met=True,
                ))
                continue

            # Operating period
            # Per-period target: dynamic schedule if provided, else static scalar.
            target = balance_schedule[period_pos] if balance_schedule is not None else req

            if not first_op_seen:
                # COD funding handshake: opening is actual reserve cash funded as
                # a Project Use. The dynamic schedule is target evidence only.
                opening = req
                first_op_seen = True
            else:
                opening = prev_closing

            # Source CF Operation row releases the amount by which Beginning
            # exceeds Target. A target change cannot itself create cash: only
            # previously funded reserve cash can be released.
            release = max(0.0, opening - target)
            balance_after_release = opening - release

            if cash_before >= 0.0:
                top_up = min(max(0.0, target - opening), cash_before)
                draw = 0.0
            else:
                # Negative post-Senior cash: draw from reserve to cover shortfall.
                if release > _FLOAT_TOLERANCE and -cash_before > balance_after_release + _FLOAT_TOLERANCE:
                    raise ValueError(
                        "DSRA_SIMULTANEOUS_EXCESS_RELEASE_AND_SHORTFALL_POLICY_UNRESOLVED: "
                        "workbook Operation release plus Shortfall would produce a negative "
                        "reserve balance. The clean engine fails closed instead of silently "
                        "claiming source parity."
                    )
                draw = min(balance_after_release, -cash_before)
                top_up = 0.0

            closing = opening + top_up - draw - release
            cash_after = cash_before - top_up + draw + release
            shortfall = max(0.0, target - closing)
            target_met = closing >= target - _FLOAT_TOLERANCE

            total_top_up += top_up
            total_draw += draw
            total_release += release
            prev_closing = closing

            period_results.append(CashDsraPeriodResult(
                period_index=idx,
                is_construction=False,
                opening_balance_keur=opening,
                required_balance_keur=target,
                cash_before_dsra_keur=cash_before,
                draw_to_cover_shortfall_keur=draw,
                top_up_keur=top_up,
                release_keur=release,
                closing_balance_keur=closing,
                cash_after_dsra_keur=cash_after,
                shortfall_keur=shortfall,
                target_met=target_met,
            ))

    diagnostics = _build_diagnostics(mode, req, has_dynamic_schedule=balance_schedule is not None)
    final_closing = period_results[-1].closing_balance_keur if period_results else 0.0

    return CashDsraSchedules(
        mode=mode.value,
        requirement_keur=req,
        period_results=tuple(period_results),
        total_top_up_keur=total_top_up,
        total_draw_keur=total_draw,
        total_release_keur=total_release,
        final_closing_balance_keur=final_closing,
        diagnostics=tuple(diagnostics),
    )


def _neutral_period(
    period_index: int,
    is_construction: bool,
    cash_before: float,
    requirement_keur: float,
) -> CashDsraPeriodResult:
    """Return a zero-movement period result (NONE / DSRF mode or construction pass-through)."""
    return CashDsraPeriodResult(
        period_index=period_index,
        is_construction=is_construction,
        opening_balance_keur=0.0,
        required_balance_keur=0.0,
        cash_before_dsra_keur=cash_before,
        draw_to_cover_shortfall_keur=0.0,
        top_up_keur=0.0,
        release_keur=0.0,
        closing_balance_keur=0.0,
        cash_after_dsra_keur=cash_before,
        shortfall_keur=0.0,
        target_met=True,
    )


def _build_diagnostics(
    mode: DebtServiceReserveSupportMode,
    req: float,
    has_dynamic_schedule: bool = False,
) -> list[str]:
    diags: list[str] = []
    if mode == DebtServiceReserveSupportMode.NONE:
        diags.append("DSRA_NONE_NEUTRAL_PASS_THROUGH: all reserve movements zero")
    elif mode == DebtServiceReserveSupportMode.DSRF:
        diags.append(
            "DSRF_FEE_ENGINE_NOT_HERE: DSRF commitment fee handled by "
            "financial_engine.financing.dsrf; no DSRA draw engine added"
        )
        diags.append("CASH_DSRA_ROLL_FORWARD_NOT_APPLICABLE_FOR_DSRF_MODE: pass-through only")
    elif mode == DebtServiceReserveSupportMode.CASH_DSRA:
        diags.append(
            "CASH_DSRA_SOURCE_PROVEN_EXCESS_RELEASE: when opening balance exceeds "
            "target, release_keur equals "
            "opening minus target."
        )
        if has_dynamic_schedule:
            diags.append(
                "COD_FUNDING_HANDSHAKE: opening_balance at first operating period "
                f"= {req} kEUR = requirement_keur funded as a Project Use; "
                "required_balance_schedule supplies target evidence only"
            )
        else:
            diags.append(
                f"COD_FUNDING_HANDSHAKE: opening_balance at first operating period "
                f"= {req} kEUR = debt_service_reserve_requirement_keur "
                f"(funded as Project Use at construction close)"
            )
        if has_dynamic_schedule:
            diags.append(
                "CASH_DSRA_TARGET_AUTHORITY: FORWARD_DEBT_SERVICE_MONTHS dynamic schedule "
                "(required_balance_schedule provided via DsraTargetPolicy). "
                "The schedule does not fund or overwrite COD opening cash."
            )
        else:
            diags.append(
                "CASH_DSRA_TARGET_AUTHORITY: FIXED_AMOUNT static scalar requirement_keur. "
                "dsra_months NOT consumed — no required_balance_schedule provided."
            )
    return diags
