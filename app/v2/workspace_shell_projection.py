"""app.v2.workspace_shell_projection — finance workspace shell presentation.

Presentation-only projection for the Model V2 workspace chrome:

- the compact project header (identity + Working Copy / Last Run state +
  Run Model action) — values come verbatim from the authorities the
  workbook route already resolves (``resolve_runtime_freshness`` state,
  persisted workspace record, ProjectInputs identity fields).  No financial
  arithmetic, no engine execution.
- the persistent left navigation tree — a mapping onto EXISTING workbook
  sheet tabs.  A nav item either targets a real existing tab or is clearly
  marked as a future capability; no fake pages are created.

State semantics (hard product contract, see docs/model_v2/UX_FOUNDATION_CONTRACT.md):
    NOT_RUN  — Working Copy, no successful run yet
    CURRENT  — Last Run successful, matches current Working Copy identity
    STALE    — Working Copy changed since the Last Run; the Last Run stays
               visible but is classified stale (never presented as current)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

# Canonical runtime states (mirrors RuntimeFreshness.state vocabulary).
STATE_NOT_RUN = "NOT_RUN"
STATE_CURRENT = "CURRENT"
STATE_STALE = "STALE"

_VALID_STATES = frozenset({STATE_NOT_RUN, STATE_CURRENT, STATE_STALE})


@dataclass(frozen=True)
class WorkspaceNavGroup:
    label: str
    items: tuple["WorkspaceNavItem", ...]


@dataclass(frozen=True)
class WorkspaceNavItem:
    label: str
    # Existing workbook tab id this item activates; None = future capability.
    tab_id: Optional[str]
    available: bool


def workspace_nav_groups() -> tuple[WorkspaceNavGroup, ...]:
    """The persistent finance workspace navigation tree.

    Every ``available`` item activates an EXISTING sheet tab (one economic
    edit authority per field — navigation never duplicates editable
    surfaces).  Items without a safe current presentation seam are
    ``available=False`` future capabilities, rendered disabled and truthfully
    labelled — never as shipped pages.
    """
    return (
        WorkspaceNavGroup("Overview", (
            WorkspaceNavItem("Overview", "tab-overview", True),
        )),
        WorkspaceNavGroup("Model", (
            WorkspaceNavItem("Project", "tab-project-setup", True),
            WorkspaceNavItem("Timeline & Discounting", None, False),
            WorkspaceNavItem("Escalation", None, False),
            WorkspaceNavItem("Revenue", "tab-revenue", True),
            WorkspaceNavItem("Development", "tab-capex", True),
            WorkspaceNavItem("Operations", "tab-opex", True),
        )),
        WorkspaceNavGroup("Financing", (
            WorkspaceNavItem("Senior Debt", "tab-debt", True),
            WorkspaceNavItem("Investor", "tab-investor", True),
            WorkspaceNavItem("Tax", "tab-tax", True),
        )),
        WorkspaceNavGroup("Outputs", (
            WorkspaceNavItem("Statements", "tab-fs", True),
            WorkspaceNavItem("Returns", "tab-returns", True),
            WorkspaceNavItem("Analytics", None, False),
        )),
        WorkspaceNavGroup("Analysis", (
            WorkspaceNavItem("Scenarios", "tab-scenarios", True),
            WorkspaceNavItem("Sensitivity", "tab-sensitivity", True),
            WorkspaceNavItem("Compare", "tab-compare", True),
        )),
        WorkspaceNavGroup("Trust", (
            WorkspaceNavItem("Assumptions", "tab-trust", True),
            WorkspaceNavItem("Calculation Trace", "tab-trust", True),
        )),
        WorkspaceNavGroup("Delivery", (
            WorkspaceNavItem("Exports", None, False),
            WorkspaceNavItem("Run History", "tab-run-history", True),
        )),
    )


@dataclass(frozen=True)
class WorkspaceHeaderProjection:
    """Display payload for the compact persistent project header."""

    project_name: str
    technology: str
    country_iso: str
    capacity_display: str
    project_editable: bool
    state: str                    # NOT_RUN | CURRENT | STALE
    last_run_display: str         # formatted timestamp or ""
    active_scenario_name: str

    @property
    def state_label(self) -> str:
        if self.state == STATE_CURRENT:
            return "CURRENT"
        if self.state == STATE_STALE:
            return "STALE"
        return "NOT RUN"

    @property
    def state_detail(self) -> str:
        if self.state == STATE_CURRENT:
            return f"Last Run · Successful{self._at_suffix()}"
        if self.state == STATE_STALE:
            return (f"Working Copy · changes not run — "
                    f"Last Run · Successful{self._at_suffix()}")
        return "No successful run yet"

    def _at_suffix(self) -> str:
        return f" · {self.last_run_display}" if self.last_run_display else ""


def build_workspace_header_projection(
    *,
    project_name: str,
    technology: str = "",
    country_iso: str = "",
    capacity_mw: Any = None,
    project_editable: bool,
    runtime_state: str,
    has_runtime: bool,
    last_runtime_at_display: str = "",
    active_scenario_name: str = "",
) -> WorkspaceHeaderProjection:
    """Project the compact header from already-resolved authority values.

    ``runtime_state`` is the canonical freshness vocabulary produced by
    ``resolve_runtime_freshness`` (NOT_RUN / CURRENT / STALE via
    ``freshness.state.value``).  A missing runtime with a stale flag
    degrades honestly to NOT_RUN — never to a fabricated CURRENT.
    """
    state = str(runtime_state or "").strip().upper()
    if state not in _VALID_STATES or (state != STATE_NOT_RUN and not has_runtime):
        state = STATE_NOT_RUN
    capacity = str(capacity_mw).strip() if capacity_mw is not None else ""
    if capacity and not capacity.lower().endswith("mw"):
        capacity = f"{capacity} MW"
    return WorkspaceHeaderProjection(
        project_name=project_name,
        technology=str(technology or "").strip(),
        country_iso=str(country_iso or "").strip().upper(),
        capacity_display=capacity,
        project_editable=bool(project_editable),
        state=state,
        last_run_display=str(last_runtime_at_display or ""),
        active_scenario_name=str(active_scenario_name or "").strip(),
    )


def build_workspace_header_from_pis(
    pis: Any,
    *,
    project_name: str,
    project_type: str = "",
    project_editable: bool,
    runtime_state: str,
    has_runtime: bool,
    last_runtime_at_display: str = "",
    active_scenario_name: str = "",
) -> WorkspaceHeaderProjection:
    """Header projection directly from a ProjectInputSet (post-run/save path).

    Identity fields come verbatim from the same ``pis.to_projectinputs()``
    authority the overview projection uses; no recomputation beyond display
    formatting.
    """
    country = ""
    capacity: Any = None
    try:
        pi = pis.to_projectinputs()
        country = getattr(pi.info, "country_iso", "") or ""
        capacity = getattr(pi.technical, "capacity_mw", None)
    except Exception:
        pass
    return build_workspace_header_projection(
        project_name=project_name,
        technology=project_type,
        country_iso=country,
        capacity_mw=capacity,
        project_editable=project_editable,
        runtime_state=runtime_state,
        has_runtime=has_runtime,
        last_runtime_at_display=last_runtime_at_display,
        active_scenario_name=active_scenario_name,
    )
