"""Charging-cost semantics: NET_SPREAD vs EXPLICIT_BUY_LEG (WF-08A, release-closed).

Two economically distinct bases, never mixed:

- ``NET_SPREAD``: the quoted price ALREADY is a net arbitrage spread. The gross
  charging purchase cost is not independently known, so it is reported as
  MISSING (``None``) and no charging cost is ever deducted or reconstructed.
- ``EXPLICIT_BUY_LEG``: independently reported gross sale and purchase receipts
  (charging purchase, auxiliary purchase, grid import/export charges), as the
  native hourly engine settles them. Charging cost is deducted exactly once.

Native units are kept: MWh, EUR/MWh, kEUR. The candidate reads the existing
native receipts (``FinancialPeriodProposal`` / ``HourEvidence``) and never
recomputes battery physics or round-trip losses.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional

from app.bess_commercial_candidate.contracts import (
    exact_arithmetic,
    CANDIDATE, UNAVAILABLE, BessCommercialError, ChargingBasis, dec, enum_member,
    ident, opt_dec, reconciles, require_release, tuple_of, unique,
)


class LegKind(str, Enum):
    GROSS_SALE = "GROSS_SALE"
    CHARGING_PURCHASE = "CHARGING_PURCHASE"
    AUXILIARY_PURCHASE = "AUXILIARY_PURCHASE"
    GRID_IMPORT_CHARGE = "GRID_IMPORT_CHARGE"
    GRID_EXPORT_CHARGE = "GRID_EXPORT_CHARGE"


_REVENUE = (LegKind.GROSS_SALE,)
_ALL_LEGS = tuple(LegKind)


@dataclass(frozen=True)
class ReceiptLeg:
    """One independently reported receipt/expense. ``amount_keur`` None = MISSING."""

    kind: LegKind
    receipt_id: str
    amount_keur: Optional[Decimal]

    def __post_init__(self):
        enum_member(self.kind, LegKind, "leg kind")
        ident(self.receipt_id, "receipt_id")
        opt_dec(self.amount_keur, f"{self.kind.value} amount_keur", nonnegative=True)


@dataclass(frozen=True)
class ChargingPeriod:
    """Charging-economics input for ONE aligned period."""

    period_id: str
    basis: ChargingBasis
    evidence_id: str
    legs: tuple = ()
    spread_eur_mwh: Optional[Decimal] = None
    delivered_mwh: Optional[Decimal] = None
    grid_import_mwh: Optional[Decimal] = None
    grid_export_mwh: Optional[Decimal] = None

    def __post_init__(self):
        ident(self.period_id, "period_id")
        ident(self.evidence_id, "evidence_id")
        enum_member(self.basis, ChargingBasis, "charging basis")
        tuple_of(self.legs, "legs")
        opt_dec(self.spread_eur_mwh, "spread_eur_mwh")  # a spread may be negative; zero is legitimate
        opt_dec(self.delivered_mwh, "delivered_mwh", nonnegative=True)
        opt_dec(self.grid_import_mwh, "grid_import_mwh", nonnegative=True)
        opt_dec(self.grid_export_mwh, "grid_export_mwh", nonnegative=True)
        if self.basis is ChargingBasis.NET_SPREAD:
            if self.legs or self.grid_import_mwh is not None or self.grid_export_mwh is not None:
                raise BessCommercialError(
                    "BESS_COMMERCIAL_MIXED_BASIS: NET_SPREAD carries no gross sale/purchase legs or grid "
                    "quantities; a charging cost is never reconstructed from a net spread")
        else:
            if self.spread_eur_mwh is not None or self.delivered_mwh is not None:
                raise BessCommercialError(
                    "BESS_COMMERCIAL_MIXED_BASIS: EXPLICIT_BUY_LEG carries independently reported receipts "
                    "only; a net spread price would double-count the charging cost")
            kinds = [leg.kind for leg in self.legs]
            if sorted(k.value for k in kinds) != sorted(k.value for k in _ALL_LEGS):
                raise BessCommercialError(
                    "BESS_COMMERCIAL_SCHEMA: EXPLICIT_BUY_LEG requires exactly one leg of each kind "
                    f"{[k.value for k in _ALL_LEGS]} (a missing amount is None, not an omitted leg)")
            for leg in self.legs:
                if not isinstance(leg, ReceiptLeg):
                    raise BessCommercialError("BESS_COMMERCIAL_SCHEMA: legs must be ReceiptLeg")
        unique([leg.receipt_id for leg in self.legs], "receipt_id")


@dataclass(frozen=True)
class StatementLine:
    line_id: str
    side: str          # REVENUE | COST
    kind: str
    amount_keur: Decimal


@dataclass(frozen=True)
class ChargingStatement:
    status: str
    reason: str
    period_id: str
    basis: ChargingBasis
    evidence_id: str
    lines: tuple
    net_contribution_keur: Optional[Decimal]
    gross_charging_cost_keur: Optional[Decimal]
    charging_cost_deductions: int
    grid_import_mwh: Optional[Decimal]
    grid_export_mwh: Optional[Decimal]
    delivered_mwh: Optional[Decimal] = None   # NET_SPREAD only: AC MWh the quoted spread applies to


def _unavailable(period: ChargingPeriod, reason: str) -> ChargingStatement:
    return ChargingStatement(UNAVAILABLE, reason, period.period_id, period.basis, period.evidence_id,
                             (), None, None, 0, None, None)


@exact_arithmetic
def charging_statement(period: ChargingPeriod) -> ChargingStatement:
    """Resolve one period under its declared basis; missing evidence is UNAVAILABLE."""
    require_release()
    if period.basis is ChargingBasis.NET_SPREAD:
        if period.spread_eur_mwh is None or period.delivered_mwh is None:
            return _unavailable(period, "missing net-spread price or delivered MWh evidence (missing is not zero)")
        net = period.spread_eur_mwh * period.delivered_mwh / 1000
        line = StatementLine(f"{period.evidence_id}:NET_SPREAD", "REVENUE", "NET_SPREAD_CONTRIBUTION", net)
        # gross charging cost is NOT independently known: reported as None, never invented
        return ChargingStatement(CANDIDATE, "net spread; no gross charging cost is known or deducted",
                                 period.period_id, period.basis, period.evidence_id, (line,), net, None, 0,
                                 None, None, period.delivered_mwh)
    missing = [leg.kind.value for leg in period.legs if leg.amount_keur is None]
    if missing or period.grid_import_mwh is None or period.grid_export_mwh is None:
        return _unavailable(period, "missing explicit receipt/quantity evidence: "
                            + ", ".join(missing + [n for n, v in (("grid_import_mwh", period.grid_import_mwh),
                                                                 ("grid_export_mwh", period.grid_export_mwh)) if v is None]))
    lines, net, charging = [], Decimal(0), Decimal(0)
    for leg in period.legs:
        revenue = leg.kind in _REVENUE
        lines.append(StatementLine(leg.receipt_id, "REVENUE" if revenue else "COST", leg.kind.value, leg.amount_keur))
        net += leg.amount_keur if revenue else -leg.amount_keur
        if leg.kind in (LegKind.CHARGING_PURCHASE, LegKind.AUXILIARY_PURCHASE):
            charging += leg.amount_keur
    return ChargingStatement(CANDIDATE, "explicit buy leg; charging cost deducted exactly once", period.period_id,
                             period.basis, period.evidence_id, tuple(lines), net, charging, 1,
                             period.grid_import_mwh, period.grid_export_mwh)


@exact_arithmetic
def charging_book(periods) -> tuple:
    """Statements for several periods with cross-period double-count guards.

    One basis per period; every period id, evidence id and receipt id is unique, so the same source
    amount or the same period can never be counted under two bases or twice.
    """
    require_release()
    periods = tuple_of(periods, "periods")
    for period in periods:
        if not isinstance(period, ChargingPeriod):
            raise BessCommercialError("BESS_COMMERCIAL_SCHEMA: ChargingPeriod required")
    unique([p.period_id for p in periods], "period_id (a period cannot be settled under two bases)")
    unique([p.evidence_id for p in periods], "evidence_id")
    unique([leg.receipt_id for p in periods for leg in p.legs], "receipt_id")
    return tuple(charging_statement(p) for p in periods)


# ── Native evidence adapters (read-only; no physics) ─────────────────────────


@exact_arithmetic
def native_charging_period(proposal, period_id: str, evidence_id: str) -> ChargingPeriod:
    """EXPLICIT_BUY_LEG period from a native ``FinancialPeriodProposal`` (existing receipts, existing units).

    The native net merchant contribution must equal gross sale minus the four cost legs; otherwise the
    receipts are inconsistent and the period fails closed.
    """
    require_release()
    ident(period_id, "period_id")
    ident(evidence_id, "evidence_id")
    values = {
        LegKind.GROSS_SALE: proposal.gross_sale_revenue_keur,
        LegKind.CHARGING_PURCHASE: proposal.charging_purchase_cost_keur,
        LegKind.AUXILIARY_PURCHASE: proposal.auxiliary_purchase_cost_keur,
        LegKind.GRID_IMPORT_CHARGE: proposal.import_charges_keur,
        LegKind.GRID_EXPORT_CHARGE: proposal.export_charges_keur,
    }
    legs = tuple(ReceiptLeg(kind, f"{evidence_id}:{kind.value}", dec(v, kind.value, nonnegative=True))
                 for kind, v in values.items())
    net = values[LegKind.GROSS_SALE] - sum((values[k] for k in _ALL_LEGS[1:]), Decimal(0))
    if not reconciles(net, dec(proposal.net_merchant_contribution_keur, "net_merchant_contribution_keur")):
        raise BessCommercialError(
            "BESS_COMMERCIAL_RECONCILIATION: native net merchant contribution does not equal gross sale "
            "minus the reported cost legs")
    return ChargingPeriod(period_id, ChargingBasis.EXPLICIT_BUY_LEG, evidence_id, legs, None, None,
                          dec(proposal.grid_import_mwh, "grid_import_mwh", nonnegative=True),
                          dec(proposal.grid_export_mwh, "grid_export_mwh", nonnegative=True))


@exact_arithmetic
def native_net_spread_period(period_id: str, evidence_id: str, spread_eur_mwh: Optional[Decimal],
                             hours) -> ChargingPeriod:
    """NET_SPREAD period whose delivered MWh comes from native hourly evidence (AC discharge)."""
    require_release()
    delivered = sum((dec(h.ac_discharge_mwh, "ac_discharge_mwh", nonnegative=True) for h in hours), Decimal(0))
    return ChargingPeriod(period_id, ChargingBasis.NET_SPREAD, evidence_id, (), spread_eur_mwh, delivered)


@exact_arithmetic
def reconcile_with_native_hours(statement: ChargingStatement, hours) -> ChargingStatement:
    """Reconcile a statement against the native hourly evidence for exactly its period.

    EXPLICIT_BUY_LEG: grid import/export MWh and every receipt leg must equal the hourly sums.
    NET_SPREAD: delivered AC MWh must equal the hourly AC discharge; gross legs are not checkable
    because they are not independently known (reported, never invented).
    """
    require_release()
    if statement.status != CANDIDATE:
        raise BessCommercialError("BESS_COMMERCIAL_RECONCILIATION: only a CANDIDATE statement can be reconciled")
    hours = tuple(hours)
    if not hours:
        raise BessCommercialError("BESS_COMMERCIAL_RECONCILIATION: native hourly evidence required")

    def total(field):
        return sum((getattr(h, field) for h in hours), Decimal(0))

    if statement.basis is ChargingBasis.NET_SPREAD:
        if not reconciles(statement.delivered_mwh, total("ac_discharge_mwh")):
            raise BessCommercialError(
                "BESS_COMMERCIAL_RECONCILIATION: delivered MWh differs from native AC discharge")
        return statement
    checks = (("grid_import_mwh", statement.grid_import_mwh, "grid_import_mwh"),
              ("grid_export_mwh", statement.grid_export_mwh, "grid_export_mwh"))
    for label, claimed, field in checks:
        if not reconciles(claimed, total(field)):
            raise BessCommercialError(f"BESS_COMMERCIAL_RECONCILIATION: {label} differs from native hourly evidence")
    native_fields = {
        LegKind.GROSS_SALE.value: "gross_sale_revenue_keur",
        LegKind.CHARGING_PURCHASE.value: "charging_purchase_cost_keur",
        LegKind.AUXILIARY_PURCHASE.value: "auxiliary_purchase_cost_keur",
        LegKind.GRID_IMPORT_CHARGE.value: "grid_import_charge_keur",
        LegKind.GRID_EXPORT_CHARGE.value: "grid_export_charge_keur",
    }
    for line in statement.lines:
        if not reconciles(line.amount_keur, total(native_fields[line.kind])):
            raise BessCommercialError(
                f"BESS_COMMERCIAL_RECONCILIATION: {line.kind} differs from native hourly receipts")
    return statement
