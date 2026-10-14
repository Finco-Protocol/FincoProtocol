"""Diagnostics V2 advanced financial checks (``DX-*``): period-level identities over COMMITTED Run evidence.

These are NOT Model Quality registry checks: they never change the Quality score, coverage percentages or the
30 stable ``QM-*`` identities.  They are a separate, additive diagnostic family with their own stable ids.

Rules enforced here (and pinned by tests):
* evidence only: statements, schedules and Run Integrity evidence persisted with the committed Run; no engine call,
  no Working Copy value, no editable CAPEX/OPEX reconstruction of an older Run;
* a period is evaluated only from rows joined by the committed period index (and equal dates where both rows carry
  one); a missing row, term or digest mismatch is ``UNAVAILABLE`` with an exact reason - never zero, never PASS;
* ``NOT_APPLICABLE`` only when the committed evidence itself proves it (an explicit phase flag, all-zero committed
  balances and flows, an explicit reserve regime);
* no balancing plug: the residual is the signed difference ``observed - expected`` of a stated identity;
* tolerance sources: ``TOL_KEUR`` (Run Integrity, full-precision evidence) plus, only for values the product persists
  rounded to 2 decimals, a half-quantum representation allowance per non-zero rounded term - reported, never hidden.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

from app.run_integrity.contracts import TOL_KEUR

SCHEMA = "model-diagnostics-v2-dx-1"
QUANTUM_2DP = 0.005

PASS, FAIL, WARNING, UNAVAILABLE, NOT_APPLICABLE = "PASS", "FAIL", "WARNING", "UNAVAILABLE", "NOT_APPLICABLE"
FULL, ROUNDED = "FULL_PRECISION", "PERSISTED_2DP"

# Per-check classification of the evidence behind it (see docs/model_v2/MODEL_DIAGNOSTICS_V2.md).
PERIODIC_PROVEN = "PERIODIC_PROVEN"


@dataclass(frozen=True)
class DxDefinition:
    check_id: str
    family: str                  # heatmap group
    title: str
    definition: str
    severity: str                # CRITICAL | HIGH | MEDIUM | LOW
    prerequisites: tuple[str, ...]
    tolerance_source: str
    evidence_source: str
    navigation_target: str
    related_assumptions: tuple[str, ...] = ()
    related_checks: tuple[str, ...] = ()
    classification: str = PERIODIC_PROVEN


DEFINITIONS: tuple[DxDefinition, ...] = (
    DxDefinition(
        "DX-CAPEX-001", "CAPEX/OPEX", "Construction spending against authoritative total uses",
        "Per construction period: spending is non-negative and the cumulative spending never exceeds the total Project "
        "Uses authority less the recorded Financial Close non-construction use; at the last construction period "
        "cumulative spending plus that use equals total Uses (residual = total Uses - cumulative - non-construction use).",
        "HIGH", ("integrity_evidence.sources_uses.construction_periods", "integrity_evidence.sources_uses.summary.total_uses_keur",
                 "runtime_summary.financing_evidence.construction_funding.non_construction_fc_use.uses_keur"),
        "TOL_KEUR (full precision, Run Integrity)", "run_integrity_evidence.sources_uses + runtime_summary.financing_evidence",
        "tab-sources-uses", ("capex.summary.total",), ("QM-SU-001", "QM-SU-002")),
    DxDefinition(
        "DX-OPEX-001", "CAPEX/OPEX", "Operating cost, EBITDA and EBIT statement reconciliation",
        "Per period: P&L operating expenses equal cash-waterfall OPEX; cash EBITDA = cash revenue - cash OPEX; "
        "EBIT = revenue - OPEX - depreciation. Capital expenditure, financing costs and tax are different lines and are "
        "shown separately, never netted into operating cost.",
        "HIGH", ("financial_statements.pnl", "financial_statements.pf_cash_waterfall"),
        "TOL_KEUR + half-quantum per non-zero 2dp statement term", "financial_statements.pnl + pf_cash_waterfall",
        "tab-fs", ("opex.summary.total_y1",), ("QM-ACC-003",)),
    DxDefinition(
        "DX-DEP-001", "Accounting", "Accumulated depreciation roll-forward",
        "Per period with an adjacent committed opening: accumulated depreciation(closing) - accumulated depreciation(opening) "
        "= P&L depreciation; and gross fixed assets - accumulated depreciation = net fixed assets. Fixed-asset additions "
        "and disposals have no independent committed evidence and are NOT inferred.",
        "MEDIUM", ("integrity_evidence.balance_sheet", "financial_statements.pnl", "financial_statements.balance_sheet"),
        "TOL_KEUR + half-quantum per non-zero 2dp statement term", "run_integrity_evidence.balance_sheet + statements",
        "tab-fs", (), ("QM-ACC-001",)),
    DxDefinition(
        "DX-CASH-001", "Cash Flow", "Distributable cash after debt service and reserve movements",
        "Per operating period: cash available for distribution = CFADS - Senior debt service - Junior debt service "
        "(only where a Junior facility is part of the committed financing authority) - DSRA funding + DSRA release. "
        "Project cash only: shareholder and restricted-cash balances are not mixed in.",
        "HIGH", ("financial_statements.pf_cash_waterfall", "tax_schedule.periods.is_operation"),
        "TOL_KEUR + half-quantum per non-zero 2dp statement term", "financial_statements.pf_cash_waterfall",
        "tab-fs", ("debt.senior.target_dscr",), ("QM-CASH-001", "QM-SD-003")),
    DxDefinition(
        "DX-SHL-001", "SHL", "Shareholder loan balance roll-forward including capitalised interest",
        "Per operating period with adjacent committed balances: closing = opening + drawdown + capitalised interest - "
        "principal repaid, where capitalised interest = P&L SHL interest accrual - cash interest paid. All-zero committed "
        "SHL balances and flows make the check NOT_APPLICABLE; a missing accrual line is UNAVAILABLE.",
        "HIGH", ("integrity_evidence.balance_sheet.shl", "integrity_evidence.sponsor.periods", "financial_statements.pnl.shl_interest_expense_keur"),
        "TOL_KEUR + half-quantum for the 2dp P&L accrual", "run_integrity_evidence + pnl",
        "tab-returns", ("shl.interest_rate", "shl.maturity"), ("QM-TERM-002", "QM-ACC-002")),
    DxDefinition(
        "DX-SHL-002", "SHL", "SHL contractual-maturity evidence is consistent",
        "At the committed contractual-maturity period the committed balance sheet SHL balance equals the canonical "
        "terminal-state balance; an unpaid maturity balance is reported as the canonical status (a risk, not a mismatch).",
        "HIGH", ("sponsor_schedule.summary.terminal_financial_state.shareholder_loan", "integrity_evidence.balance_sheet.shl"),
        "TOL_KEUR (cross-source consistency)", "sponsor_schedule.summary + run_integrity_evidence",
        "tab-returns", ("shl.maturity",), ("QM-TERM-002",)),
    DxDefinition(
        "DX-DIST-001", "Cash Flow", "Distributions stay within distributable cash and the model's own lock-up gate",
        "Per period: committed net dividends do not exceed cash available for distribution; no distribution is paid in a "
        "period the committed distribution schedule flags as lock-up; the sponsor legal-equity distribution equals the "
        "cash-waterfall dividend. No contractual lock-up rule is invented.",
        "HIGH", ("financial_statements.pf_cash_waterfall", "distribution_schedule.periods.lockup_active",
                 "integrity_evidence.sponsor.periods"),
        "TOL_KEUR + half-quantum per non-zero 2dp statement term", "pf_cash_waterfall + distribution_schedule + sponsor",
        "tab-returns", ("debt.senior.lockup_dscr",), ("QM-COV-003",)),
    DxDefinition(
        "DX-RES-001", "Reserves", "Cash DSRA balance roll-forward",
        "Per operating period: closing DSRA = opening + funding - release, where a single movement that is not explained "
        "by the cash-waterfall funding/release lines must equal the Financial Close initial DSRA funding recorded in "
        "Sources & Uses. A standby DSRF or an explicit no-reserve regime is NOT a cash balance; unproven structure with "
        "zero balances is UNAVAILABLE, never compliance.",
        "HIGH", ("integrity_evidence.balance_sheet.dsra_balance", "financial_statements.pf_cash_waterfall.dsra_*",
                 "integrity_evidence.sources_uses.summary.initial_dsra_funding_keur", "terms.reserve_regime (Quality evidence)"),
        "TOL_KEUR + half-quantum per non-zero 2dp statement term", "run_integrity_evidence + pf_cash_waterfall",
        "tab-debt", ("financing.dsra_support_mode", "financing.debt_service_reserve_requirement_keur"), ("QM-CASH-002",)),
    DxDefinition(
        "DX-REV-001", "Revenue", "Revenue statement and contracted-component reconciliation",
        "Per period: P&L revenue equals cash-waterfall revenue; where the Run carries Revenue V2 contract evidence, net "
        "revenue = sum of stream revenue - balancing cost + legacy certificate revenue, and equals the P&L revenue. "
        "Revenue V3 is release-closed and is never read.",
        "MEDIUM", ("financial_statements.pnl.revenues_keur", "financial_statements.pf_cash_waterfall.revenue_cash_keur",
                   "runtime_summary.revenue_multistream_audit (optional)"),
        "TOL_KEUR + half-quantum per non-zero 2dp statement term", "financial_statements + runtime_summary.revenue_multistream_audit",
        "tab-revenue", ("revenue.ppa.base_tariff",), ("QM-ACC-003",)),
)
DEFINITION_BY_ID = {d.check_id: d for d in DEFINITIONS}


# ── evidence access ───────────────────────────────────────────────────────────────────────────────────────────
def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if math.isfinite(f) else None


def _rows(container: Any, *path: str) -> list[Mapping]:
    for key in path:
        container = container.get(key) if isinstance(container, Mapping) else None
    if isinstance(container, Mapping):
        container = container.get("periods")
    return [r for r in container if isinstance(r, Mapping)] if isinstance(container, list) else []


def _index(row: Mapping, *keys: str) -> Optional[int]:
    for key in keys or ("period_index", "period"):
        value = row.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _by_index(rows: list[Mapping], *keys: str) -> tuple[dict[int, Mapping], set[int]]:
    """Rows keyed by committed period index; indices that occur more than once are returned as duplicates."""
    out: dict[int, Mapping] = {}
    dup: set[int] = set()
    for row in rows:
        i = _index(row, *keys)
        if i is None:
            continue
        if i in out:
            dup.add(i)
        out[i] = row
    return out, dup


@dataclass
class Facts:
    """Typed, read-only view over ONE committed Run's persisted payloads."""

    pnl: dict[int, Mapping]
    pf: dict[int, Mapping]
    bs: dict[int, Mapping]
    ibs: dict[int, Mapping]
    sponsor: dict[int, Mapping]
    dist: dict[int, Mapping]
    phase: dict[int, bool]                 # period index -> is_operation, from the committed tax schedule
    su: Mapping
    summary: Mapping
    sponsor_summary: Mapping
    audit: list[Mapping]
    digest_ok: bool
    junior_applicable: bool
    reserve_regime: Optional[str]
    duplicates: set[str] = field(default_factory=set)         # evidence sources with a repeated period key

    @classmethod
    def from_workspace(cls, ws: Any, *, digest_ok: bool, reserve_regime: Optional[str] = None) -> "Facts":
        statements = getattr(ws, "last_financial_statements", None) or {}
        ev = getattr(ws, "last_integrity_evidence", None) or {}
        pnl, d1 = _by_index(_rows(statements, "pnl"), "period", "period_index")
        pf, d2 = _by_index(_rows(statements, "pf_cash_waterfall"), "period_index", "period")
        bs, d3 = _by_index(_rows(statements, "balance_sheet"), "period_index", "period")
        ibs, d4 = _by_index(_rows(ev, "balance_sheet"), "period_index")
        # Sponsor rows are keyed by ISO DATE: their own period index can collide with the statement axis (F3.9).
        sponsor: dict[Any, Mapping] = {}
        d5: set[Any] = set()
        for row in _rows(ev, "sponsor"):
            key = str(row.get("date") or "") or None
            if key is None:
                continue
            if key in sponsor:
                d5.add(key)
            sponsor[key] = row
        dist, d6 = _by_index(_rows(getattr(ws, "last_distribution_schedule", None) or {}), "period", "period_index")
        phase: dict[int, bool] = {}
        for row in _rows(getattr(ws, "last_tax_schedule", None) or {}):
            i, flag = _index(row, "period", "period_index"), row.get("is_operation")
            if i is not None and isinstance(flag, bool):
                phase[i] = flag
        summary = getattr(ws, "last_runtime_summary", None) or {}
        sp = (getattr(ws, "last_sponsor_schedule", None) or {})
        sp_summary = sp.get("summary") if isinstance(sp, Mapping) and isinstance(sp.get("summary"), Mapping) else {}
        audit = summary.get("revenue_multistream_audit") if isinstance(summary, Mapping) else None
        authority = str(ev.get("financing_authority") or "") if isinstance(ev, Mapping) else ""
        junior = bool(isinstance(ev, Mapping) and (ev.get("junior_debt") or "JUNIOR" in authority.upper()))
        return cls(pnl=pnl, pf=pf, bs=bs, ibs=ibs, sponsor=sponsor, dist=dist, phase=phase,
                   su=ev.get("sources_uses") if isinstance(ev.get("sources_uses"), Mapping) else {},
                   summary=summary if isinstance(summary, Mapping) else {}, sponsor_summary=sp_summary,
                   audit=[r for r in audit if isinstance(r, Mapping)] if isinstance(audit, list) else [],
                   digest_ok=digest_ok, junior_applicable=junior, reserve_regime=reserve_regime,
                   duplicates={name for name, dup in (("pnl", d1), ("pf", d2), ("bs", d3), ("ibs", d4),
                                                      ("sponsor", d5), ("dist", d6)) if dup})

    def sp(self, index: int) -> Optional[Mapping]:
        """Sponsor row for a statement period, joined by ISO date (never by the sponsor's own index)."""
        d = self.date(index)
        return self.sponsor.get(d) if d else None

    def date(self, index: int) -> Optional[str]:
        for source in (self.pf, self.pnl, self.bs):
            row = source.get(index)
            if row and row.get("date"):
                return str(row["date"])
        return None

    def indices(self) -> list[int]:
        return sorted(set(self.pf) | set(self.pnl) | set(self.bs) | set(self.ibs))


