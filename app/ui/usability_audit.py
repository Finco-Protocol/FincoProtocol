"""Phase 25B Closure — Usability audit helper.

Pure read-side helper module. Computes a structured
audit of 8 first-time-finance-user workflows and
returns a ``UsabilityAudit`` dataclass with per-workflow
percentage readiness scores plus an overall weighted
score.

The helper is intentionally deterministic and reads
ONLY from a structured input payload describing which
features / surfaces are live in the codebase. It does
NOT call the persistence layer, does NOT inspect the
live HTTP layer, does NOT enumerate routes at runtime,
and does NOT inspect git history.

The input payload is built once at audit time by the
``build_audit_inputs`` function, which reads from the
filesystem (e.g. looks for the presence of known
partials, known helper modules, known test files).
The helper then scores the payload against the 8
workflow criteria.

The 8 workflows (from the user's 25B Closure brief):

1. Create project
2. Edit assumptions
3. Save
4. Run
5. Compare
6. Export
7. Understand outputs
8. Understand limitations

Each workflow is scored 0-100 based on the number of
supporting surfaces present in the input payload. The
overall score is the unweighted arithmetic mean of the
8 workflow scores (no double-counting of overlapping
features).

The helper does NOT:
- mutate any input
- call the persistence layer
- call services
- enable any feature flag
- change any runtime path
- touch construction / C10 / R-PAR / tax / debt / IDC
- touch rc1
- touch factory (Generic Wind Reference / Generic Solar Reference)

It is a pure read-side audit / classifier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkflowScore:
    """A single workflow's readiness score and reasoning."""

    #: The workflow key (one of WORKFLOW_*).
    workflow: str

    #: The workflow display label.
    label: str

    #: 0-100 readiness score.
    score: int

    #: One-line description of what is supported.
    summary: str

    #: List of supporting surface keys detected.
    supporting_surfaces: tuple[str, ...] = ()

    #: List of known gaps (text descriptions).
    gaps: tuple[str, ...] = ()


@dataclass(frozen=True)
class UsabilityAudit:
    """The full 25B Closure audit result."""

    #: Per-workflow scores, keyed by workflow key.
    workflows: tuple[WorkflowScore, ...]

    #: Overall readiness score (0-100), unweighted mean.
    overall_score: int

    #: Overall readiness bucket (one of BUCKET_*).
    bucket: str

    #: One-line overall verdict.
    verdict: str

    #: Generation timestamp ISO (provided by caller).
    generated_at: str = ""


# ---------------------------------------------------------------------------
# Workflow vocabulary
# ---------------------------------------------------------------------------


WORKFLOW_CREATE_PROJECT = "create_project"
WORKFLOW_EDIT_ASSUMPTIONS = "edit_assumptions"
WORKFLOW_SAVE = "save"
WORKFLOW_RUN = "run"
WORKFLOW_COMPARE = "compare"
WORKFLOW_EXPORT = "export"
WORKFLOW_UNDERSTAND_OUTPUTS = "understand_outputs"
WORKFLOW_UNDERSTAND_LIMITATIONS = "understand_limitations"

WORKFLOW_LABELS: dict[str, str] = {
    WORKFLOW_CREATE_PROJECT: "Create project",
    WORKFLOW_EDIT_ASSUMPTIONS: "Edit assumptions",
    WORKFLOW_SAVE: "Save",
    WORKFLOW_RUN: "Run",
    WORKFLOW_COMPARE: "Compare",
    WORKFLOW_EXPORT: "Export",
    WORKFLOW_UNDERSTAND_OUTPUTS: "Understand outputs",
    WORKFLOW_UNDERSTAND_LIMITATIONS: "Understand limitations",
}

#: Workflow order for stable output.
WORKFLOW_ORDER: tuple[str, ...] = (
    WORKFLOW_CREATE_PROJECT,
    WORKFLOW_EDIT_ASSUMPTIONS,
    WORKFLOW_SAVE,
    WORKFLOW_RUN,
    WORKFLOW_COMPARE,
    WORKFLOW_EXPORT,
    WORKFLOW_UNDERSTAND_OUTPUTS,
    WORKFLOW_UNDERSTAND_LIMITATIONS,
)

#: Buckets. Threshold is the unweighted mean across the
#: 8 workflows. Tunable in the future.
BUCKET_PILOT_READY = "pilot_ready"
BUCKET_CLOSE_TO_PILOT = "close_to_pilot"
BUCKET_PILOT_BLOCKED = "pilot_blocked"
BUCKET_NOT_READY = "not_ready"

