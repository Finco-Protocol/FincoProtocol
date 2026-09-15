"""Phase 25C-1 — Generic Solar / Wind first-user pilot script.

Pure read-side helper module. Builds a 9-step
"Try this workflow" panel for a Generic Solar /
Generic Wind exploratory user.

The helper does NOT:
- mutate any input
- call the persistence layer
- call services
- enable any feature flag
- change any runtime path
- touch construction / C10 / R-PAR / tax / debt / IDC
- touch rc1
- touch factory (Generic Wind Reference / Generic Solar Reference)

It is a pure deterministic classifier over the
already-available context.

9 steps (per the user's 25C-1 brief):
1. create Generic Solar
2. use generic defaults
3. save Base
4. run
5. duplicate Downside
6. change tariff / OPEX / CAPEX
7. run Downside
8. compare Base vs Downside
9. export
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence


# ---------------------------------------------------------------------------
# Step vocabulary
# ---------------------------------------------------------------------------


STEP_CREATE = "create_generic_solar"
STEP_USE_DEFAULTS = "use_generic_defaults"
STEP_SAVE_BASE = "save_base"
STEP_RUN = "run"
STEP_DUPLICATE_DOWNSIDE = "duplicate_downside"
STEP_CHANGE_INPUTS = "change_inputs"
STEP_RUN_DOWNSIDE = "run_downside"
STEP_COMPARE = "compare"
STEP_EXPORT = "export"

STEP_LABELS: dict[str, str] = {
    STEP_CREATE: "Create Generic Solar",
    STEP_USE_DEFAULTS: "Use generic defaults",
    STEP_SAVE_BASE: "Save Base",
    STEP_RUN: "Run",
    STEP_DUPLICATE_DOWNSIDE: "Duplicate Downside",
    STEP_CHANGE_INPUTS: "Change tariff / OPEX / CAPEX",
    STEP_RUN_DOWNSIDE: "Run Downside",
    STEP_COMPARE: "Compare Base vs Downside",
    STEP_EXPORT: "Export",
}

STEP_HINTS: dict[str, str] = {
    STEP_CREATE: (
        "Create a new project using the Generic Solar "
        "template. Generic projects are exploratory; "
        "they are not reference-validated."
    ),
    STEP_USE_DEFAULTS: (
        "Accept the generic defaults that the form "
        "pre-fills. They are reasonable starting "
        "values; you can change them in step 6."
    ),
    STEP_SAVE_BASE: (
        "Save the Base scenario. The save creates a "
        "named snapshot; later runs reference this "
        "snapshot."
    ),
    STEP_RUN: (
        "Run the model. The runtime takes a few "
        "seconds. Outputs are stored on the latest "
        "run record."
    ),
    STEP_DUPLICATE_DOWNSIDE: (
        "Duplicate the Base scenario as a new "
        "Downside scenario. The duplicate inherits "
        "the Base inputs."
    ),
    STEP_CHANGE_INPUTS: (
        "In the Downside scenario, change one or "
        "more inputs (tariff, OPEX, CAPEX). The "
        "override is shown as a highlighted cell."
    ),
    STEP_RUN_DOWNSIDE: (
        "Re-run with the updated inputs. The "
        "downside run replaces the previous "
        "downside run."
    ),
    STEP_COMPARE: (
        "Open the compare view to see Base vs "
        "Downside side by side. KPIs, IRR, DSCR "
        "and other outputs are aligned for "
        "comparison."
    ),
    STEP_EXPORT: (
        "Export the workbook to Excel. The export "
        "includes the scenario inputs, the run "
        "outputs and an exploratory banner."
    ),
}

#: Order for stable output.
STEP_ORDER: tuple[str, ...] = (
    STEP_CREATE,
    STEP_USE_DEFAULTS,
    STEP_SAVE_BASE,
    STEP_RUN,
    STEP_DUPLICATE_DOWNSIDE,
    STEP_CHANGE_INPUTS,
    STEP_RUN_DOWNSIDE,
    STEP_COMPARE,
    STEP_EXPORT,
)

#: Routes used by each step. These are the canonical
#: existing routes in the app; we never invent
#: new ones.
STEP_ROUTES: dict[str, str] = {
    STEP_CREATE: "/projects/create",
    STEP_USE_DEFAULTS: "/scenarios/tab",
    STEP_SAVE_BASE: "/scenarios/save",
    STEP_RUN: "/scenarios/run",
    STEP_DUPLICATE_DOWNSIDE: "/scenarios/add",
    STEP_CHANGE_INPUTS: "/scenarios/tab",
    STEP_RUN_DOWNSIDE: "/scenarios/run",
    STEP_COMPARE: "/scenarios/compare",
    STEP_EXPORT: "/download",
}

#: Exploratory disclaimer shown at the top of the
#: panel. This is not a no-go claim; it is descriptive
#: scope language. We never claim reference validation, lender
#: readiness, audit readiness, or bank approval.
EXPLORATORY_DISCLAIMER: str = (
    "This is an exploratory workflow for Generic "
    "Solar / Generic Wind models. Outputs are not "
    "reference-validated, not lender-ready, not "
    "audit-ready, and not bank-approved. Use this "
    "workflow to learn the product; do not use it "
    "for external signoff."
)


@dataclass(frozen=True)
class PilotStep:
    """A single step in the first-user pilot script."""

    #: The step key (one of STEP_*).
    key: str

    #: The step display label.
    label: str

    #: The step hint shown below the label.
    hint: str

    #: The canonical route the user navigates to.
    route: str

    #: The 1-based order.
    order: int


@dataclass(frozen=True)
class PilotScript:
    """The full 9-step first-user pilot script."""

    steps: tuple[PilotStep, ...]
    exploratory_disclaimer: str
    project_type: str
    project_label: str

    def step_count(self) -> int:
        return len(self.steps)


__all__ = [
    "PilotStep",
    "PilotScript",
    "STEP_ORDER",
    "STEP_LABELS",
    "STEP_HINTS",
    "STEP_ROUTES",
    "EXPLORATORY_DISCLAIMER",
    "build_pilot_script",
    "is_supported_project_type",
]


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def is_supported_project_type(project_type: str) -> bool:
    """Return True if the project type is supported
    by the generic pilot script. Currently Generic
    Solar and Generic Wind only."""
    pt = (project_type or "").strip().lower()
    return pt in {"generic_solar", "generic_wind"}


def build_pilot_script(
    project_type: str = "generic_solar",
    project_label: str = "Generic Solar",
) -> PilotScript:
    """Build the 9-step first-user pilot script.

    Parameters
    ----------
    project_type : str
        The active project type. Must be
        ``generic_solar`` or ``generic_wind``. The
        helper does NOT raise on unsupported types;
        it returns a script anyway, with a clear
        ``project_label`` indicating the type. The
        template is responsible for hiding the panel
        on factory projects.
    project_label : str
        The display label for the project type.
    """
    steps: list[PilotStep] = []
    for i, key in enumerate(STEP_ORDER, start=1):
        steps.append(
            PilotStep(
                key=key,
                label=STEP_LABELS[key],
                hint=STEP_HINTS[key],
                route=STEP_ROUTES[key],
                order=i,
            )
        )
    return PilotScript(
        steps=tuple(steps),
        exploratory_disclaimer=EXPLORATORY_DISCLAIMER,
        project_type=project_type,
        project_label=project_label,
    )
