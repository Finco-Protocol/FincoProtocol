"""Phase 25C Closure — Third-Party Test Readiness
Gate.

Pure read-side audit helper module. Computes a
third-party test readiness score for the Generic
Solar / Wind exploratory pilot.

The helper does NOT:
- mutate any input
- call the persistence layer
- call services
- enable any feature flag
- change any runtime path
- touch construction / C10 / R-PAR / tax / debt / IDC
- touch rc1
- touch factory (Generic Wind Reference / Generic Solar Reference)
- invent fake outputs, fake run IDs, fake
  validation claims
- run the model

The 10 workflows audited are:
1. create_project — User creates a project
2. prefill_defaults — User accepts generic defaults
3. save — User saves a scenario
4. run — User runs the model
5. edit — User edits scenario inputs
6. rerun — User re-runs a scenario
7. compare — User opens the compare view
8. export — User exports the workbook
9. understand_limitations — User understands what
   the exploratory pilot does NOT do
10. report_feedback — User reports feedback via
    the 25C-3 capture panel

The audit combines:
- helper presence (does the workflow have a
  Phase 25X UI helper?)
- partial existence (does the partial exist?)
- helper tests passing (do the helper tests
  pass?)
- factory safety tests passing (do the factory
  safety tests pass?)

The output is a JSON-serializable dataclass
``ThirdPartyTestReadiness`` with:
- per-workflow score (0-100)
- overall score (0-100)
- readiness bucket (pilot_ready, close_to_pilot,
  pilot_blocked, not_ready)
- Go / No-Go recommendation
- exact pilot test checklist (10 items)
- remaining blockers (list of strings)
- suggested tester instructions (list of strings)
- phase 25C link (the 4 phases: 25C-1, 25C-2,
  25C-3, 25C Closure)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence


# ---------------------------------------------------------------------------
# Workflow vocabulary
# ---------------------------------------------------------------------------


WORKFLOW_CREATE_PROJECT = "create_project"
WORKFLOW_PREFILL_DEFAULTS = "prefill_defaults"
WORKFLOW_SAVE = "save"
WORKFLOW_RUN = "run"
WORKFLOW_EDIT = "edit"
WORKFLOW_RERUN = "rerun"
WORKFLOW_COMPARE = "compare"
WORKFLOW_EXPORT = "export"
WORKFLOW_UNDERSTAND_LIMITATIONS = "understand_limitations"
WORKFLOW_REPORT_FEEDBACK = "report_feedback"

ALL_WORKFLOWS: tuple[str, ...] = (
    WORKFLOW_CREATE_PROJECT,
    WORKFLOW_PREFILL_DEFAULTS,
    WORKFLOW_SAVE,
    WORKFLOW_RUN,
    WORKFLOW_EDIT,
    WORKFLOW_RERUN,
    WORKFLOW_COMPARE,
    WORKFLOW_EXPORT,
    WORKFLOW_UNDERSTAND_LIMITATIONS,
    WORKFLOW_REPORT_FEEDBACK,
)

# ---------------------------------------------------------------------------
# Workflow label / description
# ---------------------------------------------------------------------------


WORKFLOW_LABELS: dict[str, str] = {
    WORKFLOW_CREATE_PROJECT: "Create project",
    WORKFLOW_PREFILL_DEFAULTS: "Prefill defaults",
    WORKFLOW_SAVE: "Save scenario",
    WORKFLOW_RUN: "Run model",
    WORKFLOW_EDIT: "Edit inputs",
    WORKFLOW_RERUN: "Re-run scenario",
    WORKFLOW_COMPARE: "Compare scenarios",
    WORKFLOW_EXPORT: "Export workbook",
    WORKFLOW_UNDERSTAND_LIMITATIONS: (
        "Understand exploratory limitations"
    ),
    WORKFLOW_REPORT_FEEDBACK: "Report feedback",
}

WORKFLOW_DESCRIPTIONS: dict[str, str] = {
    WORKFLOW_CREATE_PROJECT: (
        "User can create a new project using the "
        "Generic Solar / Generic Wind template."
    ),
    WORKFLOW_PREFILL_DEFAULTS: (
        "User can accept the generic defaults that "
        "the form pre-fills."
    ),
    WORKFLOW_SAVE: (
        "User can save a Base scenario."
    ),
    WORKFLOW_RUN: (
        "User can run the model and see a run "
        "summary."
    ),
    WORKFLOW_EDIT: (
        "User can edit scenario inputs (tariff, "
        "OPEX, CAPEX)."
    ),
    WORKFLOW_RERUN: (
        "User can re-run a scenario after edits."
    ),
    WORKFLOW_COMPARE: (
        "User can open the compare view and see "
        "Base vs Downside side by side."
    ),
    WORKFLOW_EXPORT: (
        "User can export the workbook to Excel."
    ),
    WORKFLOW_UNDERSTAND_LIMITATIONS: (
        "User can read the exploratory disclaimer "
        "and understand what the pilot does NOT do "
        "(no parity, no lender, no audit, no bank)."
    ),
    WORKFLOW_REPORT_FEEDBACK: (
        "User can open the feedback panel and "
        "report an issue or feedback via the "
        "6-field template."
    ),
}

# ---------------------------------------------------------------------------
# Phase 25C link
# ---------------------------------------------------------------------------


PHASE_25C_LINK: dict[str, str] = {
    WORKFLOW_CREATE_PROJECT: "25C-1 (pilot script, step 1)",
    WORKFLOW_PREFILL_DEFAULTS: (
        "25C-1 (pilot script, step 2)"
    ),
    WORKFLOW_SAVE: "25C-1 (pilot script, step 3)",
    WORKFLOW_RUN: "25C-1 (pilot script, step 4)",
    WORKFLOW_EDIT: "25C-1 (pilot script, step 6)",
    WORKFLOW_RERUN: "25C-1 (pilot script, step 7)",
    WORKFLOW_COMPARE: "25C-1 (pilot script, step 8)",
    WORKFLOW_EXPORT: "25C-1 (pilot script, step 9)",
    WORKFLOW_UNDERSTAND_LIMITATIONS: (
        "25C-1 (exploratory disclaimer) + 25C-2 "
        "(export_before_run warning)"
    ),
    WORKFLOW_REPORT_FEEDBACK: "25C-3 (feedback panel)",
}

# ---------------------------------------------------------------------------
# Readiness buckets
# ---------------------------------------------------------------------------


BUCKET_PILOT_READY = "pilot_ready"
BUCKET_CLOSE_TO_PILOT = "close_to_pilot"
BUCKET_PILOT_BLOCKED = "pilot_blocked"
BUCKET_NOT_READY = "not_ready"

ALL_BUCKETS: tuple[str, ...] = (
    BUCKET_PILOT_READY,
    BUCKET_CLOSE_TO_PILOT,
    BUCKET_PILOT_BLOCKED,
    BUCKET_NOT_READY,
)

#: Per the user brief, pilot_ready requires >= 90
#: overall score, close_to_pilot >= 70, pilot_blocked
#: >= 50, otherwise not_ready.
BUCKET_THRESHOLDS: dict[str, int] = {
    BUCKET_PILOT_READY: 90,
    BUCKET_CLOSE_TO_PILOT: 70,
    BUCKET_PILOT_BLOCKED: 50,
}


# ---------------------------------------------------------------------------
# Workflow score
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkflowScore:
    """A single workflow's readiness score."""

    workflow: str
    label: str
    description: str
    phase_link: str
    helper_present: bool
    partial_present: bool
    helper_tests_pass: bool
    factory_safety_tests_pass: bool
    score: int

    def is_ready(self) -> bool:
        return self.score >= 90


