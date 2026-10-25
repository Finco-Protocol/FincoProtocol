"""Immutable typed receipts: run identity, period axis, costs, energy, discounting.

Receipts are explicitly supplied evidence; this module never reads a Run, a
database or another candidate, and never fabricates a missing value.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from app.model_v2.costing_wf09b_candidate.contracts import (
    KIND_COMPONENT, NON_COST_KINDS, Component, EnergyBoundary, Freshness, LineKind, Phase,
    PriceBasis, Treatment, Wf09bError, calendar, dec, enum, ident, opt_dec, opt_ident, unique,
)


@dataclass(frozen=True)
class RunIdRef:
    """The identity every receipt must carry; it must equal the RunReceipt's."""

    snapshot_id: str
    composite_hash: str

    def __post_init__(self):
        ident(self.snapshot_id, "run.snapshot_id")
        ident(self.composite_hash, "run.composite_hash")


@dataclass(frozen=True)
class RunReceipt:
    """Mirror of the canonical RunIdentity plus authority, freshness and completeness
    as SUPPLIED by the caller (never inferred or looked up)."""

    snapshot_id: str
    composite_hash: str
    workbook_version: str
    engine_version: str
    calculation_authority: str
    freshness: Freshness
    evidence_complete: bool
    project_id: Optional[str] = None
    scenario_id: Optional[str] = None

    def __post_init__(self):
        for name in ("snapshot_id", "composite_hash", "workbook_version", "engine_version",
                     "calculation_authority"):
            ident(getattr(self, name), f"run.{name}")
        enum(self.freshness, Freshness, "run.freshness")
        if not isinstance(self.evidence_complete, bool):
            raise Wf09bError("WF09B_VALUE", "run.evidence_complete must be a bool")
        opt_ident(self.project_id, "run.project_id")
        opt_ident(self.scenario_id, "run.scenario_id")

    @property
    def ref(self) -> RunIdRef:
        return RunIdRef(self.snapshot_id, self.composite_hash)


@dataclass(frozen=True)
class PeriodSpec:
    """One aligned period. Canonical rows cover ``(start, end]``; the dates are only
    validated for ordering and contiguity, never used to derive an amount."""

    period_id: str
    phase: Phase
    start: date
    end: date

    def __post_init__(self):
        ident(self.period_id, "period.period_id")
        enum(self.phase, Phase, "period.phase")
        calendar(self.start, "period.start")
        calendar(self.end, "period.end")
        if self.end <= self.start:
            raise Wf09bError("WF09B_PERIOD_ALIGNMENT", f"{self.period_id}: end must be after start")


@dataclass(frozen=True)
class PeriodAxis:
    run: RunIdRef
    periods: tuple

    def __post_init__(self):
        if not isinstance(self.run, RunIdRef):
            raise Wf09bError("WF09B_VALUE", "axis.run must be a RunIdRef")
        if not isinstance(self.periods, tuple) or not self.periods \
                or not all(isinstance(p, PeriodSpec) for p in self.periods):
            raise Wf09bError("WF09B_VALUE", "axis.periods must be a non-empty tuple of PeriodSpec")
        unique([p.period_id for p in self.periods], "period id")
        for a, b in zip(self.periods, self.periods[1:]):
            if b.start != a.end:
                raise Wf09bError("WF09B_PERIOD_ALIGNMENT",
                                 f"{a.period_id}->{b.period_id}: periods must be contiguous (no gap or overlap)")
            if a.phase is Phase.OPERATING and b.phase is Phase.CONSTRUCTION:
                raise Wf09bError("WF09B_PERIOD_ALIGNMENT", "construction periods must precede operating periods")

    @property
    def ids(self) -> tuple:
        return tuple(p.period_id for p in self.periods)