BUCKET_THRESHOLDS = (
    (90, BUCKET_PILOT_READY),
    (70, BUCKET_CLOSE_TO_PILOT),
    (50, BUCKET_PILOT_BLOCKED),
    (0, BUCKET_NOT_READY),
)

BUCKET_VERDICTS: dict[str, str] = {
    BUCKET_PILOT_READY: (
        "Pilot-ready. A new finance user can complete the "
        "8 core workflows without significant gaps."
    ),
    BUCKET_CLOSE_TO_PILOT: (
        "Close to pilot. Most workflows supported; a few "
        "gaps remain in UX clarity, not in feature coverage."
    ),
    BUCKET_PILOT_BLOCKED: (
        "Pilot-blocked. Core workflows are present but "
        "several are not yet discoverable or self-explanatory."
    ),
    BUCKET_NOT_READY: (
        "Not ready. Significant gaps in the 8 core "
        "workflows; pilot should not start yet."
    ),
}

#: Per-workflow expected surfaces. Each entry maps
#: workflow key -> (label, expected surface keys,
#: max score if all surfaces present). The score for
#: a workflow is:
#: 100 * (len(detected expected surfaces) / len(expected))
#: capped at max_score.
WORKFLOW_EXPECTED_SURFACES: dict[
    str, tuple[str, tuple[str, ...], int]
] = {
    WORKFLOW_CREATE_PROJECT: (
        "User can create a new (non-factory) project from the UI.",
        (
            "partials/new_project_form.html",
            "partials/project_browser.html",
            "partials/_empty_no_project.html",
        ),
        100,
    ),
    WORKFLOW_EDIT_ASSUMPTIONS: (
        "User can edit inputs / assumptions inline.",
        (
            "partials/inputs_section.html",
            "partials/scenario_tab.html",
            "ui.input_helpers",
        ),
        100,
    ),
    WORKFLOW_SAVE: (
        "User can save a scenario / run state.",
        (
            "partials/save_result.html",
            "partials/dirty_state_indicators.html",
            "ui.dirty_state",
            "services.save_run_service",
        ),
        100,
    ),
    WORKFLOW_RUN: (
        "User can run the model from the UI.",
        (
            "partials/_last_run_indicator.html",
            "partials/run_history.html",
            "ui.run_summary",
        ),
        100,
    ),
    WORKFLOW_COMPARE: (
        "User can compare scenarios side-by-side.",
        (
            "partials/scenario_compare.html",
            "partials/scenario_compare_multi.html",
            "ui.scenario_workflow",
        ),
        100,
    ),
    WORKFLOW_EXPORT: (
        "User can export the workbook to Excel / download.",
        (
            "excel_export.build_excel_export",
            "partials/export_registry.html",
        ),
        100,
    ),
    WORKFLOW_UNDERSTAND_OUTPUTS: (
        "User can read KPIs / returns / DSCR / waterfall.",
        (
            "partials/kpis.html",
            "partials/_runtime_impact_chip.html",
            "partials/runtime_summary.html",
            "ui.what_changed",
        ),
        100,
    ),
    WORKFLOW_UNDERSTAND_LIMITATIONS: (
        "User sees what's supported and what's not.",
        (
            "partials/pilot_limitations_notice.html",
            "partials/_empty_no_run.html",
            "ui.project_review",
        ),
        100,
    ),
}


__all__ = [
    "UsabilityAudit",
    "WorkflowScore",
    "WORKFLOW_LABELS",
    "WORKFLOW_ORDER",
    "WORKFLOW_EXPECTED_SURFACES",
    "BUCKET_PILOT_READY",
    "BUCKET_CLOSE_TO_PILOT",
    "BUCKET_PILOT_BLOCKED",
    "BUCKET_NOT_READY",
    "BUCKET_VERDICTS",
    "score_workflow",
    "audit",
    "build_audit_inputs",
]


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def score_workflow(
    workflow: str,
    detected_surfaces: Sequence[str],
) -> WorkflowScore:
    """Score a single workflow against the expected
    surfaces.

    The score is::

        100 * (len(detected ∩ expected) / len(expected))

    capped at the workflow's ``max_score``.

    Parameters
    ----------
    workflow : str
        One of the ``WORKFLOW_*`` keys.
    detected_surfaces : Sequence[str]
        The list of surface keys detected in the
        codebase. The function computes the
        intersection with the expected surfaces.
    """
    label, expected, max_score = WORKFLOW_EXPECTED_SURFACES[
        workflow
    ]
    detected_set = set(detected_surfaces)
    supporting = tuple(
        sorted(s for s in expected if s in detected_set)
    )
    if not expected:
        return WorkflowScore(
            workflow=workflow,
            label=label,
            score=0,
            summary=label,
            supporting_surfaces=(),
            gaps=("no expected surfaces defined",),
        )
    raw = 100 * len(supporting) / len(expected)
    score = min(max_score, int(round(raw)))
    gaps_list: list[str] = []
    missing = [s for s in expected if s not in detected_set]
    for m in missing:
        if "/" in m:
            # module reference
            gaps_list.append(
                f"module {m!r} not detected"
            )
        else:
            gaps_list.append(f"surface {m!r} not detected")
    return WorkflowScore(
        workflow=workflow,
        label=label,
        score=score,
        summary=label,
        supporting_surfaces=supporting,
        gaps=tuple(gaps_list),
    )