# ---------------------------------------------------------------------------
# Workflow entry — input shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkflowEntry:
    """An input describing the readiness of a single
    workflow."""

    workflow: str
    helper_present: bool
    partial_present: bool
    helper_tests_pass: bool
    factory_safety_tests_pass: bool


# ---------------------------------------------------------------------------
# Test readiness — output shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TestChecklistItem:
    """A single item in the pilot test checklist."""

    workflow: str
    label: str
    step: str
    expected_outcome: str


@dataclass(frozen=True)
class ThirdPartyTestReadiness:
    """The full third-party test readiness report."""

    per_workflow: tuple[WorkflowScore, ...]
    overall_score: int
    bucket: str
    is_go: bool
    go_no_go_reason: str
    pilot_test_checklist: tuple[TestChecklistItem, ...]
    remaining_blockers: tuple[str, ...]
    suggested_tester_instructions: tuple[str, ...]
    phase_25c_summary: tuple[str, ...]


__all__ = [
    "WorkflowEntry",
    "WorkflowScore",
    "TestChecklistItem",
    "ThirdPartyTestReadiness",
    "ALL_WORKFLOWS",
    "ALL_BUCKETS",
    "WORKFLOW_LABELS",
    "WORKFLOW_DESCRIPTIONS",
    "PHASE_25C_LINK",
    "BUCKET_THRESHOLDS",
    "BUCKET_PILOT_READY",
    "BUCKET_CLOSE_TO_PILOT",
    "BUCKET_PILOT_BLOCKED",
    "BUCKET_NOT_READY",
    "build_third_party_test_readiness",
    "is_supported_workflow",
    "is_supported_bucket",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_supported_workflow(workflow: str) -> bool:
    """Return True if the workflow is one of the 10
    audited workflows."""
    return workflow in ALL_WORKFLOWS


def is_supported_bucket(bucket: str) -> bool:
    """Return True if the bucket is a valid readiness
    bucket."""
    return bucket in ALL_BUCKETS


# ---------------------------------------------------------------------------
# Pilot test checklist
# ---------------------------------------------------------------------------


PILOT_TEST_CHECKLIST: tuple[tuple[str, str, str], ...] = (
    (
        WORKFLOW_CREATE_PROJECT,
        "Create a new project with template = "
        "'Generic Solar'.",
        "Project is listed in the project list and "
        "opens cleanly.",
    ),
    (
        WORKFLOW_PREFILL_DEFAULTS,
        "Open the new project; verify the form "
        "pre-fills generic defaults.",
        "All inputs have a value; no empty / 0 / NaN.",
    ),
    (
        WORKFLOW_SAVE,
        "Save the Base scenario.",
        "Scenario appears as 'Base' in the scenario "
        "list.",
    ),
    (
        WORKFLOW_RUN,
        "Click Run on the Base scenario.",
        "Run completes in a few seconds; the run "
        "summary shows IRR / DSCR / NPV / payback "
        "values.",
    ),
    (
        WORKFLOW_EDIT,
        "Duplicate Base as Downside; change the "
        "tariff, OPEX, and CAPEX values.",
        "Override is shown as a highlighted cell; "
        "the scenario is dirty until saved.",
    ),
    (
        WORKFLOW_RERUN,
        "Click Run on the Downside scenario.",
        "Run completes; the run summary shows the "
        "new values.",
    ),
    (
        WORKFLOW_COMPARE,
        "Open the compare view with Base vs "
        "Downside.",
        "Side-by-side compare with IRR / DSCR / "
        "NPV / payback aligned for comparison.",
    ),
    (
        WORKFLOW_EXPORT,
        "Click Export.",
        "Excel workbook downloads; includes the "
        "scenario inputs, run outputs, and the "
        "exploratory banner.",
    ),
    (
        WORKFLOW_UNDERSTAND_LIMITATIONS,
        "Read the exploratory disclaimer at the "
        "top of the pilot panel and the export "
        "warning before exporting.",
        "Disclaimer mentions: exploratory, not "
        "reference-validated, not lender-ready, "
        "not audit-ready, not bank-approved.",
    ),
    (
        WORKFLOW_REPORT_FEEDBACK,
        "Open the feedback panel; copy the 6-field "
        "template; paste it into email / chat.",
        "Panel shows 6 fields; short template is "
        "3 lines; disclaimer warns against secrets "
        "/ PII.",
    ),
)


# ---------------------------------------------------------------------------
# Tester instructions
# ---------------------------------------------------------------------------


TESTER_INSTRUCTIONS: tuple[str, ...] = (
    "1. Start from a clean state: create a new "
    "project using the Generic Solar template.",
    "2. Accept the generic defaults that the form "
    "pre-fills. Do NOT change any input until step "
    "5.",
    "3. Save the Base scenario. Verify the scenario "
    "list shows 'Base'.",
    "4. Click Run on the Base scenario. Wait for "
    "the run to complete. Note the IRR / DSCR / "
    "NPV / payback values.",
    "5. Duplicate Base as Downside. Change one or "
    "more of: tariff, OPEX, CAPEX.",
    "6. Click Run on the Downside scenario. Wait "
    "for the run to complete.",
    "7. Open the compare view. Verify Base and "
    "Downside are aligned for comparison.",
    "8. Click Export. Verify the Excel workbook "
    "downloads and includes the exploratory "
    "banner.",
    "9. Read the exploratory disclaimer. Confirm "
    "you understand: this is exploratory; not "
    "reference-validated; not lender-ready; not "
    "audit-ready; not bank-approved.",
    "10. Open the feedback panel. Copy the 6-field "
    "template; paste it into email or chat with "
    "your findings. Do NOT include secrets or PII.",
    "11. Report any issue you encountered using the "
    "6-field template. If you do not encounter an "
    "issue, you can say 'No issues encountered' "
    "and submit.",
)


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def _score_workflow(entry: WorkflowEntry) -> int:
    """Compute the readiness score (0-100) for a
    single workflow.

    Scoring:
    - 25 points: helper present
    - 25 points: partial present
    - 25 points: helper tests pass
    - 25 points: factory safety tests pass
    """
    score = 0
    if entry.helper_present:
        score += 25
    if entry.partial_present:
        score += 25
    if entry.helper_tests_pass:
        score += 25
    if entry.factory_safety_tests_pass:
        score += 25
    return score


def _bucket_for_score(score: int) -> str:
    """Map a score to a readiness bucket."""
    for bucket in (
        BUCKET_PILOT_READY,
        BUCKET_CLOSE_TO_PILOT,
        BUCKET_PILOT_BLOCKED,
    ):
        if score >= BUCKET_THRESHOLDS[bucket]:
            return bucket
    return BUCKET_NOT_READY


def build_third_party_test_readiness(
    entries: Sequence[WorkflowEntry],
) -> ThirdPartyTestReadiness:
    """Build the full third-party test readiness
    report.

    Parameters
    ----------
    entries : Sequence[WorkflowEntry]
        One entry per workflow in
        ``ALL_WORKFLOWS``. Missing workflows count
        as 0 score.
    """
    by_workflow = {e.workflow: e for e in entries}

    per_workflow: list[WorkflowScore] = []
    for wf in ALL_WORKFLOWS:
        e = by_workflow.get(wf)
        if e is None:
            e = WorkflowEntry(
                workflow=wf,
                helper_present=False,
                partial_present=False,
                helper_tests_pass=False,
                factory_safety_tests_pass=False,
            )
        score = _score_workflow(e)
        per_workflow.append(
            WorkflowScore(
                workflow=wf,
                label=WORKFLOW_LABELS[wf],
                description=WORKFLOW_DESCRIPTIONS[wf],
                phase_link=PHASE_25C_LINK[wf],
                helper_present=e.helper_present,
                partial_present=e.partial_present,
                helper_tests_pass=e.helper_tests_pass,
                factory_safety_tests_pass=e.factory_safety_tests_pass,
                score=score,
            )
        )

    if per_workflow:
        overall_score = sum(
            s.score for s in per_workflow
        ) // len(per_workflow)
    else:
        overall_score = 0

    bucket = _bucket_for_score(overall_score)
    is_go = bucket in (BUCKET_PILOT_READY, BUCKET_CLOSE_TO_PILOT)
    if is_go:
        if bucket == BUCKET_PILOT_READY:
            go_no_go_reason = (
                f"Overall score {overall_score} >= "
                f"{BUCKET_THRESHOLDS[BUCKET_PILOT_READY]}; "
                f"third-party pilot test is GO."
            )
        else:
            go_no_go_reason = (
                f"Overall score {overall_score} >= "
                f"{BUCKET_THRESHOLDS[BUCKET_CLOSE_TO_PILOT]}; "
                f"third-party pilot test is GO with the "
                f"caveat that the user must read the "
                f"exploratory disclaimer."
            )
    else:
        if bucket == BUCKET_PILOT_BLOCKED:
            go_no_go_reason = (
                f"Overall score {overall_score} < "
                f"{BUCKET_THRESHOLDS[BUCKET_CLOSE_TO_PILOT]}; "
                f"third-party pilot test is NO-GO; "
                f"address remaining blockers first."
            )
        else:
            go_no_go_reason = (
                f"Overall score {overall_score} < "
                f"{BUCKET_THRESHOLDS[BUCKET_PILOT_BLOCKED]}; "
                f"third-party pilot test is NO-GO; "
                f"fundamental gaps remain."
            )

    checklist: list[TestChecklistItem] = []
    for wf, step, expected in PILOT_TEST_CHECKLIST:
        checklist.append(
            TestChecklistItem(
                workflow=wf,
                label=WORKFLOW_LABELS[wf],
                step=step,
                expected_outcome=expected,
            )
        )

    blockers: list[str] = []
    for s in per_workflow:
        if not s.is_ready():
            if not s.helper_present:
                blockers.append(
                    f"{s.label}: helper module missing"
                )
            if not s.partial_present:
                blockers.append(
                    f"{s.label}: display partial missing"
                )
            if not s.helper_tests_pass:
                blockers.append(
                    f"{s.label}: helper tests not passing"
                )
            if not s.factory_safety_tests_pass:
                blockers.append(
                    f"{s.label}: factory safety tests "
                    f"not passing"
                )

    phase_25c_summary: tuple[str, ...] = (
        "25C-1: First-User Pilot Script (PR #594) — "
        "9-step exploratory workflow for Generic "
        "Solar / Wind users.",
        "25C-2: User-Facing Error / Empty State "
        "Cleanup (PR #595) — 7 friendly empty / "
        "error state messages.",
        "25C-3: Pilot Feedback Capture (PR #596) — "
        "6-field structured, copyable feedback "
        "template.",
        "25C Closure: Third-Party Test Readiness "
        "Gate (this PR) — 10-workflow readiness "
        "audit, Go/No-Go, exact pilot test "
        "checklist, suggested tester instructions.",
    )

    return ThirdPartyTestReadiness(
        per_workflow=tuple(per_workflow),
        overall_score=overall_score,
        bucket=bucket,
        is_go=is_go,
        go_no_go_reason=go_no_go_reason,
        pilot_test_checklist=tuple(checklist),
        remaining_blockers=tuple(blockers),
        suggested_tester_instructions=TESTER_INSTRUCTIONS,
        phase_25c_summary=phase_25c_summary,
    )
