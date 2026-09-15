"""
app.v2.scenario_presentation — Template-safe presentation layer for ScenarioRecord.

Converts raw ScenarioRecord objects (which carry datetime-typed fields) into
fully normalised ScenarioPresentation instances that Jinja templates can consume
without any type-aware logic.

Stale semantics (UI-3B):
  NOT_RUN  — no authoritative run result stored on this scenario
  CURRENT  — scenario financial input identity matches last run identity
  STALE    — scenario financial inputs have changed since the last run

Financial staleness is determined by comparing a hash of the scenario's current
resolved snapshot against the snapshot_hash stored in last_run_summary at run
time.  This means:
  - rename alone does NOT make a result stale (snapshot unchanged)
  - archive alone does NOT make a result stale
  - scenario selection alone does NOT make a result stale
  - changing a financial override DOES make the result stale (snapshot changes)

If last_run_summary has no snapshot_hash (records from before Correction B), we
fall back to comparing overrides identity — if overrides are empty and no
snapshot_hash, we conservatively mark CURRENT; otherwise NOT_RUN.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class ScenarioPresentation:
    """Normalised, template-safe view of a ScenarioRecord."""

    scenario_id: str
    scenario_name: str
    is_base_case: bool
    is_active: bool

    # Display strings — never None, never require slicing in templates
    updated_at_display: str    # "YYYY-MM-DD HH:MM" or ""
    run_at_display: str        # "YYYY-MM-DD HH:MM" or ""

    # Financial state for badge display
    state: str                 # "NOT_RUN" | "CURRENT" | "STALE"
    is_stale: bool
    has_run: bool


# ── helpers ──────────────────────────────────────────────────────────────────

def _fmt_dt(value: "datetime | str | None", chars: int = 16) -> str:
    """Return a display-safe timestamp string, always ≤ chars characters."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        iso = value.isoformat()
    else:
        iso = str(value)
    # normalise: replace T separator with space, drop timezone suffix
    iso = iso.replace("T", " ")
    # strip trailing Z or +HH:MM
    for suffix in ("Z", "+00:00"):
        if iso.endswith(suffix):
            iso = iso[: -len(suffix)]
    return iso[:chars]


def _scenario_snapshot_hash(sc) -> Optional[str]:
    """Stable hash of the scenario's current resolved snapshot dict.

    Returns None if no snapshot data is available.
    """
    snap = getattr(sc, "snapshot", None)
    if not snap:
        overrides = getattr(sc, "overrides", None) or {}
        base = getattr(sc, "base_input_set", None) or {}
        if not overrides and not base:
            return None
        snap = {"overrides": overrides, "base": base}
    try:
        canon = json.dumps(snap, sort_keys=True, default=str)
        return hashlib.sha256(canon.encode()).hexdigest()[:16]
    except Exception:
        return None


def _is_stale(sc) -> bool:
    """Return True iff the scenario has a run result that is now stale.

    Stale = financial inputs changed after the last run.
    Uses snapshot_hash stored in last_run_summary for comparison.
    Falls back gracefully when snapshot_hash is absent (old records).
    """
    rs = getattr(sc, "last_run_summary", None)
    if not rs or not rs.get("kpis"):
        return False  # NOT_RUN — not stale

    stored_hash = rs.get("scenario_snapshot_hash")
    current_hash = _scenario_snapshot_hash(sc)

    if stored_hash is not None and current_hash is not None:
        return stored_hash != current_hash

    # Fallback for records without snapshot_hash: compare overrides identity.
    # If both are missing, we can't tell — conservatively report CURRENT.
    stored_overrides = rs.get("scenario_overrides_at_run")
    current_overrides = getattr(sc, "overrides", None) or {}
    if stored_overrides is not None:
        try:
            return json.dumps(stored_overrides, sort_keys=True, default=str) != \
                   json.dumps(current_overrides, sort_keys=True, default=str)
        except Exception:
            pass
    return False


# ── public API ───────────────────────────────────────────────────────────────

def build_scenario_presentation(sc, active_scenario_id: Optional[str]) -> ScenarioPresentation:
    """Convert a ScenarioRecord to a template-safe ScenarioPresentation."""
    rs = getattr(sc, "last_run_summary", None) or {}
    has_run = bool(rs.get("kpis"))

    stale = _is_stale(sc)
    if not has_run:
        state = "NOT_RUN"
    elif stale:
        state = "STALE"
    else:
        state = "CURRENT"

    run_at_raw = rs.get("ran_at") if rs else None
    updated_at_raw = getattr(sc, "updated_at", None)

    return ScenarioPresentation(
        scenario_id=sc.scenario_id,
        scenario_name=sc.scenario_name,
        is_base_case=getattr(sc, "is_base_case", False),
        is_active=(sc.scenario_id == active_scenario_id),
        updated_at_display=_fmt_dt(updated_at_raw),
        run_at_display=_fmt_dt(run_at_raw),
        state=state,
        is_stale=stale,
        has_run=has_run,
    )


def build_scenario_presentations(
    scenarios,
    active_scenario_id: Optional[str],
) -> list[ScenarioPresentation]:
    return [build_scenario_presentation(sc, active_scenario_id) for sc in scenarios]