@dataclass(frozen=True)
class CostLine:
    """One atomic source amount (kEUR). ``origin_id`` is the economic origin and must
    be unique among ATTRIBUTED lines; ``contains`` lists origins already included in
    this line's amount (e.g. DEVEX or IDC capitalised into CAPEX) and may not repeat
    an origin that is attributed elsewhere."""

    line_id: str
    origin_id: str
    kind: LineKind
    period_id: str
    amount_keur: Optional[Decimal]          # None = MISSING, Decimal(0) = evidenced zero
    treatment: Treatment
    source_ref: str
    contains: tuple = ()

    def __post_init__(self):
        ident(self.line_id, "line.line_id")
        ident(self.origin_id, "line.origin_id")
        enum(self.kind, LineKind, "line.kind")
        ident(self.period_id, "line.period_id")
        opt_dec(self.amount_keur, "line.amount_keur")
        enum(self.treatment, Treatment, "line.treatment")
        ident(self.source_ref, "line.source_ref")
        if not isinstance(self.contains, tuple):
            raise Wf09bError("WF09B_VALUE", "line.contains must be a tuple of origin ids")
        for c in self.contains:
            ident(c, "line.contains")
        if self.origin_id in self.contains:
            raise Wf09bError("WF09B_SELF_CONTAINMENT", self.line_id)
        if self.kind in NON_COST_KINDS and self.treatment is Treatment.ATTRIBUTED:
            raise Wf09bError("WF09B_CASH_MOVEMENT_NOT_COST",
                             f"{self.line_id}: {self.kind.value} is a cash movement / non-cash item, not a cost")
        if self.amount_keur is not None and self.kind is LineKind.CASH_TAX_REFUND and self.amount_keur > 0:
            raise Wf09bError("WF09B_TAX_REFUND_SIGN", f"{self.line_id}: a refund is a credit (<= 0)")
        if (self.amount_keur is not None and self.kind in KIND_COMPONENT
                and self.kind is not LineKind.CASH_TAX_REFUND and self.amount_keur < 0):
            raise Wf09bError("WF09B_NEGATIVE_COST", f"{self.line_id}: only a tax refund may be negative")

    @property
    def component(self) -> Optional[Component]:
        return KIND_COMPONENT.get(self.kind)


@dataclass(frozen=True)
class CostReceipts:
    run: RunIdRef
    price_basis: PriceBasis
    lines: tuple

    def __post_init__(self):
        if not isinstance(self.run, RunIdRef):
            raise Wf09bError("WF09B_VALUE", "costs.run must be a RunIdRef")
        enum(self.price_basis, PriceBasis, "costs.price_basis")
        if not isinstance(self.lines, tuple) or not all(isinstance(x, CostLine) for x in self.lines):
            raise Wf09bError("WF09B_VALUE", "costs.lines must be a tuple of CostLine")
        unique([x.line_id for x in self.lines], "cost line id")
        attributed = [x for x in self.lines if x.treatment is Treatment.ATTRIBUTED]
        unique([x.origin_id for x in attributed], "economic origin")
        origins = {x.origin_id for x in attributed}
        for x in attributed:
            overlap = origins.intersection(x.contains)
            if overlap:
                raise Wf09bError(
                    "WF09B_DOUBLE_COUNT",
                    f"{x.line_id} already contains {sorted(overlap)}, which is also attributed on its own")
        unique([c for x in attributed for c in x.contains], "contained origin")


