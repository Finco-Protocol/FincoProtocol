"""Explicit tariff binding at the scenario boundary, not global alias precedence."""
from __future__ import annotations

from math import isfinite


def bind_scenario_tariff(snapshot: dict, overrides: dict) -> dict:
    """Copy a snapshot and bind the admitted legacy scenario tariff to its input.

    A canonical Working Copy tariff still wins globally. Only an explicit
    scenario override replaces it here. No write, inference or engine logic.
    Legacy-only snapshots retain their shape and use the existing adapter.
    """
    effective = dict(snapshot)
    from app.workbook.revenue_multistream import SNAPSHOT_KEY, canonical_json
    if SNAPSHOT_KEY in overrides:
        effective[SNAPSHOT_KEY] = canonical_json(overrides[SNAPSHOT_KEY])
    if effective.get(SNAPSHOT_KEY) and any(
        key in overrides for key in ("tariff_eur_mwh", "ppa_tariff_eur_mwh", "ppa_term_years")
    ):
        raise ValueError("REVENUE_V2_SCENARIO: replace the explicit contracts, not legacy PPA aliases")
    if "tariff_eur_mwh" not in overrides:
        return effective
    project_type = str(snapshot.get("project_type") or "").strip().lower()
    if project_type and project_type not in ("solar", "wind"):
        raise ValueError("Scenario PPA tariff overrides are only supported for Solar and Wind.")
    raw = overrides["tariff_eur_mwh"]
    try:
        tariff = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Scenario tariff must be a finite non-negative number.") from exc
    if isinstance(raw, bool) or not isfinite(tariff) or tariff < 0:
        raise ValueError("Scenario tariff must be a finite non-negative number.")
    effective["tariff_eur_mwh"] = tariff
    if "rev_ppa_base_tariff" in effective:
        effective["rev_ppa_base_tariff"] = tariff
    return effective
