"""app.model_quality — MODEL QUALITY / LENDER READINESS ADVISORY (read-only).

An independent, typed evaluation layer over the committed canonical Last Run.  It:

* reads ONLY persisted evidence (runtime summary, run-bound financing evidence, Run Integrity
  evidence, run identity) and optional typed project terms;
* reuses the existing Run Integrity report for every identity it already proves (no duplicated
  arithmetic) and adds new checks only over evidence Run Integrity does not cover;
* never runs the financial engine, never recomputes sizing, statements or returns, never writes;
* reports evidence availability separately from actual failure, and a coverage-aware advisory
  score that is UNAVAILABLE (never an invented zero) when evidence is insufficient.

It is an advisory screen.  It is NOT bank approval, certification or verification, and a
convergent solver result is never treated as lender acceptance.
"""
from app.model_quality.contracts import (  # noqa: F401
    ADVISORY_LABEL,
    CheckClass,
    CheckStatus,
    QualityCheck,
    QualityReport,
    ScoreSummary,
    Severity,
)
from app.model_quality.projection import (  # noqa: F401
    evaluate_model_quality,
    evaluate_workspace,
    project_quality_report,
)