def _same_dates(*rows: Optional[Mapping]) -> bool:
    dates = {str(r.get("date")) for r in rows if r is not None and r.get("date")}
    return len(dates) <= 1


# ── period result helpers ─────────────────────────────────────────────────────────────────────────────────────
def _comp(value: Optional[float], source: str, basis: str) -> dict[str, Any]:
    return {"value": value, "source": source, "basis": basis}


def _tol(rounded_terms: list[Optional[float]], *, full_only: bool = False) -> float:
    if full_only:
        return TOL_KEUR
    return TOL_KEUR + QUANTUM_2DP * sum(1 for v in rounded_terms if v is not None and v != 0)


def _period(index: int, facts: Facts, status: str, *, reason: Optional[str] = None, observed: Optional[float] = None,
            expected: Optional[float] = None, tolerance: Optional[float] = None, scope: str = "PERIOD",
            components: Optional[Mapping[str, Any]] = None, residual: Optional[float] = None) -> dict[str, Any]:
    if residual is None and observed is not None and expected is not None:
        residual = observed - expected
    return {"period_index": index, "date": facts.date(index), "status": status, "scope": scope, "reason": reason,
            "observed": observed, "expected": expected, "residual": residual, "tolerance": tolerance,
            "components": dict(components or {})}


def _verdict(index: int, facts: Facts, identities: list[tuple[str, float, float, float]],
             components: Mapping[str, Any], scope: str = "PERIOD") -> dict[str, Any]:
    """Several identities in one period: FAIL if any residual exceeds its allowance; report the worst residual."""
    worst = max(identities, key=lambda it: abs(it[1] - it[2]) - it[3])
    status = FAIL if any(abs(o - e) > t for _n, o, e, t in identities) else PASS
    name, observed, expected, tolerance = worst
    comps = dict(components)
    comps["identity_evaluated"] = {"value": name, "source": "stated identity", "basis": "TEXT"}
    return _period(index, facts, status, observed=observed, expected=expected, tolerance=tolerance,
                   components=comps, scope=scope, reason=None if status == PASS else f"IDENTITY_RESIDUAL_OUTSIDE_TOLERANCE:{name}")


