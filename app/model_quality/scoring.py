"""Coverage-aware advisory scoring (transparent, deterministic).

Definitions (all tested):

* applicable   = registered checks whose status is not NOT_APPLICABLE
* evaluated    = applicable checks with status PASS, WARNING or FAIL
* eligible denominator of the score = severity weights of the EVALUATED checks only
* credit       = PASS 1.0, WARNING 0.5, FAIL 0.0  (UNAVAILABLE is not scored; it lowers coverage)
* weights      = CRITICAL 8, HIGH 4, MEDIUM 2, LOW 1
* coverage     = evaluated / applicable, both by count and severity-weighted
* a numeric score is PUBLISHED only when weighted coverage >= MIN_COVERAGE; otherwise it is
  UNAVAILABLE (``None``) — never zero, never normalised over the evaluated subset alone
* blocked      = any FAIL of a MATHEMATICAL_INTEGRITY check or of a CRITICAL check.  Blocking is
  independent of the score: it is reported even when the score is unavailable, and a published
  score is capped at BLOCKED_SCORE_CAP so many low-risk passes cannot offset it.
* sorting      = top issues by (severity weight desc, FAIL before WARNING, check id);
  evidence gaps by (severity weight desc, check id).
"""
from __future__ import annotations

from app.model_quality.contracts import (
    ADVISORY_LABEL,
    NOT_CLAIMS,
    SCHEMA_VERSION,
    CheckClass,
    CheckStatus,
    QualityCheck,
    QualityReport,
    ScoreSummary,
    Severity,
)

MIN_COVERAGE = 0.80
BLOCKED_SCORE_CAP = 50.0
CREDIT = {CheckStatus.PASS: 1.0, CheckStatus.WARNING: 0.5, CheckStatus.FAIL: 0.0}


def score_checks(checks: tuple[QualityCheck, ...], *, has_run: bool = True) -> ScoreSummary:
    counts = {s: sum(1 for c in checks if c.status is s) for s in CheckStatus}
    applicable = [c for c in checks if c.status is not CheckStatus.NOT_APPLICABLE]
    evaluated = [c for c in applicable if c.evaluated]
    w_app = sum(c.weight for c in applicable)
    w_eval = sum(c.weight for c in evaluated)
    cov_count = (len(evaluated) / len(applicable)) if applicable else None
    cov_weighted = (w_eval / w_app) if w_app else None
    blocked = any(c.blocking for c in checks)

    score = None
    if not has_run:
        status = "UNAVAILABLE_NO_RUN"
    elif cov_weighted is None or cov_weighted < MIN_COVERAGE or not evaluated:
        status = "UNAVAILABLE_INSUFFICIENT_EVIDENCE"
    else:
        raw = 100.0 * sum(c.weight * CREDIT[c.status] for c in evaluated) / w_eval
        score = round(min(raw, BLOCKED_SCORE_CAP) if blocked else raw, 2)
        status = "PUBLISHED"

    breakdown = {
        sev.value: {s.value: sum(1 for c in checks if c.severity is sev and c.status is s) for s in CheckStatus}
        for sev in Severity
    }
    if blocked:
        label = "BLOCKED — a mathematical-integrity or critical check failed"
    elif status != "PUBLISHED":
        label = "NOT SCORED — evidence coverage is insufficient"
    elif counts[CheckStatus.FAIL]:
        label = "FAILING CHECKS PRESENT"
    elif counts[CheckStatus.WARNING]:
        label = "ADVISORY WARNINGS PRESENT"
    else:
        label = "NO FINDINGS IN EVALUATED CHECKS (advisory only)"
    return ScoreSummary(
        registered=len(checks), applicable=len(applicable), evaluated=len(evaluated),
        passed=counts[CheckStatus.PASS], warnings=counts[CheckStatus.WARNING], failed=counts[CheckStatus.FAIL],
        not_applicable=counts[CheckStatus.NOT_APPLICABLE], unavailable=counts[CheckStatus.UNAVAILABLE],
        coverage_count=None if cov_count is None else round(cov_count, 6),
        coverage_weighted=None if cov_weighted is None else round(cov_weighted, 6),
        min_coverage=MIN_COVERAGE, score=score, score_status=status, blocked=blocked,
        blocked_score_cap=BLOCKED_SCORE_CAP, severity_breakdown=breakdown, readiness_label=label,
    )


def rank_issues(checks: tuple[QualityCheck, ...]) -> tuple[str, ...]:
    issues = [c for c in checks if c.status in (CheckStatus.FAIL, CheckStatus.WARNING)]
    issues.sort(key=lambda c: (-c.weight, 0 if c.status is CheckStatus.FAIL else 1, c.check_id))
    return tuple(c.check_id for c in issues)


def rank_gaps(checks: tuple[QualityCheck, ...]) -> tuple[str, ...]:
    gaps = [c for c in checks if c.status is CheckStatus.UNAVAILABLE]
    gaps.sort(key=lambda c: (-c.weight, c.check_id))
    return tuple(c.check_id for c in gaps)


def build_report(checks: tuple[QualityCheck, ...], *, freshness, identity, has_run: bool) -> QualityReport:
    summary = score_checks(checks, has_run=has_run)
    blocking = tuple(sorted(c.check_id for c in checks if c.blocking))
    return QualityReport(
        label=ADVISORY_LABEL, not_claims=NOT_CLAIMS, schema_version=SCHEMA_VERSION,
        freshness=freshness, score_is_current=(freshness == "CURRENT"), run_identity=dict(identity),
        checks=checks, summary=summary, top_issues=rank_issues(checks), evidence_gaps=rank_gaps(checks),
        blocking_findings=blocking,
    )