@dataclass(frozen=True)
class EnergyLine:
    """Delivered energy for one period. Gross / curtailment / loss / auxiliary are
    taken ONLY from actual source evidence; when ``gross_mwh`` is given the full
    breakdown must reconcile exactly to ``delivered_mwh``."""

    line_id: str
    period_id: str
    boundary: EnergyBoundary
    delivered_mwh: Optional[Decimal]       # None = MISSING, Decimal(0) = evidenced zero
    source_ref: str
    gross_mwh: Optional[Decimal] = None
    curtailment_mwh: Optional[Decimal] = None
    loss_mwh: Optional[Decimal] = None
    auxiliary_mwh: Optional[Decimal] = None
    #: Any generic haircut (RTE, availability, degradation) is a synthetic energy
    #: reconstruction and is rejected: actual measured energy already reflects it.
    generic_adjustment_factor: Optional[Decimal] = None

    def __post_init__(self):
        ident(self.line_id, "energy.line_id")
        ident(self.period_id, "energy.period_id")
        enum(self.boundary, EnergyBoundary, "energy.boundary")
        opt_dec(self.delivered_mwh, "energy.delivered_mwh", nonnegative=True)
        ident(self.source_ref, "energy.source_ref")
        for name in ("gross_mwh", "curtailment_mwh", "loss_mwh", "auxiliary_mwh"):
            opt_dec(getattr(self, name), f"energy.{name}", nonnegative=True)
        if self.generic_adjustment_factor is not None:
            raise Wf09bError("WF09B_SYNTHETIC_ENERGY_ADJUSTMENT",
                             f"{self.line_id}: RTE / loss haircuts must not be applied on top of measured energy")
        parts = (self.curtailment_mwh, self.loss_mwh, self.auxiliary_mwh)
        if self.gross_mwh is not None:
            if self.delivered_mwh is None or any(p is None for p in parts):
                raise Wf09bError("WF09B_ENERGY_BREAKDOWN_INCOMPLETE", self.line_id)
            if self.gross_mwh - sum(parts, Decimal(0)) != self.delivered_mwh:
                raise Wf09bError("WF09B_ENERGY_BREAKDOWN_MISMATCH", self.line_id)
        elif any(p is not None for p in parts):
            raise Wf09bError("WF09B_ENERGY_BREAKDOWN_INCOMPLETE", f"{self.line_id}: deductions without gross")


@dataclass(frozen=True)
class EnergyReceipts:
    run: RunIdRef
    lines: tuple

    def __post_init__(self):
        if not isinstance(self.run, RunIdRef):
            raise Wf09bError("WF09B_VALUE", "energy.run must be a RunIdRef")
        if not isinstance(self.lines, tuple) or not all(isinstance(x, EnergyLine) for x in self.lines):
            raise Wf09bError("WF09B_VALUE", "energy.lines must be a tuple of EnergyLine")
        unique([x.line_id for x in self.lines], "energy line id")
        unique([x.period_id for x in self.lines], "energy period")


@dataclass(frozen=True)
class DiscountReceipt:
    """Explicit valuation origin: supplied factors only. No rate, WACC, day-count or
    conversion is derived. ``convention`` / ``rate_source`` / ``valuation_date`` /
    ``factors_as_of`` may be None (MISSING) and then yield UNAVAILABLE; a valuation
    date is NEVER inferred from the Run date, the first period, financial close or
    the convention text. ``factors_as_of`` is the date the supplied factor schedule
    itself discounts to; it must equal ``valuation_date`` (it can never stand in for it).
    """

    run: RunIdRef
    convention: Optional[str]
    rate_source: Optional[str]
    currency: str
    basis: PriceBasis
    valuation_date: Optional[date]
    factors: tuple                         # ((period_id, Decimal factor), ...)
    source_ref: str
    factors_as_of: Optional[date] = None

    def __post_init__(self):
        if not isinstance(self.run, RunIdRef):
            raise Wf09bError("WF09B_VALUE", "discount.run must be a RunIdRef")
        opt_ident(self.convention, "discount.convention")
        opt_ident(self.rate_source, "discount.rate_source")
        ident(self.currency, "discount.currency")
        enum(self.basis, PriceBasis, "discount.basis")
        if self.valuation_date is not None:
            calendar(self.valuation_date, "discount.valuation_date")
        ident(self.source_ref, "discount.source_ref")
        if self.factors_as_of is not None:
            calendar(self.factors_as_of, "discount.factors_as_of")
        if not isinstance(self.factors, tuple):
            raise Wf09bError("WF09B_VALUE", "discount.factors must be a tuple")
        for f in self.factors:
            if not isinstance(f, tuple) or len(f) != 2:
                raise Wf09bError("WF09B_VALUE", "each factor must be a (period_id, Decimal) pair")
            ident(f[0], "discount.factor.period_id")
            dec(f[1], "discount.factor", positive=True)
        unique([f[0] for f in self.factors], "discount factor period")