def _aggregate(periods: list[dict[str, Any]]) -> tuple[str, Optional[str], dict[str, Any]]:
    counts = {s: sum(1 for p in periods if p["status"] == s) for s in (PASS, FAIL, WARNING, UNAVAILABLE, NOT_APPLICABLE)}
    applicable = counts[PASS] + counts[FAIL] + counts[WARNING] + counts[UNAVAILABLE]
    coverage = {"counts": counts, "applicable_periods": applicable, "evaluated_periods": counts[PASS] + counts[FAIL] + counts[WARNING],
                "complete": applicable > 0 and counts[UNAVAILABLE] == 0}
    if counts[FAIL]:
        return FAIL, "PERIOD_IDENTITY_FAILED", coverage
    if counts[WARNING]:
        return WARNING, "PERIOD_WARNING", coverage
    if counts[PASS]:
        return PASS, ("PARTIAL_COVERAGE_SOME_PERIODS_UNAVAILABLE" if counts[UNAVAILABLE] else None), coverage
    if counts[UNAVAILABLE]:
        reasons = sorted({p["reason"] for p in periods if p["status"] == UNAVAILABLE and p["reason"]})
        return UNAVAILABLE, (reasons[0] if len(reasons) == 1 else "EVIDENCE_MISSING"), coverage
    if periods:
        reasons = sorted({p["reason"] for p in periods if p["reason"]})
        return NOT_APPLICABLE, (reasons[0] if reasons else None), coverage
    return UNAVAILABLE, "NO_PERIOD_EVIDENCE", coverage


# ── evaluators ────────────────────────────────────────────────────────────────────────────────────────────────
def _unavailable_all(facts: Facts, reason: str, indices: Optional[list[int]] = None) -> list[dict[str, Any]]:
    return [_period(i, facts, UNAVAILABLE, reason=reason) for i in (indices if indices is not None else facts.indices())]


