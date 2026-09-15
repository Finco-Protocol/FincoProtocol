"""Generic Solar Reference revenue canonical key backfill for old working copies.

Old working copies created before C2B3 may carry only legacy snapshot keys
(tariff_eur_mwh, ppa_term_years) and lack the canonical rev_* keys introduced
in C2B2/C2B3.  This module provides a deterministic migration that fills in
missing canonical keys from the Generic Solar Reference factory defaults without overwriting
any user-entered values.

Rules:
- Only runs on user-created Generic Solar Reference working copies (template_source == "generic_solar_reference",
  project_origin != "factory_template").
- Only fills ABSENT or EMPTY keys — never overwrites existing values.
- Does not touch the protected Generic Solar Reference reference project.
- Idempotent: safe to call on every GET.
"""
from __future__ import annotations

GENERIC_SOLAR_REFERENCE_CANONICAL_REVENUE_KEYS = (
    "rev_ppa_base_tariff",
    "rev_ppa_index",
    "rev_ppa_term_years",
    "rev_ppa_production_share",
    "rev_ppa_indexation_start_policy",
    "rev_merchant_balancing_pct",
    "rev_balancing_cost_eur_per_mwh",
    "rev_co2_enabled",
    "rev_co2_price_eur_mwh",
    "rev_merchant_price_curve_json",
)


def needs_revenue_backfill(project_record, draft_snapshot: dict) -> bool:
    """Return True if this project is an Generic Solar Reference working copy missing canonical keys."""
    if (project_record.project_origin or "") == "factory_template":
        return False
    if (project_record.template_source or "").strip().lower() != "generic_solar_reference":
        return False
    return any(
        not draft_snapshot.get(k)
        for k in GENERIC_SOLAR_REFERENCE_CANONICAL_REVENUE_KEYS
    )


def backfill_generic_solar_reference_revenue_canonical_keys(
    project_id: str,
    user_id: str,
    project_record,
    draft_snapshot: dict,
) -> dict:
    """Return an updated snapshot with missing canonical revenue keys filled in.

    Does NOT write to the database — the caller decides whether to persist.
    Returns the (possibly unchanged) snapshot dict.
    """
    if not needs_revenue_backfill(project_record, draft_snapshot):
        return draft_snapshot

    from app.project_factories import create_generic_solar_reference
    from app.revenue_snapshot_utils import materialize_revenue_snapshot_defaults

    generic_solar_reference = create_generic_solar_reference()
    defaults = materialize_revenue_snapshot_defaults(generic_solar_reference.revenue)

    updated = dict(draft_snapshot)
    for key, default_val in defaults.items():
        if not updated.get(key):
            updated[key] = default_val

    return updated


def persist_revenue_backfill(
    project_id: str,
    user_id: str,
    project_record,
    *,
    conn=None,
) -> bool:
    """Backfill missing canonical revenue keys in the workspace draft snapshot.

    Reads the current draft, fills missing keys, and writes back if changed.
    Returns True if the snapshot was updated, False if no change needed.

    Safe to call on every GET — only writes when missing keys are detected.
    Does not update the content hash (migration write, not a user edit).

    If ``conn`` is supplied the caller's connection is used; otherwise the
    application connection from get_connection() is used.
    """
    import json as _json

    if conn is None:
        from app.persistence.db import get_connection
        conn = get_connection()

    row = conn.execute(
        "SELECT draft_snapshot_json FROM workspace_states WHERE user_id=? AND project_id=?",
        (user_id, project_id),
    ).fetchone()
    if row is None:
        return False

    current_snapshot = _json.loads(row["draft_snapshot_json"] or "{}")
    if not needs_revenue_backfill(project_record, current_snapshot):
        return False

    updated_snapshot = backfill_generic_solar_reference_revenue_canonical_keys(
        project_id, user_id, project_record, current_snapshot
    )
    if updated_snapshot is current_snapshot:
        return False

    conn.execute(
        "UPDATE workspace_states SET draft_snapshot_json=? WHERE user_id=? AND project_id=?",
        (_json.dumps(updated_snapshot), user_id, project_id),
    )
    conn.commit()
    return True
