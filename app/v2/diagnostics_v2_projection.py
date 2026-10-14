"""Model Diagnostics V2 — read-only institutional intelligence over ONE committed Run (presentation only).

Adds to Diagnostics V1, never replaces it:

* ``advanced_checks``  - the additive ``DX-*`` period checks (``app.v2.diagnostics_dx_checks``), outside the
  Quality registry, score and coverage;
* ``root_causes``      - an explicit check-to-evidence relationship model with typed confidence
  (PROVEN / RELATED_EVIDENCE / POSSIBLE_CAUSE / UNAVAILABLE); no free text generation, no inference of causes;
* ``heatmap``          - a period risk overview on the EXISTING Diagnostics period axis; aggregate-only and global
  findings are listed separately and never repeated as per-period failures;
* ``bankability``      - threshold authority inventory and measured headroom (contractual covenant vs financing
  sizing target vs project-input advisory threshold; none is invented);
* ``inventory``        - CHECK ID -> SOURCE -> PERIOD -> VALIDATOR -> TOLERANCE -> STATUS -> EVIDENCE GAP.

No engine call, no write, no Working Copy value mixed into a committed Run, full precision kept in evidence.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional

from app.v2.diagnostics_dx_checks import (
    DEFINITION_BY_ID, DEFINITIONS, FAIL, NOT_APPLICABLE, PASS, UNAVAILABLE, WARNING, Facts, evaluate_advanced_checks,
)

SCHEMA = "model-diagnostics-v2-1"
SEVERITY_RANK = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
RANK_SEVERITY = {v: k for k, v in SEVERITY_RANK.items()}
GROUPS = ("Accounting", "CAPEX/OPEX", "Cash Flow", "Senior Debt", "Reserves", "SHL", "Revenue", "Returns/Scenario")
V1_GROUP = {"ACCOUNTING_INTEGRITY": "Accounting", "SOURCES_USES": "CAPEX/OPEX", "CAPEX_CONSTRUCTION": "CAPEX/OPEX",
            "SENIOR_DEBT": "Senior Debt", "CASH_LIQUIDITY": "Cash Flow", "COVENANTS": "Senior Debt",
            "REVENUE": "Revenue", "TERMINAL_LIABILITY": "SHL", "PROVENANCE_FRESHNESS": "Returns/Scenario"}
FAILURE_STATUSES = ("FAIL", "WARNING")
CONFIDENCE_ORDER = ("PROVEN", "RELATED_EVIDENCE", "POSSIBLE_CAUSE", "UNAVAILABLE")


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if math.isfinite(f) else None


# ── inventory ────────────────────────────────────────────────────────────────────────────────────────────────────
def _inventory() -> list[dict[str, Any]]:
    rows = []
    for d in DEFINITIONS:
        rows.append({"check_id": d.check_id, "family": d.family, "source": d.evidence_source,
                     "financial_period": "Per committed period (join by period index and equal dates; sponsor rows by ISO date)"
                     if d.check_id != "DX-SHL-002" else "Single committed contractual-maturity period",
                     "validator": "Stated identity in app.v2.diagnostics_dx_checks (additive; not in the Quality registry)",
                     "tolerance": d.tolerance_source, "classification": d.classification,
                     "evidence_gap": {
                         "DX-CAPEX-001": "Spending by calendar date is not committed; only construction period indices.",
                         "DX-OPEX-001": "Detailed OPEX line schedules are not committed with the Run; statement lines only.",
                         "DX-DEP-001": "Fixed-asset additions and disposals have no committed evidence (not inferred).",
                         "DX-CASH-001": "Closing cash roll-forward needs shareholder / restricted / distribution-account flows that are not committed.",
                         "DX-SHL-001": "Financial-close boundary periods have no presented SHL balance (UNAVAILABLE).",
                         "DX-SHL-002": "Point-in-time at the contractual maturity period only.",
                         "DX-DIST-001": "No contractual distribution rule is committed; only the model's own lock-up flag.",
                         "DX-RES-001": "Reserve structure other than cash DSRA is unsupported; DSRF is a standby facility, not a balance.",
                         "DX-REV-001": "Revenue V2 components only where explicit contracts are committed; Revenue V3 is release-closed.",
                     }.get(d.check_id, "")})
    rows += [
        {"check_id": "QM-SU-001/002", "family": "CAPEX/OPEX", "source": "run_integrity_evidence.sources_uses", "financial_period": "Construction periods",
         "validator": "Existing Run Integrity", "tolerance": "TOL_KEUR", "classification": "EXISTING_PARTIAL", "evidence_gap": "No independent spending-profile control (added as DX-CAPEX-001)."},
        {"check_id": "QM-ACC-003", "family": "CAPEX/OPEX", "source": "runtime_summary", "financial_period": "Aggregate", "validator": "Existing Quality evaluator",
         "tolerance": "TOL_KEUR", "classification": "AGGREGATE_ONLY", "evidence_gap": "Period EBITDA identity added as DX-OPEX-001."},
        {"check_id": "QM-TERM-002", "family": "SHL", "source": "sponsor_schedule.summary", "financial_period": "Contractual maturity", "validator": "Existing Quality evaluator",
         "tolerance": "SHL terminal tolerance", "classification": "EXISTING_PARTIAL", "evidence_gap": "No local repayment schedule validator."},
        {"check_id": "QM-PRV-005", "family": "Returns/Scenario", "source": "committed Run identity", "financial_period": "Global", "validator": "Existing Quality evaluator",
         "tolerance": "identity equality", "classification": "EXISTING_FULL", "evidence_gap": "Yield-case (P50/P90) consistency has no explicit committed authority: EVIDENCE_MISSING, never inferred from a number."},
        {"check_id": "(reserve instruments other than cash DSRA)", "family": "Reserves", "source": "-", "financial_period": "-", "validator": "-", "tolerance": "-",
         "classification": "EVIDENCE_MISSING", "evidence_gap": "No committed schedule for MRA or other reserve instruments (mra_balance is null)."},
        {"check_id": "(Revenue V3 contracted components)", "family": "Revenue", "source": "-", "financial_period": "-", "validator": "-", "tolerance": "-",
         "classification": "NOT_APPLICABLE", "evidence_gap": "Release-closed: no committed Run can carry V3 evidence; never read."},
    ]
    return rows


# ── normalised findings (DX + existing V1 period evidence) ─────────────────────────────────────────────────────
def _v1_components(check_id: str, ws: Any) -> dict[str, Any]:
    if check_id != "QM-SU-001":
        return {}
    summary = ((getattr(ws, "last_integrity_evidence", None) or {}).get("sources_uses") or {}).get("summary") or {}
    keys = ("base_project_capex_keur", "capitalized_idc_keur", "commitment_fee_keur", "structuring_fee_keur", "other_financing_costs_keur",
            "initial_dsra_funding_keur", "total_uses_keur", "senior_debt_keur", "junior_or_other_keur",
            "share_capital_and_other_equity_keur", "shareholder_loan_cash_keur", "total_sources_keur")
    return {k: {"value": _num(summary.get(k)), "source": f"integrity_evidence.sources_uses.summary.{k}", "basis": "FULL_PRECISION"}
            for k in keys if k in summary}


def _findings(ws: Any, v1: Mapping, dx: list[dict]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in dx:
        group = c["family"]
        for p in c["periods"]:
            if p["status"] in FAILURE_STATUSES:
                out.append({"family": "DX", "check_id": c["check_id"], "title": c["title"], "group": group, "severity": c["severity"],
                            "status": p["status"], "period_index": p["period_index"], "date": p["date"], "observed": p["observed"],
                            "expected": p["expected"], "residual": p["residual"], "tolerance": p["tolerance"], "unit": "kEUR",
                            "components": p["components"], "scope": p["scope"], "reason": p["reason"],
                            "evidence_source": c["evidence_source"], "navigation_target": c["navigation_target"],
                            "related_assumptions": c["related_assumptions"], "related_checks": c["related_checks"],
                            "identity": (p["components"].get("identity_evaluated") or {}).get("value") or c["definition"]})
    for c in v1.get("checks", []):
        group = V1_GROUP.get(c.get("category"), "Returns/Scenario")
        periodic_fail = [p for p in c.get("periods", []) if p["status"] in FAILURE_STATUSES]
        for p in periodic_fail:
            out.append({"family": "QM", "check_id": c["check_id"], "title": c["title"], "group": group, "severity": c["severity"],
                        "status": p["status"], "period_index": p["period_index"], "date": p["date"], "observed": p.get("observed"),
                        "expected": p.get("expected"), "residual": p.get("residual"), "tolerance": p.get("tolerance"),
                        "unit": c.get("measured_unit"), "components": _v1_components(c["check_id"], ws), "scope": p["scope"],
                        "reason": p.get("reason"), "evidence_source": c["evidence_source"],
                        "navigation_target": c.get("navigation_target"), "related_assumptions": list(c.get("related_assumption_ids") or []),
                        "related_checks": [], "identity": c.get("description")})
        if c["status"] in FAILURE_STATUSES and not periodic_fail:
            out.append({"family": "QM", "check_id": c["check_id"], "title": c["title"], "group": group, "severity": c["severity"],
                        "status": c["status"], "period_index": None, "date": None, "observed": c.get("measured_value"),
                        "expected": None, "residual": c.get("measured_value"), "tolerance": c.get("threshold_value"),
                        "unit": c.get("measured_unit"), "components": _v1_components(c["check_id"], ws),
                        "scope": "AGGREGATE_OR_GLOBAL", "reason": c.get("reason_code"), "evidence_source": c["evidence_source"],
                        "navigation_target": c.get("navigation_target"), "related_assumptions": list(c.get("related_assumption_ids") or []),
                        "related_checks": [], "identity": c.get("description")})
    return out


# ── root cause relationship model ───────────────────────────────────────────────────────────────────────────────
def _fmt(value: Optional[float]) -> str:
    return "UNAVAILABLE" if value is None else (f"{value:.6g}" if abs(value) < 0.005 and value != 0 else f"{value:,.2f}")


def _root_cause(entry: Mapping, all_findings: list[Mapping], unavailable_reasons: list[str]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    residual, observed, expected, tol = entry["residual"], entry["observed"], entry["expected"], entry["tolerance"]
    where = f"P{entry['period_index']} {entry['date'] or 'date unavailable'}" if entry["period_index"] is not None else "the whole run (aggregate)"
    refs = [{"source": v["source"], "value": v["value"]} for v in entry["components"].values()
            if isinstance(v, Mapping) and v.get("source") and v.get("basis") != "TEXT"][:12]
    if residual is not None and (observed is not None or entry["period_index"] is None):
        items.append({"confidence": "PROVEN", "statement":
                      f"The committed evidence proves the reconciliation does not close in {where}: observed {_fmt(observed)}, expected {_fmt(expected)}, "
                      f"residual {_fmt(residual)} against tolerance {_fmt(tol)} ({entry['status']}). Stated identity: {entry['identity']}. "
                      "This proves the size and location of the residual; it does not by itself prove why.",
                      "evidence": refs})
    related = [f for f in all_findings if f is not entry and f["check_id"] != entry["check_id"]
               and entry["period_index"] is not None and f["period_index"] == entry["period_index"]]
    related += [f for f in all_findings if f["check_id"] in entry["related_checks"] and f not in related and f is not entry]
    for f in related[:6]:
        items.append({"confidence": "RELATED_EVIDENCE", "statement":
                      f"{f['check_id']} is also {f['status']} ({'same period' if f['period_index'] == entry['period_index'] else 'related check'}; "
                      f"residual {_fmt(f['residual'])}). Connection is demonstrated by co-occurrence or by the registered check relation, not by causality.",
                      "evidence": [{"source": f["evidence_source"], "value": f["residual"]}]})
    if residual is not None:
        window = max(tol or 0.0, 0.011)
        for name, comp in entry["components"].items():
            v = comp.get("value") if isinstance(comp, Mapping) else None
            if not isinstance(v, (int, float)) or isinstance(v, bool) or abs(v) < 0.011:
                continue
            for factor, label in ((1, "equals"), (2, "equals twice")):
                if abs(abs(residual) - factor * abs(v)) <= window:
                    items.append({"confidence": "POSSIBLE_CAUSE", "statement":
                                  f"The residual magnitude {label} the committed component '{name}' ({_fmt(v)}): possibly an omitted, duplicated or "
                                  "sign-reversed line. This is an arithmetic coincidence worth inspecting; it is NOT verified.",
                                  "evidence": [{"source": comp.get("source"), "value": v}]})
    if unavailable_reasons:
        items.append({"confidence": "UNAVAILABLE", "statement":
                      "A fuller explanation needs evidence that is not committed: " + ", ".join(sorted(set(unavailable_reasons))[:6]) + ".",
                      "evidence": []})
    confidence = next((c for c in CONFIDENCE_ORDER if any(i["confidence"] == c for i in items)), "UNAVAILABLE")
    return {"check_id": entry["check_id"], "title": entry["title"], "status": entry["status"], "severity": entry["severity"],
            "period_index": entry["period_index"], "date": entry["date"], "observed": observed, "expected": expected,
            "residual": residual, "tolerance": tol, "unit": entry["unit"], "scope": entry["scope"], "group": entry["group"],
            "components": entry["components"], "evidence_source": entry["evidence_source"],
            "related_assumptions": entry["related_assumptions"], "navigation_target": entry["navigation_target"],
            "related_checks": [r["check_id"] for r in related[:6]], "items": items, "confidence": confidence,
            "cause_established": False,
            "explanation": "Typed relationship model: PROVEN states the measured residual and its committed components; "
                           "RELATED_EVIDENCE links other findings; POSSIBLE_CAUSE is an unverified arithmetic coincidence; "
                           "UNAVAILABLE names the missing evidence. No root cause is asserted."}


# ── period risk heatmap ─────────────────────────────────────────────────────────────────────────────────────────
def _heatmap(v1: Mapping, dx: list[dict]) -> dict[str, Any]:
    columns = list(v1.get("columns", []))
    cells: dict[int, dict[str, Any]] = {c["index"]: {"index": c["index"], "date": c["date"], "label": c["label"], "proven_fail": 0, "warning": 0,
                                                     "unavailable": 0, "pass": 0, "applicable": 0, "severity": {k: 0 for k in SEVERITY_RANK},
                                                     "highest": None, "groups": {g: {"fail": 0, "warning": 0, "unavailable": 0, "pass": 0, "checks": []}
                                                                                 for g in GROUPS}, "failed_checks": []} for c in columns}

    def add(index: int, group: str, check_id: str, severity: str, status: str) -> None:
        cell = cells.get(index)
        if cell is None or status not in ("PASS", "FAIL", "WARNING", "UNAVAILABLE"):
            return                                # NOT_APPLICABLE, AGGREGATE_ONLY and NOT_PERIODIC are never counted
        g = cell["groups"].setdefault(group, {"fail": 0, "warning": 0, "unavailable": 0, "pass": 0, "checks": []})
        cell["applicable"] += 1
        key = {"PASS": "pass", "FAIL": "fail", "WARNING": "warning", "UNAVAILABLE": "unavailable"}[status]
        g[key] += 1
        if status == "PASS":
            cell["pass"] += 1
        elif status == "UNAVAILABLE":
            cell["unavailable"] += 1
        else:
            cell["proven_fail" if status == "FAIL" else "warning"] += 1
            cell["severity"][severity] = cell["severity"].get(severity, 0) + 1
            g["checks"].append({"check_id": check_id, "status": status, "severity": severity})
            cell["failed_checks"].append({"check_id": check_id, "status": status, "severity": severity, "group": group})
            rank = SEVERITY_RANK.get(severity, 0)
            if cell["highest"] is None or rank > SEVERITY_RANK[cell["highest"]]:
                cell["highest"] = severity

    for c in v1.get("checks", []):
        for p in c.get("periods", []):
            add(p["period_index"], V1_GROUP.get(c.get("category"), "Returns/Scenario"), c["check_id"], c["severity"], p["status"])
    for c in dx:
        for p in c["periods"]:
            add(p["period_index"], c["family"], c["check_id"], c["severity"], p["status"])
    globals_ = []
    for c in v1.get("checks", []):
        if c["status"] in FAILURE_STATUSES and not any(p["status"] in FAILURE_STATUSES for p in c.get("periods", [])):
            globals_.append({"check_id": c["check_id"], "title": c["title"], "status": c["status"], "severity": c["severity"],
                             "scope": c.get("period_scope"), "note": "Aggregate or global finding: not attributed to any period."})
        elif c["status"] in FAILURE_STATUSES and c.get("global_component"):
            globals_.append({"check_id": c["check_id"], "title": c["title"], "status": c["status"], "severity": c["severity"],
                             "scope": "GLOBAL_COMPONENT", "note": "Global / boundary component reported separately."})
    for c in dx:
        if c["global_component"] and c["global_component"].get("status") in FAILURE_STATUSES:
            globals_.append({"check_id": c["check_id"], "title": c["title"], "status": c["global_component"]["status"], "severity": c["severity"],
                             "scope": "GLOBAL_COMPONENT", "note": str(c["global_component"].get("reason"))})
    return {"axis": "Existing Diagnostics V1 committed period axis (persisted indices and dates; no new calendar)",
            "groups": list(GROUPS), "cells": [cells[c["index"]] for c in columns],
            "global_findings": globals_,
            "rules": "Only period-evaluated checks count. NOT_APPLICABLE, AGGREGATE_ONLY and NOT_PERIODIC are excluded; annual checks are not "
                     "spread across monthly cells; a global finding is never repeated as a per-period failure."}


# ── bankability monitor ────────────────────────────────────────────────────────────────────────────────────────
def _bankability(ws: Any, report: Any, evidence: Any, facts: Facts, v1: Mapping) -> dict[str, Any]:
    terms = evidence.terms
    ev = getattr(ws, "last_integrity_evidence", None) or {}
    debt_rows = [r for r in ((ev.get("senior_debt") or {}).get("periods") or []) if isinstance(r, Mapping)]
    by_id = {c.check_id: c for c in report.checks}
    state = evidence.freshness
    contractual = bool(terms.contractual)

    def authority(kind: str, value: Optional[float], source: str, note: str) -> dict[str, Any]:
        return {"subject": kind, "value": value, "source": source, "note": note}

    thresholds = [
        {**authority("Contractual minimum DSCR", terms.min_dscr_covenant, "ProjectTerms.min_dscr_covenant",
                     "Used only when a contractual term is source-proven."),
         "class": "CONTRACTUAL_COVENANT" if (contractual and terms.min_dscr_covenant is not None) else "NOT_SOURCE_PROVEN",
         "available": bool(contractual and terms.min_dscr_covenant is not None)},
        {**authority("Distribution lock-up DSCR", terms.lockup_dscr, terms.authority("lockup_dscr"),
                     "Project input; FINCO cannot tell a negotiated term from a default."),
         "class": "CONTRACTUAL_COVENANT" if (contractual and terms.lockup_dscr is not None) else "PROJECT_INPUT_ADVISORY",
         "available": terms.lockup_dscr is not None},
        {**authority("Minimum LLCR", terms.min_llcr, terms.authority("min_llcr"), "Project input; not a verified contractual term unless supplied as such."),
         "class": "CONTRACTUAL_COVENANT" if (contractual and terms.min_llcr is not None) else "PROJECT_INPUT_ADVISORY",
         "available": terms.min_llcr is not None},
        {**authority("Cash DSRA requirement", terms.dsra_target_keur, terms.authority("dsra_target_keur"),
                     f"Reserve regime: {terms.reserve_regime or 'UNPROVEN'}"),
         "class": "PROJECT_INPUT_ADVISORY" if terms.dsra_target_keur is not None else "NOT_SOURCE_PROVEN",
         "available": terms.dsra_target_keur is not None},
        {"subject": "Debt-sizing target DSCR (financing assumption)", "value": _num((getattr(ws, "last_runtime_summary", None) or {}).get("target_dscr")),
         "source": "runtime_summary.target_dscr / integrity_evidence.senior_debt.periods.target_dscr",
         "note": "A sizing assumption used to size debt. It is NOT a loan covenant.", "class": "FINANCING_SIZING_TARGET",
         "available": _num((getattr(ws, "last_runtime_summary", None) or {}).get("target_dscr")) is not None},
        {"subject": "Default DSCR / event of default", "value": None, "source": "none", "class": "NOT_SOURCE_PROVEN", "available": False,
         "note": "ProjectInputs defines no default-DSCR term: no event of default is declared."},
    ]
    missing = [t["subject"] for t in thresholds if t["class"] in ("NOT_SOURCE_PROVEN",) or
               (t["class"] == "PROJECT_INPUT_ADVISORY" and not contractual)]
    rows = []
    for r in debt_rows:
        idx = r.get("period_index")
        dscr, target = _num(r.get("reported_dscr")), _num(r.get("target_dscr"))
        row = {"period_index": idx, "date": facts.date(idx) if isinstance(idx, int) else None, "dscr": dscr,
               "debt_service": _num(r.get("debt_service")), "checks": []}

        def test(kind: str, threshold: Optional[float], klass: str, label_below: str) -> None:
            if dscr is None or threshold is None:
                return
            head = dscr - threshold
            status = label_below if head < 0 else "WITHIN"
            row["checks"].append({"kind": kind, "class": klass, "threshold": threshold, "headroom_abs": head,
                                  "headroom_pct": None if threshold == 0 else head / threshold, "status": status})
        if terms.min_dscr_covenant is not None and contractual:
            test("Contractual minimum DSCR", terms.min_dscr_covenant, "CONTRACTUAL_COVENANT", "BELOW_CONTRACTUAL_THRESHOLD")
        if terms.lockup_dscr is not None:
            test("Lock-up DSCR", terms.lockup_dscr, "CONTRACTUAL_COVENANT" if contractual else "PROJECT_INPUT_ADVISORY",
                 "BELOW_CONTRACTUAL_THRESHOLD" if contractual else "BELOW_PROJECT_INPUT")
        test("Sizing target DSCR", target, "FINANCING_SIZING_TARGET", "BELOW_SIZING_TARGET")
        rows.append(row)
    shortfalls = []
    for i in facts.indices():
        pf = facts.pf.get(i)
        if pf is None:
            continue
        cf, ds, avail = _num(pf.get("fcf_banks_keur")), _num(pf.get("senior_total_ds_keur")), _num(pf.get("fcf_for_distribution_keur"))
        if cf is not None and ds is not None and cf < ds - 0.011:
            shortfalls.append({"period_index": i, "date": facts.date(i), "cfads": cf, "senior_debt_service": ds, "shortfall": ds - cf})
        elif avail is not None and avail < -0.011:
            shortfalls.append({"period_index": i, "date": facts.date(i), "cash_available_after_debt_service": avail, "shortfall": -avail})
    lock_periods = [i for i, d in facts.dist.items() if d.get("lockup_active") is True]
    at_risk = {}
    for r in rows:
        bad = [c for c in r["checks"] if c["status"] != "WITHIN"]
        if bad:
            at_risk.setdefault(r["period_index"], {"period_index": r["period_index"], "date": r["date"], "reasons": []})["reasons"] += [
                f"{c['kind']}: {c['status']} (headroom {c['headroom_abs']:+.3f}x)" for c in bad]
    for s in shortfalls:
        at_risk.setdefault(s["period_index"], {"period_index": s["period_index"], "date": s["date"], "reasons": []})["reasons"].append(
            f"Debt-service / cash shortfall {s['shortfall']:,.2f} kEUR (committed lines)")
    for i in lock_periods:
        at_risk.setdefault(i, {"period_index": i, "date": facts.date(i), "reasons": []})["reasons"].append(
            "Distribution lock-up flagged by the committed distribution schedule")
    # reserve coverage: DSRA balance over the next period's Senior debt service (committed values only)
    reserve = []
    regime = terms.reserve_regime
    balances = {i: _num(r.get("dsra_balance")) for i, r in facts.ibs.items()}
    ds_by_index = {r.get("period_index"): _num(r.get("debt_service")) for r in debt_rows}
    for i in sorted(balances):
        bal, nxt = balances[i], ds_by_index.get(i + 1)
        if bal is None or not nxt or nxt <= 0:
            continue
        reserve.append({"period_index": i, "date": facts.date(i), "dsra_balance": bal, "next_period_senior_debt_service": nxt, "coverage_x": bal / nxt})
    llcr = by_id.get("QM-COV-003")
    terminal = (facts.sponsor_summary.get("terminal_financial_state") or {}) if isinstance(facts.sponsor_summary, Mapping) else {}
    return {
        "state": state or "UNAVAILABLE", "identity": v1.get("identity"), "thresholds": thresholds,
        "missing_contractual_authorities": missing,
        "dscr_periods": rows, "periods_at_risk": [at_risk[k] for k in sorted(at_risk)],
        "min_dscr_headroom": _min_headroom(rows),
        "llcr": {"measured_min": None if llcr is None else llcr.measured_value, "threshold": terms.min_llcr,
                 "threshold_class": "CONTRACTUAL_COVENANT" if (contractual and terms.min_llcr is not None) else "PROJECT_INPUT_ADVISORY",
                 "status": None if llcr is None else llcr.status.value, "by_period": "UNAVAILABLE - LLCR by period is not persisted"},
        "reserve": {"regime": regime or "UNPROVEN", "coverage_by_period": reserve if regime in (None, "CASH_DSRA_FIXED", "AUTOMATIC_PEAK") else [],
                    "note": ("Standby DSRF: not cash funded; no cash balance is interpreted as a DSRA." if regime == "DSRF" else
                             "Explicit no-reserve regime." if regime == "NONE" else
                             "Missing reserve evidence is not a zero balance and not compliance." if not reserve else
                             "DSRA balance divided by the next period's Senior debt service; the requirement is a project input.")},
        "debt_service_shortfalls": shortfalls,
        "debt_maturity": terminal.get("senior") if isinstance(terminal, Mapping) else None,
        "sponsor_distributions": {"total_legal_equity_distributions_keur": _num(facts.sponsor_summary.get("total_legal_equity_distributions_keur")),
                                  "lockup_periods": len(lock_periods)},
        "disclosure": "FINCO decision intelligence over committed Run evidence. Not lender certification, not a contractual covenant test "
                      "unless a contractual term is source-proven, and no event of default is declared."}


def _min_headroom(rows: list[dict]) -> Optional[dict[str, Any]]:
    best = None
    for r in rows:
        for c in r["checks"]:
            if best is None or c["headroom_abs"] < best["headroom_abs"]:
                best = {"period_index": r["period_index"], "date": r["date"], "kind": c["kind"], "class": c["class"],
                        "headroom_abs": c["headroom_abs"], "headroom_pct": c["headroom_pct"], "dscr": r["dscr"], "threshold": c["threshold"]}
    return best



# ── guided resolution: verified navigation / context only (no mutation, no Run, no scenario write) ──────────────
Q4_MAPPED = {"QM-SD-004", "QM-SD-006", "QM-SD-007"}                 # mirrors app.v2.whatif.CANDIDATES (asserted by a test)
Q4_VERTICALS = {"solar", "wind"}
FINANCING_GROUPS = {"Senior Debt", "Cash Flow", "Reserves", "SHL", "CAPEX/OPEX"}


def _vertical(ws: Any) -> Optional[str]:
    snapshot = getattr(ws, "draft_snapshot", None)
    kind = snapshot.get("project_type") if isinstance(snapshot, Mapping) else None
    return str(kind).strip().lower().replace(" ", "_") if kind else None


def guided_actions(check_id: str, *, group: str, navigation_target: Optional[str], related_assumptions: list[str],
                   vertical: Optional[str]) -> list[dict[str, Any]]:
    """Context actions for one check. Each is navigation to an EXISTING workflow; unsupported ones are disabled with a reason.

    Diagnostics never writes: Q4 keeps authority over scenario writes and signed confirmation, Goal Seek over its solve and
    apply, and Run over executing the model. Nothing here changes gearing, repayment or revenue, or creates a Run.
    """
    def action(action_id: str, label: str, enabled: bool, reason: str, tab: Optional[str] = None, **extra: Any) -> dict[str, Any]:
        return {"id": action_id, "label": label, "enabled": enabled, "reason": reason, "target_tab": tab if enabled else None, **extra}

    actions = [
        action("open_schedule", "Open the financial schedule", bool(navigation_target), "" if navigation_target else
               "No owning schedule is registered for this check.", navigation_target),
        action("open_assumptions", "Open the related assumptions (Input Grid)", bool(related_assumptions), "" if related_assumptions else
               "No registered related assumption for this check; nothing is guessed from labels.", "tab-input-grid",
               assumptions=list(related_assumptions)),
        action("open_trace", "Open the Statements & Debt calculation trace", group in FINANCING_GROUPS, "" if group in FINANCING_GROUPS else
               "The financing calculation trace covers debt, cash, reserve, SHL and funding schedules only.", "tab-outputs"),
        action("compare_runs", "Open scenario / Run comparison", True, "", "tab-compare"),
    ]
    if check_id not in Q4_MAPPED:
        what_if = action("finding_whatif", "Open Finding-to-What-if (Insight)", False,
                         "Q4 maps only QM-SD-004, QM-SD-006 and QM-SD-007 to an editable assumption; this finding has no registered mapping.")
    elif vertical not in Q4_VERTICALS:
        what_if = action("finding_whatif", "Open Finding-to-What-if (Insight)", False,
                         "Q4 supports Solar and Wind projects only.")
    else:
        what_if = {"id": "finding_whatif", "label": "Open Finding-to-What-if (Insight)", "enabled": True, "reason": "", "target_tab": None,
                   "opens_insight": True,
                   "note": "Opens FINCO Insight. Q4 keeps authority over any scenario write, preview and signed confirmation."}
    actions.append(what_if)
    goal = ("Goal Seek solves the PPA tariff for a Project / Equity / Sponsor IRR target. A reconciliation or schedule finding is not a "
            "return shortfall, so no solve is offered.")
    actions.append(action("goal_seek", "Open Goal Seek / Tender Pricing", False, goal))
    return actions


# ── entry point ─────────────────────────────────────────────────────────────────────────────────────────────────
def build_diagnostics_v2(ws: Any, v1: Mapping[str, Any], *, evidence: Any, report: Any, history_quality: Any = None) -> dict[str, Any]:
    digest_ok = any(c.get("check_id") == "EVIDENCE_DIGEST" and c.get("status") == "PASS" for c in (v1.get("integrity") or {}).get("checks", []))
    regime = evidence.terms.reserve_regime if evidence.freshness == "CURRENT" else None
    facts = Facts.from_workspace(ws, digest_ok=digest_ok, reserve_regime=regime)
    dx = evaluate_advanced_checks(facts)
    column_index = [c["index"] for c in v1.get("columns", [])]
    for c in dx:      # status per EXISTING axis column; "-" = this check has no evidence scope in that period
        by_period = {p["period_index"]: p for p in c["periods"]}
        c["aligned"] = [{"period_index": i, "status": (by_period[i]["status"] if i in by_period else "NOT_IN_SCOPE"),
                         "reason": (by_period[i]["reason"] if i in by_period else None),
                         "scope": (by_period[i]["scope"] if i in by_period else None)} for i in column_index]
    findings = _findings(ws, v1, dx)
    by_check = {c["check_id"]: c for c in dx}
    root = []
    for f in findings:
        source = by_check.get(f["check_id"])
        reasons = sorted({p["reason"] for p in (source["periods"] if source else []) if p["status"] == UNAVAILABLE and p["reason"]})
        root.append(_root_cause(f, findings, reasons))
    counts = {s: sum(1 for c in dx if c["status"] == s) for s in (PASS, FAIL, WARNING, UNAVAILABLE, NOT_APPLICABLE)}
    vertical = _vertical(ws)
    actions: dict[str, list[dict[str, Any]]] = {}
    for c in v1.get("checks", []):
        actions[c["check_id"]] = guided_actions(c["check_id"], group=V1_GROUP.get(c.get("category"), "Returns/Scenario"),
                                                navigation_target=c.get("navigation_target"),
                                                related_assumptions=list(c.get("related_assumption_ids") or []), vertical=vertical)
    for c in dx:
        actions[c["check_id"]] = guided_actions(c["check_id"], group=c["family"], navigation_target=c["navigation_target"],
                                                related_assumptions=list(c["related_assumptions"]), vertical=vertical)
    for rc in root:
        rc["actions"] = actions.get(rc["check_id"], [])
    comparison = {"available": False, "reason": "NOT_REQUESTED"}
    try:
        from app.v2.diagnostics_run_compare import build_run_comparison
        comparison = build_run_comparison(ws, quality_for_entry=history_quality)
    except Exception:  # noqa: BLE001 - a comparison failure never hides the Run's own diagnostics
        comparison = {"available": False, "reason": "COMPARISON_UNAVAILABLE"}
    return {"schema": SCHEMA, "actions": actions, "run_comparison": comparison, "advanced_checks": dx,
            "advanced_summary": {"registered": len(DEFINITIONS), "counts": counts,
                                 "note": "Additive DX checks: they do not change the Quality score, coverage or the 30 QM check identities."},
            "root_causes": root, "heatmap": _heatmap(v1, dx), "bankability": _bankability(ws, report, evidence, facts, v1),
            "inventory": _inventory(), "reserve_regime_bound": regime is not None}


__all__ = ["SCHEMA", "build_diagnostics_v2"]