def _eval_capex(facts: Facts) -> tuple[list[dict], Optional[dict]]:
    su = facts.su
    rows = su.get("construction_periods") if isinstance(su.get("construction_periods"), list) else []
    rows = [r for r in rows if isinstance(r, Mapping) and _index(r, "period") is not None]
    if not rows:
        return [], {"status": UNAVAILABLE, "reason": "CONSTRUCTION_PERIOD_EVIDENCE_MISSING"}
    total = _num((su.get("summary") or {}).get("total_uses_keur"))
    nc = ((facts.summary.get("financing_evidence") or {}).get("construction_funding") or {}).get("non_construction_fc_use")
    nc_uses = _num(nc.get("uses_keur")) if isinstance(nc, Mapping) else None
    nc_source = "runtime_summary.financing_evidence.construction_funding.non_construction_fc_use.uses_keur"
    if nc_uses is None:
        # No separate Financial Close record: the only committed non-construction use is the initial DSRA funding in
        # Sources & Uses. If anything else were funded outside construction, the terminal identity below FAILS.
        nc_uses = _num((su.get("summary") or {}).get("initial_dsra_funding_keur"))
        nc_source = "sources_uses.summary.initial_dsra_funding_keur"
    out: list[dict] = []
    cumulative = 0.0
    ordered = sorted(rows, key=lambda r: _index(r, "period"))
    last = _index(ordered[-1], "period")
    for row in ordered:
        i = _index(row, "period")
        if not facts.digest_ok:
            out.append(_period(i, facts, UNAVAILABLE, reason="EVIDENCE_DIGEST_NOT_INTACT"))
            continue
        amount = _num(row.get("uses"))
        if amount is None or total is None or nc_uses is None:
            reason = ("PERIOD_USES_MISSING" if amount is None else "TOTAL_USES_AUTHORITY_MISSING" if total is None
                      else "NON_CONSTRUCTION_FC_USE_EVIDENCE_MISSING")
            out.append(_period(i, facts, UNAVAILABLE, reason=reason))
            cumulative = float("nan")
            continue
        cumulative += amount
        budget = total - nc_uses
        comps = {"period_spending": _comp(amount, "sources_uses.construction_periods.uses", FULL),
                 "cumulative_spending": _comp(cumulative, "running sum of committed construction uses", FULL),
                 "total_uses_authority": _comp(total, "sources_uses.summary.total_uses_keur", FULL),
                 "non_construction_fc_use": _comp(nc_uses, nc_source, FULL),
                 "remaining_budget": _comp(budget - cumulative, "total uses - non-construction use - cumulative", FULL)}
        negative, over = amount < -TOL_KEUR, cumulative > budget + TOL_KEUR
        if i == last:
            residual = total - cumulative - nc_uses
            status = FAIL if (negative or over or abs(residual) > TOL_KEUR) else PASS
            out.append(_period(i, facts, status, observed=cumulative + nc_uses, expected=total, tolerance=TOL_KEUR,
                               components=comps, scope="PERIOD_AND_TERMINAL_IDENTITY",
                               reason=None if status == PASS else "SPENDING_OR_TERMINAL_RESIDUAL_OUTSIDE_TOLERANCE"))
        else:
            out.append(_period(i, facts, FAIL if (negative or over) else PASS, observed=cumulative, expected=budget,
                               tolerance=TOL_KEUR, components=comps, residual=(cumulative - budget) if over else 0.0,
                               reason="NEGATIVE_OR_OVERSPENT" if (negative or over) else None))
    return out, None


def _eval_opex(facts: Facts) -> tuple[list[dict], Optional[dict]]:
    out = []
    for i in facts.indices():
        pnl, pf = facts.pnl.get(i), facts.pf.get(i)
        if pnl is None or pf is None:
            out.append(_period(i, facts, UNAVAILABLE, reason="STATEMENT_ROW_MISSING"))
            continue
        if not _same_dates(pnl, pf):
            out.append(_period(i, facts, UNAVAILABLE, reason="STATEMENT_DATES_DISAGREE"))
            continue
        v = {k: _num(pnl.get(k)) for k in ("revenues_keur", "operating_expenses_keur", "depreciation_keur", "ebit_keur")}
        c = {k: _num(pf.get(k)) for k in ("revenue_cash_keur", "opex_cash_keur", "ebitda_cash_keur")}
        if None in v.values() or None in c.values():
            out.append(_period(i, facts, UNAVAILABLE, reason="STATEMENT_LINE_MISSING"))
            continue
        comps = {"operating_expenses_pnl": _comp(v["operating_expenses_keur"], "pnl.operating_expenses_keur", ROUNDED),
                 "operating_expenses_cash": _comp(c["opex_cash_keur"], "pf_cash_waterfall.opex_cash_keur", ROUNDED),
                 "depreciation": _comp(v["depreciation_keur"], "pnl.depreciation_keur", ROUNDED),
                 "senior_interest_financing_cost": _comp(_num(pnl.get("senior_interest_expense_keur")), "pnl.senior_interest_expense_keur", ROUNDED),
                 "shl_interest_financing_cost": _comp(_num(pnl.get("shl_interest_expense_keur")), "pnl.shl_interest_expense_keur", ROUNDED),
                 "cash_tax": _comp(_num(pf.get("cash_tax_keur")), "pf_cash_waterfall.cash_tax_keur", ROUNDED)}
        ids = [("OPEX(P&L) = OPEX(cash)", v["operating_expenses_keur"], c["opex_cash_keur"],
                _tol([v["operating_expenses_keur"], c["opex_cash_keur"]])),
               ("EBITDA = revenue - OPEX", c["ebitda_cash_keur"], c["revenue_cash_keur"] - c["opex_cash_keur"],
                _tol([c["ebitda_cash_keur"], c["revenue_cash_keur"], c["opex_cash_keur"]])),
               ("EBIT = revenue - OPEX - depreciation", v["ebit_keur"],
                v["revenues_keur"] - v["operating_expenses_keur"] - v["depreciation_keur"],
                _tol(list(v.values())))]
        out.append(_verdict(i, facts, ids, comps))
    return out, None


