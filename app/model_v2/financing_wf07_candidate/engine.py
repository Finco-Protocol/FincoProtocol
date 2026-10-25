"""WF-07 integrated period engine — pure, deterministic, release-closed.

Consumes explicit evidence only (see :mod:`contracts`). Order of one operating
period under the single supported policy (anything else is UNSUPPORTED):

    1. SENIOR contractual service (N pari-passu facilities, aggregate) from CFADS
    2. senior shortfall -> reserve draws (DSRA cash, then DSRF), else halt
    3. DSRA excess release (never together with a senior shortfall)
    4. DSRF restoration, then DSRA top-up
    5. JUNIOR service
    6. SHAREHOLDER LOAN cash interest + scheduled principal
    7. remainder: distribution candidate only when every reserve meets target,
       otherwise RETAINED (no invented distribution, nothing carried implicitly)

Construction periods reconcile Sources & Uses with dated senior draws, dated
SHL draws and depleting equity pools; a residual is a typed FUNDING_GAP and is
never filled, ignored or distributed. A shortfall at any creditor layer, a
missing evidence item, or an unsupported combination halts the run with a typed
reason: deferral, capitalisation of arrears, pro-rata sharing, default and cure
are OPEN owner decisions and are never inferred.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from app.model_v2.financing_wf07_candidate import shl as shl_mod
from app.model_v2.financing_wf07_candidate.contracts import (
    CANDIDATE, UNAVAILABLE, UNSUPPORTED, ClaimClass, EvidenceStatus, Layer, Phase,
    ReserveType, Wf07Error, dec, enum, exact_arithmetic, ident, identity, index,
    opt_dec, require_release, unique,
)
from app.model_v2.financing_wf07_candidate.reserves import (
    DsraRow, DsrfRow, FacilityService, ReserveContract, ReserveOpening, ReserveTargetEvidence,
)
from app.model_v2.financing_wf07_candidate.shl import ShlRow, ShlTerms

ZERO = Decimal(0)
RESERVE_FUNDING = "RESERVE_FUNDING"


class ReservePosition(str, Enum):
    AFTER_SENIOR = "AFTER_SENIOR"
    AFTER_JUNIOR = "AFTER_JUNIOR"
    BEFORE_SENIOR = "BEFORE_SENIOR"


@dataclass(frozen=True)
class WaterfallPolicy:
    """Explicit and mandatory. Only :data:`SUPPORTED_POLICY` is calculable; every
    other representable combination returns UNSUPPORTED (no default is inferred)."""

    ranking: tuple
    reserve_position: ReservePosition
    draw_order: tuple
    restoration_order: tuple
    dsrf_draws_permitted: bool

    def __post_init__(self):
        enum(self.reserve_position, ReservePosition, "reserve_position")
        if not isinstance(self.dsrf_draws_permitted, bool):
            raise Wf07Error("WF07_VALUE", "dsrf_draws_permitted must be a bool")
        for name in ("ranking", "draw_order", "restoration_order"):
            if not isinstance(getattr(self, name), tuple):
                raise Wf07Error("WF07_VALUE", f"{name} must be a tuple")


SUPPORTED_POLICY = WaterfallPolicy(
    ranking=(Layer.SENIOR, Layer.JUNIOR, Layer.SHAREHOLDER_LOAN),
    reserve_position=ReservePosition.AFTER_SENIOR,
    draw_order=(ReserveType.DSRA, ReserveType.DSRF),
    restoration_order=(ReserveType.DSRF, ReserveType.DSRA),
    dsrf_draws_permitted=True,
)


@dataclass(frozen=True)
class PeriodEvidence:
    period_index: int
    end_date: date
    phase: Phase
    accrual_fraction: Decimal
    cash_available: Optional[Decimal] = None   # CFADS for operating periods; None = MISSING
    cash_source_id: Optional[str] = None

    def __post_init__(self):
        index(self.period_index, "period.period_index")
        if not isinstance(self.end_date, date) or hasattr(self.end_date, "hour"):
            raise Wf07Error("WF07_VALUE", "period.end_date must be a calendar date")
        enum(self.phase, Phase, "period.phase")
        dec(self.accrual_fraction, "period.accrual_fraction", positive=True)
        opt_dec(self.cash_available, "period.cash_available", nonnegative=True)
        if self.cash_available is not None:
            ident(self.cash_source_id, "period.cash_source_id")


@dataclass(frozen=True)
class ConstructionUse:
    period_index: int
    category: str
    amount: Decimal
    evidence_id: str
    reserve_id: Optional[str] = None

    def __post_init__(self):
        index(self.period_index, "use.period_index")
        ident(self.category, "use.category")
        dec(self.amount, "use.amount", nonnegative=True)
        ident(self.evidence_id, "use.evidence_id")
        if (self.category == RESERVE_FUNDING) != (self.reserve_id is not None):
            raise Wf07Error("WF07_RESERVE_FUNDING_USE", "RESERVE_FUNDING uses (and only they) name a reserve_id")


@dataclass(frozen=True)
class SeniorDraw:
    period_index: int
    facility_id: str
    amount: Decimal
    evidence_id: str

    def __post_init__(self):
        index(self.period_index, "draw.period_index")
        ident(self.facility_id, "draw.facility_id")
        dec(self.amount, "draw.amount", positive=True)
        ident(self.evidence_id, "draw.evidence_id")


@dataclass(frozen=True)
class EquityPool:
    """Depleting legal-equity commitment, used in the declared order."""

    source_id: str
    commitment: Decimal
    claim_class: ClaimClass = ClaimClass.LEGAL_EQUITY

    def __post_init__(self):
        ident(self.source_id, "pool.source_id")
        dec(self.commitment, "pool.commitment", positive=True)
        if self.claim_class is not ClaimClass.LEGAL_EQUITY:
            raise Wf07Error("WF07_EQUITY_CLAIM_CLASS", "an equity pool is legal equity")


@dataclass(frozen=True)
class Wf07Inputs:
    periods: tuple
    services: tuple
    senior_draws: tuple
    uses: tuple
    equity_pools: tuple
    shl: tuple
    reserves: tuple
    targets: tuple
    openings: tuple
    policy: WaterfallPolicy

    def __post_init__(self):
        for name, kind in (("periods", PeriodEvidence), ("services", FacilityService),
                           ("senior_draws", SeniorDraw), ("uses", ConstructionUse),
                           ("equity_pools", EquityPool), ("shl", ShlTerms),
                           ("reserves", ReserveContract), ("targets", ReserveTargetEvidence),
                           ("openings", ReserveOpening)):
            value = getattr(self, name)
            if not isinstance(value, tuple) or not all(isinstance(v, kind) for v in value):
                raise Wf07Error("WF07_VALUE", f"{name} must be a tuple of {kind.__name__}")
        if not isinstance(self.policy, WaterfallPolicy):
            raise Wf07Error("WF07_POLICY_REQUIRED", "an explicit WaterfallPolicy is mandatory")
        if not self.periods:
            raise Wf07Error("WF07_VALUE", "at least one period is required")
        idx = [p.period_index for p in self.periods]
        if idx != sorted(set(idx)) or any(b.end_date <= a.end_date for a, b in zip(self.periods, self.periods[1:])):
            raise Wf07Error("WF07_PERIODS", "periods must be strictly increasing in index and date")
        phases = [p.phase for p in self.periods]
        first_op = phases.index(Phase.OPERATING) if Phase.OPERATING in phases else len(phases)
        if Phase.CONSTRUCTION in phases[first_op:]:
            raise Wf07Error("WF07_PERIODS", "construction periods must precede operating periods")
        known = set(idx)
        op = {p.period_index for p in self.periods if p.phase is Phase.OPERATING}
        for s in self.services:
            if s.period_index not in op:
                raise Wf07Error("WF07_SERVICE_PERIOD", f"{s.facility_id}@{s.period_index}: debt service only in operating periods")
        unique([(s.period_index, s.facility_id) for s in self.services], "facility service row")
        unique([s.source_id for s in self.services], "debt-service source")
        layers = {}
        for s in self.services:
            if layers.setdefault(s.facility_id, s.layer) is not s.layer:
                raise Wf07Error("WF07_FACILITY_LAYER", s.facility_id)
        for d in self.senior_draws:
            if d.period_index not in known or d.period_index in op:
                raise Wf07Error("WF07_DRAW_PERIOD", f"{d.facility_id}@{d.period_index}")
            if layers.get(d.facility_id) is not Layer.SENIOR:
                raise Wf07Error("WF07_DRAW_FACILITY", d.facility_id)
        for u in self.uses:
            if u.period_index not in known or u.period_index in op:
                raise Wf07Error("WF07_USE_PERIOD", f"{u.category}@{u.period_index}")
        for t in self.shl:
            for d in t.draws:
                if d.period_index not in known:
                    raise Wf07Error("WF07_DRAW_PERIOD", f"{t.shl_id}@{d.period_index}")
        unique([d.evidence_id for d in self.senior_draws]
               + [u.evidence_id for u in self.uses]
               + [d.evidence_id for t in self.shl for d in t.draws], "funding/use evidence")
        unique([t.shl_id for t in self.shl] + [p.source_id for p in self.equity_pools], "funding source")
        unique([r.reserve_id for r in self.reserves], "reserve")
        if sum(r.reserve_type is ReserveType.DSRA for r in self.reserves) > 1 \
                or sum(r.reserve_type is ReserveType.DSRF for r in self.reserves) > 1:
            raise Wf07Error("WF07_MULTIPLE_RESERVES_OF_TYPE_UNSUPPORTED", "at most one DSRA and one DSRF")
        rid = {r.reserve_id: r for r in self.reserves}
        unique([(t.period_index, t.reserve_id) for t in self.targets], "reserve target row")
        unique([t.source_id for t in self.targets] + [o.source_id for o in self.openings]
               + [r.limit_evidence_id for r in self.reserves if r.limit_evidence_id], "reserve evidence source")
        for t in self.targets:
            if t.reserve_id not in rid or t.period_index not in op:
                raise Wf07Error("WF07_RESERVE_TARGET", f"{t.reserve_id}@{t.period_index}")
        unique([o.reserve_id for o in self.openings], "reserve opening")
        for o in self.openings:
            if o.reserve_id not in rid:
                raise Wf07Error("WF07_RESERVE_OPENING", o.reserve_id)
            if rid[o.reserve_id].reserve_type is ReserveType.DSRF and o.amount > rid[o.reserve_id].facility_limit:
                raise Wf07Error("WF07_DSRF_DRAWN_EXCEEDS_LIMIT", o.reserve_id)
        for u in self.uses:
            if u.category == RESERVE_FUNDING:
                r = rid.get(u.reserve_id)
                if r is None:
                    raise Wf07Error("WF07_RESERVE_FUNDING_USE", f"unknown reserve {u.reserve_id}")
                if r.reserve_type is ReserveType.DSRF:
                    raise Wf07Error("WF07_DSRF_CASH_FUNDING_REJECTED",
                                    "a facility-backed reserve is not pre-funded with project cash")


@dataclass(frozen=True)
class ConstructionRow:
    period_index: int
    uses_total: Decimal
    shl_cash_interest_use: Decimal
    capitalized_shl_interest: Decimal
    senior_draws: Decimal
    shl_draws: Decimal
    equity_draws: tuple          # ((pool id, amount), ...)
    funding_gap: Decimal


@dataclass(frozen=True)
class OperatingRow:
    period_index: int
    cash_available: Decimal
    senior_due: Decimal
    senior_paid_from_cash: Decimal
    dsra_draw: Decimal
    dsrf_draw: Decimal
    senior_shortfall: Decimal
    facility_paid: tuple         # ((facility id, paid), ...) senior and junior
    dsra_release: Decimal
    dsrf_restoration: Decimal
    dsra_top_up: Decimal
    junior_due: Decimal
    junior_paid: Decimal
    shl_cash_interest_due: Decimal
    shl_principal_due: Decimal
    shl_paid: Decimal
    shl_shortfall: Decimal
    distribution_candidate: Decimal
    retained_cash: Decimal

    def conservation_residual(self) -> Decimal:
        senior_total = self.senior_paid_from_cash + self.dsra_draw + self.dsrf_draw
        sources = self.cash_available + self.dsra_draw + self.dsrf_draw + self.dsra_release
        uses = (senior_total + self.dsrf_restoration + self.dsra_top_up + self.junior_paid
                + self.shl_paid + self.distribution_candidate + self.retained_cash)
        return sources - uses


@dataclass(frozen=True)
class Wf07Result:
    status: str
    reasons: tuple
    complete: bool
    construction: tuple
    operating: tuple
    shl_rows: tuple
    dsra_rows: tuple
    dsrf_rows: tuple
    provenance: str
    authority: str = "WF07_FINANCING_RESERVES_CANDIDATE_V0"
    non_authoritative: bool = True


def _halt(inp, status, reason, c, o, s, da, df, complete=False):
    result = dict(status=status, reasons=(reason,), complete=complete, construction=tuple(c),
                  operating=tuple(o), shl_rows=tuple(s), dsra_rows=tuple(da), dsrf_rows=tuple(df))
    return Wf07Result(provenance=identity({"inputs": inp, "result": result}), **result)


@exact_arithmetic
def run(inp: Wf07Inputs) -> Wf07Result:
    require_release()
    if not isinstance(inp, Wf07Inputs):
        raise Wf07Error("WF07_VALUE", "run() requires Wf07Inputs")
    c, o, s, da, df = [], [], [], [], []
    if inp.policy != SUPPORTED_POLICY:
        return _halt(inp, UNSUPPORTED, "WF07_POLICY_COMBINATION_UNSUPPORTED", c, o, s, da, df)
    reserves = {r.reserve_type: r for r in inp.reserves}
    dsra_c, dsrf_c = reserves.get(ReserveType.DSRA), reserves.get(ReserveType.DSRF)
    shl_bal = {t.shl_id: ZERO for t in inp.shl}
    pools = [[p.source_id, p.commitment] for p in inp.equity_pools]
    op_started = False
    dsra_bal = dsrf_drawn = ZERO

    for per in inp.periods:
        i = per.period_index
        if per.phase is Phase.CONSTRUCTION:
            dues = [shl_mod.shl_due(t, shl_bal[t.shl_id], i, Phase.CONSTRUCTION, per.accrual_fraction)
                    for t in inp.shl]
            cash_int = sum((d.cash_interest for d in dues), ZERO)
            pik = sum((d.pik_interest for d in dues), ZERO)
            uses = sum((u.amount for u in inp.uses if u.period_index == i), ZERO) + cash_int
            senior = sum((d.amount for d in inp.senior_draws if d.period_index == i), ZERO)
            shl_draw = sum((d.draw for d in dues), ZERO)
            residual = uses - senior - shl_draw
            if residual < 0:
                return _halt(inp, UNSUPPORTED, "WF07_SOURCES_EXCEED_USES", c, o, s, da, df)
            taken = []
            for pool in pools:
                take = min(pool[1], residual)
                if take > 0:
                    pool[1] -= take
                    residual -= take
                    taken.append((pool[0], take))
            c.append(ConstructionRow(i, uses, cash_int, pik, senior, shl_draw, tuple(taken), residual))
            if residual > 0:
                return _halt(inp, UNAVAILABLE, "WF07_FUNDING_GAP", c, o, s, da, df)
            for d in dues:
                row = shl_mod.settle(d, d.cash_interest, ZERO)
                shl_bal[d.shl_id] = row.closing
                s.append(row)
            continue

        # ── operating ──
        if per.cash_available is None:
            return _halt(inp, UNAVAILABLE, "WF07_CASH_EVIDENCE_MISSING", c, o, s, da, df)
        rows = {sv.facility_id: sv for sv in inp.services if sv.period_index == i}
        known = {sv.facility_id for sv in inp.services}
        if known - set(rows) or any(r.contractual_service is None for r in rows.values()):
            return _halt(inp, UNAVAILABLE, "WF07_CONTRACTUAL_SERVICE_EVIDENCE_MISSING", c, o, s, da, df)
        tgt = {}
        for r in inp.reserves:
            t = next((x for x in inp.targets if x.period_index == i and x.reserve_id == r.reserve_id), None)
            if t is None or t.target is None or t.status is not EvidenceStatus.EVIDENCED:
                return _halt(inp, UNAVAILABLE, "WF07_RESERVE_TARGET_EVIDENCE_MISSING", c, o, s, da, df)
            tgt[r.reserve_type] = t.target
        if not op_started:
            op_started = True
            for r in inp.reserves:
                op = next((x for x in inp.openings if x.reserve_id == r.reserve_id), None)
                if op is None:
                    return _halt(inp, UNAVAILABLE, "WF07_RESERVE_OPENING_MISSING", c, o, s, da, df)
                funded = sum((u.amount for u in inp.uses if u.reserve_id == r.reserve_id), ZERO)
                if r.reserve_type is ReserveType.DSRA:
                    if funded != op.amount:
                        raise Wf07Error("WF07_RESERVE_FUNDING_MISMATCH",
                                        f"{r.reserve_id}: opening {op.amount} vs construction funding {funded}")
                    dsra_bal = op.amount
                else:
                    dsrf_drawn = op.amount
        # SHL dues for the period
        dues = [shl_mod.shl_due(t, shl_bal[t.shl_id], i, Phase.OPERATING, per.accrual_fraction)
                for t in inp.shl]
        senior = [r for r in rows.values() if r.layer is Layer.SENIOR]
        junior = [r for r in rows.values() if r.layer is Layer.JUNIOR]
        s_due = sum((r.contractual_service for r in senior), ZERO)
        j_due = sum((r.contractual_service for r in junior), ZERO)
        shl_cash = sum((d.cash_interest for d in dues), ZERO)
        shl_prin = sum((d.principal_due for d in dues), ZERO)
        cash = per.cash_available
        paid_cash = min(cash, s_due)
        cash -= paid_cash
        short = s_due - paid_cash
        dsra_t, dsrf_t = tgt.get(ReserveType.DSRA, ZERO), tgt.get(ReserveType.DSRF, ZERO)
        dsra_draw = dsrf_draw = release = restore = top_up = ZERO
        if short > 0:
            if dsra_c is not None and dsra_bal > dsra_t:
                return _halt(inp, UNSUPPORTED, "WF07_RELEASE_AND_SHORTFALL_OPEN", c, o, s, da, df)
            if dsra_c is not None:
                dsra_draw = min(dsra_bal, short)
                short -= dsra_draw
            if dsrf_c is not None and inp.policy.dsrf_draws_permitted and short > 0:
                dsrf_draw = min(dsrf_c.facility_limit - dsrf_drawn, short)
                short -= dsrf_draw
        facility_paid = []
        if short > 0:
            funds = paid_cash + dsra_draw + dsrf_draw
            if any(r.paid_service is None for r in senior):
                return _halt(inp, UNAVAILABLE, "WF07_SHORTFALL_ALLOCATION_POLICY_OPEN", c, o, s, da, df)
            if any(r.paid_service > r.contractual_service for r in senior) \
                    or sum((r.paid_service for r in senior), ZERO) != funds:
                raise Wf07Error("WF07_PAID_EVIDENCE_MISMATCH", f"period {i}: paid evidence vs available funds")
            facility_paid = [(r.facility_id, r.paid_service) for r in senior]
        else:
            for r in senior + junior:
                if r.paid_service is not None and r.paid_service != r.contractual_service:
                    raise Wf07Error("WF07_PAID_EVIDENCE_MISMATCH", f"{r.facility_id}@{i}")
            facility_paid = [(r.facility_id, r.contractual_service) for r in senior]
        dsra_open, drawn_open = dsra_bal, dsrf_drawn
        j_paid = shl_paid = ZERO
        j_short = shl_short = ZERO
        shl_status = None
        if short == 0:
            if dsra_c is not None and dsra_draw == 0:
                release = max(ZERO, dsra_bal - dsra_t)
                cash += release
            if dsrf_c is not None and dsrf_draw == 0 and drawn_open > 0:
                restore = min(cash, drawn_open)
                cash -= restore
            if dsra_c is not None and dsra_draw == 0 and release == 0:
                top_up = min(cash, max(ZERO, dsra_t - dsra_bal))
                cash -= top_up
            j_paid = min(cash, j_due)
            cash -= j_paid
            j_short = j_due - j_paid
            if j_short == 0:
                facility_paid += [(r.facility_id, r.contractual_service) for r in junior]
                shl_due_total = shl_cash + shl_prin
                shl_paid = min(cash, shl_due_total)
                cash -= shl_paid
                shl_short = shl_due_total - shl_paid
        dsra_close = dsra_open - dsra_draw - release + top_up
        drawn_close = drawn_open + dsrf_draw - restore
        dsra_ok = dsra_c is None or dsra_close >= dsra_t
        dsrf_ok = dsrf_c is None or (dsrf_c.facility_limit - drawn_close) >= dsrf_t
        clean = short == 0 and j_short == 0 and shl_short == 0
        distribution = cash if (clean and dsra_ok and dsrf_ok) else ZERO
        retained = cash - distribution
        dsra_bal, dsrf_drawn = dsra_close, drawn_close
        if dsra_c is not None:
            da.append(DsraRow(dsra_c.reserve_id, i, dsra_open, dsra_t, top_up, dsra_draw, release,
                              dsra_close, max(ZERO, dsra_t - dsra_close)))
        if dsrf_c is not None:
            df.append(DsrfRow(dsrf_c.reserve_id, i, dsrf_c.facility_limit, drawn_open, dsrf_t, dsrf_draw,
                              restore, drawn_close, dsrf_c.facility_limit - drawn_close,
                              max(ZERO, dsrf_t - (dsrf_c.facility_limit - drawn_close))))
        o.append(OperatingRow(i, per.cash_available, s_due, paid_cash, dsra_draw, dsrf_draw, short,
                              tuple(facility_paid), release, restore, top_up, j_due, j_paid,
                              shl_cash, shl_prin, shl_paid, shl_short, distribution, retained))
        if short > 0:
            return _halt(inp, UNSUPPORTED, "WF07_DEFAULT_CURE_POLICY_OPEN", c, o, s, da, df)
        if j_short > 0:
            return _halt(inp, UNSUPPORTED, "WF07_JUNIOR_SHORTFALL_POLICY_OPEN", c, o, s, da, df)
        if shl_short > 0:
            return _halt(inp, UNSUPPORTED, "WF07_SHL_SHORTFALL_POLICY_OPEN", c, o, s, da, df)
        for d in dues:
            row = shl_mod.settle(d, d.cash_interest, d.principal_due)
            shl_bal[d.shl_id] = row.closing
            s.append(row)
    return _halt(inp, CANDIDATE, "WF07_COMPLETE", c, o, s, da, df, complete=True)
