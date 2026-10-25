"""Receipt validation, attribution and reconciliation around the WF-09A arithmetic.

The ONLY discounting / LCOE arithmetic is ``research.wf09a.costing.calculate``.
This module validates and atomises receipts into its rows, then independently
re-derives the discounted numerator, denominator and per-component values from
the receipts and fails if they do not reconcile.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from research.wf09a import costing as wf09a

from app.model_v2.costing_wf09b_candidate.contracts import (
    BESS_ONLY_KINDS, CANDIDATE, COMPONENT_SUM_TOLERANCE, LIFECYCLE_KINDS, UNAVAILABLE,
    WF09B_CANDIDATE_AUTHORITY, AugmentationEvidence, ChargingEvidence, Component, EnergyBoundary,
    Freshness, LineKind, Metric, Phase, Treatment, Vertical, Wf09bError, enum, exact_arithmetic,
    identity, require_release,
)
from app.model_v2.costing_wf09b_candidate.receipts import (
    CostReceipts, DiscountReceipt, EnergyReceipts, PeriodAxis, RunReceipt,
)

_COMPONENTS = tuple(Component)
_REQUIRED = {
    Metric.UNLEVERED_PRE_FINANCING: (Component.DEVEX, Component.CAPEX, Component.OPEX),
    Metric.LEVERED_AFTER_TAX: _COMPONENTS,
    Metric.LCOS: _COMPONENTS,
}
_VERTICAL_METRICS = {
    Vertical.SOLAR: (Metric.UNLEVERED_PRE_FINANCING, Metric.LEVERED_AFTER_TAX),
    Vertical.WIND: (Metric.UNLEVERED_PRE_FINANCING, Metric.LEVERED_AFTER_TAX),
    Vertical.BESS: (Metric.LCOS,),
}
_VERTICAL_BOUNDARY = {
    Vertical.SOLAR: EnergyBoundary.DELIVERED_AC_EXPORT,
    Vertical.WIND: EnergyBoundary.DELIVERED_AC_EXPORT,
    Vertical.BESS: EnergyBoundary.DELIVERED_AC_DISCHARGE,
}


@dataclass(frozen=True)
class CostingRequest:
    vertical: Vertical
    metric: Metric
    run: RunReceipt
    axis: PeriodAxis
    costs: CostReceipts
    energy: EnergyReceipts
    discount: DiscountReceipt
    charging: ChargingEvidence = ChargingEvidence.NOT_APPLICABLE
    augmentation: AugmentationEvidence = AugmentationEvidence.UNKNOWN

    def __post_init__(self):
        enum(self.vertical, Vertical, "vertical")
        enum(self.metric, Metric, "metric")
        for name, kind in (("run", RunReceipt), ("axis", PeriodAxis), ("costs", CostReceipts),
                           ("energy", EnergyReceipts), ("discount", DiscountReceipt)):
            if not isinstance(getattr(self, name), kind):
                raise Wf09bError("WF09B_VALUE", f"{name} must be a {kind.__name__}")
        enum(self.charging, ChargingEvidence, "charging")
        enum(self.augmentation, AugmentationEvidence, "augmentation")


@dataclass(frozen=True)
class Reconciliation:
    numerator_equals_attributed_discounted_lines: bool
    components_equal_attributed_discounted_lines: bool
    discounted_energy_equals_receipts: bool
    component_quotients_sum_to_total: bool
    max_component_sum_difference: Decimal
    attributed_line_ids: tuple
    excluded_movement_line_ids: tuple


@dataclass(frozen=True)
class CostingResult:
    status: str
    reasons: tuple
    vertical: Vertical
    metric: Metric
    pv_energy_mwh: Optional[Decimal]
    pv_components_keur: Optional[tuple]
    numerator_keur: Optional[Decimal]
    components_eur_mwh: Optional[tuple]
    total_eur_mwh: Optional[Decimal]
    reconciliation: Optional[Reconciliation]
    provenance: str
    authority: str = WF09B_CANDIDATE_AUTHORITY
    non_authoritative: bool = True


def _unavailable(req, *reasons) -> CostingResult:
    return CostingResult(UNAVAILABLE, tuple(sorted(set(reasons))), req.vertical, req.metric,
                         None, None, None, None, None, None, identity({"request": req, "reasons": sorted(set(reasons))}))


@exact_arithmetic
def evaluate(req: CostingRequest) -> CostingResult:
    require_release()
    if not isinstance(req, CostingRequest):
        raise Wf09bError("WF09B_VALUE", "evaluate() requires a CostingRequest")
    run = req.run
    # ── identity consistency: every receipt must be bound to the SAME Run ──
    for name, ref in (("axis", req.axis.run), ("costs", req.costs.run), ("energy", req.energy.run),
                      ("discount", req.discount.run)):
        if ref != run.ref:
            raise Wf09bError("WF09B_RUN_IDENTITY_MISMATCH", f"{name} receipt is bound to a different Run")
    if run.freshness is not Freshness.FRESH:
        return _unavailable(req, "WF09B_RUN_NOT_FRESH")
    if not run.evidence_complete:
        return _unavailable(req, "WF09B_RUN_EVIDENCE_INCOMPLETE")
    # ── vertical / metric / boundary ──
    if req.vertical not in _VERTICAL_METRICS:
        return _unavailable(req, "WF09B_VERTICAL_DENOMINATOR_NOT_APPROVED")
    if req.metric not in _VERTICAL_METRICS[req.vertical]:
        return _unavailable(req, "WF09B_METRIC_NOT_SUPPORTED_FOR_VERTICAL")
    for e in req.energy.lines:
        if e.boundary is not _VERTICAL_BOUNDARY[req.vertical]:
            raise Wf09bError("WF09B_ENERGY_BOUNDARY_MISMATCH", f"{e.line_id}: {e.boundary.value}")
    boundary = _VERTICAL_BOUNDARY[req.vertical].value
    axis_ids = req.axis.ids
    axis_set = set(axis_ids)
    # ── structural period alignment of every receipt ──
    for ln in req.costs.lines:
        if ln.period_id not in axis_set:
            raise Wf09bError("WF09B_PERIOD_ALIGNMENT", f"cost line {ln.line_id}: unknown period {ln.period_id}")
    for e in req.energy.lines:
        if e.period_id not in axis_set:
            raise Wf09bError("WF09B_PERIOD_ALIGNMENT", f"energy line {e.line_id}: unknown period {e.period_id}")
    factors = dict(req.discount.factors)
    if set(factors) - axis_set:
        raise Wf09bError("WF09B_PERIOD_ALIGNMENT", "discount receipt names a period not on the axis")
    # ── discount evidence ──
    reasons = []
    if req.discount.currency != "EUR":
        raise Wf09bError("WF09B_CURRENCY", f"costs are EUR; discount receipt is {req.discount.currency}")
    if req.discount.basis is not req.costs.price_basis:
        raise Wf09bError("WF09B_BASIS_MISMATCH", "real/nominal basis of costs and discount factors differ")
    if not req.discount.convention:
        reasons.append("WF09B_DISCOUNT_CONVENTION_MISSING")
    if not req.discount.rate_source:
        reasons.append("WF09B_DISCOUNT_RATE_SOURCE_MISSING")
    if axis_set - set(factors):
        reasons.append("WF09B_DISCOUNT_FACTOR_MISSING")
    # ── kinds applicable to this vertical / metric ──
    attributed = [ln for ln in req.costs.lines if ln.treatment is Treatment.ATTRIBUTED]
    excluded = [ln for ln in req.costs.lines if ln.treatment is Treatment.EXCLUDED_MOVEMENT]
    for ln in req.costs.lines:
        if ln.kind in BESS_ONLY_KINDS and req.vertical is not Vertical.BESS:
            raise Wf09bError("WF09B_KIND_NOT_APPLICABLE", f"{ln.line_id}: {ln.kind.value} only applies to BESS")
    if req.metric is Metric.UNLEVERED_PRE_FINANCING:
        bad = [ln.line_id for ln in attributed if ln.component in (Component.FINANCE, Component.TAX)]
        if bad:
            raise Wf09bError("WF09B_UNLEVERED_EXCLUDES_FINANCE_TAX", ",".join(bad))
    if any(ln.kind in LIFECYCLE_KINDS for ln in req.costs.lines):
        reasons.append("WF09B_AUGMENTATION_UNAPPROVED")
    # ── missing cost amounts ──
    if any(ln.amount_keur is None for ln in attributed):
        reasons.append("WF09B_COST_AMOUNT_MISSING")
    # ── BESS / LCOS evidence ──
    if req.metric is Metric.LCOS:
        has_spread = any(ln.kind is LineKind.NET_ARBITRAGE_SPREAD for ln in req.costs.lines)
        has_buy = any(ln.kind is LineKind.CHARGING_ELECTRICITY_PAID for ln in attributed)
        if req.charging is ChargingEvidence.NET_SPREAD or (has_spread and not has_buy):
            reasons.append("WF09B_LCOS_NET_SPREAD_ONLY")
        elif req.charging is not ChargingEvidence.EXPLICIT_BUY or not has_buy:
            reasons.append("WF09B_LCOS_CHARGING_COST_MISSING")
        if req.augmentation is not AugmentationEvidence.NOT_APPLICABLE_EVIDENCED:
            reasons.append("WF09B_AUGMENTATION_UNAPPROVED")
    elif req.charging is not ChargingEvidence.NOT_APPLICABLE:
        raise Wf09bError("WF09B_CHARGING_BELONGS_TO_LCOS", req.charging.value)
    # ── required component coverage per period (an explicit zero line counts) ──
    required = _REQUIRED[req.metric]
    covered = {(ln.period_id, ln.component) for ln in attributed}
    for pid in axis_ids:
        for comp in required:
            if (pid, comp) not in covered:
                reasons.append("WF09B_COMPONENT_EVIDENCE_MISSING")
    # ── energy evidence ──
    energy_by_period = {e.period_id: e for e in req.energy.lines}
    if axis_set - set(energy_by_period):
        reasons.append("WF09B_ENERGY_EVIDENCE_MISSING")
    if any(e.delivered_mwh is None for e in req.energy.lines):
        reasons.append("WF09B_ENERGY_EVIDENCE_MISSING")
    if reasons:
        return _unavailable(req, *reasons)

    # ── atomise into WF-09A rows ──
    rows = []
    for pid in axis_ids:
        costs, origins = [], []
        for comp in _COMPONENTS:
            lines = [ln for ln in attributed if ln.period_id == pid and ln.component is comp]
            if lines:
                costs.append(sum((ln.amount_keur for ln in lines), Decimal(0)))
                origins.append(tuple(ln.line_id for ln in lines))
            else:  # only reachable for components definitionally outside the metric
                costs.append(Decimal(0))
                origins.append((f"wf09b:definitional-exclusion:{req.metric.value}:{comp.value}:{pid}",))
        rows.append(wf09a.Row(pid, factors[pid], energy_by_period[pid].delivered_mwh,
                              tuple(costs), tuple(origins)))
    charging = {Metric.LCOS: "explicit_buy"}.get(req.metric, "not_applicable")
    basis = wf09a.Basis(req.metric.value, req.discount.convention, req.discount.rate_source,
                        req.discount.currency, boundary, charging)
    res = wf09a.calculate(tuple(rows), basis)
    if res.status != "CANDIDATE":
        return _unavailable(req, "WF09B_WF09A_UNAVAILABLE:" + res.reason)

    # ── independent reconciliation from the receipts ──
    pv_comp = {c: Decimal(0) for c in _COMPONENTS}
    for ln in attributed:
        pv_comp[ln.component] += ln.amount_keur * factors[ln.period_id]
    pv_energy = sum((energy_by_period[p].delivered_mwh * factors[p] for p in axis_ids), Decimal(0))
    numerator = sum(pv_comp.values(), Decimal(0))
    comp_ok = tuple(pv_comp[c] for c in _COMPONENTS) == res.pv_components_keur
    num_ok = numerator == res.numerator_keur
    en_ok = pv_energy == res.pv_energy_mwh
    diff = abs(sum(res.components_eur_mwh, Decimal(0)) - res.total_eur_mwh)
    sum_ok = diff <= COMPONENT_SUM_TOLERANCE
    if not (comp_ok and num_ok and en_ok and sum_ok):
        raise Wf09bError("WF09B_RECONCILIATION_FAILED",
                         f"components={comp_ok} numerator={num_ok} energy={en_ok} sum={sum_ok}")
    rec = Reconciliation(num_ok, comp_ok, en_ok, sum_ok, diff,
                         tuple(ln.line_id for ln in attributed), tuple(ln.line_id for ln in excluded))
    out = dict(status=CANDIDATE, reasons=(), vertical=req.vertical, metric=req.metric,
               pv_energy_mwh=res.pv_energy_mwh, pv_components_keur=res.pv_components_keur,
               numerator_keur=res.numerator_keur, components_eur_mwh=res.components_eur_mwh,
               total_eur_mwh=res.total_eur_mwh, reconciliation=rec)
    return CostingResult(provenance=identity({"request": req, "result": out}), **out)