def _eval_dep(facts: Facts) -> tuple[list[dict], Optional[dict]]:
    glob = {"additions_and_disposals": "UNAVAILABLE - no independent fixed-asset additions or disposals evidence is committed; none is inferred"}
    if not facts.digest_ok:
        return _unavailable_all(facts, "EVIDENCE_DIGEST_NOT_INTACT"), glob
    out = []
    for i in facts.indices():
        cur, prev = facts.ibs.get(i), facts.ibs.get(i - 1)
        pnl, bs = facts.pnl.get(i), facts.bs.get(i)
        if cur is None or prev is None:
            out.append(_period(i, facts, UNAVAILABLE, reason="ADJACENT_OPENING_BALANCE_MISSING" if cur is not None else "BALANCE_SHEET_PERIOD_MISSING"))
            continue
        close_a, open_a, dep = _num(cur.get("accumulated_depreciation")), _num(prev.get("accumulated_depreciation")), _num((pnl or {}).get("depreciation_keur"))
        gross, nfa = _num(cur.get("gross_fixed_assets")), _num((bs or {}).get("net_fixed_assets_keur"))
        if None in (close_a, open_a, dep, gross, nfa) or not _same_dates(pnl, bs):
            out.append(_period(i, facts, UNAVAILABLE, reason="DEPRECIATION_EVIDENCE_MISSING"))
            continue
        comps = {"opening_accumulated_depreciation": _comp(open_a, "integrity_evidence.balance_sheet[i-1].accumulated_depreciation", FULL),
                 "depreciation_charge": _comp(dep, "pnl.depreciation_keur", ROUNDED),
                 "closing_accumulated_depreciation": _comp(close_a, "integrity_evidence.balance_sheet[i].accumulated_depreciation", FULL),
                 "gross_fixed_assets": _comp(gross, "integrity_evidence.balance_sheet[i].gross_fixed_assets", FULL),
                 "net_fixed_assets_statement": _comp(nfa, "balance_sheet.net_fixed_assets_keur", ROUNDED)}
        ids = [("closing - opening accumulated depreciation = charge", close_a - open_a, dep, _tol([dep])),
               ("gross fixed assets - accumulated depreciation = net fixed assets", gross - close_a, nfa, _tol([nfa]))]
        out.append(_verdict(i, facts, ids, comps))
    return out, glob


def _construction(facts: Facts, i: int) -> Optional[bool]:
    flag = facts.phase.get(i)
    return None if flag is None else (not flag)


def _eval_cash(facts: Facts) -> tuple[list[dict], Optional[dict]]:
    out = []
    for i in facts.indices():
        pf = facts.pf.get(i)
        if pf is None:
            out.append(_period(i, facts, UNAVAILABLE, reason="CASH_WATERFALL_ROW_MISSING"))
            continue
        if _construction(facts, i) is True:
            out.append(_period(i, facts, NOT_APPLICABLE, reason="CONSTRUCTION_PHASE_NO_OPERATING_WATERFALL"))
            continue
        t = {k: _num(pf.get(k)) for k in ("fcf_banks_keur", "senior_total_ds_keur", "dsra_funding_keur", "dsra_release_keur", "fcf_for_distribution_keur")}
        junior = _num(pf.get("junior_debt_service_keur"))
        if facts.junior_applicable and junior is None:
            out.append(_period(i, facts, UNAVAILABLE, reason="JUNIOR_DEBT_SERVICE_LINE_MISSING"))
            continue
        if None in t.values():
            out.append(_period(i, facts, UNAVAILABLE, reason="CASH_WATERFALL_LINE_MISSING"))
            continue
        jd = junior if facts.junior_applicable else 0.0
        expected = t["fcf_banks_keur"] - t["senior_total_ds_keur"] - jd - t["dsra_funding_keur"] + t["dsra_release_keur"]
        terms = [t["fcf_banks_keur"], t["senior_total_ds_keur"], t["dsra_funding_keur"], t["dsra_release_keur"], t["fcf_for_distribution_keur"]]
        if facts.junior_applicable:
            terms.append(junior)
        comps = {"cfads": _comp(t["fcf_banks_keur"], "pf_cash_waterfall.fcf_banks_keur", ROUNDED),
                 "senior_debt_service": _comp(t["senior_total_ds_keur"], "pf_cash_waterfall.senior_total_ds_keur", ROUNDED),
                 "junior_debt_service": _comp(junior if facts.junior_applicable else None, "pf_cash_waterfall.junior_debt_service_keur", ROUNDED),
                 "dsra_funding": _comp(t["dsra_funding_keur"], "pf_cash_waterfall.dsra_funding_keur", ROUNDED),
                 "dsra_release": _comp(t["dsra_release_keur"], "pf_cash_waterfall.dsra_release_keur", ROUNDED),
                 "cash_available_for_distribution": _comp(t["fcf_for_distribution_keur"], "pf_cash_waterfall.fcf_for_distribution_keur", ROUNDED)}
        out.append(_verdict(i, facts, [("distributable cash = CFADS - debt service - reserve funding + release",
                                        t["fcf_for_distribution_keur"], expected, _tol(terms))], comps))
    glob = {"closing_cash_roll_forward": "UNAVAILABLE - the committed evidence has no complete shareholder, restricted and distribution-account cash flows; closing cash is not reconstructed"}
    return out, glob