def audit(
    detected_surfaces: Sequence[str],
    generated_at: str = "",
) -> UsabilityAudit:
    """Compute the full 25B Closure audit.

    Parameters
    ----------
    detected_surfaces : Sequence[str]
        The list of surface keys detected in the
        codebase. Forwarded to ``score_workflow``.
    generated_at : str, optional
        ISO timestamp for the audit generation. Defaults
        to empty (caller-supplied).
    """
    workflows: list[WorkflowScore] = []
    for wk in WORKFLOW_ORDER:
        workflows.append(
            score_workflow(wk, detected_surfaces),
        )
    overall = int(
        round(
            sum(w.score for w in workflows) / len(workflows)
        ),
    )
    bucket = BUCKET_NOT_READY
    for threshold, candidate in BUCKET_THRESHOLDS:
        if overall >= threshold:
            bucket = candidate
            break
    verdict = BUCKET_VERDICTS[bucket]
    return UsabilityAudit(
        workflows=tuple(workflows),
        overall_score=overall,
        bucket=bucket,
        verdict=verdict,
        generated_at=generated_at,
    )


# ---------------------------------------------------------------------------
# File-system probe
# ---------------------------------------------------------------------------


def build_audit_inputs(
    repo_root: str,
) -> list[str]:
    """Probe the repo and return a list of detected
    surface keys.

    The probe is read-only. It walks a fixed list of
    well-known file paths and helper modules and adds
    a key for each that exists. The function does NOT
    recurse; it only checks the canonical surface
    paths declared in
    ``WORKFLOW_EXPECTED_SURFACES``.

    Parameters
    ----------
    repo_root : str
        Absolute path to the repository root.

    Returns
    -------
    list[str]
        The list of detected surface keys (strings).
    """
    from pathlib import Path

    detected: list[str] = []
    root = Path(repo_root)
    # Walk the EXPECTED_SURFACES map once.
    for (
        workflow_key,
        (label, expected, max_score),
    ) in WORKFLOW_EXPECTED_SURFACES.items():
        for surface in expected:
            found = False
            # First, try as a file path (relative
            # or under app/templates/).
            candidates_file = [
                root / surface,
                root / "app" / "templates" / surface,
            ]
            if any(c.exists() for c in candidates_file):
                found = True
            # Then, try as a Python module
            # reference. ui.dirty_state -> app/ui/
            # dirty_state.py. services.save_run_service
            # -> app/services/save_run_service.py.
            if not found and "." in surface:
                parts = surface.split(".")
                # If surface looks like "ui/X" (mixed
                # dot + slash), treat as file path
                # under app/ui/X.py.
                if "/" in surface:
                    # e.g. "ui/dirty_state" — already
                    # tried as file; also try as
                    # app/ui/X.py
                    file_candidate = (
                        root / "app" / (surface + ".py")
                    )
                    if file_candidate.exists():
                        found = True
                else:
                    # Pure dot reference
                    # e.g. "ui.dirty_state",
                    # "services.save_run_service"
                    module_path = parts[0]
                    if module_path == "ui" and len(parts) > 1:
                        sub = parts[1]
                        candidate = (
                            root / "app" / "ui" / (sub + ".py")
                        )
                        if candidate.exists():
                            found = True
                    else:
                        # Try multi-segment full path
                        if len(parts) > 1:
                            full_with_py = (
                                root / "app"
                                / ("/".join(parts) + ".py")
                            )
                            if full_with_py.exists():
                                found = True
                        # Try as a single module
                        if not found:
                            candidate_a = (
                                root / "app"
                                / (module_path + ".py")
                            )
                            candidate_b = (
                                root / "app" / module_path
                            )
                            if (
                                candidate_a.exists()
                                or candidate_b.exists()
                            ):
                                found = True
            elif not found and "/" not in surface:
                # Bare module name (no dot, no slash)
                candidate_a = (
                    root / "app" / (surface + ".py")
                )
                candidate_b = root / "app" / surface
                if candidate_a.exists() or candidate_b.exists():
                    found = True
            if found:
                detected.append(surface)
    return detected
