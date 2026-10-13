"""app.v2.insight_quality_projection — FINCO Insight view of the Q1 Model Quality report (presentation only).

Reuses, never re-implements:

* the Q1 registry / evaluators / scorer (``app.model_quality``) — the report is built by the canonical
  ``evaluate_model_quality`` over the persisted Last Run evidence; this module only *groups and formats* it;
* the Run Integrity report (through Q1);
* the exact canonical path mapping of Q2 (``register_path_for_field``) is not needed here: assumption links
  point at Explore register paths that actually exist in the Working Copy register view.

Nothing here runs the engine, recomputes a score, or writes.  Unavailable evidence is never shown as PASS,
evidence completeness (coverage) is shown separately from financial findings, and a covenant row exists only
with the authority that supports it: an absent threshold is ``CONTRACTUAL_THRESHOLD_UNAVAILABLE``.

Threshold binding: the Run does not persist the lock-up / LLCR / reserve terms it was executed with, so the
Working Copy terms are bound to the Last Run only when the canonical freshness is CURRENT (inputs identical to
the Run).  For a STALE Last Run the thresholds are declared unavailable instead of silently mixing unsaved
Working Copy inputs with a historical Run.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from app.model_quality import ADVISORY_LABEL, evaluate_model_quality
from app.model_quality.contracts import CheckStatus, QualityCheck, QualityReport
from app.model_quality.evidence import ProjectTerms, evidence_from_workspace, terms_from_project_inputs

# Owning workbook tabs (ids exist in app/templates/v2/workbook.html; parity is test-pinned).
TAB_LABELS = {
    "tab-overview": "Overview", "tab-scenarios": "Scenarios", "tab-project-setup": "Project Setup",
    "tab-inputs": "Inputs", "tab-revenue": "Revenue", "tab-capex": "CAPEX", "tab-opex": "OPEX",
    "tab-debt": "Debt", "tab-tax": "Tax", "tab-fs": "Financial Statements", "tab-returns": "Returns",
    "tab-trust": "Trust Pack", "tab-run-history": "Run History",
}

CONTRACTUAL_THRESHOLD_UNAVAILABLE = "CONTRACTUAL_THRESHOLD_UNAVAILABLE"

NOT_CLAIMS_LINE = ("Advisory screen of the committed Last Run. Not bank approval, not lender certification, "
                   "not SOC 2 certification and not FAST/IFC compliance certification.")


def _fmt_value(value: Optional[float], unit: str) -> str:
    if value is None:
        return "—"
    if unit == "kEUR":
        return f"{value:,.2f} kEUR" if abs(value) < 1e-3 and value != 0 else f"{value:,.1f} kEUR"
    if unit == "ratio":
        return f"{value:.3f}x"
    if unit == "fraction":
        return f"{value * 100:.2f}%"
    return f"{value:g}" + (f" {unit}" if unit and unit not in ("flag", "count") else "")


def _tab(target: str) -> Optional[dict[str, str]]:
    label = TAB_LABELS.get(str(target or ""))
    return {"tab_id": target, "label": label} if label else None


def _check_row(check: QualityCheck, *, register_paths: frozenset[str], kpi_keys: frozenset[str]) -> dict[str, Any]:
    explore: list[dict[str, str]] = []
    for path in check.related_assumption_ids:
        if path in register_paths:           # only a proven Working Copy register path is linkable
            explore.append({"value": f"f:{path}", "label": f"Assumption {path}"})
    for key in check.related_output_keys:
        if key in kpi_keys:                  # only an existing Last Run KPI is linkable
            explore.append({"value": f"k:{key}", "label": f"KPI {key}"})
    unlinked = [p for p in check.related_assumption_ids if p not in register_paths]
    return {
        "check_id": check.check_id, "title": check.title, "description": check.description,
        "category": check.category.value, "check_class": check.check_class.value,
        "severity": check.severity.value, "status": check.status.value, "blocking": check.blocking,
        "measured": _fmt_value(check.measured_value, check.measured_unit),
        "measured_unit": check.measured_unit,
        "threshold": _fmt_value(check.threshold_value, check.measured_unit),
        "threshold_authority": check.threshold_authority, "evidence_source": check.evidence_source,
        "reason_code": check.reason_code or "", "detail": check.detail,
        "nav": _tab(check.navigation_target), "explore": explore,
        "unlinked_assumptions": unlinked,
    }


def _score_block(report: QualityReport) -> dict[str, Any]:
    s = report.summary
    cov = None if s.coverage_weighted is None else round(s.coverage_weighted * 100, 1)
    if s.score_status == "PUBLISHED" and s.score is not None:
        score_display = f"{s.score:.1f} / 100"
        note = "Advisory score from the Q1 scorer"
        if s.blocked:
            note += f" (capped at {s.blocked_score_cap:.0f} while a blocking check fails)"
    else:
        score_display = None
        note = (f"Not scored — weighted evidence coverage {cov if cov is not None else '—'}% is below the "
                f"{s.min_coverage * 100:.0f}% minimum" if s.score_status == "UNAVAILABLE_INSUFFICIENT_EVIDENCE"
                else "Not scored — no committed Run")
    return {
        "score": s.score, "score_display": score_display, "score_note": note, "score_status": s.score_status,
        "coverage_weighted_pct": cov,
        "coverage_count_pct": None if s.coverage_count is None else round(s.coverage_count * 100, 1),
        "min_coverage_pct": round(s.min_coverage * 100),
        "readiness_label": s.readiness_label, "blocked": s.blocked,
        "counts": {"registered": s.registered, "applicable": s.applicable, "evaluated": s.evaluated,
                   "pass": s.passed, "warning": s.warnings, "fail": s.failed,
                   "unavailable": s.unavailable, "not_applicable": s.not_applicable},
    }


def _min_dscr_period(integrity_evidence: Optional[Mapping[str, Any]]) -> tuple[Optional[int], int]:
    """(period index of the lowest persisted base DSCR, number of tested debt periods) — selection only."""
    periods = ((integrity_evidence or {}).get("senior_debt") or {}).get("periods")
    if not isinstance(periods, list):
        return None, 0
    rows = [(p.get("reported_dscr"), p.get("period_index")) for p in periods
            if isinstance(p, Mapping) and isinstance(p.get("reported_dscr"), (int, float))
            and not isinstance(p.get("reported_dscr"), bool)]
    if not rows:
        return None, 0
    worst = min(rows, key=lambda r: r[0])
    return (worst[1] if isinstance(worst[1], int) else None), len(rows)


def _headroom(check: QualityCheck, *, higher_is_better: bool = True) -> Optional[str]:
    if check.measured_value is None or check.threshold_value is None:
        return None
    delta = (check.measured_value - check.threshold_value) if higher_is_better \
        else (check.threshold_value - check.measured_value)
    if check.measured_unit == "kEUR":
        return f"{delta:+,.1f} kEUR"
    return f"{delta:+.3f}x"


def _covenant_rows(report: QualityReport, *, run_state: str, terms_bound: bool,
                   integrity_evidence: Optional[Mapping[str, Any]], runtime_summary: Optional[Mapping[str, Any]],
                   terms: ProjectTerms) -> list[dict[str, Any]]:
    by_id = {c.check_id: c for c in report.checks}
    period_idx, tested = _min_dscr_period(integrity_evidence)
    freshness = {"CURRENT": "CURRENT — Working Copy matches the Run",
                 "STALE": "STALE — describes the prior Last Run, not unsaved Working Copy inputs",
                 "NOT_RUN": "NOT_RUN"}.get(run_state, run_state)
    dscr_period = (f"Minimum over {tested} tested debt periods; lowest in period #{period_idx}"
                   if tested and period_idx is not None else "Minimum over tested debt periods (period unavailable)")
    rows: list[dict[str, Any]] = []

    def unavailable_reason(check: QualityCheck, *, supplied: bool) -> str:
        if not supplied and not terms_bound and run_state != "CURRENT":
            return "RUN_THRESHOLD_NOT_BOUND — the Run does not persist its terms and the Working Copy has changed"
        return check.reason_code or CONTRACTUAL_THRESHOLD_UNAVAILABLE

    def add(check_id: str, ctype: str, *, observed_label: str, period: str, supplied: bool, auth_key: str,
            higher_is_better: bool = True) -> None:
        c = by_id[check_id]
        has_threshold = c.threshold_value is not None
        if has_threshold:
            authority = terms.authority(auth_key).replace("PROJECT_INPUT:", "Project input (not verified as a "
                                                                            "contractual term): ")
            authority = authority.replace("CONTRACTUAL_TERM:", "Supplied contractual term: ")
        else:
            authority = CONTRACTUAL_THRESHOLD_UNAVAILABLE
        rows.append({
            "check_id": c.check_id, "type": ctype, "status": c.status.value,
            "threshold": _fmt_value(c.threshold_value, c.measured_unit) if has_threshold else CONTRACTUAL_THRESHOLD_UNAVAILABLE,
            "threshold_authority": authority,
            "observed_label": observed_label, "observed": _fmt_value(c.measured_value, c.measured_unit),
            "unit": c.measured_unit, "testing_period": period,
            "headroom": _headroom(c, higher_is_better=higher_is_better) if has_threshold else None,
            "freshness": freshness, "reason": ("" if c.evaluated else unavailable_reason(c, supplied=has_threshold)),
            "detail": c.detail, "blocking": c.blocking,
        })

    add("QM-COV-001", "Minimum DSCR covenant", observed_label="Lowest persisted base DSCR", period=dscr_period,
        supplied=terms.min_dscr_covenant is not None, auth_key="min_dscr_covenant")
    add("QM-COV-002", "Distribution lock-up DSCR", observed_label="Lowest persisted base DSCR", period=dscr_period,
        supplied=terms.lockup_dscr is not None, auth_key="lockup_dscr")
    lockup_periods = (runtime_summary or {}).get("periods_in_lockup")
    if isinstance(lockup_periods, (int, float)) and not isinstance(lockup_periods, bool):
        rows[-1]["engine_observation"] = f"{int(lockup_periods)} period(s) in lock-up reported by the Run"
    add("QM-COV-003", "Minimum LLCR", observed_label="Minimum LLCR persisted by the Run",
        period="Life of loan (persisted minimum)", supplied=terms.min_llcr is not None, auth_key="min_llcr")
    add("QM-CASH-002", "Reserve account (DSRA) funding", observed_label="Initial cash DSRA funding",
        period="At financial close", supplied=terms.dsra_target_keur is not None, auth_key="dsra_target_keur")
    # No input anywhere in ProjectInputs models a default-DSCR event: say so instead of inventing a level.
    rows.append({
        "check_id": "", "type": "Default DSCR", "status": "UNAVAILABLE",
        "threshold": CONTRACTUAL_THRESHOLD_UNAVAILABLE, "threshold_authority": CONTRACTUAL_THRESHOLD_UNAVAILABLE,
        "observed_label": "Lowest persisted base DSCR", "observed": "—", "unit": "ratio",
        "testing_period": dscr_period, "headroom": None, "freshness": freshness,
        "reason": "NO_MODEL_AUTHORITY — ProjectInputs defines no default-DSCR term",
        "detail": "", "blocking": False,
    })
    return rows


def build_quality_insight(
    ws: Any, *, run_state: str, project_inputs: Any = None, active_scenario_id: Optional[str] = None,
    scenario_name: str = "", register_paths: Iterable[str] = (), kpi_keys: Iterable[str] = (),
    terms_override: Optional[ProjectTerms] = None,
) -> dict[str, Any]:
    """Compact, JSON-safe Model Quality + covenant view of the committed Last Run of ``ws``.

    ``project_inputs`` is the EFFECTIVE Working Copy ``ProjectInputs``; its thresholds are bound to the Run
    only when ``run_state == 'CURRENT'``.  ``terms_override`` lets a caller supply terms it can prove were in
    force (for example a contractual term) — it is used as given.
    """
    state = run_state if run_state in ("CURRENT", "STALE") else "NOT_RUN"
    base = {"label": ADVISORY_LABEL, "not_claims": NOT_CLAIMS_LINE, "run_state": state,
            "scenario_name": scenario_name, "available": False}
    has_run = bool(getattr(ws, "last_runtime_summary", None) or getattr(ws, "last_integrity_evidence", None)
                   or getattr(ws, "last_runtime_snapshot_id", None))
    if state == "NOT_RUN" or not has_run:
        base.update({"state": "NOT_RUN", "message": "No committed Run — Model Quality is evaluated only over a "
                                                   "committed Last Run. Nothing is estimated."})
        return base
    terms = ProjectTerms()
    terms_bound = False
    if terms_override is not None:
        terms, terms_bound = terms_override, True
    elif state == "CURRENT" and project_inputs is not None:
        terms, terms_bound = terms_from_project_inputs(project_inputs), True
    evidence = evidence_from_workspace(ws, freshness=state, terms=terms,
                                       active_scenario_id=active_scenario_id, scenario_known=True)
    report = evaluate_model_quality(evidence)
    paths, keys = frozenset(register_paths), frozenset(kpi_keys)
    by_id = {c.check_id: c for c in report.checks}

    def rows(ids: Iterable[str]) -> list[dict[str, Any]]:
        return [_check_row(by_id[i], register_paths=paths, kpi_keys=keys) for i in ids]

    blocking_ids = list(report.blocking_findings)
    issue_ids = [i for i in report.top_issues if i not in set(blocking_ids)]
    # blocking order follows materiality like top_issues
    blocking_ids.sort(key=lambda i: (-by_id[i].weight, i))
    gap_ids = list(report.evidence_gaps)
    pass_ids = sorted(c.check_id for c in report.checks if c.status is CheckStatus.PASS)
    na_ids = sorted(c.check_id for c in report.checks if c.status is CheckStatus.NOT_APPLICABLE)
    base.update({
        "available": True, "state": state,
        "identity": {
            "scenario_id": evidence.last_run_scenario_id, "scenario_name": scenario_name,
            "snapshot_id": evidence.snapshot_id, "composite_hash": evidence.composite_hash,
            "run_at": evidence.run_at, "engine_version": evidence.engine_version,
        },
        "context_note": ("CURRENT — evaluates the committed Last Run, which matches the Working Copy." if state == "CURRENT"
                         else "STALE — evaluates the PRIOR Last Run. Working Copy changes since that Run are not "
                              "evaluated and thresholds are not bound to it."),
        "score": _score_block(report),
        "groups": {
            "blocking": rows(blocking_ids), "issues": rows(issue_ids), "gaps": rows(gap_ids),
            "passed": rows(pass_ids), "not_applicable": rows(na_ids),
        },
        "covenants": _covenant_rows(report, run_state=state, terms_bound=terms_bound,
                                    integrity_evidence=evidence.integrity_evidence,
                                    runtime_summary=evidence.runtime_summary, terms=terms),
        "terms_bound": terms_bound,
    })
    return base


def build_quality_insight_safe(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Fail closed: a surface must never 500 or invent a verdict when the adapter cannot evaluate."""
    try:
        return build_quality_insight(*args, **kwargs)
    except Exception:  # noqa: BLE001 - presentation adapter must fail closed
        return {"label": ADVISORY_LABEL, "not_claims": NOT_CLAIMS_LINE, "available": False, "state": "UNAVAILABLE",
                "run_state": str(kwargs.get("run_state") or ""), "scenario_name": str(kwargs.get("scenario_name") or ""),
                "message": "Model Quality could not be evaluated from the persisted evidence."}


__all__ = ["CONTRACTUAL_THRESHOLD_UNAVAILABLE", "NOT_CLAIMS_LINE", "TAB_LABELS", "build_quality_insight",
           "build_quality_insight_safe"]