def _eval_shl(facts: Facts) -> tuple[list[dict], Optional[dict]]:
    if not facts.digest_ok:
        return _unavailable_all(facts, "EVIDENCE_DIGEST_NOT_INTACT"), None
    balances = [_num(r.get("shl")) for r in facts.ibs.values()]
    flows = [(_num(r.get("shl_contribution")), _num(r.get("shl_cash_interest")), _num(r.get("shl_principal")))
             for r in facts.sponsor.values()]
    funded = _num((facts.su.get("summary") or {}).get("shareholder_loan_cash_keur"))
    # Explicit committed zeros prove "no SHL": every present balance is zero, every flow is present and zero, and the
    # committed Sources & Uses records zero SHL cash funding. A missing value alone never proves it.
    if (balances and flows and funded is not None and abs(funded) <= TOL_KEUR
            and all(b is None or abs(b) <= TOL_KEUR for b in balances)
            and all(x is not None and abs(x) <= TOL_KEUR for tup in flows for x in tup)):
        return [_period(i, facts, NOT_APPLICABLE, reason="NO_SHL_COMMITTED_ZERO_FUNDING_BALANCES_AND_FLOWS") for i in facts.indices()], None
    out = []
    for i in facts.indices():
        sp, cur, prev, pnl = facts.sp(i), facts.ibs.get(i), facts.ibs.get(i - 1), facts.pnl.get(i)
        if sp is None:
            out.append(_period(i, facts, UNAVAILABLE, reason="SPONSOR_PERIOD_MISSING"))
            continue
        if sp.get("is_construction") is True:
            out.append(_period(i, facts, NOT_APPLICABLE, reason="CONSTRUCTION_PHASE_SHL_DRAWN_AT_FINANCIAL_CLOSE"))
            continue
        opening, closing = _num((prev or {}).get("shl")), _num((cur or {}).get("shl"))
        draw, cash_int, principal = _num(sp.get("shl_contribution")), _num(sp.get("shl_cash_interest")), _num(sp.get("shl_principal"))
        accrual = _num((pnl or {}).get("shl_interest_expense_keur"))
        if opening is None or closing is None:
            out.append(_period(i, facts, UNAVAILABLE, reason="ADJACENT_SHL_BALANCE_NOT_PRESENTED"))
            continue
        if None in (draw, cash_int, principal):
            out.append(_period(i, facts, UNAVAILABLE, reason="SHL_FLOW_MISSING"))
            continue
        if accrual is None or not _same_dates(pnl, sp):
            out.append(_period(i, facts, UNAVAILABLE, reason="SHL_INTEREST_ACCRUAL_EVIDENCE_MISSING"))
            continue
        capitalised = accrual - cash_int
        expected = opening + draw + capitalised - principal
        comps = {"opening_principal": _comp(opening, "integrity_evidence.balance_sheet[i-1].shl", FULL),
                 "drawdown": _comp(draw, "integrity_evidence.sponsor.shl_contribution", FULL),
                 "interest_accrual": _comp(accrual, "pnl.shl_interest_expense_keur", ROUNDED),
                 "cash_pay_interest": _comp(cash_int, "integrity_evidence.sponsor.shl_cash_interest", FULL),
                 "capitalised_interest": _comp(capitalised, "accrual - cash interest (derived from two committed lines)", ROUNDED),
                 "principal_repaid": _comp(principal, "integrity_evidence.sponsor.shl_principal", FULL),
                 "closing_balance": _comp(closing, "integrity_evidence.balance_sheet[i].shl", FULL)}
        out.append(_verdict(i, facts, [("closing = opening + draw + capitalised interest - principal", closing, expected,
                                         _tol([accrual]))], comps))
    return out, None


def _eval_shl_maturity(facts: Facts) -> tuple[list[dict], Optional[dict]]:
    terminal = (facts.sponsor_summary.get("terminal_financial_state") or {})
    shl = terminal.get("shareholder_loan") if isinstance(terminal, Mapping) else None
    if not isinstance(shl, Mapping):
        return [], {"status": UNAVAILABLE, "reason": "TERMINAL_STATE_EVIDENCE_MISSING"}
    status = shl.get("status")
    index = shl.get("contractual_maturity_period_index")
    if status == "NOT_APPLICABLE":
        return [], {"status": NOT_APPLICABLE, "reason": "CANONICAL_TERMINAL_STATE_NO_SHL"}
    if not isinstance(index, int) or isinstance(index, bool):
        return [], {"status": UNAVAILABLE, "reason": "CONTRACTUAL_MATURITY_PERIOD_MISSING"}
    if not facts.digest_ok:
        return [_period(index, facts, UNAVAILABLE, reason="EVIDENCE_DIGEST_NOT_INTACT")], None
    reported = _num(shl.get("balance_at_contractual_maturity_keur"))
    committed = _num((facts.ibs.get(index) or {}).get("shl"))
    unpaid = _num(shl.get("unpaid_at_maturity_keur"))
    if reported is None or committed is None:
        return [_period(index, facts, UNAVAILABLE, reason="MATURITY_BALANCE_EVIDENCE_MISSING")], None
    comps = {"canonical_status": _comp(None, "terminal_financial_state.shareholder_loan.status=" + str(status), "TEXT"),
             "balance_at_contractual_maturity": _comp(reported, "terminal_financial_state.shareholder_loan.balance_at_contractual_maturity_keur", FULL),
             "committed_balance_sheet_balance": _comp(committed, "integrity_evidence.balance_sheet[maturity].shl", FULL),
             "unpaid_at_maturity": _comp(unpaid, "terminal_financial_state.shareholder_loan.unpaid_at_maturity_keur", FULL),
             "repayment_mode": _comp(None, "terminal_financial_state.shareholder_loan.repayment_mode=" + str(shl.get("repayment_mode")), "TEXT")}
    if abs(committed - reported) > TOL_KEUR:
        return [_period(index, facts, FAIL, observed=committed, expected=reported, tolerance=TOL_KEUR, components=comps,
                        scope="CONTRACTUAL_MATURITY_POINT", reason="BALANCE_SHEET_DISAGREES_WITH_CANONICAL_TERMINAL_STATE")], None
    if status == "UNPAID_AT_CONTRACTUAL_MATURITY":
        return [_period(index, facts, WARNING, observed=committed, expected=reported, tolerance=TOL_KEUR, components=comps,
                        scope="CONTRACTUAL_MATURITY_POINT",
                        reason="CANONICAL_STATUS_UNPAID_AT_CONTRACTUAL_MATURITY (financing risk per the original obligation, not a mismatch)")], None
    return [_period(index, facts, PASS, observed=committed, expected=reported, tolerance=TOL_KEUR, components=comps,
                    scope="CONTRACTUAL_MATURITY_POINT")], None


