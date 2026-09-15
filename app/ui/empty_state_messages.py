"""Phase 25C-2 — User-Facing Error / Empty State
messages.

Pure read-side helper module. Builds user-friendly
empty-state and error-state messages for 7 canonical
conditions encountered in the Generic Solar / Wind
exploratory workflow.

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

The 7 conditions are described in
``CONDITION_*`` constants. Each condition is a pure
constant; ``build_message`` is a pure classifier
that returns a ``Message`` object for the given
condition.

Each message has:
- ``condition``: the condition key
- ``title``: a short, friendly title
- ``body``: 1-2 sentence description
- ``next_action``: what the user should do
- ``next_action_route``: pre-existing route the user
  can navigate to
- ``severity``: ``"info"`` (empty) or ``"warning"``
  (something is wrong) or ``"error"`` (something
  blocked them)
- ``is_exploratory_note``: True if the message
  carries the exploratory scope language

The 7 conditions (per the user's 25C-2 brief):
1. CONDITION_NO_PROJECT — no project exists yet
2. CONDITION_NO_SCENARIO — project exists but no
   scenarios
3. CONDITION_NOT_RUN — scenarios exist but no run
4. CONDITION_LT_2_SCENARIOS — compare page open with
   fewer than 2 scenarios
5. CONDITION_EXPORT_BEFORE_RUN — trying to export
   before running
6. CONDITION_DIRTY_UNSAVED — current scenario has
   unsaved changes
7. CONDITION_STALE_RUN — comparing two scenarios
   where one has a stale run
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Condition vocabulary
# ---------------------------------------------------------------------------


CONDITION_NO_PROJECT = "no_project"
CONDITION_NO_SCENARIO = "no_scenario"
CONDITION_NOT_RUN = "not_run"
CONDITION_LT_2_SCENARIOS = "lt_2_scenarios"
CONDITION_EXPORT_BEFORE_RUN = "export_before_run"
CONDITION_DIRTY_UNSAVED = "dirty_unsaved"
CONDITION_STALE_RUN = "stale_run"

ALL_CONDITIONS: tuple[str, ...] = (
    CONDITION_NO_PROJECT,
    CONDITION_NO_SCENARIO,
    CONDITION_NOT_RUN,
    CONDITION_LT_2_SCENARIOS,
    CONDITION_EXPORT_BEFORE_RUN,
    CONDITION_DIRTY_UNSAVED,
    CONDITION_STALE_RUN,
)

# ---------------------------------------------------------------------------
# Severity vocabulary
# ---------------------------------------------------------------------------


SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"

ALL_SEVERITIES: tuple[str, ...] = (
    SEVERITY_INFO,
    SEVERITY_WARNING,
    SEVERITY_ERROR,
)

# ---------------------------------------------------------------------------
# Action vocabulary
# ---------------------------------------------------------------------------


ACTION_CREATE_PROJECT = "Create a project"
ACTION_USE_DEFAULTS = "Accept the generic defaults"
ACTION_SAVE_SCENARIO = "Save the Base scenario"
ACTION_RUN = "Run the model"
ACTION_DUPLICATE_SCENARIO = "Duplicate a scenario"
ACTION_SAVE_DRAFT = "Save the current draft"
ACTION_RERUN = "Re-run the scenario"
ACTION_GO_TO_TAB = "Go to the scenario tab"
ACTION_RUN_TWO_SCENARIOS = "Run the Base and Downside scenarios"


# ---------------------------------------------------------------------------
# Action routes
# ---------------------------------------------------------------------------


# Pre-existing app routes; we never invent new ones.
ACTION_ROUTES: dict[str, str] = {
    ACTION_CREATE_PROJECT: "/projects/create",
    ACTION_USE_DEFAULTS: "/scenarios/tab",
    ACTION_SAVE_SCENARIO: "/scenarios/save",
    ACTION_RUN: "/scenarios/run",
    ACTION_DUPLICATE_SCENARIO: "/scenarios/add",
    ACTION_SAVE_DRAFT: "/scenarios/save",
    ACTION_RERUN: "/scenarios/run",
    ACTION_GO_TO_TAB: "/scenarios/tab",
    ACTION_RUN_TWO_SCENARIOS: "/scenarios/run",
}


# ---------------------------------------------------------------------------
# Message data class
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Message:
    """A single user-facing empty / error state
    message."""

    #: The condition key (one of CONDITION_*).
    condition: str

    #: Short, friendly title.
    title: str

    #: 1-2 sentence description.
    body: str

    #: What the user should do.
    next_action: str

    #: Pre-existing app route for the action.
    next_action_route: str

    #: ``info`` / ``warning`` / ``error``.
    severity: str

    #: True if the message includes exploratory
    #: scope language.
    is_exploratory_note: bool


__all__ = [
    "Message",
    "ALL_CONDITIONS",
    "ALL_SEVERITIES",
    "CONDITION_NO_PROJECT",
    "CONDITION_NO_SCENARIO",
    "CONDITION_NOT_RUN",
    "CONDITION_LT_2_SCENARIOS",
    "CONDITION_EXPORT_BEFORE_RUN",
    "CONDITION_DIRTY_UNSAVED",
    "CONDITION_STALE_RUN",
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "SEVERITY_ERROR",
    "ACTION_CREATE_PROJECT",
    "ACTION_USE_DEFAULTS",
    "ACTION_SAVE_SCENARIO",
    "ACTION_RUN",
    "ACTION_DUPLICATE_SCENARIO",
    "ACTION_SAVE_DRAFT",
    "ACTION_RERUN",
    "ACTION_GO_TO_TAB",
    "ACTION_RUN_TWO_SCENARIOS",
    "ACTION_ROUTES",
    "build_message",
    "build_all_messages",
    "is_supported_condition",
]


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def is_supported_condition(condition: str) -> bool:
    """Return True if the condition is one of the 7
    canonical conditions handled by this helper."""
    return condition in ALL_CONDITIONS


def build_message(
    condition: str,
    project_label: str = "Generic Solar",
) -> Message:
    """Build a single user-facing message for the
    given condition.

    Parameters
    ----------
    condition : str
        One of ``CONDITION_*``. If unknown, returns
        a generic ``info`` message that points the
        user back to the project list.
    project_label : str
        The display label for the project type.
    """
    pl = project_label or "this project"

    if condition == CONDITION_NO_PROJECT:
        return Message(
            condition=CONDITION_NO_PROJECT,
            title="No project yet",
            body=(
                f"You don't have a project yet for "
                f"{pl}. Create a project to start the "
                f"exploratory workflow."
            ),
            next_action=ACTION_CREATE_PROJECT,
            next_action_route=ACTION_ROUTES[ACTION_CREATE_PROJECT],
            severity=SEVERITY_INFO,
            is_exploratory_note=False,
        )
    if condition == CONDITION_NO_SCENARIO:
        return Message(
            condition=CONDITION_NO_SCENARIO,
            title="No scenarios yet",
            body=(
                f"{pl} exists, but it has no scenarios "
                f"yet. Save a Base scenario to start "
                f"running the model."
            ),
            next_action=ACTION_SAVE_SCENARIO,
            next_action_route=ACTION_ROUTES[ACTION_SAVE_SCENARIO],
            severity=SEVERITY_INFO,
            is_exploratory_note=False,
        )
    if condition == CONDITION_NOT_RUN:
        return Message(
            condition=CONDITION_NOT_RUN,
            title="No run yet",
            body=(
                f"The scenario exists, but the model "
                f"has not been run yet. Run the model "
                f"to see outputs."
            ),
            next_action=ACTION_RUN,
            next_action_route=ACTION_ROUTES[ACTION_RUN],
            severity=SEVERITY_INFO,
            is_exploratory_note=False,
        )
    if condition == CONDITION_LT_2_SCENARIOS:
        return Message(
            condition=CONDITION_LT_2_SCENARIOS,
            title="Need at least 2 scenarios to compare",
            body=(
                f"The compare view needs at least two "
                f"scenarios with a run. Add a second "
                f"scenario and run it to see a side-by-"
                f"side compare."
            ),
            next_action=ACTION_DUPLICATE_SCENARIO,
            next_action_route=ACTION_ROUTES[
                ACTION_DUPLICATE_SCENARIO
            ],
            severity=SEVERITY_INFO,
            is_exploratory_note=False,
        )
    if condition == CONDITION_EXPORT_BEFORE_RUN:
        return Message(
            condition=CONDITION_EXPORT_BEFORE_RUN,
            title="Run the model before exporting",
            body=(
                f"The export contains scenario inputs "
                f"and the latest run. Run the model "
                f"first to include the latest run."
            ),
            next_action=ACTION_RUN,
            next_action_route=ACTION_ROUTES[ACTION_RUN],
            severity=SEVERITY_WARNING,
            is_exploratory_note=True,
        )
    if condition == CONDITION_DIRTY_UNSAVED:
        return Message(
            condition=CONDITION_DIRTY_UNSAVED,
            title="You have unsaved changes",
            body=(
                f"The current scenario has unsaved "
                f"changes. Save the draft before "
                f"running, comparing, or exporting."
            ),
            next_action=ACTION_SAVE_DRAFT,
            next_action_route=ACTION_ROUTES[ACTION_SAVE_DRAFT],
            severity=SEVERITY_WARNING,
            is_exploratory_note=False,
        )
    if condition == CONDITION_STALE_RUN:
        return Message(
            condition=CONDITION_STALE_RUN,
            title="Run is out of date",
            body=(
                f"One of the scenarios you're "
                f"comparing has a stale run. Re-run "
                f"the affected scenario to see the "
                f"latest values."
            ),
            next_action=ACTION_RERUN,
            next_action_route=ACTION_ROUTES[ACTION_RERUN],
            severity=SEVERITY_WARNING,
            is_exploratory_note=False,
        )
    # Unknown condition: return a generic info.
    return Message(
        condition=condition,
        title="Nothing to show",
        body=(
            f"We don't have anything to show for {pl} "
            f"in this state. Go to the project list to "
            f"pick a project."
        ),
        next_action=ACTION_CREATE_PROJECT,
        next_action_route=ACTION_ROUTES[ACTION_CREATE_PROJECT],
        severity=SEVERITY_INFO,
        is_exploratory_note=False,
    )


def build_all_messages(
    project_label: str = "Generic Solar",
) -> dict[str, Message]:
    """Build all 7 messages for the given project
    label. Returns a dict keyed by condition."""
    return {
        c: build_message(c, project_label=project_label)
        for c in ALL_CONDITIONS
    }
