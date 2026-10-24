"""LCOS receipt specification (WF-08A, release-closed). SPECIFICATION ONLY — no LCOS arithmetic.

PR #362 (``research/wf09a``) already owns the isolated LCOE/LCOS arithmetic and is neither imported nor changed
here. This module only assembles the typed RECEIPTS a later, separately approved adapter would need, from the
native hourly evidence and a charging statement:

    gross charging purchase cost, auxiliary purchase cost, grid-fee receipts, delivered AC discharge MWh,
    operating-cost receipt, optional augmentation investment receipt, methodology reference, evidence identities.

Anything not independently known — a NET_SPREAD basis, a missing receipt, a missing methodology reference —
yields UNAVAILABLE with the reasons, never a zero and never an estimate. Receipt units are kEUR and MWh as in the
native settlement proposals.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from app.bess_commercial_candidate.charging import ChargingStatement, LegKind
from app.bess_commercial_candidate.contracts import (
    exact_arithmetic,
    CANDIDATE, UNAVAILABLE, BessCommercialError, ChargingBasis, dec, ident, opt_dec, opt_ident, reconciles,
    require_release, tuple_of,
)


@dataclass(frozen=True)
class LcosReceiptSet:
    status: str
    reasons: tuple
    period_id: str
    basis: ChargingBasis
    gross_charging_purchase_keur: Optional[Decimal]
    auxiliary_purchase_keur: Optional[Decimal]
    grid_fee_receipts_keur: Optional[Decimal]
    delivered_ac_discharge_mwh: Optional[Decimal]
    operating_cost_keur: Optional[Decimal]
    augmentation_investment_keur: Optional[Decimal]
    methodology_ref: Optional[str]
    evidence_ids: tuple
    lcos_arithmetic_performed: bool = False


@exact_arithmetic
def build_lcos_receipts(statement: ChargingStatement, native_hours, *, operating_cost_keur: Optional[Decimal],
                        operating_cost_ref: Optional[str], methodology_ref: Optional[str],
                        augmentation_investment_keur: Optional[Decimal] = None,
                        augmentation_receipt_ref: Optional[str] = None) -> LcosReceiptSet:
    require_release()
    opt_dec(operating_cost_keur, "operating_cost_keur", nonnegative=True)
    opt_dec(augmentation_investment_keur, "augmentation_investment_keur", nonnegative=True)
    opt_ident(operating_cost_ref, "operating_cost_ref")
    opt_ident(methodology_ref, "methodology_ref")
    opt_ident(augmentation_receipt_ref, "augmentation_receipt_ref")
    if (operating_cost_keur is None) != (operating_cost_ref is None):
        raise BessCommercialError("BESS_COMMERCIAL_SCHEMA: an operating-cost receipt and its reference come together")
    if (augmentation_investment_keur is None) != (augmentation_receipt_ref is None):
        raise BessCommercialError(
            "BESS_COMMERCIAL_SCHEMA: an augmentation investment receipt and its reference come together")
    hours = tuple_of(native_hours, "native_hours")
    reasons = []
    if statement.basis is ChargingBasis.NET_SPREAD:
        reasons.append("NET_SPREAD basis: the gross charging purchase cost is not independently known")
    if statement.status != CANDIDATE:
        reasons.append("charging statement is UNAVAILABLE: " + statement.reason)
    if not hours:
        reasons.append("native hourly evidence missing")
    if operating_cost_keur is None:
        reasons.append("operating-cost receipt missing")
    if methodology_ref is None:
        reasons.append("approved LCOS methodology / denominator convention reference missing")

    delivered = sum((dec(h.ac_discharge_mwh, "ac_discharge_mwh", nonnegative=True) for h in hours), Decimal(0)) \
        if hours else None
    gross = auxiliary = fees = None
    ids = [statement.evidence_id]
    if statement.basis is ChargingBasis.EXPLICIT_BUY_LEG and statement.status == CANDIDATE:
        by = {line.kind: line for line in statement.lines}
        gross = by[LegKind.CHARGING_PURCHASE.value].amount_keur
        auxiliary = by[LegKind.AUXILIARY_PURCHASE.value].amount_keur
        fees = by[LegKind.GRID_IMPORT_CHARGE.value].amount_keur + by[LegKind.GRID_EXPORT_CHARGE.value].amount_keur
        ids += [line.line_id for line in statement.lines]
        if delivered is not None and not reconciles(statement.grid_export_mwh, delivered):
            raise BessCommercialError(
                "BESS_COMMERCIAL_RECONCILIATION: delivered AC discharge differs from the statement's grid export")
    for ref in (operating_cost_ref, augmentation_receipt_ref):
        if ref is not None:
            ids.append(ref)
    status = UNAVAILABLE if reasons else CANDIDATE
    return LcosReceiptSet(status, tuple(reasons), statement.period_id, statement.basis, gross, auxiliary, fees,
                          delivered, operating_cost_keur, augmentation_investment_keur, methodology_ref, tuple(ids))
