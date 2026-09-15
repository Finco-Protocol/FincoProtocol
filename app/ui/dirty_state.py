"""Phase 25B-4 — Dirty state UI helpers (pure functions).

This module is the single source of truth for mapping the underlying
workspace dirty/stale state (already exposed by
``app.services.scenario_state_service.build_workspace_state_metadata``)
into the four UI badges/notices that the user sees on the workspace.

The badges are visual only; no DB I/O, no time, no random, no side
effects. The template side just calls these helpers and renders the
returned dict.

Four UI surfaces (kept distinct on purpose):

- ``badge_saved_state``  — small chip shown in the workspace top bar
  ("Saved" / "Unsaved edits" / "Stale — older than current draft").

- ``scenario_dirty_indicator`` — small dot (or empty) on each scenario
  card. A scenario is "dirty" when the workspace is dirty AND this
  scenario is the active one. Factory projects can never be dirty
  (they are read-only), and non-active scenarios are clean (the draft
  edits apply to the active scenario, not to other saved scenarios).

- ``changes_not_saved_notice`` — banner shown in the input section
  when the workspace is dirty. Renders a clear, non-alarming
  description: "Save to persist. Run does not auto-save."

- ``run_disabled_warning`` — small warning chip shown next to the Run
  button when running the model would compute against a stale
  snapshot. "Run will use older than current draft" — explicit, not
  scary.

The helper is called from main_web._workspace_refresh_payload and
populates the ``dirty_state_ui`` field on the payload. Templates read
``dirty_state_ui.badge``, ``dirty_state_ui.scenario_dots``,
``dirty_state_ui.notice`` and ``dirty_state_ui.run_warning``.
"""
from __future__ import annotations

from typing import Any

# ── Constants ─────────────────────────────────────────────────────────────
# Visual only — no behavioural side effects.

SAVED_BADGE_LABEL = "Saved"
UNSAVED_BADGE_LABEL = "Unsaved edits"
STALE_BADGE_LABEL = "Stale — older than current draft"
STALE_SCENARIO_LABEL = "Stale — scenario changed since last Run"

CHANGES_NOT_SAVED_TITLE = "Changes not yet saved"
CHANGES_NOT_SAVED_BODY = (
    "Save to persist. Run does not auto-save. "
    "Runtime-backed exports remain tied to the last clean snapshot "
    "until you save and re-run."
)

RUN_DISABLED_TITLE = "Run will use older than current draft"
RUN_DISABLED_BODY = (
    "The runtime snapshot is bound to the last clean save. "
    "Re-run after saving to apply draft edits to the model."
)

FACTORY_NO_DIRTY_BODY = (
    "Protected original is read-only. Use Duplicate or Save As to create "
    "an editable copy before modifying."
)


# ── Public helpers ────────────────────────────────────────────────────────

def badge_saved_state(
    dirty: bool,
    has_runtime_snapshot: bool,
    *,
    is_user_project: bool = True,
    active_scenario_id: str = "",
    last_runtime_scenario_id: str | None = None,
    any_run_committed: bool = False,
) -> dict[str, Any]:
    """Build the workspace-top 'Saved state' chip.

    Parameters
    ----------
    dirty:
        True when the workspace has unsaved edits.
    has_runtime_snapshot:
        True when a runtime snapshot id is bound to the workspace
        (``workspace_state.last_runtime_snapshot_id`` is non-empty).
        A dirty workspace WITH a runtime snapshot means "stale".
    is_user_project:
        False for factory baselines (Generic Wind Reference / Generic Solar Reference). Factory
        baselines are always read-only and never have unsaved edits.
    active_scenario_id:
        The currently active scenario id. Empty when no scenario active.
    last_runtime_scenario_id:
        The scenario id that was active when the last Run completed.
        ``None`` means no Run has ever been committed (never-run state).
        Empty string ``""`` means the last Run was Base (no active scenario).

    Returns
    -------
    dict with fields:
      - ``label``: str (text for the chip)
      - ``state``: one of "saved" | "unsaved" | "stale" | "stale_scenario" | "factory"
      - ``css_class``: str (CSS class for the chip)
      - ``icon``: str (single character used as a visual hint)
    """
    if not is_user_project:
        return {
            "label": "Read-only protected original",
            "state": "factory",
            "css_class": "ds-badge--factory",
            "icon": "🔒",
        }
    if dirty and has_runtime_snapshot:
        return {
            "label": STALE_BADGE_LABEL,
            "state": "stale",
            "css_class": "ds-badge--stale",
            "icon": "⏱",
        }
    if dirty:
        return {
            "label": UNSAVED_BADGE_LABEL,
            "state": "unsaved",
            "css_class": "ds-badge--unsaved",
            "icon": "●",
        }
    # R9/N03: scenario switch without re-run makes the persisted runtime stale.
    # active_scenario_id != last_runtime_scenario_id even when dirty=False.
    # last_runtime_scenario_id is preserved across scenario switches (it records
    # which scenario produced the last Run, not the currently selected one).
    # None means "Base run" or "never run"; any_run_committed distinguishes them.
    if _scenario_changed(active_scenario_id, last_runtime_scenario_id, any_run_committed=any_run_committed):
        return {
            "label": STALE_SCENARIO_LABEL,
            "state": "stale_scenario",
            "css_class": "ds-badge--stale",
            "icon": "⏱",
        }
    return {
        "label": SAVED_BADGE_LABEL,
        "state": "saved",
        "css_class": "ds-badge--saved",
        "icon": "✓",
    }


