"""FINCO45B (B1, OD-TIME-01 promotion): the date authority of a NEWLY CREATED ordinary Solar/Wind project.

Scope (exact route semantics):

* applies ONLY at creation of a new ordinary working project - the New Project form (Legacy ``/projects/create``),
  the React New Project create (``create_reference_seeded_project_once``) and the Library "create working copy" of a
  canonical protected reference - all of which seed a brand-new project from the protected reference template;
* never on read, never by inference, never by bulk rewrite: existing drafts, imports, Save-As clones of an existing
  project (``project_save_as_service`` copies the source snapshot verbatim, so a legacy source stays legacy and a dated
  source stays dated), protected reference templates, Run History, XLSX and stored snapshots keep exactly what they
  persisted (an absent key keeps meaning ``LEGACY_CALENDAR/v0``);
* only Solar/Wind on the released semi-annual 6/6 grid. Data Center, EV Charging, BESS and any explicit quarterly 3/3
  selection are never stamped (they stay on their released legacy contract; an explicit dated request on them keeps
  its typed ``DATE_AUTHORITY_TECHNOLOGY_UNSUPPORTED`` refusal in ``app.input_adapter``);
* R04 absolute physical PPA is NOT enabled by this default: scalar PPA and explicit R04 remain separate choices.

Rollback for NEW creations only: ``FINCO_NEW_PROJECT_DATE_AUTHORITY=legacy`` (also ``0``/``off``/``false``) creates
new projects exactly as before (no key). It can never reinterpret a project that already persisted a version.
"""
from __future__ import annotations

import os

from finco_core.engine.date_authority import DATE_AUTHORITY_VERSION

ENV = "FINCO_NEW_PROJECT_DATE_AUTHORITY"
SNAPSHOT_KEY = "date_authority_version"
ELIGIBLE_PROJECT_TYPES = frozenset({"Solar", "Wind"})
ELIGIBLE_TEMPLATE_SOURCES = frozenset({"generic_solar_reference", "generic_wind_reference"})
_ROLLBACK_VALUES = frozenset({"legacy", "legacy_calendar/v0", "0", "off", "false", "no"})


def dated_default_enabled() -> bool:
    raw = os.environ.get(ENV, "").strip().lower()
    if raw == "":
        return True
    if raw in _ROLLBACK_VALUES:
        return False
    return raw == DATE_AUTHORITY_VERSION.lower() or raw in {"1", "on", "true", "yes", "od-time-01"}


def _is_quarterly(snapshot: dict) -> bool:
    from app.workbook.quarterly_frequency_config import SNAPSHOT_KEY as Q_KEY
    return bool(str(snapshot.get(Q_KEY) or "").strip())


def stamp_new_project_date_authority(snapshot: dict, *, project_type: str | None = None,
                                     template_source: str | None = None) -> dict:
    """Return the creation snapshot with ``date_authority_version`` set when (and only when) it is eligible."""
    if not dated_default_enabled():
        return snapshot
    if str(snapshot.get(SNAPSHOT_KEY) or "").strip():
        return snapshot                                   # an explicit persisted choice is never overridden
    if template_source is not None:
        eligible = template_source in ELIGIBLE_TEMPLATE_SOURCES
    else:
        eligible = (project_type or str(snapshot.get("project_type") or "")) in ELIGIBLE_PROJECT_TYPES
    if not eligible:
        return snapshot
    if _is_quarterly(snapshot) or snapshot.get("bess_enabled") in (True, "true", "1", 1):
        return snapshot
    return {**snapshot, SNAPSHOT_KEY: DATE_AUTHORITY_VERSION}
