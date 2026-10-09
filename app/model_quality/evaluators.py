"""Evaluators: each reads persisted evidence and returns an ``Outcome``.  None executes the engine.

Status semantics
----------------
PASS / WARNING / FAIL    the check was evaluated (the evidence it needs exists and is well formed)
NOT_APPLICABLE           the check genuinely does not apply to this run (e.g. no Senior facility)
UNAVAILABLE              the evidence or the threshold authority needed is absent or malformed;
                         this is NEVER a PASS and NEVER an invented failure

Identities already proven by the Run Integrity report are reused through ``integrity_check``;
the arithmetic is not duplicated here.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from app.model_quality.contracts import CheckStatus
from app.model_quality.evidence import (
    RESERVE_AUTOMATIC,
    RESERVE_CASH_FIXED,
    RESERVE_DSRF,
    RESERVE_NONE,
    QualityEvidence,
)

TOL_KEUR = 1e-6
TOL_RATIO = 1e-9
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class Outcome:
    status: CheckStatus
    reason: Optional[str] = None
    value: Optional[float] = None
    threshold: Optional[float] = None
    detail: str = ""


def _unavailable(reason: str, detail: str = "") -> Outcome:
    return Outcome(CheckStatus.UNAVAILABLE, reason, detail=detail)


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if math.isfinite(f) else None


class Context:
    """One evaluation pass: caches the (pure) Run Integrity report over the persisted evidence."""

    def __init__(self, evidence: QualityEvidence) -> None:
        self.ev = evidence
        self._report = None

    @property
    def summary(self) -> Mapping[str, Any]:
        return self.ev.runtime_summary or {}

    @property
    def integrity_report(self):
        if self._report is None:
            from app.run_integrity import run_integrity_checks
            self._report = run_integrity_checks(self.ev.integrity_evidence)
        return self._report

    def senior_periods(self) -> Optional[list]:
        sd = (self.ev.integrity_evidence or {}).get("senior_debt")
        periods = sd.get("periods") if isinstance(sd, Mapping) else None
        return periods if isinstance(periods, list) else None

    def min_dscr(self) -> tuple[Optional[float], Optional[float], str]:
        """Minimum persisted base DSCR, the sizing target of that period, and its source."""
        periods = self.senior_periods()
        if periods:
            rows = [(_num(p.get("reported_dscr")), _num(p.get("target_dscr"))) for p in periods if isinstance(p, Mapping)]
            rows = [r for r in rows if r[0] is not None]
            if rows:
                worst = min(rows, key=lambda r: r[0])
                return worst[0], worst[1], "integrity_evidence.senior_debt.periods"
        value = _num(self.summary.get("min_dscr"))
        return value, _num(self.summary.get("target_dscr")), "runtime_summary.min_dscr"


Evaluator = Callable[[Context], Outcome]


# ── reuse of the existing Run Integrity report ───────────────────────────────────────────────
def integrity_check(check_id: str) -> Evaluator:
    def evaluate(ctx: Context) -> Outcome:
        found = next((c for c in ctx.integrity_report.checks if c.check_id == check_id), None)
        if found is None:
            return _unavailable("RUN_INTEGRITY_CHECK_NOT_REPORTED")
        status = CheckStatus(found.status.value)
        reason = found.reason_code
        if status is CheckStatus.UNAVAILABLE and not reason:
            reason = "RUN_INTEGRITY_EVIDENCE_UNAVAILABLE"
        return Outcome(status, reason, found.max_abs_deviation, found.tolerance, found.detail)
    return evaluate


# ── A. Accounting integrity ──────────────────────────────────────────────────────────────────
def ebitda_identity(ctx: Context) -> Outcome:
    rev, opex, ebitda = (_num(ctx.summary.get(k)) for k in ("total_revenue_keur", "total_opex_keur", "total_ebitda_keur"))
    if None in (rev, opex, ebitda):
        return _unavailable("EBITDA_AGGREGATES_MISSING")
    deviation = abs(rev - opex - ebitda)
    ok = deviation <= TOL_KEUR
    return Outcome(CheckStatus.PASS if ok else CheckStatus.FAIL, None if ok else "EBITDA_NOT_REVENUE_MINUS_OPEX",
                   deviation, TOL_KEUR, "total EBITDA = total revenue - total OPEX (persisted aggregates)")


def return_metric_availability(ctx: Context) -> Outcome:
    s = ctx.summary
    keys = ("project_irr", "equity_irr", "total_sponsor_xirr")
    if not any(k in s for k in keys):
        return _unavailable("RETURN_METRICS_NOT_PERSISTED")
    present = [k for k in keys if _num(s.get(k)) is not None]   # a genuine 0.0 counts as present
    statuses = {k: s.get(f) for k, f in (("equity_irr", "share_capital_irr_status"), ("total_sponsor_xirr", "total_sponsor_xirr_status"))}
    bad = sorted(k for k, v in statuses.items() if v not in (None, "OK") and _num(s.get(k)) is None)
    if len(present) == len(keys):
        return Outcome(CheckStatus.PASS, None, float(len(present)), float(len(keys)), "all return metrics published")
    missing = sorted(set(keys) - set(present))
    return Outcome(CheckStatus.WARNING, "RETURN_METRIC_NOT_PUBLISHED", float(len(present)), float(len(keys)),
                   f"not published: {', '.join(missing)}" + (f"; typed non-OK status: {', '.join(bad)}" if bad else ""))


# ── B. Sources & Uses ────────────────────────────────────────────────────────────────────────
def construction_funding_reconciliation(ctx: Context) -> Outcome:
    fe = ctx.summary.get("financing_evidence")
    cf = fe.get("construction_funding") if isinstance(fe, Mapping) else None
    if not isinstance(cf, Mapping):
        return _unavailable("FINANCING_EVIDENCE_NOT_PERSISTED")
    keys = ("maximum_period_difference_keur", "maximum_cumulative_difference_keur", "total_audit_residual_keur")
    values = [_num(cf.get(k)) for k in keys]
    if any(v is None for v in values):
        return _unavailable("CONSTRUCTION_FUNDING_EVIDENCE_INCOMPLETE")
    worst = max(abs(v) for v in values)
    ok = worst <= TOL_KEUR
    return Outcome(CheckStatus.PASS if ok else CheckStatus.FAIL, None if ok else "CONSTRUCTION_FUNDING_RESIDUAL",
                   worst, TOL_KEUR, "construction draws reconcile to uses in every period and cumulatively")


def developer_uses_itemised(ctx: Context) -> Outcome:
    su = ((ctx.ev.integrity_evidence or {}).get("sources_uses") or {}).get("summary")
    if not isinstance(su, Mapping):
        return _unavailable("SOURCES_USES_EVIDENCE_MISSING")
    keys = ("development_cost_reimbursement_keur", "developer_fee_keur")
    if any(k not in su for k in keys):
        return _unavailable("DEVELOPER_USES_EVIDENCE_MISSING", "never assumed zero")
    values = [_num(su[k]) for k in keys]
    if any(v is None or v < 0 for v in values):
        return _unavailable("DEVELOPER_USES_EVIDENCE_INVALID")
    total = values[0] + values[1]
    if total == 0.0:
        return Outcome(CheckStatus.NOT_APPLICABLE, "NO_DEVELOPER_USES", 0.0, None, "recorded as an actual zero")
    return Outcome(CheckStatus.PASS, None, total, None, "reimbursement and fee itemised separately in Uses")


# ── C. Senior debt / bankability ─────────────────────────────────────────────────────────────
def solver_authority(ctx: Context) -> Outcome:
    sd = (ctx.ev.integrity_evidence or {}).get("senior_debt")
    diag = sd.get("diagnostics") if isinstance(sd, Mapping) else None
    if not isinstance(diag, Mapping) or "termination_reason" not in diag:
        return _unavailable("SOLVER_DIAGNOSTICS_NOT_PERSISTED")
    ok = diag.get("termination_reason") == "CONVERGED" and diag.get("is_authoritative") is True
    return Outcome(CheckStatus.PASS if ok else CheckStatus.FAIL, None if ok else "SOLVER_RESULT_NOT_AUTHORITATIVE",
                   detail="authoritative convergence only; convergence is not lender approval")


def actual_vs_requested_gearing(ctx: Context) -> Outcome:
    actual, cap = _num(ctx.summary.get("actual_gearing_pct")), _num(ctx.summary.get("gearing_cap_pct"))
    if actual is None or cap is None:
        return _unavailable("ACTUAL_OR_REQUESTED_GEARING_MISSING")
    fe = ctx.summary.get("financing_evidence")
    binding = ((fe or {}).get("bankability") or {}).get("binding_senior_constraint") if isinstance(fe, Mapping) else None
    ok = actual <= cap + TOL_KEUR
    detail = f"actual funded gearing vs requested cap; binding constraint: {binding}" if binding else "actual funded gearing vs requested cap"
    return Outcome(CheckStatus.PASS if ok else CheckStatus.FAIL, None if ok else "ACTUAL_GEARING_EXCEEDS_REQUESTED_CAP",
                   actual, cap, detail)


def minimum_dscr(ctx: Context) -> Outcome:
    worst, target, source = ctx.min_dscr()
    if worst is None:
        return _unavailable("DSCR_EVIDENCE_MISSING")
    if worst < 1.0 - TOL_RATIO:
        return Outcome(CheckStatus.FAIL, "DSCR_BELOW_ONE", worst, 1.0,
                       f"base CFADS does not cover debt service in at least one period ({source})")
    if target is not None and worst < target - 1e-6:
        return Outcome(CheckStatus.WARNING, "DSCR_BELOW_SIZING_TARGET", worst, target,
                       f"minimum base DSCR is below the effective sizing target ({source})")
    return Outcome(CheckStatus.PASS, None, worst, target, f"minimum base DSCR meets 1.0x and the sizing target ({source})")


# ── D. Cash / liquidity ──────────────────────────────────────────────────────────────────────
def dsra_funding_vs_target(ctx: Context) -> Outcome:
    terms = ctx.ev.terms
    regime = terms.reserve_regime
    if regime is None:
        return _unavailable("DSRA_TARGET_AUTHORITY_MISSING")
    if regime in (RESERVE_NONE, RESERVE_DSRF):
        why = "no reserve configured" if regime == RESERVE_NONE else "standby facility; not cash funded at close"
        return Outcome(CheckStatus.NOT_APPLICABLE, "NO_CASH_RESERVE_REQUIRED", detail=why)
    if regime == RESERVE_AUTOMATIC or terms.dsra_target_keur is None:
        return _unavailable("DSRA_TARGET_AUTHORITY_MISSING", "engine-derived target is not persisted with the Run")
    su = ((ctx.ev.integrity_evidence or {}).get("sources_uses") or {}).get("summary")
    funded = _num(su.get("initial_dsra_funding_keur")) if isinstance(su, Mapping) else None
    if funded is None:
        return _unavailable("DSRA_FUNDING_EVIDENCE_MISSING")
    target = float(terms.dsra_target_keur)
    ok = funded >= target - TOL_KEUR
    return Outcome(CheckStatus.PASS if ok else CheckStatus.FAIL, None if ok else "DSRA_UNDERFUNDED",
                   funded, target, "initial cash DSRA funding vs the typed fixed requirement")


# ── E. Covenants (only against supplied thresholds) ──────────────────────────────────────────
def covenant_min_dscr(ctx: Context) -> Outcome:
    covenant = ctx.ev.terms.min_dscr_covenant
    if covenant is None:
        return _unavailable("MIN_DSCR_COVENANT_NOT_SUPPLIED")
    worst, _target, source = ctx.min_dscr()
    if worst is None:
        return _unavailable("DSCR_EVIDENCE_MISSING")
    ok = worst >= covenant - TOL_RATIO
    return Outcome(CheckStatus.PASS if ok else CheckStatus.FAIL, None if ok else "MIN_DSCR_COVENANT_BREACH",
                   worst, covenant, f"minimum base DSCR vs the supplied minimum-DSCR covenant ({source})")


def lockup_dscr(ctx: Context) -> Outcome:
    lockup = ctx.ev.terms.lockup_dscr
    if lockup is None:
        return _unavailable("LOCKUP_DSCR_NOT_SUPPLIED")
    worst, _target, source = ctx.min_dscr()
    if worst is None:
        return _unavailable("DSCR_EVIDENCE_MISSING")
    ok = worst >= lockup - TOL_RATIO
    return Outcome(CheckStatus.PASS if ok else CheckStatus.WARNING, None if ok else "DISTRIBUTION_LOCKUP_TRIGGERED",
                   worst, lockup, f"a lock-up trigger restricts distributions; it is not a default ({source})")


def llcr_requirement(ctx: Context) -> Outcome:
    requirement = ctx.ev.terms.min_llcr
    if requirement is None:
        return _unavailable("LLCR_REQUIREMENT_NOT_SUPPLIED")
    llcr = _num(ctx.summary.get("min_llcr"))
    if llcr is None:
        return _unavailable("LLCR_NOT_PERSISTED", "the Last Run does not publish a minimum LLCR")
    ok = llcr >= requirement - TOL_RATIO
    return Outcome(CheckStatus.PASS if ok else CheckStatus.FAIL, None if ok else "LLCR_BELOW_REQUIREMENT",
                   llcr, requirement, "persisted minimum LLCR vs the supplied requirement")


def covenant_ordering(ctx: Context) -> Outcome:
    terms = ctx.ev.terms
    _worst, target, _src = ctx.min_dscr()
    supplied = [("min_dscr_covenant", terms.min_dscr_covenant), ("lockup_dscr", terms.lockup_dscr)]
    supplied = [(n, v) for n, v in supplied if v is not None]
    if not supplied or target is None:
        return _unavailable("COVENANT_THRESHOLDS_NOT_SUPPLIED")
    chain = supplied + [("sizing_target_dscr", target)]
    for (n1, v1), (n2, v2) in zip(chain, chain[1:]):
        if v1 > v2 + TOL_RATIO:
            return Outcome(CheckStatus.FAIL, "COVENANT_ORDER_INVERTED", v1, v2, f"{n1} ({v1}) exceeds {n2} ({v2})")
    return Outcome(CheckStatus.PASS, None, detail="covenant <= lock-up <= sizing target for the supplied thresholds")


# ── F. CAPEX / construction ──────────────────────────────────────────────────────────────────
def contingency_adequacy(ctx: Context) -> Outcome:
    t = ctx.ev.terms
    if t.contingency_policy_min_pct is None:
        return _unavailable("CONTINGENCY_POLICY_NOT_SUPPLIED")
    amount, base = t.contingency_amount_keur, t.contingency_base_keur
    if amount is None or base is None or base <= 0:
        return _unavailable("CONTINGENCY_EVIDENCE_MISSING")
    pct = amount / base
    ok = pct >= t.contingency_policy_min_pct - TOL_RATIO
    return Outcome(CheckStatus.PASS if ok else CheckStatus.WARNING, None if ok else "CONTINGENCY_BELOW_PROJECT_POLICY",
                   pct, t.contingency_policy_min_pct, "contingency share of its base vs the project's documented policy")


# ── G. Revenue ───────────────────────────────────────────────────────────────────────────────
def _revenue_derivation(ctx: Context) -> Optional[Mapping[str, Any]]:
    rd = ctx.summary.get("revenue_derivation")
    return rd if isinstance(rd, Mapping) else None


def revenue_evidence_complete(ctx: Context) -> Outcome:
    rd = _revenue_derivation(ctx)
    if rd is None:
        return _unavailable("REVENUE_DERIVATION_NOT_PERSISTED")
    periods = rd.get("revenue_periods")
    count = rd.get("period_count")
    if not isinstance(periods, list) or not periods or isinstance(count, bool) or not isinstance(count, int):
        return _unavailable("REVENUE_PERIOD_EVIDENCE_MISSING")
    ok = len(periods) == count
    return Outcome(CheckStatus.PASS if ok else CheckStatus.FAIL, None if ok else "REVENUE_PERIOD_COUNT_MISMATCH",
                   float(len(periods)), float(count), "revenue derivation lists every period it claims")


def revenue_periods_reconcile(ctx: Context) -> Outcome:
    rd = _revenue_derivation(ctx)
    total = _num(ctx.summary.get("total_revenue_keur"))
    periods = rd.get("revenue_periods") if rd else None
    if not isinstance(periods, list) or not periods or total is None:
        return _unavailable("REVENUE_RECONCILIATION_EVIDENCE_MISSING")
    values = [_num(p.get("revenue_keur_raw")) if isinstance(p, Mapping) else None for p in periods]
    if any(v is None for v in values):
        return _unavailable("REVENUE_PERIOD_VALUES_MALFORMED")
    deviation = abs(sum(values) - total)
    ok = deviation <= TOL_KEUR
    return Outcome(CheckStatus.PASS if ok else CheckStatus.FAIL, None if ok else "REVENUE_PERIODS_DO_NOT_SUM_TO_TOTAL",
                   deviation, TOL_KEUR, "sum of period revenue equals the published total")


# ── H. Terminal liability ────────────────────────────────────────────────────────────────────
def senior_settled_at_maturity(ctx: Context) -> Outcome:
    periods = ctx.senior_periods()
    su = ((ctx.ev.integrity_evidence or {}).get("sources_uses") or {}).get("summary")
    senior_size = _num(su.get("senior_debt_keur")) if isinstance(su, Mapping) else None
    if periods is None:
        return _unavailable("SENIOR_SCHEDULE_NOT_PERSISTED")
    if not periods:
        if senior_size is not None and senior_size <= ctx.ev.terminal_tolerance_keur:
            return Outcome(CheckStatus.NOT_APPLICABLE, "NO_SENIOR_DEBT")
        return _unavailable("SENIOR_SCHEDULE_NOT_PERSISTED")
    closing = _num(periods[-1].get("closing")) if isinstance(periods[-1], Mapping) else None
    if closing is None:
        return _unavailable("SENIOR_TERMINAL_BALANCE_MISSING", "a missing balance is never treated as settled")
    tol = ctx.ev.terminal_tolerance_keur
    ok = closing <= tol
    return Outcome(CheckStatus.PASS if ok else CheckStatus.FAIL, None if ok else "SENIOR_MATURITY_UNSETTLED_LIABILITY",
                   closing, tol, "closing Senior principal at the final contractual period vs canonical solver precision")


def shl_terminal(ctx: Context) -> Outcome:
    reported = ((ctx.ev.integrity_evidence or {}).get("sponsor") or {}).get("reported")
    if not isinstance(reported, Mapping) or not any(k.endswith("_status") for k in reported):
        return _unavailable("SPONSOR_RETURN_STATUS_NOT_PERSISTED")
    unpaid = sorted(k for k, v in reported.items() if k.endswith("_status") and v == "UNPAID_SHL_AT_CONTRACTUAL_MATURITY")
    if unpaid:
        return Outcome(CheckStatus.FAIL, "UNPAID_SHL_AT_CONTRACTUAL_MATURITY", detail=", ".join(unpaid))
    return Outcome(CheckStatus.PASS, None, detail="no unpaid shareholder-loan balloon at contractual maturity")


# ── I. Provenance and freshness ──────────────────────────────────────────────────────────────
def run_identity_complete(ctx: Context) -> Outcome:
    ev = ctx.ev
    missing = []
    if not ev.snapshot_id:
        missing.append("snapshot_id")
    if not ev.composite_hash or not _HEX64.match(str(ev.composite_hash)):
        missing.append("composite_hash")
    if not ev.run_at:
        missing.append("run_at")
    if not ev.engine_version:
        missing.append("engine_version")
    if missing:
        return Outcome(CheckStatus.FAIL, "RUN_IDENTITY_INCOMPLETE", float(len(missing)), 0.0, "missing: " + ", ".join(missing))
    return Outcome(CheckStatus.PASS, None, 0.0, 0.0, "snapshot, composite hash, time and engine version present")


def freshness(ctx: Context) -> Outcome:
    state = ctx.ev.freshness
    if state == "CURRENT":
        return Outcome(CheckStatus.PASS, None, detail="Last Run matches the current Working Copy")
    if state == "STALE":
        return Outcome(CheckStatus.WARNING, "WORKING_COPY_CHANGED_SINCE_LAST_RUN",
                       detail="evaluation describes the PRIOR Last Run, not the current Working Copy")
    return _unavailable("FRESHNESS_NOT_DETERMINED" if state not in ("NOT_RUN",) else "NO_LAST_RUN")


def financing_evidence_bound(ctx: Context) -> Outcome:
    fe = ctx.summary.get("financing_evidence")
    binding = fe.get("run_binding") if isinstance(fe, Mapping) else None
    if not isinstance(binding, Mapping):
        return _unavailable("FINANCING_EVIDENCE_NOT_BOUND", "legacy Run without run-bound financing evidence")
    ev = ctx.ev
    mismatches = [name for name, mine in (("snapshot_id", ev.snapshot_id), ("composite_hash", ev.composite_hash),
                                           ("scenario_id", ev.last_run_scenario_id))
                  if binding.get(name) != mine]
    if mismatches:
        return Outcome(CheckStatus.FAIL, "FINANCING_EVIDENCE_NOT_BOUND_TO_THIS_RUN", detail="differs: " + ", ".join(mismatches))
    return Outcome(CheckStatus.PASS, None, detail="financing evidence is bound to this exact Run")


def scenario_identity(ctx: Context) -> Outcome:
    ev = ctx.ev
    if not ev.scenario_known:
        return _unavailable("ACTIVE_SCENARIO_NOT_SUPPLIED")
    if ev.active_scenario_id == ev.last_run_scenario_id:
        return Outcome(CheckStatus.PASS, None, detail="Last Run was produced under the active scenario")
    return Outcome(CheckStatus.WARNING, "ACTIVE_SCENARIO_DIFFERS_FROM_LAST_RUN",
                   detail="the active scenario is not the scenario the Last Run was produced under")
