"""Public, read-only API for the Model Quality evaluator.

``evaluate_model_quality`` is the single entry point for future UI integration (Q2): it takes
persisted evidence and returns a typed report.  ``project_quality_report`` returns a plain,
JSON-safe dictionary with a short summary for compact surfaces.  No HTTP route exists in Q1.
"""
from __future__ import annotations

from typing import Any, Optional

from app.model_quality.contracts import QualityReport
from app.model_quality.evidence import ProjectTerms, QualityEvidence, evidence_from_workspace
from app.model_quality.registry import run_registry
from app.model_quality.scoring import build_report


def evaluate_model_quality(evidence: QualityEvidence) -> QualityReport:
    """Evaluate the registry over persisted evidence.  Pure: no engine, no I/O, no mutation."""
    checks = run_registry(evidence)
    return build_report(checks, freshness=evidence.freshness, identity=evidence.run_identity,
                        has_run=evidence.has_last_run)


def evaluate_workspace(ws: Any, *, current_composite_hash: Optional[str], terms: Optional[ProjectTerms] = None,
                       active_scenario_id: Optional[str] = None, scenario_known: bool = False) -> QualityReport:
    """Evaluate a persisted workspace record.

    Freshness comes from the canonical ``resolve_runtime_freshness`` authority; the caller supplies
    the current composite hash exactly as the workbook surfaces do.
    """
    from app.workbook.runtime_authority import resolve_runtime_freshness

    state = resolve_runtime_freshness(ws, current_composite_hash=current_composite_hash).state.value
    evidence = evidence_from_workspace(ws, freshness=state, terms=terms,
                                       active_scenario_id=active_scenario_id, scenario_known=scenario_known)
    return evaluate_model_quality(evidence)


def project_quality_report(report: QualityReport, *, top_n: int = 5) -> dict[str, Any]:
    """Compact JSON-safe projection for a panel: headline, counts, top issues and evidence gaps."""
    summary = report.summary
    by_id = {c.check_id: c for c in report.checks}

    def row(check_id: str) -> dict[str, Any]:
        c = by_id[check_id]
        return {"check_id": c.check_id, "title": c.title, "status": c.status.value, "severity": c.severity.value,
                "reason_code": c.reason_code, "navigation_target": c.navigation_target}

    return {
        "label": report.label, "not_claims": list(report.not_claims), "freshness": report.freshness,
        "score_is_current": report.score_is_current, "blocked": summary.blocked,
        "readiness_label": summary.readiness_label, "score": summary.score, "score_status": summary.score_status,
        "coverage_weighted": summary.coverage_weighted, "coverage_count": summary.coverage_count,
        "counts": {"registered": summary.registered, "applicable": summary.applicable, "evaluated": summary.evaluated,
                   "pass": summary.passed, "warning": summary.warnings, "fail": summary.failed,
                   "not_applicable": summary.not_applicable, "unavailable": summary.unavailable},
        "blocking": [row(i) for i in report.blocking_findings],
        "top_issues": [row(i) for i in report.top_issues[:top_n]],
        "evidence_gaps": [row(i) for i in report.evidence_gaps[:top_n]],
    }