def _scenario_changed(
    active_scenario_id: str,
    last_runtime_scenario_id: str | None,
    *,
    any_run_committed: bool = False,
) -> bool:
    """True when the active scenario differs from the last-run scenario.

    Three authoritative states derived from ``last_runtime_scenario_id`` and
    ``any_run_committed``:

    - **Never run**: ``last_runtime_scenario_id is None`` AND
      ``any_run_committed=False``.  Stale concept does not apply → returns False.

    - **Last run was Base**: ``last_runtime_scenario_id is None`` AND
      ``any_run_committed=True``.  Stale when ``active_scenario_id`` is set.

    - **Last run was Scenario X**: ``last_runtime_scenario_id == X``.
      Stale when active differs from X.
    """
    if last_runtime_scenario_id is None:
        if not any_run_committed:
            return False  # never run — not stale
        # Base run: last_runtime_scenario_id=None means Base was the last run.
        # Stale when the user has since switched to a Scenario.
        return bool(active_scenario_id)
    return (active_scenario_id or "") != (last_runtime_scenario_id or "")


def scenario_dirty_indicator(
    *,
    is_active_scenario: bool,
    workspace_dirty: bool,
    is_user_project: bool = True,
) -> dict[str, Any]:
    """Build the per-scenario dirty dot for the scenario list.

    A scenario is "dirty" when:
    1. The workspace is dirty, AND
    2. This scenario is the active scenario, AND
    3. The project is a user project (factory projects are read-only).

    Inactive scenarios are always shown as clean — the user only edits
    one scenario at a time, and saving creates a new version history
    entry for the active scenario, not for the others.

    Returns
    -------
    dict with fields:
      - ``is_dirty``: bool
      - ``css_class``: str ("" when clean, "ds-dot--dirty" when dirty)
      - ``title``: str (tooltip text)
    """
    if not is_user_project:
        return {
            "is_dirty": False,
            "css_class": "",
            "title": "Protected original — read-only",
        }
    if is_active_scenario and workspace_dirty:
        return {
            "is_dirty": True,
            "css_class": "ds-dot--dirty",
            "title": "Active scenario has unsaved edits",
        }
    return {
        "is_dirty": False,
        "css_class": "",
        "title": "Clean saved state",
    }


def changes_not_saved_notice(
    dirty: bool,
    *,
    is_user_project: bool = True,
) -> dict[str, Any] | None:
    """Build the 'Changes not yet saved' notice.

    Returns ``None`` when there is nothing to show (clean state, or
    factory project). Templates can use ``{% if notice %}`` to skip
    rendering.
    """
    if not is_user_project:
        return {
            "title": "Protected original",
            "body": FACTORY_NO_DIRTY_BODY,
            "css_class": "ds-notice--factory",
            "icon": "🔒",
        }
    if not dirty:
        return None
    return {
        "title": CHANGES_NOT_SAVED_TITLE,
        "body": CHANGES_NOT_SAVED_BODY,
        "css_class": "ds-notice--unsaved",
        "icon": "⚠",
    }