def _eval_dist(facts: Facts) -> tuple[list[dict], Optional[dict]]:
    out = []
    for i in facts.indices():
        pf = facts.pf.get(i)
        if pf is None:
            out.append(_period(i, facts, UNAVAILABLE, reason="CASH_WATERFALL_ROW_MISSING"))
            continue
        if _construction(facts, i) is True:
            out.append(_period(i, facts, NOT_APPLICABLE, reason="CONSTRUCTION_PHASE_NO_OPERATING_DISTRIBUTIONS"))
            continue
        paid, available = _num(pf.get("net_dividends_keur")), _num(pf.get("fcf_for_distribution_keur"))
        d = facts.dist.get(i)
        lock = d.get("lockup_active") if d is not None else None
        if paid is None or available is None or not isinstance(lock, bool):
            out.append(_period(i, facts, UNAVAILABLE, reason="DISTRIBUTION_OR_LOCKUP_EVIDENCE_MISSING"))
            continue
        legal = _num((facts.sp(i) or {}).get("legal_equity_distribution")) if facts.digest_ok else None
        comps = {"net_dividends": _comp(paid, "pf_cash_waterfall.net_dividends_keur", ROUNDED),
                 "cash_available_for_distribution": _comp(available, "pf_cash_waterfall.fcf_for_distribution_keur", ROUNDED),
                 "lockup_active_committed_flag": {"value": lock, "source": "distribution_schedule.lockup_active", "basis": "FLAG"},
                 "sponsor_legal_equity_distribution": _comp(legal, "integrity_evidence.sponsor.legal_equity_distribution", FULL)}
        tol_cap = _tol([paid, available])
        problems = []
        if paid - available > tol_cap:
            problems.append("DISTRIBUTION_EXCEEDS_CASH_AVAILABLE")
        if lock and paid >= QUANTUM_2DP:
            problems.append("DISTRIBUTION_PAID_IN_COMMITTED_LOCKUP_PERIOD")
        if legal is not None and abs(legal - paid) > _tol([paid]):
            problems.append("SPONSOR_DISTRIBUTION_DISAGREES_WITH_CASH_WATERFALL")
        excess = max(paid - available, 0.0)
        status = FAIL if problems else PASS
        out.append(_period(i, facts, status, observed=paid, expected=min(paid, available) if not lock else 0.0,
                           tolerance=tol_cap, components=comps, reason=";".join(problems) or None,
                           residual=(excess if "DISTRIBUTION_EXCEEDS_CASH_AVAILABLE" in problems else (paid if lock and problems else
                                     (paid - legal if legal is not None and problems else 0.0)))))
    return out, None


def _eval_res(facts: Facts) -> tuple[list[dict], Optional[dict]]:
    regime = facts.reserve_regime
    balances = {i: _num(r.get("dsra_balance")) for i, r in facts.ibs.items()}
    known = [b for b in balances.values() if b is not None]
    if regime in ("NONE", "DSRF"):
        if known and any(abs(b) > TOL_KEUR for b in known):
            return ([_period(i, facts, WARNING, reason=f"COMMITTED_CASH_DSRA_BALANCE_UNDER_{regime}_REGIME") for i in facts.indices()
                     if (balances.get(i) or 0) > TOL_KEUR], None)
        return [], {"status": NOT_APPLICABLE, "reason": "STANDBY_DSRF_NOT_CASH_FUNDED" if regime == "DSRF" else "EXPLICIT_NO_RESERVE_REGIME"}
    if not facts.digest_ok:
        return _unavailable_all(facts, "EVIDENCE_DIGEST_NOT_INTACT"), None
    if known and all(abs(b) <= TOL_KEUR for b in known) and len(known) == len(balances) and regime is None:
        return [], {"status": UNAVAILABLE, "reason": "RESERVE_STRUCTURE_NOT_PROVEN_ZERO_BALANCES_ARE_NOT_COMPLIANCE"}
    initial = _num((facts.su.get("summary") or {}).get("initial_dsra_funding_keur"))
    out: list[dict] = []
    explained = 0
    for i in facts.indices():
        cur, prev, pf = balances.get(i), balances.get(i - 1), facts.pf.get(i)
        if i not in balances or cur is None or prev is None or pf is None:
            out.append(_period(i, facts, UNAVAILABLE, reason="ADJACENT_RESERVE_BALANCE_OR_MOVEMENT_MISSING"))
            continue
        fund, rel = _num(pf.get("dsra_funding_keur")), _num(pf.get("dsra_release_keur"))
        if fund is None or rel is None:
            out.append(_period(i, facts, UNAVAILABLE, reason="RESERVE_MOVEMENT_LINES_MISSING"))
            continue
        unexplained = cur - prev - fund + rel
        tol = _tol([fund, rel])
        comps = {"opening_balance": _comp(prev, "integrity_evidence.balance_sheet[i-1].dsra_balance", FULL),
                 "funding": _comp(fund, "pf_cash_waterfall.dsra_funding_keur", ROUNDED),
                 "release": _comp(rel, "pf_cash_waterfall.dsra_release_keur", ROUNDED),
                 "closing_balance": _comp(cur, "integrity_evidence.balance_sheet[i].dsra_balance", FULL),
                 "unexplained_movement": _comp(unexplained, "closing - opening - funding + release", FULL),
                 "reserve_regime": {"value": regime or "UNPROVEN", "source": "terms.reserve_regime (Quality evidence)", "basis": "TEXT"}}
        if abs(unexplained) <= tol:
            out.append(_period(i, facts, PASS, observed=cur, expected=prev + fund - rel, tolerance=tol, components=comps))
        elif initial is not None and initial > TOL_KEUR and abs(unexplained - initial) <= TOL_KEUR and explained == 0:
            explained += 1
            comps["financial_close_initial_funding"] = _comp(initial, "integrity_evidence.sources_uses.summary.initial_dsra_funding_keur", FULL)
            out.append(_period(i, facts, PASS, observed=cur, expected=prev + fund - rel + initial, tolerance=TOL_KEUR, components=comps,
                               scope="PERIOD_WITH_FINANCIAL_CLOSE_FUNDING", residual=unexplained - initial))
        else:
            out.append(_period(i, facts, FAIL, observed=cur, expected=prev + fund - rel, tolerance=tol, components=comps,
                               reason="UNEXPLAINED_RESERVE_MOVEMENT"))
    return out, None


