"""Phase 5A cash ledger adapters — map existing result types to cash movements.

Best-effort audit layer only. No financial outputs are changed.
These adapters read existing result types and emit CashMovement tuples.
"""
from __future__ import annotations

from typing import Any

from domain.portfolio.cash_ledger.inputs import CashMovement, CashMovementType


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Safely cast a value to float, rejecting bool and non-numeric types.

    MagicMock returns a Mock for any attribute, which is truthy and comparable
    to numbers but is not a real float. This helper guards against that.
    """
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def movements_from_holdco_result(
    holdco_result: Any,
) -> tuple[CashMovement, ...]:
    """Map HoldCoPeriodResult fields to CashMovement tuples.

    This is an audit/accounting mapping only.
    Does NOT change any HoldCo result fields.

    Mapping:
    - dividend_keur → OPERATING_CASHFLOW (positive, dividend income)
    - shl_interest_keur → SHL_INTEREST (positive, interest income)
    - shl_principal_keur → SHL_PRINCIPAL (positive, principal receipt)
    - holdco_opex_keur → HOLDCO_OPEX (negative, expense)
    - tax_keur → HOLDCO_TAX (negative, tax paid)
    - distribution_to_sponsor_keur → SPONSOR_DISTRIBUTION (negative, payout)
    """
    movements: list[CashMovement] = []
    for period_idx, period in enumerate(holdco_result.periods):
        entity = holdco_result.name or "HOLDCO"
        desc = f"HoldCo period {period_idx}"

        dividend = _safe_float(getattr(period, "dividend_keur", None))
        if dividend > 0:
            movements.append(CashMovement(
                period=period_idx,
                entity_code=entity,
                movement_type=CashMovementType.OPERATING_CASHFLOW,
                amount_keur=dividend,
                description=f"{desc} — dividend income from SPVs",
            ))

        shl_int = _safe_float(getattr(period, "shl_interest_keur", None))
        if shl_int > 0:
            movements.append(CashMovement(
                period=period_idx,
                entity_code=entity,
                movement_type=CashMovementType.SHL_INTEREST,
                amount_keur=shl_int,
                description=f"{desc} — SHL interest receipt",
            ))

        shl_principal = _safe_float(getattr(period, "shl_principal_keur", None))
        if shl_principal > 0:
            movements.append(CashMovement(
                period=period_idx,
                entity_code=entity,
                movement_type=CashMovementType.SHL_PRINCIPAL,
                amount_keur=shl_principal,
                description=f"{desc} — SHL principal receipt",
            ))

        opex = _safe_float(getattr(period, "holdco_opex_keur", None))
        if opex > 0:
            movements.append(CashMovement(
                period=period_idx,
                entity_code=entity,
                movement_type=CashMovementType.HOLDCO_OPEX,
                amount_keur=-opex,
                description=f"{desc} — HoldCo operating expense",
            ))

        tax = _safe_float(getattr(period, "tax_keur", None))
        if tax > 0:
            movements.append(CashMovement(
                period=period_idx,
                entity_code=entity,
                movement_type=CashMovementType.HOLDCO_TAX,
                amount_keur=-tax,
                description=f"{desc} — HoldCo tax",
            ))

        sponsor_dist = _safe_float(getattr(period, "distribution_to_sponsor_keur", None))
        if sponsor_dist > 0:
            movements.append(CashMovement(
                period=period_idx,
                entity_code=entity,
                movement_type=CashMovementType.SPONSOR_DISTRIBUTION,
                amount_keur=-sponsor_dist,
                description=f"{desc} — distribution to sponsor",
            ))

    return tuple(movements)


def movements_from_spv_output(
    spv_output: Any,
) -> tuple[CashMovement, ...]:
    """Map SPVOutput to CashMovement tuples.

    This is a best-effort audit mapping only.
    Does NOT modify SPVOutput.

    Mapping (conservative, prefer DSRF-adjusted if available):
    - adjusted_period_distributions_keur → EQUITY_DISTRIBUTION (negative, outflow)
    - shl_interest_keur from waterfall period → SHL_INTEREST (negative, outflow)
    - shl_principal_keur from waterfall period → SHL_PRINCIPAL (negative, outflow)
    """
    movements: list[CashMovement] = []
    entity = spv_output.project_code or "SPV"

    # Use safe float for all numeric reads
    adj_dists = spv_output.adjusted_period_distributions_keur
    wf = spv_output.waterfall_result

    if wf is not None and hasattr(wf, "periods") and wf.periods:
        for period_idx, wf_period in enumerate(wf.periods):
            desc = f"{entity} period {period_idx}"

            # Equity distribution: prefer adjusted (DSRF) over raw waterfall
            if adj_dists and period_idx < len(adj_dists):
                dist = _safe_float(adj_dists[period_idx])
                if dist > 0:
                    movements.append(CashMovement(
                        period=period_idx,
                        entity_code=entity,
                        movement_type=CashMovementType.EQUITY_DISTRIBUTION,
                        amount_keur=-dist,
                        description=f"{desc} — DSRF-adjusted equity distribution",
                    ))
            else:
                raw_dist = _safe_float(getattr(wf_period, "distribution_keur", None))
                if raw_dist > 0:
                    movements.append(CashMovement(
                        period=period_idx,
                        entity_code=entity,
                        movement_type=CashMovementType.EQUITY_DISTRIBUTION,
                        amount_keur=-raw_dist,
                        description=f"{desc} — raw equity distribution",
                    ))

            # SHL interest from waterfall period
            shl_int = _safe_float(getattr(wf_period, "shl_interest_keur", None))
            if shl_int > 0:
                movements.append(CashMovement(
                    period=period_idx,
                    entity_code=entity,
                    movement_type=CashMovementType.SHL_INTEREST,
                    amount_keur=-shl_int,
                    description=f"{desc} — SHL interest paid",
                ))

            # SHL principal from waterfall period
            shl_principal = _safe_float(getattr(wf_period, "shl_principal_keur", None))
            if shl_principal > 0:
                movements.append(CashMovement(
                    period=period_idx,
                    entity_code=entity,
                    movement_type=CashMovementType.SHL_PRINCIPAL,
                    amount_keur=-shl_principal,
                    description=f"{desc} — SHL principal repayment",
                ))
    else:
        # waterfall_result is None: emit equity distributions from adjusted_period_distributions_keur
        # if available (best-effort audit — e.g., SPV failed or non-strict mode)
        if adj_dists:
            for period_idx, raw_dist in enumerate(adj_dists):
                dist = _safe_float(raw_dist)
                if dist > 0:
                    movements.append(CashMovement(
                        period=period_idx,
                        entity_code=entity,
                        movement_type=CashMovementType.EQUITY_DISTRIBUTION,
                        amount_keur=-dist,
                        description=f"{entity} period {period_idx} — equity distribution (fallback)",
                    ))

    return tuple(movements)