def run_disabled_warning(
    dirty: bool,
    has_runtime_snapshot: bool,
    *,
    is_user_project: bool = True,
    active_scenario_id: str = "",
    last_runtime_scenario_id: str | None = None,
    any_run_committed: bool = False,
) -> dict[str, Any] | None:
    """Build the 'Run will use older than current draft' warning.

    The Run button itself remains clickable — running is the only way
    to apply the draft edits to the model. But the user must see that
    the result will reflect the LAST CLEAN snapshot, not the current
    dirty draft.

    Also fires when the active scenario differs from the last-run scenario
    (R9/N03: scenario-switch stale without dirty flag).

    ``last_runtime_scenario_id=None, any_run_committed=False`` means never-run;
    _scenario_changed returns False so no spurious warning fires.

    Returns ``None`` when there is no warning to show.
    """
    if not is_user_project:
        return None
    scenario_stale = _scenario_changed(active_scenario_id, last_runtime_scenario_id, any_run_committed=any_run_committed)
    if not (dirty and has_runtime_snapshot) and not scenario_stale:
        return None
    return {
        "title": RUN_DISABLED_TITLE,
        "body": RUN_DISABLED_BODY,
        "css_class": "ds-warning--stale",
        "icon": "⏱",
    }


def build_dirty_state_ui(
    *,
    dirty: bool,
    has_runtime_snapshot: bool,
    is_user_project: bool,
    active_scenario_id: str = "",
    last_runtime_scenario_id: str | None = None,
    any_run_committed: bool = False,
    scenarios: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the full ``dirty_state_ui`` payload for the template.

    Combines all four helpers into a single dict so the template side
    can read everything from one field.

    Parameters
    ----------
    dirty:
        ``workspace_state.dirty`` (already a bool).
    has_runtime_snapshot:
        True when ``workspace_state.last_runtime_snapshot_id`` is set.
    is_user_project:
        ``project_record.project_origin == "user_created"``.
    active_scenario_id:
        The currently active scenario id (string). Empty when no
        scenario is active.
    last_runtime_scenario_id:
        The scenario id that was active when the last Run completed.
        Empty when the last Run was Base (no scenario). Used to detect
        scenario-switch stale (R9/N03).
    scenarios:
        Optional list of scenario card dicts. When provided, each card
        gets a ``dirty_indicator`` sub-dict. When omitted, the
        ``scenario_dots`` list is empty.

    Returns
    -------
    dict with fields:
      - ``badge``: result of ``badge_saved_state``
      - ``notice``: result of ``changes_not_saved_notice`` (or None)
      - ``run_warning``: result of ``run_disabled_warning`` (or None)
      - ``scenario_dots``: list of (scenario_id, dirty_indicator) pairs
    """
    badge = badge_saved_state(
        dirty=bool(dirty),
        has_runtime_snapshot=bool(has_runtime_snapshot),
        is_user_project=bool(is_user_project),
        active_scenario_id=active_scenario_id,
        last_runtime_scenario_id=last_runtime_scenario_id,
        any_run_committed=bool(any_run_committed),
    )
    notice = changes_not_saved_notice(
        dirty=bool(dirty),
        is_user_project=bool(is_user_project),
    )
    run_warning = run_disabled_warning(
        dirty=bool(dirty),
        has_runtime_snapshot=bool(has_runtime_snapshot),
        is_user_project=bool(is_user_project),
        active_scenario_id=active_scenario_id,
        last_runtime_scenario_id=last_runtime_scenario_id,
        any_run_committed=bool(any_run_committed),
    )
    scenario_dots: list[dict[str, Any]] = []
    for item in (scenarios or []):
        sid = item.get("scenario_id") or ""
        is_active = bool(sid) and bool(active_scenario_id) and sid == active_scenario_id
        dot = scenario_dirty_indicator(
            is_active_scenario=is_active,
            workspace_dirty=bool(dirty),
            is_user_project=bool(is_user_project),
        )
        scenario_dots.append({
            "scenario_id": sid,
            "scenario_name": item.get("scenario_name", ""),
            "is_active": is_active,
            **dot,
        })
    return {
        "badge": badge,
        "notice": notice,
        "run_warning": run_warning,
        "scenario_dots": scenario_dots,
    }