def _eval_rev(facts: Facts) -> tuple[list[dict], Optional[dict]]:
    audit, dup = _by_index(facts.audit, "period_index")
    out = []
    for i in facts.indices():
        pnl, pf = facts.pnl.get(i), facts.pf.get(i)
        if pnl is None or pf is None:
            out.append(_period(i, facts, UNAVAILABLE, reason="STATEMENT_ROW_MISSING"))
            continue
        if not _same_dates(pnl, pf):
            out.append(_period(i, facts, UNAVAILABLE, reason="STATEMENT_DATES_DISAGREE"))
            continue
        rev_pnl, rev_cash = _num(pnl.get("revenues_keur")), _num(pf.get("revenue_cash_keur"))
        if rev_pnl is None or rev_cash is None:
            out.append(_period(i, facts, UNAVAILABLE, reason="REVENUE_LINE_MISSING"))
            continue
        comps = {"revenue_pnl": _comp(rev_pnl, "pnl.revenues_keur", ROUNDED), "revenue_cash": _comp(rev_cash, "pf_cash_waterfall.revenue_cash_keur", ROUNDED)}
        ids = [("revenue(P&L) = revenue(cash)", rev_pnl, rev_cash, _tol([rev_pnl, rev_cash]))]
        row = audit.get(i)
        if i in dup:
            out.append(_period(i, facts, UNAVAILABLE, reason="DUPLICATE_REVENUE_CONTRACT_PERIOD"))
            continue
        if row is not None:
            net, balancing, cert = _num(row.get("net_revenue_keur")), _num(row.get("balancing_cost_keur")), _num(row.get("legacy_certificate_revenue_keur"))
            streams = [s for s in (row.get("streams") or []) if isinstance(s, Mapping)]
            stream_rev = [_num(s.get("revenue_keur")) for s in streams]
            if None in (net, balancing, cert) or not streams or None in stream_rev:
                out.append(_period(i, facts, UNAVAILABLE, reason="CONTRACT_COMPONENT_EVIDENCE_INCOMPLETE"))
                continue
            for s in streams:
                comps[f"stream:{s.get('id')}:{s.get('type')}"] = _comp(_num(s.get("revenue_keur")), "revenue_multistream_audit.streams.revenue_keur", FULL)
            comps.update(balancing_cost=_comp(balancing, "revenue_multistream_audit.balancing_cost_keur", FULL),
                         legacy_certificate_revenue=_comp(cert, "revenue_multistream_audit.legacy_certificate_revenue_keur", FULL),
                         net_revenue=_comp(net, "revenue_multistream_audit.net_revenue_keur", FULL))
            ids.append(("net revenue = streams - balancing + certificate", net, sum(stream_rev) - balancing + cert, TOL_KEUR + 1e-9 * max(1.0, abs(net))))
            ids.append(("net revenue(contracts) = revenue(P&L)", rev_pnl, net, _tol([rev_pnl])))
        out.append(_verdict(i, facts, ids, comps))
    return out, None


EVALUATORS: dict[str, Callable[[Facts], tuple[list[dict], Optional[dict]]]] = {
    "DX-CAPEX-001": _eval_capex, "DX-OPEX-001": _eval_opex, "DX-DEP-001": _eval_dep, "DX-CASH-001": _eval_cash,
    "DX-SHL-001": _eval_shl, "DX-SHL-002": _eval_shl_maturity, "DX-DIST-001": _eval_dist, "DX-RES-001": _eval_res,
    "DX-REV-001": _eval_rev,
}


USES_SOURCES = {"DX-CAPEX-001": (), "DX-OPEX-001": ("pnl", "pf"), "DX-DEP-001": ("ibs", "pnl", "bs"), "DX-CASH-001": ("pf",),
                "DX-SHL-001": ("ibs", "sponsor", "pnl"), "DX-SHL-002": ("ibs",), "DX-DIST-001": ("pf", "dist", "sponsor"),
                "DX-RES-001": ("ibs", "pf"), "DX-REV-001": ("pnl", "pf")}


def evaluate_advanced_checks(facts: Facts) -> list[dict[str, Any]]:
    """Evaluate every DX definition over one committed Run.  Pure; never raises for malformed evidence."""
    results = []
    for d in DEFINITIONS:
        try:
            if facts.duplicates & set(USES_SOURCES[d.check_id]):
                periods, glob = _unavailable_all(facts, "DUPLICATE_PERIOD_IN_COMMITTED_EVIDENCE"), None
            else:
                periods, glob = EVALUATORS[d.check_id](facts)
        except Exception:  # noqa: BLE001 - malformed evidence fails closed to UNAVAILABLE
            periods, glob = _unavailable_all(facts, "EVIDENCE_MALFORMED"), None
        status, reason, coverage = _aggregate(periods) if periods else (
            (glob or {}).get("status", UNAVAILABLE), (glob or {}).get("reason", "NO_PERIOD_EVIDENCE"),
            {"counts": {}, "applicable_periods": 0, "evaluated_periods": 0, "complete": False})
        failing = [p for p in periods if p["status"] == FAIL]
        worst = max(failing, key=lambda p: abs(p["residual"] or 0.0)) if failing else None
        results.append({
            "check_id": d.check_id, "title": d.title, "family": d.family, "severity": d.severity,
            "definition": d.definition, "prerequisites": list(d.prerequisites), "tolerance_source": d.tolerance_source,
            "classification": d.classification, "evidence_source": d.evidence_source,
            "navigation_target": d.navigation_target, "related_assumptions": list(d.related_assumptions),
            "related_checks": list(d.related_checks), "status": status, "reason_code": reason, "coverage": coverage,
            "measured_value": None if worst is None else worst["residual"],
            "measured_unit": "kEUR", "threshold_value": None if worst is None else worst["tolerance"],
            "global_component": {k: v for k, v in (glob or {}).items()} if glob else None,
            "periods": periods, "not_in_quality_score": True,
            "claim": "PASS states only that every evaluated period satisfied the stated identity within its tolerance; "
                     "unevaluated periods stay UNAVAILABLE and are never counted as passed.",
        })
    return results


__all__ = ["DEFINITIONS", "DEFINITION_BY_ID", "Facts", "SCHEMA", "evaluate_advanced_checks", "PASS", "FAIL", "WARNING",
           "UNAVAILABLE", "NOT_APPLICABLE"]
