"""app.v2.credit_decision_projection — read-only institutional credit decision view over COMMITTED Runs (RC-4 / B).

This module is a decision *workspace* projection, not a debt-sizing engine.  It contains no financial formula, no solver,
no Run writer, no scenario writer and no recalculation: every number is a value that an immutable Run History entry
already persisted (runtime summary, ``financing_evidence``, debt / distribution / sponsor schedules, Run Integrity
evidence).  The only arithmetic is presentation arithmetic over persisted numbers, always labelled with its basis:

* plain differences between two persisted values of two Runs (the same "display arithmetic" the Run Compare surfaces use),
* ``math.fsum`` totals of persisted period vectors (basis string states the periods summed),
* ordering / comparison of persisted values against a stated threshold (strict, with the tolerances of the existing
  Model Quality evaluators; no tolerance is widened).

Authority rules (pinned by tests):

* A binding sizing constraint, DSCR / gearing capacity, lender case, covenant, LLCR, PLCR, event of default or cash sweep
  that a Run did not persist is ``UNAVAILABLE`` with its exact evidence gap — never reconstructed from unrelated values.
* The lender case and project thresholds are not persisted with a Run.  They are shown only for the Last Run while it is
  CURRENT (Working Copy terms provably equal the Run's inputs, the Q3 rule) and are always labelled as bound Working Copy
  terms.  Every other Run shows them as UNAVAILABLE.
* Findings are deterministic and carry one of four classes: CONTRACTUAL_COVENANT, PROJECT_INPUT_ADVISORY,
  OBSERVED_FINANCIAL_RESULT, UNSUPPORTED_EVIDENCE_MISSING.  No scoring, no probability of default; severity and status are
  those of the existing Model Quality rules wherever such a rule exists.
* Numerical convergence of the solver is shown separately from credit feasibility.
* A Run that failed or fail-closed is never committed, so it can never be selected here; a committed Run whose Run
  Integrity failed is labelled as such, never as a bankable scenario.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Iterable, Mapping, Optional, Sequence

from app.model_quality import evaluate_model_quality
from app.model_quality.contracts import CheckStatus
from app.model_quality.evaluators import TOL_KEUR, TOL_RATIO
from app.model_quality.evidence import ProjectTerms, evidence_from_history_entry
from app.workbook.runtime_projection import thaw_runtime_payload

SCHEMA = "RC4B_CREDIT_DECISION_V1"
MIN_RUNS, MAX_RUNS = 1, 3

# Finding classes (the four the workstream distinguishes).
CONTRACTUAL = "CONTRACTUAL_COVENANT"
ADVISORY = "PROJECT_INPUT_ADVISORY"
OBSERVED = "OBSERVED_FINANCIAL_RESULT"
UNSUPPORTED = "UNSUPPORTED_EVIDENCE_MISSING"
CLASSES = (CONTRACTUAL, ADVISORY, OBSERVED, UNSUPPORTED)

# Run states (presentation labels; CURRENT / STALE only exist for the canonical Last Run).
LAST_CURRENT = "LAST RUN · CURRENT"
LAST_STALE = "LAST RUN · STALE"
HISTORICAL = "HISTORICAL"
TWO_SENIOR_AUTHORITY = "F3_TWO_SENIOR_EXPLICIT_COMMITMENTS_V1"
JUNIOR_AUTHORITY = "F3_SINGLE_SENIOR_JUNIOR_EXPLICIT_V1"

RESIDUAL_QM = frozenset({"QM-SD-003", "QM-SD-004", "QM-SD-005"})

# Same literal as the existing minimum-DSCR rule (QM-SD-007) uses for the sizing-target comparison.
SIZING_TARGET_TOL = 1e-6

UNAVAILABLE = "UNAVAILABLE"

FINDING_LIMIT_PERIODS = 12          # periods listed in one finding; the full list stays in the timeline matrix

CREDIT_QM = {
    # check id -> (class when evaluated, short note)
    "QM-SD-003": (OBSERVED, "DSCR equals base CFADS over debt service (persisted identity)"),
    "QM-SD-004": (OBSERVED, "Scheduled debt service vs the allowed debt service under the sizing target (a sizing ceiling, not a covenant)"),
    "QM-SD-005": (OBSERVED, "Solver result authoritative (convergence is not lender approval)"),
    "QM-SD-006": (OBSERVED, "Actual funded gearing vs the requested gearing cap"),
    "QM-SD-007": (ADVISORY, "Minimum DSCR vs 1.0x and the sizing target"),
    "QM-CASH-002": (ADVISORY, "Initial cash DSRA funding vs the typed fixed requirement"),
    "QM-COV-001": (CONTRACTUAL, "Minimum DSCR covenant"),
    "QM-COV-002": (ADVISORY, "Distribution lock-up DSCR"),
    "QM-COV-003": (ADVISORY, "Minimum LLCR requirement"),
    "QM-COV-004": (ADVISORY, "Covenant ordering"),
}


# ── tiny presentation helpers ─────────────────────────────────────────────────────────────────────────────────────
def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if math.isfinite(f) else None


def _cell(value: Any, kind: str = "keur", reason: str = "") -> dict[str, Any]:
    """{v, d, reason}: ``v`` the persisted value (or None), ``d`` its display.  Missing is UNAVAILABLE, never 0."""
    if isinstance(value, bool):
        return {"v": value, "d": "YES" if value else "no", "reason": ""}
    if kind == "text":
        text = value if isinstance(value, str) and value.strip() else None
        return {"v": text, "d": text or UNAVAILABLE, "reason": "" if text else reason}
    v = _num(value)
    if v is None:
        return {"v": None, "d": UNAVAILABLE, "reason": reason or "Not persisted in this Run's evidence."}
    if kind == "x":
        d = f"{v:.2f}x"
    elif kind == "pct":                      # a persisted FRACTION rendered as percent
        d = f"{v * 100:.2f}%"
    elif kind == "int":
        d = f"{int(round(v)):,}"
    else:                                    # keur
        d = f"{v:,.2f}"
    return {"v": v, "d": d, "reason": ""}


def _diff(a: Optional[float], b: Optional[float], kind: str) -> dict[str, Any]:
    """b - a as presentation arithmetic between two persisted values; unavailable when either side is missing."""
    if a is None or b is None:
        return {"v": None, "d": "—", "reason": "A value is unavailable in one of the two Runs."}
    delta = b - a
    if abs(delta) <= 1e-12:
        delta = 0.0
    if kind == "pct":
        return {"v": delta, "d": f"{delta * 100:+.2f} pp", "reason": ""}
    if kind == "x":
        return {"v": delta, "d": f"{delta:+.2f}x", "reason": ""}
    if kind == "int":
        return {"v": delta, "d": f"{int(round(delta)):+,}", "reason": ""}
    return {"v": delta, "d": f"{delta:+,.2f}", "reason": ""}


def _mapping(value: Any) -> Mapping:
    value = thaw_runtime_payload(value) if value is not None else None
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[Mapping]:
    value = thaw_runtime_payload(value) if value is not None else None
    return [r for r in value if isinstance(r, Mapping)] if isinstance(value, (list, tuple)) else []


# ── inputs ────────────────────────────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RunInput:
    """One committed Run selected for the workspace.

    ``state`` is supplied by the authorised request layer (canonical freshness authority); ``terms`` / ``working``
    only for the Last Run while it is CURRENT.
    """
    entry: Any
    state: str = HISTORICAL
    scenario_label: Optional[str] = None
    terms: Optional[ProjectTerms] = None
    working: Optional[Mapping[str, Any]] = None


def _links(project_code: str, history_id: str, *, last_run: bool) -> dict[str, str]:
    from urllib.parse import quote
    p, h = quote(project_code, safe=""), quote(history_id, safe="")
    return {
        "statements": f"/v2/workbook/run-history/statements?project={p}&history_id={h}",
        "run_detail": f"/v2/workbook/run-history/detail?project={p}&history_id={h}",
        "diagnostics": f"/v2/workbook?project={p}#diagnostics",
        "financing": f"/v2/workbook?project={p}#debt",
        "run_history": f"/v2/workbook?project={p}#run-history",
    }


# ── per-Run sections ──────────────────────────────────────────────────────────────────────────────────────────────
def _integrity(entry: Any) -> dict[str, Any]:
    evidence = getattr(entry, "integrity_evidence", None)
    if not evidence:
        return {"status": UNAVAILABLE, "counts": {}, "failures": [], "reason": "Run Integrity evidence not persisted for this Run."}
    try:
        from app.run_integrity import run_integrity_checks
        report = run_integrity_checks(evidence).to_dict()
    except Exception:  # noqa: BLE001 - presentation fails closed
        return {"status": UNAVAILABLE, "counts": {}, "failures": [], "reason": "Run Integrity evidence could not be evaluated."}
    overall = str(report.get("overall") or "")
    status = overall if overall in ("PASS", "FAIL", "INCOMPLETE") else UNAVAILABLE
    return {"status": status, "counts": dict(report.get("counts") or {}),
            "failures": [{"id": c.get("check_id"), "title": c.get("title"), "reason": c.get("reason_code")}
                         for c in report.get("checks", ()) if c.get("status") == "FAIL"], "reason": ""}


def _identity(inp: RunInput, integrity: Mapping[str, Any]) -> dict[str, Any]:
    e = inp.entry
    return {
        # The label must be proven by the authorised request layer; an unproven id is UNAVAILABLE, never Base Case.
        "history_id": e.history_id, "state": inp.state, "scenario": inp.scenario_label or UNAVAILABLE,
        "scenario_id": e.last_runtime_scenario_id, "ran_at": (e.ran_at or "")[:19].replace("T", " "),
        "snapshot_id": e.runtime_snapshot_id, "composite_hash": e.composite_hash, "engine_version": e.engine_version,
        "integrity": integrity["status"],
        "committed_with_integrity_failure": integrity["status"] == "FAIL",
    }


def _structure(inp: RunInput) -> dict[str, Any]:
    """Financing structure of the committed Run (sources, facilities, fees, reserve, observed interest/tenor)."""
    entry = inp.entry
    rs = _mapping(entry.runtime_summary)
    fe = _mapping(rs.get("financing_evidence"))
    su = _mapping(fe.get("sources_uses"))
    bank = _mapping(fe.get("bankability"))
    sd = _mapping(_mapping(entry.integrity_evidence).get("senior_debt"))
    periods = [p for p in _rows(sd.get("periods")) if (_num(p.get("debt_service")) or 0.0) > 1e-6]
    debt_rows = _rows(_mapping(entry.debt_schedule).get("periods"))
    sponsor = _mapping(_mapping(entry.sponsor_schedule).get("summary"))
    terminal = _mapping(_mapping(sponsor.get("terminal_financial_state")).get("senior"))
    authority = fe.get("facility_authority")
    state, reason, facilities = "AVAILABLE", "", []
    instrument_note = ""
    typed_ok = bool(fe)
    if typed_ok:
        # Reuse the F1/F3.7 read-only validators: malformed evidence fails closed instead of being repaired.
        try:
            from app.v2.financing_sources_uses_projection import FinancingEvidenceInvalid, build_sources_uses_projection
            view = build_sources_uses_projection(
                runtime_result=SimpleNamespace(runtime_summary=entry.runtime_summary, debt_schedule=entry.debt_schedule,
                                               sponsor_schedule=entry.sponsor_schedule),
                integrity_evidence=entry.integrity_evidence, freshness="NOT_RUN", run_kind="HISTORICAL_RUN",
                expected_snapshot_id=entry.runtime_snapshot_id, expected_composite_hash=entry.composite_hash,
                expected_scenario_id=entry.last_runtime_scenario_id)
            iv = view.get("instrument_view")
            if iv and iv.get("available"):
                for f in iv["instruments"]:
                    facilities.append({
                        "id": f["instrument_id"], "role": f["role"], "commitment": _cell(f["commitment"].value),
                        "drawn": _cell(f["drawn"].value), "idc": _cell(f["idc"].value), "upfront_fee": _cell(f["upfront"].value),
                        "commitment_fee": _cell(f["commitment_fee"].value), "draw_state": f["draw_state"]})
            elif iv:
                instrument_note = str(iv.get("unavailable_reason") or "")
        except FinancingEvidenceInvalid as exc:        # type: ignore[misc]
            state, reason = "INVALID", str(exc)
            su, bank, facilities = {}, {}, []
    else:
        state, reason = "LEGACY", "Legacy Run — typed financing evidence is not persisted; nothing is backfilled."
    rates = [r for r in (_num(p.get("annual_rate")) for p in periods) if r is not None]
    maturity_date = terminal.get("contractual_maturity_date")
    dsra_bal = [b for b in (_num(r.get("dsra_balance_keur")) for r in debt_rows) if b is not None]
    first_ds = next((r.get("date") for r in debt_rows if (_num(r.get("senior_ds_keur")) or 0.0) > 0), None)
    last_ds = next((r.get("date") for r in reversed(debt_rows) if (_num(r.get("senior_ds_keur")) or 0.0) > 0), None)
    explicit = authority == TWO_SENIOR_AUTHORITY
    junior = authority == JUNIOR_AUTHORITY
    sizing_note = ("Explicit contractual Senior commitments (F3): the commitment is an input, not a sizing result."
                   if explicit else
                   "Senior debt with an explicit Junior facility (F3)." if junior else
                   "Single Senior facility sized by the canonical solver; the sized amount is the committed commitment.")
    bound = dict(inp.working or {})
    equity_src = _num(su.get("share_capital_and_other_equity_keur"))
    shl_cash = _num(su.get("shareholder_loan_cash_keur"))
    sponsor_contrib = _num(sponsor.get("total_sponsor_contributed_keur"))
    return {
        "state": state, "reason": reason, "authority": authority or ("AGGREGATE_SINGLE_SENIOR" if typed_ok else None),
        "sizing_note": sizing_note, "instrument_note": instrument_note, "facilities": facilities,
        "commitment": _cell(su.get("senior_debt_keur") if typed_ok else rs.get("senior_debt_keur")),
        "commitment_label": "Contractual Senior commitments (sum)" if explicit else "Senior commitment (sized)",
        "requested_gearing": _cell(bank.get("gearing_ratio"), "pct", "Requested gearing cap not persisted for this Run."),
        "actual_gearing": _cell(rs.get("actual_gearing_pct"), "pct"),
        "gearing_cap_run": _cell(rs.get("gearing_cap_pct"), "pct"),
        "total_uses": _cell(su.get("total_uses_keur")), "total_sources": _cell(su.get("total_sources_keur")),
        "equity_sources": _cell(equity_src), "shl_cash": _cell(shl_cash), "sponsor_contributed": _cell(sponsor_contrib),
        "tenor": {
            "first_debt_service_date": _cell(first_ds, "text"), "last_debt_service_date": _cell(last_ds, "text"),
            "debt_service_periods": _cell(len(periods) if periods else None, "int", "No scheduled Senior debt service in this Run."),
            "contractual_maturity_date": _cell(maturity_date, "text", "Contractual maturity not persisted for this Run."),
            "basis": "Observed in the committed debt schedule — not an input term."},
        "interest": {
            "day_count": _cell(sd.get("day_count"), "text", "Day count not persisted for this Run."),
            "annual_rate_min": _cell(min(rates) if rates else None, "pct"), "annual_rate_max": _cell(max(rates) if rates else None, "pct"),
            "basis": "Observed annual all-in rate over the scheduled debt-service periods (per-facility operating rates are not persisted)."},
        "fees": {
            "commitment_fee": _cell(su.get("commitment_fee_keur")), "structuring_fee": _cell(su.get("structuring_fee_keur")),
            "capitalized_idc": _cell(su.get("capitalized_idc_keur")), "other_financing_costs": _cell(su.get("other_financing_costs_keur")),
            "basis": "Committed Sources & Uses lines (kEUR)."},
        "reserve": {
            "initial_dsra_funding": _cell(su.get("initial_dsra_funding_keur")),
            "dsra_peak_balance": _cell(max(dsra_bal) if dsra_bal else None, "keur", "DSRA balance series not persisted."),
            "dsra_final_balance": _cell(dsra_bal[-1] if dsra_bal else None),
            "regime": _cell(bound.get("reserve_regime"), "text", "Reserve instrument (cash DSRA / DSRF standby / none) is not persisted "
                            "with the Run; shown only for the CURRENT Last Run."),
            "dsrf_note": "A DSRF standby commitment is not cash funded and is not a DSRA balance; missing reserve evidence is not zero."},
        "lender_case": {
            "value": _cell(bound.get("lender_case"), "text", "The lender case (P50 / P90-10y) is not persisted with a Run; shown only for the "
                           "CURRENT Last Run."),
            "operating_case": "Operational generation case (P50): the Run's revenue, EBITDA and CFADS series.",
            "credit_case": ("Credit-sizing case: " + str(bound["lender_case"]) + " (bound Working Copy value)") if bound.get("lender_case")
            else "Credit-sizing case: UNAVAILABLE for this Run (see above).",
            "sizing_cfads_persisted": any(_num(p.get("bank_cfads")) is not None for p in periods),
            "note": "The operating case and the lender case are separate: lender assumptions size debt, they never change the operating case."},
        "sizing_mode": {
            "value": _cell(bound.get("sizing_mode"), "text", "Sizing mode is not persisted with a Run; shown only for the CURRENT Last Run."),
            "note": "`flat_dscr_sculpted` still applies the Total-Project-Uses gearing cap, so it behaves like the combined minimum of DSCR capacity "
                    "and gearing capacity — there is no pure DSCR-only sizing route (WF-A F-1, naming vs behaviour, financial-authority review "
                    "pending). `gearing_cap` keeps level principal independent of CFADS and has no feasibility check (WF-A F-2)."},
        "maturity": {"status": _cell(terminal.get("status"), "text", "Senior terminal state not persisted."),
                     "balance_at_maturity": _cell(terminal.get("balance_at_contractual_maturity_keur"))},
        "active_terms_basis": ("Committed Run evidence only. Working Copy terms are bound only for the CURRENT Last Run." if not bound else
                               "Committed Run evidence; Working Copy terms are bound (Last Run is CURRENT)."),
    }


def _capacity(inp: RunInput, structure: Mapping[str, Any]) -> dict[str, Any]:
    entry = inp.entry
    rs = _mapping(entry.runtime_summary)
    fe = _mapping(rs.get("financing_evidence"))
    bank = _mapping(fe.get("bankability")) if structure.get("state") == "AVAILABLE" else {}
    sd = _mapping(_mapping(entry.integrity_evidence).get("senior_debt"))
    diag = _mapping(sd.get("diagnostics"))
    periods = [p for p in _rows(sd.get("periods")) if (_num(p.get("debt_service")) or 0.0) > 1e-6]
    debt_summary = _mapping(_mapping(entry.debt_schedule).get("summary"))
    n = len(periods)

    def total(key: str) -> dict[str, Any]:
        values = [_num(p.get(key)) for p in periods]
        if not periods or any(v is None for v in values):
            return _cell(None, "keur", "Period series not persisted for this Run.")
        c = _cell(math.fsum(values))
        c["basis"] = f"Sum of {n} committed Senior-debt period values."
        return c
    binding = bank.get("binding_senior_constraint")
    explicit = fe.get("facility_authority") == TWO_SENIOR_AUTHORITY
    pf = [r for r in _rows(_mapping(_mapping(entry.financial_statements).get("pf_cash_waterfall")).get("periods"))]
    pf_values = [_num(r.get("fcf_banks_keur")) for r in pf]
    if pf and all(v is not None for v in pf_values):
        statement_cfads = _cell(math.fsum(pf_values))
        statement_cfads["basis"] = f"Sum of 'FCF to banks' (CFADS) over {len(pf)} committed statement periods."
    else:
        statement_cfads = _cell(None, "keur", "FCF-to-banks statement series not persisted for this Run.")
    return {
        "cfads_statement_total": statement_cfads,
        "dscr_debt_capacity": _cell(bank.get("dscr_debt_capacity_keur"), "keur", "DSCR debt capacity is not persisted for this Run."),
        "gearing_debt_capacity": _cell(bank.get("gearing_debt_capacity_keur"), "keur", "Gearing debt capacity is not persisted for this Run."),
        "final_commitment": _cell(bank.get("final_senior_commitment_keur"), "keur", "Final sized commitment is not persisted for this Run."),
        "binding_constraint": _cell(binding, "text", "Binding Senior constraint is not persisted for this Run; it is never inferred from gearing "
                                    "or capacity values."),
        "gearing_basis": _cell(bank.get("gearing_basis_keur")),
        "fixed_point_iterations": _cell(bank.get("fixed_point_iteration_count"), "int"),
        "explicit_commitments": explicit,
        "convergence": {
            "termination_reason": _cell(diag.get("termination_reason"), "text", "Solver diagnostics not persisted for this Run."),
            "converged": diag.get("converged") if isinstance(diag.get("converged"), bool) else None,
            "authoritative": diag.get("is_authoritative") if isinstance(diag.get("is_authoritative"), bool) else None,
            "note": "Numerical convergence of the solver is not credit feasibility: a Run can converge with a DSCR below 1.0x."},
        "min_dscr": _cell(rs.get("min_dscr"), "x", "Minimum DSCR not persisted."),
        "avg_dscr": _cell(rs.get("avg_dscr"), "x", "Average DSCR not persisted."),
        "target_dscr": _cell(rs.get("target_dscr") if rs.get("target_dscr") is not None else debt_summary.get("target_dscr"), "x",
                             "Sizing target DSCR not persisted."),
        "min_llcr": _cell(rs.get("min_llcr") if rs.get("min_llcr") is not None else debt_summary.get("min_llcr"), "x",
                          str(debt_summary.get("llcr_unavailable_reason") or "Minimum LLCR is not persisted with this Run (no discount basis).")),
        "total_senior_ds": _cell(rs.get("total_senior_ds_keur") if rs.get("total_senior_ds_keur") is not None
                                 else debt_summary.get("total_senior_ds_keur")),
        "principal_total": total("principal"), "interest_total": total("interest"), "debt_service_total": total("debt_service"),
        "base_cfads_total": total("base_cfads"), "bank_cfads_total": total("bank_cfads"),
        "periods_in_lockup": _cell(rs.get("periods_in_lockup") if rs.get("periods_in_lockup") is not None
                                   else debt_summary.get("periods_in_lockup"), "int"),
        "tightest": _tightest(periods, _dates(entry)),
    }


def _dates(entry: Any) -> dict[int, str]:
    out: dict[int, str] = {}
    for r in _rows(_mapping(entry.debt_schedule).get("periods")):
        if isinstance(r.get("period"), int) and isinstance(r.get("date"), str):
            out[r["period"]] = r["date"]
    return out


def _tightest(periods: Sequence[Mapping], dates: Mapping[int, str], limit: int = 3) -> list[dict[str, Any]]:
    scored = [(p["reported_dscr"], p["period_index"]) for p in periods
              if _num(p.get("reported_dscr")) is not None and isinstance(p.get("period_index"), int)]
    scored.sort()
    out = []
    for dscr, idx in scored[:limit]:
        row = next(p for p in periods if p["period_index"] == idx)
        out.append({"period_index": idx, "date": dates.get(idx), "dscr": _cell(dscr, "x"),
                    "target": _cell(row.get("target_dscr"), "x"), "debt_service": _cell(row.get("debt_service")),
                    "base_cfads": _cell(row.get("base_cfads"))})
    return out


# credit-risk timeline ---------------------------------------------------------------------------------------------
_ROWS = (
    # key, label, kind, class/authority, link target
    ("dscr", "DSCR (reported, base CFADS)", "x", "financing"),
    ("target_dscr", "Sizing target DSCR (not a covenant)", "x", "financing"),
    ("base_cfads", "CFADS — base case (kEUR)", "keur", "statements"),
    ("bank_cfads", "CFADS — lender / sizing case (kEUR)", "keur", "financing"),
    ("debt_service", "Senior debt service (kEUR)", "keur", "financing"),
    ("interest", "Senior interest (kEUR)", "keur", "financing"),
    ("principal", "Senior principal (kEUR)", "keur", "financing"),
    ("closing", "Senior closing balance (kEUR)", "keur", "financing"),
    ("dsra_balance", "DSRA balance (kEUR)", "keur", "financing"),
    ("distribution", "Distribution paid (kEUR)", "keur", "statements"),
    ("lockup", "Distribution lock-up flagged (committed)", "flag", "diagnostics"),
    ("below_one", "CFADS below debt service (DSCR < 1.0x, observed)", "flag", "diagnostics"),
    ("below_target", "DSCR below the sizing target (advisory)", "flag", "diagnostics"),
)


def _timeline(inp: RunInput) -> dict[str, Any]:
    entry = inp.entry
    sd = _mapping(_mapping(entry.integrity_evidence).get("senior_debt"))
    periods = [p for p in _rows(sd.get("periods")) if isinstance(p.get("period_index"), int)]
    if not periods:
        return {"available": False, "reason": "No committed Senior-debt period evidence for this Run.", "columns": [], "rows": []}
    dates = _dates(entry)
    dist = {r.get("period"): r for r in _rows(_mapping(entry.distribution_schedule).get("periods"))}
    dsra = {r.get("period"): r for r in _rows(_mapping(entry.debt_schedule).get("periods"))}
    # RC-7B Correction B: the committed axis is contiguous and half-open, so a period starts where the committed previous period ended.
    # ``start`` is that committed end date; when the previous period is not persisted it is None (never inferred), and Credit V4 then
    # cannot prove the interval and reports NOT_COMPARABLE.
    columns = [{"index": p["period_index"], "date": dates.get(p["period_index"]) or _mapping(dist.get(p["period_index"])).get("date"),
                "start": dates.get(p["period_index"] - 1)}
               for p in periods]
    rows = []
    for key, label, kind, link in _ROWS:
        cells = []
        for p in periods:
            i = p["period_index"]
            ds = (_num(p.get("debt_service")) or 0.0) > 1e-6
            dscr, target = _num(p.get("reported_dscr")), _num(p.get("target_dscr"))
            if key in ("dscr", "target_dscr", "base_cfads", "bank_cfads", "debt_service", "interest", "principal"):
                src = {"dscr": "reported_dscr", "target_dscr": "target_dscr"}.get(key, key)
                cells.append(_cell(p.get(src), kind))
            elif key == "closing":
                cells.append(_cell(p.get("closing"), "keur"))
            elif key == "dsra_balance":
                cells.append(_cell(_mapping(dsra.get(i)).get("dsra_balance_keur"), "keur", "DSRA balance not persisted for this period."))
            elif key == "distribution":
                cells.append(_cell(_mapping(dist.get(i)).get("distribution_keur"), "keur", "Distribution not persisted for this period."))
            elif key == "lockup":
                flag = _mapping(dist.get(i)).get("lockup_active")
                cells.append(_cell(flag if isinstance(flag, bool) else None, "flag", "Lock-up flag not persisted for this period."))
            elif key == "below_one":
                cells.append(_cell(None, "flag", "No DSCR persisted.") if dscr is None or not ds else
                             {"v": dscr < 1.0 - TOL_RATIO, "d": "YES" if dscr < 1.0 - TOL_RATIO else "no", "reason": ""})
            else:
                bad = None if dscr is None or target is None or not ds else dscr < target - SIZING_TARGET_TOL
                cells.append(_cell(None, "flag", "No DSCR or sizing target persisted.") if bad is None else
                             {"v": bad, "d": "YES" if bad else "no", "reason": ""})
        rows.append({"key": key, "label": label, "kind": kind, "link": link, "cells": cells})
    return {"available": True, "reason": "", "columns": columns, "rows": rows,
            "basis": "Every cell is a value persisted by the Run (period identity = the committed period index and date). Flags compare a "
                     "persisted DSCR with 1.0x or the sizing target using the existing Model Quality tolerances; nothing is recalculated."}


# ── findings ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _finding(*, fid: str, source: str, title: str, klass: str, status: str, run: Mapping[str, Any], metric: str, actual: Any = None,
             threshold: Any = None, authority: str = "", headroom: Any = None, evidence_source: str = "", severity: str = "",
             detail: str = "", period: Any = None, reason_code: str = "", links: Optional[Mapping[str, str]] = None,
             check_id: str = "") -> dict[str, Any]:
    return {"id": fid, "source": source, "check_id": check_id, "title": title, "classification": klass, "status": status,
            "severity": severity or "INFORMATION", "run_history_id": run["history_id"], "run_state": run["state"],
            "scenario": run["scenario"], "period": period if period is not None else "AGGREGATE", "metric": metric,
            "actual": actual if actual is not None else _cell(None, "text"), "threshold": threshold if threshold is not None else _cell(None, "text"),
            "threshold_authority": authority or "NONE", "headroom": headroom if headroom is not None else _cell(None, "text"),
            "evidence_source": evidence_source, "detail": detail, "reason_code": reason_code, "links": dict(links or {})}


def _headroom(actual: Optional[float], threshold: Optional[float], kind: str) -> Optional[dict[str, Any]]:
    if actual is None or threshold is None:
        return None
    return _diff(threshold, actual, kind)       # actual − threshold; positive = above the threshold


def _qm_findings(inp: RunInput, run: Mapping[str, Any], links: Mapping[str, str]) -> list[dict[str, Any]]:
    entry = inp.entry
    freshness = {LAST_CURRENT: "CURRENT", LAST_STALE: "STALE"}.get(inp.state)
    terms = inp.terms if inp.state == LAST_CURRENT else None
    report = evaluate_model_quality(evidence_from_history_entry(
        entry, freshness=freshness, terms=terms, active_scenario_id=entry.last_runtime_scenario_id, scenario_known=True))
    contractual_terms = bool(terms and terms.contractual)
    out = []
    for c in report.checks:
        if c.check_id not in CREDIT_QM:
            continue
        klass, note = CREDIT_QM[c.check_id]
        status = c.status.value
        if c.status is CheckStatus.UNAVAILABLE:
            klass = UNSUPPORTED
        elif c.check_id in ("QM-COV-001", "QM-COV-002", "QM-COV-003", "QM-COV-004") and contractual_terms:
            klass = CONTRACTUAL                     # only a term supplied as contractual is ever classified as a covenant
        elif c.check_id in ("QM-SD-003", "QM-SD-004", "QM-SD-005", "QM-SD-006"):
            klass = OBSERVED
        elif c.check_id == "QM-SD-007" and c.reason_code == "DSCR_BELOW_ONE":
            klass = OBSERVED
        authority = c.threshold_authority
        if c.check_id in ("QM-COV-001", "QM-COV-002", "QM-COV-003", "QM-COV-004") and c.status is not CheckStatus.UNAVAILABLE:
            if not contractual_terms:
                klass = ADVISORY              # a supplied threshold is a project input until it is proven contractual
                if status == "FAIL":          # never present a project-input shortfall as a covenant breach
                    status = "BELOW_PROJECT_INPUT_THRESHOLD"
                authority = f"{authority} · project input, not verified as contractual"
            else:
                authority = f"{authority} · supplied as a CONTRACTUAL term"
        kind = "x" if c.measured_unit in ("x", "ratio") else "keur"
        if c.check_id == "QM-SD-006":
            kind = "pct"
        detail = c.detail
        if c.check_id in RESIDUAL_QM:           # these checks measure a reconciliation residual, not a credit metric
            actual = _cell(None, "text", "Reconciliation check: the measured value is a residual, shown in the detail.")
            if c.measured_value is not None:
                detail = f"{detail} (max residual {c.measured_value:.3g})".strip()
        else:
            actual = _cell(c.measured_value, kind)
        threshold = _cell(c.threshold_value, kind)
        head = _headroom(c.measured_value, c.threshold_value, kind) if (
            c.threshold_value is not None and c.measured_value is not None and klass in (CONTRACTUAL, ADVISORY, OBSERVED)
            and c.check_id in ("QM-SD-007", "QM-COV-001", "QM-COV-002", "QM-COV-003", "QM-SD-006", "QM-CASH-002")) else None
        out.append(_finding(
            fid=f"{run['history_id']}:{c.check_id}", source="MODEL_QUALITY", check_id=c.check_id, title=c.title, klass=klass, status=status,
            run=run, metric=note, actual=actual, threshold=threshold, authority=authority, headroom=head,
            evidence_source=c.evidence_source, severity=c.severity.value if status in ("FAIL", "WARNING") else "INFORMATION",
            detail=detail, reason_code=c.reason_code or "", links=links))
    return out


def _credit_findings(inp: RunInput, run: Mapping[str, Any], structure: Mapping[str, Any], capacity: Mapping[str, Any],
                     timeline: Mapping[str, Any], integrity: Mapping[str, Any], links: Mapping[str, str],
                     qm_by_id: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    entry = inp.entry
    rs = _mapping(entry.runtime_summary)
    debt_summary = _mapping(_mapping(entry.debt_schedule).get("summary"))
    out: list[dict[str, Any]] = []
    sev_d = qm_by_id.get("QM-SD-007", {}).get("severity", "HIGH")

    # F-2: convergence is not credit feasibility.
    min_dscr = _num(rs.get("min_dscr"))
    conv = capacity["convergence"]
    if min_dscr is not None and min_dscr < 1.0 - TOL_RATIO:
        converged = conv["termination_reason"]["v"] == "CONVERGED"
        out.append(_finding(
            fid=f"{run['history_id']}:CD-F2", source="CREDIT_DECISION", title="DSCR below 1.0x" + (" although the solver CONVERGED" if converged else ""),
            klass=OBSERVED, status="FAIL", run=run, metric="Minimum DSCR (base CFADS ÷ Senior debt service)", actual=_cell(min_dscr, "x"),
            threshold=_cell(1.0, "x"), authority="DSCR identity (CFADS = debt service); not a lender covenant",
            headroom=_headroom(min_dscr, 1.0, "x"), evidence_source="runtime_summary.min_dscr; integrity_evidence.senior_debt.diagnostics.termination_reason",
            severity=sev_d, links=links, reason_code="DSCR_BELOW_ONE",
            detail=("Solver termination: " + str(conv["termination_reason"]["d"]) + ". Numerical convergence and credit feasibility are different "
                    "questions: base CFADS does not cover scheduled Senior debt service in at least one period (WF-A F-2).")))
    # DSCR-below-1.0x periods.
    if timeline.get("available"):
        row = next(r for r in timeline["rows"] if r["key"] == "below_one")
        bad = [c for c, cell in zip(timeline["columns"], row["cells"]) if cell["v"] is True]
        if bad:
            out.append(_finding(
                fid=f"{run['history_id']}:CD-SHORTFALL", source="CREDIT_DECISION", title="Periods where base CFADS does not cover Senior debt service",
                klass=OBSERVED, status="FAIL", run=run, metric="Periods with DSCR < 1.0x", actual=_cell(len(bad), "int"),
                period=", ".join(f"P{c['index']} {c['date'] or ''}".strip() for c in bad[:FINDING_LIMIT_PERIODS]) + (" …" if len(bad) > FINDING_LIMIT_PERIODS else ""),
                evidence_source="integrity_evidence.senior_debt.periods.reported_dscr", severity=sev_d, links=links,
                detail="Committed period values; see the credit-risk timeline for every period."))
        lock = next(r for r in timeline["rows"] if r["key"] == "lockup")
        locked = [c for c, cell in zip(timeline["columns"], lock["cells"]) if cell["v"] is True]
        if locked:
            out.append(_finding(
                fid=f"{run['history_id']}:CD-LOCKUP", source="CREDIT_DECISION", title="Distribution lock-up flagged by the committed distribution schedule",
                klass=OBSERVED, status="OBSERVED", run=run, metric="Periods with lock-up flagged", actual=_cell(len(locked), "int"),
                period=", ".join(f"P{c['index']} {c['date'] or ''}".strip() for c in locked[:FINDING_LIMIT_PERIODS]) + (" …" if len(locked) > FINDING_LIMIT_PERIODS else ""),
                evidence_source="distribution_schedule.periods.lockup_active", links=links,
                detail="A lock-up restricts distributions; it is not a default and no contractual lock-up term is asserted."))
    # F-5: unavailable equity IRR.
    if _num(rs.get("equity_irr")) is None:
        out.append(_finding(
            fid=f"{run['history_id']}:CD-F5", source="CREDIT_DECISION", title="Equity IRR is unavailable", klass=UNSUPPORTED, status=UNAVAILABLE,
            run=run, metric="Pure-equity IRR", actual=_cell(None, "pct", "The canonical Run published no equity IRR (status: "
                                                            + str(rs.get("share_capital_irr_status") or "not persisted") + ")."),
            evidence_source="runtime_summary.equity_irr / share_capital_irr_status", links=links, reason_code=str(rs.get("share_capital_irr_status") or "NOT_PERSISTED"),
            detail="Shown as unavailable — never zero and never an estimate (WF-A F-5)."))
    # F-6: LLCR / PLCR / EoD / cash sweep.
    llcr = capacity["min_llcr"]
    out.append(_finding(
        fid=f"{run['history_id']}:CD-LLCR", source="CREDIT_DECISION", title="Minimum LLCR", klass=OBSERVED if llcr["v"] is not None else UNSUPPORTED,
        status="OBSERVED" if llcr["v"] is not None else UNAVAILABLE, run=run, metric="Minimum LLCR (persisted)", actual=llcr,
        evidence_source="debt_schedule.summary.min_llcr", links=links,
        detail="Persisted value only. No threshold is applied here; a project LLCR requirement is evaluated by QM-COV-003 when bound." if llcr["v"] is not None
        else "LLCR is not computed or persisted for this Run (no discount basis): UNAVAILABLE, never derived."))
    for fid, title, why in (
        ("CD-PLCR", "Project life coverage ratio (PLCR)", "PLCR is not computed or persisted by the Run."),
        ("CD-EOD", "Event of default", "No default-DSCR term or event-of-default mechanic exists in the Run or the project inputs; no default is ever declared."),
    ):
        out.append(_finding(fid=f"{run['history_id']}:{fid}", source="CREDIT_DECISION", title=title, klass=UNSUPPORTED, status=UNAVAILABLE, run=run,
                            metric=title, evidence_source="none", links=links, reason_code="EVIDENCE_MISSING", detail=why))
    sweeps = [_num(r.get("cash_sweep_keur")) for r in _rows(_mapping(entry.distribution_schedule).get("periods"))]
    persisted = [s for s in sweeps if s is not None]
    out.append(_finding(
        fid=f"{run['history_id']}:CD-SWEEP", source="CREDIT_DECISION", title="Cash sweep", klass=OBSERVED if persisted else UNSUPPORTED,
        status="OBSERVED" if persisted else UNAVAILABLE, run=run, metric="Cash sweep amounts (persisted)",
        actual=_cell(math.fsum(persisted), "keur") if persisted else _cell(None, "keur", "No cash-sweep amount is persisted by this Run."),
        evidence_source="distribution_schedule.periods.cash_sweep_keur", links=links, reason_code="" if persisted else "EVIDENCE_MISSING",
        detail="Persisted sweep amounts only." if persisted else "The distribution schedule carries no sweep amounts: UNAVAILABLE."))
    # Senior maturity state.
    status = structure["maturity"]["status"]["v"]
    if status and status not in ("REPAID", "NOT_APPLICABLE"):
        out.append(_finding(
            fid=f"{run['history_id']}:CD-MATURITY", source="CREDIT_DECISION", title="Senior debt at contractual maturity", klass=OBSERVED, status="OBSERVED",
            run=run, metric="Senior terminal state", actual=structure["maturity"]["status"], evidence_source="sponsor_schedule.summary.terminal_financial_state.senior",
            links=links, detail="Canonical terminal state as persisted; no default is declared."))
    # F-8: committed with an integrity failure.
    if integrity["status"] in ("FAIL", "INCOMPLETE"):
        out.append(_finding(
            fid=f"{run['history_id']}:CD-INTEGRITY", source="CREDIT_DECISION", title=f"Committed Run with Run Integrity {integrity['status']}", klass=OBSERVED,
            status="FAIL" if integrity["status"] == "FAIL" else "WARNING", run=run, metric="Run Integrity overall",
            actual=_cell(integrity["status"], "text"), evidence_source="integrity_evidence (Run Integrity checks)", severity="HIGH", links=links,
            reason_code=",".join(f["id"] for f in integrity["failures"])[:200],
            detail="This is a failure state, not a bankable scenario. " + (
                "Failed checks: " + "; ".join(f"{f['id']} ({f['reason']})" for f in integrity["failures"]) if integrity["failures"] else "")))
    # Lender case not persisted.
    if capacity["binding_constraint"]["v"] is None:
        out.append(_finding(
            fid=f"{run['history_id']}:CD-BINDING", source="CREDIT_DECISION", title="Binding sizing constraint", klass=UNSUPPORTED, status=UNAVAILABLE, run=run,
            metric="Binding Senior constraint", actual=capacity["binding_constraint"], evidence_source="runtime_summary.financing_evidence.bankability.binding_senior_constraint",
            links=links, reason_code="EVIDENCE_MISSING",
            detail="Not persisted for this Run (legacy Run or explicit facilities); it is not reconstructed from gearing or capacity values."))
    return out


# ── cross-Run comparison ──────────────────────────────────────────────────────────────────────────────────────────
def _cmp_metrics(inp: RunInput, structure: Mapping, capacity: Mapping) -> dict[str, dict[str, Any]]:
    rs = _mapping(inp.entry.runtime_summary)
    su = _mapping(_mapping(rs.get("financing_evidence")).get("sources_uses")) if structure["state"] == "AVAILABLE" else {}
    sponsor = _mapping(_mapping(inp.entry.sponsor_schedule).get("summary"))
    return {
        "total_revenue": _cell(rs.get("total_revenue_keur")), "total_ebitda": _cell(rs.get("total_ebitda_keur")),
        "cfads_total": capacity["cfads_statement_total"],
        "debt_service_total": capacity["debt_service_total"], "total_senior_ds": capacity["total_senior_ds"],
        "min_dscr": capacity["min_dscr"], "avg_dscr": capacity["avg_dscr"], "target_dscr": capacity["target_dscr"], "min_llcr": capacity["min_llcr"],
        "periods_in_lockup": capacity["periods_in_lockup"],
        "dscr_capacity": capacity["dscr_debt_capacity"], "gearing_capacity": capacity["gearing_debt_capacity"],
        "final_commitment": structure["commitment"], "actual_gearing": structure["actual_gearing"],
        "total_uses": structure["total_uses"], "hard_capex": _cell(su.get("base_project_capex_keur")),
        "idc": structure["fees"]["capitalized_idc"], "commitment_fee": structure["fees"]["commitment_fee"],
        "structuring_fee": structure["fees"]["structuring_fee"], "initial_dsra": structure["reserve"]["initial_dsra_funding"],
        "other_fin_costs": structure["fees"]["other_financing_costs"],
        "equity_sources": structure["equity_sources"], "shl_cash": structure["shl_cash"], "sponsor_contributed": structure["sponsor_contributed"],
        "total_distributions": _cell(rs.get("total_distributions_keur")),
        "legal_equity_distributions": _cell(sponsor.get("total_legal_equity_distributions_keur")),
        "project_irr": _cell(rs.get("project_irr"), "pct"),
        "equity_irr": _cell(rs.get("equity_irr"), "pct", "The canonical Run published no equity IRR (status: " + str(rs.get("share_capital_irr_status") or "not persisted") + ")."),
        "sponsor_irr": _cell(rs.get("sponsor_irr"), "pct", "The canonical Run published no sponsor IRR."),
        "binding": capacity["binding_constraint"],
    }


COMPARE_GROUPS = (
    ("Revenue and cash flow", (("total_revenue", "Total revenue (kEUR)", "keur"), ("total_ebitda", "Total EBITDA (kEUR)", "keur"),
                               ("cfads_total", "CFADS (FCF to banks), Σ committed statement periods (kEUR)", "keur"))),
    ("Debt service and coverage", (("debt_service_total", "Senior debt service, Σ scheduled periods (kEUR)", "keur"), ("min_dscr", "Minimum DSCR", "x"),
                                   ("avg_dscr", "Average DSCR", "x"), ("target_dscr", "Sizing target DSCR", "x"), ("min_llcr", "Minimum LLCR", "x"),
                                   ("periods_in_lockup", "Periods in lock-up", "int"))),
    ("Available financing capacity", (("dscr_capacity", "DSCR debt capacity (kEUR)", "keur"), ("gearing_capacity", "Gearing debt capacity (kEUR)", "keur"),
                                      ("final_commitment", "Senior commitment (kEUR)", "keur"), ("actual_gearing", "Actual gearing", "pct"),
                                      ("binding", "Binding Senior constraint", "text"))),
    ("Uses that move debt (committed Sources & Uses lines)", (("hard_capex", "Hard project CAPEX (kEUR)", "keur"), ("idc", "Capitalised IDC (kEUR)", "keur"),
                                                             ("commitment_fee", "Commitment fees (kEUR)", "keur"), ("structuring_fee", "Structuring / bank fees (kEUR)", "keur"),
                                                             ("other_fin_costs", "Other financing costs (kEUR)", "keur"), ("initial_dsra", "Initial cash DSRA funding (kEUR)", "keur"),
                                                             ("total_uses", "Total uses (kEUR)", "keur"))),
    ("Equity requirement", (("equity_sources", "Share capital and other equity (kEUR)", "keur"), ("shl_cash", "Shareholder loan cash (kEUR)", "keur"),
                            ("sponsor_contributed", "Total sponsor contributed (kEUR)", "keur"))),
    ("Distributions and returns", (("total_distributions", "Total distributions (kEUR)", "keur"), ("legal_equity_distributions", "Legal equity distributions (kEUR)", "keur"),
                                   ("project_irr", "Project IRR", "pct"), ("equity_irr", "Pure-equity IRR", "pct"), ("sponsor_irr", "Total sponsor IRR", "pct"))),
)
USES_KEYS = ("hard_capex", "idc", "commitment_fee", "structuring_fee", "other_fin_costs", "initial_dsra")


def _comparison(views: Sequence[Mapping[str, Any]], metrics: Sequence[Mapping[str, Mapping]]) -> dict[str, Any]:
    if len(views) < 2:
        return {"available": False, "reason": "Select two or three committed Runs to compare.", "groups": [], "notes": [], "reference": None}
    ref = views[0]["identity"]["history_id"]
    notes = []
    ids = [v["identity"] for v in views]
    if len({i["composite_hash"] for i in ids}) < len(ids):
        notes.append("Two selected Runs share the same composite input identity: differences come from the solve path, not from changed inputs.")
    if len({i["engine_version"] for i in ids}) > 1:
        notes.append("The selected Runs were computed on different engine versions; differences may include engine changes.")
    auth = {v["structure"].get("authority") for v in views}
    if len(auth) > 1:
        notes.append("The financing authority differs between the selected Runs (single-Senior sizing vs explicit facilities): sizing metrics are not like-for-like.")
    groups = []
    for title, items in COMPARE_GROUPS:
        rows = []
        for key, label, kind in items:
            cells = [m[key] for m in metrics]
            deltas = [None] + ([_diff(cells[0]["v"], c["v"], kind) for c in cells[1:]] if kind != "text" else [None] * (len(cells) - 1))
            rows.append({"key": key, "label": label, "kind": kind, "cells": cells, "deltas": deltas})
        groups.append({"title": title, "rows": rows})
    f3 = _f3_findings(views, metrics)
    return {"available": True, "reason": "", "reference": ref, "groups": groups, "notes": notes, "f3": f3,
            "basis": "Differences are plain differences of persisted Run values (display arithmetic; the first selected Run is the reference). "
                     "Working Copy data is never compared as Run evidence."}


def _f3_findings(views: Sequence[Mapping[str, Any]], metrics: Sequence[Mapping[str, Mapping]]) -> list[dict[str, Any]]:
    """WF-A F-3: debt capacity rising while revenue falls — attribution only from committed Uses lines."""
    out = []
    base_m, base_v = metrics[0], views[0]
    for m, v in zip(metrics[1:], views[1:]):
        rev0, rev1 = base_m["total_revenue"]["v"], m["total_revenue"]["v"]
        d0, d1 = base_m["final_commitment"]["v"], m["final_commitment"]["v"]
        if None in (rev0, rev1, d0, d1) or not (rev1 < rev0 - TOL_KEUR and d1 > d0 + TOL_KEUR):
            continue
        deltas = {k: _diff(base_m[k]["v"], m[k]["v"], "keur") for k in USES_KEYS + ("total_uses",)}
        bind0, bind1 = base_m["binding"]["v"], m["binding"]["v"]
        attributable = bind0 == "GEARING" and bind1 == "GEARING"
        out.append({
            "run_history_id": v["identity"]["history_id"], "reference_history_id": base_v["identity"]["history_id"], "scenario": v["identity"]["scenario"],
            "revenue_change": _diff(rev0, rev1, "keur"), "commitment_change": _diff(d0, d1, "keur"), "uses_changes": deltas,
            "attribution": "COMMITTED_USES_LINES" if attributable else "UNAVAILABLE",
            "statement": (
                "Senior commitment increased while total revenue decreased. The binding constraint is GEARING in both Runs, so debt follows the "
                "gearing ratio applied to Total Project Uses; the Uses lines listed here changed between the two Runs (committed values). "
                "This lists what changed; it is not a causal proof." if attributable else
                "Senior commitment increased while total revenue decreased. A binding GEARING constraint is not persisted for both Runs, so "
                "the movement is not attributed: causal decomposition UNAVAILABLE.")})
    return out


# ── entry point ───────────────────────────────────────────────────────────────────────────────────────────────────
def build_credit_decision(inputs: Sequence[RunInput], *, project_code: str,
                          working_proposal: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Credit decision payload for one to three committed Runs of one project (pure; no I/O, no engine, no writes)."""
    if not MIN_RUNS <= len(inputs) <= MAX_RUNS:
        raise ValueError("CREDIT_DECISION_RUN_COUNT")
    if len({i.entry.history_id for i in inputs}) != len(inputs):
        raise ValueError("CREDIT_DECISION_DUPLICATE_RUN")
    views, metrics, findings = [], [], []
    for inp in inputs:
        integrity = _integrity(inp.entry)
        identity = _identity(inp, integrity)
        links = _links(project_code, inp.entry.history_id, last_run=inp.state != HISTORICAL)
        structure = _structure(inp)
        capacity = _capacity(inp, structure)
        timeline = _timeline(inp)
        run_findings = _qm_findings(inp, identity, links)
        qm_by = {f["check_id"]: {"severity": f["severity"]} for f in run_findings}
        run_findings += _credit_findings(inp, identity, structure, capacity, timeline, integrity, links, qm_by)
        views.append({"identity": identity, "integrity": integrity, "links": links, "structure": structure, "capacity": capacity,
                      "timeline": timeline, "findings": run_findings})
        from app.v2.diagnostics_run_compare import operating_frequency as _operating_frequency
        if _operating_frequency(inp.entry) != "6/6":
            # RC-7B: only non-default calendars are annotated; 6/6 views are unchanged.
            views[-1]["operating_frequency"] = _operating_frequency(inp.entry)
        metrics.append(_cmp_metrics(inp, structure, capacity))
        findings += run_findings
    comparison = _comparison(views, metrics)
    # RC-7 V4: observational evidence over already-authorised committed V3 views.
    # No new data reads, input terms, period authority or financial calculation.
    from app.v2.credit_v4_evidence import build_credit_v4
    credit_v4 = build_credit_v4(views)
    counts = {c: sum(1 for f in findings if f["classification"] == c) for c in CLASSES}
    return {
        "schema": SCHEMA, "project_code": project_code, "runs": views, "comparison": comparison, "findings": findings,
        "finding_counts": counts, "working_proposal": dict(working_proposal) if working_proposal else None,
        "credit_v4": credit_v4,
        "policy": {
            "failed_runs": "A failed or fail-closed Run is never committed, so it cannot be selected here. A committed Run whose Run Integrity "
                           "failed is labelled as a failure, never as a bankable scenario (WF-A F-8).",
            "classes": {CONTRACTUAL: "A term proven to be contractual (supplied as such). Never asserted from project inputs.",
                        ADVISORY: "A project input or sizing assumption used as an advisory threshold; FINCO cannot tell a negotiated term from a default.",
                        OBSERVED: "A value or fact persisted by the committed Run, without a threshold from a contract.",
                        UNSUPPORTED: "Evidence or authority missing; the exact gap is stated and nothing is inferred."},
            "disclosure": "FINCO decision intelligence over committed Run evidence. Not lender certification, not a contractual covenant test, no "
                          "probability of default and no event of default is declared."}}


__all__ = ["SCHEMA", "RunInput", "build_credit_decision", "LAST_CURRENT", "LAST_STALE", "HISTORICAL", "CONTRACTUAL", "ADVISORY", "OBSERVED",
           "UNSUPPORTED", "MAX_RUNS"]
