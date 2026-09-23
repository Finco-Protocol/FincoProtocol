"""Reference-driven project creation and capacity seed authority.

This module is the only application-layer authority that translates a
canonical Solar/Wind reference into an editable working-copy seed.  It does
not invent market averages and it never calls the economic engine.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.persistence.db import get_cursor
from app.persistence.capex_sub_lines import CAPEX_CATEGORY_TO_FIELD, create_sub_line as create_capex_line
from app.persistence.opex_sub_lines import create_sub_line as create_opex_line
from app.persistence.projects_repository import get_reference_by_template_source, update_project_record
from app.persistence.workspace_repository import get_workspace_state, save_workspace_state
from app.services.project_library_service import create_working_copy, ensure_reference_models


class ScalingMode(str, Enum):
    PER_MW = "PER_MW"
    FIXED = "FIXED"
    PERCENTAGE = "PERCENTAGE"
    RATE = "RATE"
    RATIO = "RATIO"
    DURATION = "DURATION"
    REFERENCE_LOCKED = "REFERENCE_LOCKED"
    DERIVED = "DERIVED"


@dataclass(frozen=True)
class SeedLine:
    code: str
    label: str
    amount_keur: float
    unit_rate_keur_per_mw: float
    scaling_mode: ScalingMode = ScalingMode.PER_MW


_OPEX_GROUP_BY_REFERENCE_NAME = {
    "Technical Management": "B.01",
    "Maintenance": "B.02",
    "Insurance": "B.06",
    "Lease & Tax": "B.07",
}


def _reference_inputs(template_source: str):
    from app.project_factories import create_generic_solar_reference, create_generic_wind_reference

    if template_source == "generic_solar_reference":
        return create_generic_solar_reference()
    if template_source == "generic_wind_reference":
        return create_generic_wind_reference()
    raise ValueError("Only canonical Solar and Wind references may seed a project.")


def _scaled(value: Any, ratio: float) -> str:
    return f"{float(value or 0) * ratio:.12g}"


def _seed_profile(template_source: str, reference: Any, capacity_mw: float, pi: Any) -> dict[str, Any]:
    reference_capacity = float(pi.technical.capacity_mw)
    capex_rates = {
        code: float(getattr(pi.capex, field_name).amount_keur) / reference_capacity
        for code, field_name in CAPEX_CATEGORY_TO_FIELD.items()
        if float(getattr(pi.capex, field_name).amount_keur) != 0
    }
    opex_rates = {
        item.name: float(item.y1_amount_keur) / reference_capacity
        for item in pi.opex
        if not float(getattr(item, "percentage_of_opex", 0) or 0)
    }
    return {
        "version": 1,
        "reference_project_id": reference.project_id,
        "reference_template_source": template_source,
        "reference_capacity_mw": reference_capacity,
        "seed_capacity_mw": capacity_mw,
        "scaling_modes": [mode.value for mode in ScalingMode],
        "capex_unit_rates_keur_per_mw": capex_rates,
        "opex_unit_rates_keur_per_mw": opex_rates,
        "financing_inputs": {
            "gearing_ratio": float(pi.financing.gearing_ratio),
            "base_rate": float(pi.financing.base_rate),
            "margin_bps": float(pi.financing.margin_bps),
            "senior_tenor_years": int(pi.financing.senior_tenor_years),
            "target_dscr": float(pi.financing.target_dscr),
            "lockup_dscr": float(pi.financing.lockup_dscr),
            "min_llcr": float(pi.financing.min_llcr),
            "modes": {
                "gearing_ratio": ScalingMode.RATIO.value,
                "base_rate": ScalingMode.RATE.value,
                "margin_bps": ScalingMode.RATE.value,
                "senior_tenor_years": ScalingMode.DURATION.value,
                "target_dscr": ScalingMode.RATIO.value,
                "lockup_dscr": ScalingMode.RATIO.value,
                "min_llcr": ScalingMode.RATIO.value,
            },
        },
    }


def create_reference_seeded_project(
    *, user_id: str, template_source: str, requested_name: str, capacity_mw: float
):
    """Clone and scale a canonical Solar/Wind reference into a working copy."""
    if template_source not in {"generic_solar_reference", "generic_wind_reference"}:
        raise ValueError("Reference-driven creation supports Solar and Wind only.")
    if not requested_name.strip():
        raise ValueError("Project name is required.")
    if capacity_mw <= 0:
        raise ValueError("Capacity must be greater than zero MW.")

    ensure_reference_models()
    reference = get_reference_by_template_source(template_source)
    if reference is None:
        raise RuntimeError(f"Canonical reference {template_source!r} is unavailable.")
    pi = _reference_inputs(template_source)
    reference_capacity = float(pi.technical.capacity_mw)
    ratio = float(capacity_mw) / reference_capacity
    record = create_working_copy(user_id, reference.project_id, requested_name.strip())
    ws = get_workspace_state(user_id, record.project_id)
    if ws is None:
        raise RuntimeError("Working-copy workspace was not initialized.")

    snapshot = dict(ws.draft_snapshot)
    snapshot.update({
        "capacity_mw": f"{float(capacity_mw):.12g}",
        "total_capex_keur": _scaled(pi.capex.total_capex, ratio),
        "opex_y1_keur": _scaled(sum(float(x.y1_amount_keur) for x in pi.opex), ratio),
        "_reference_seed_profile": _seed_profile(template_source, reference, capacity_mw, pi),
    })
    update_project_record(
        user_id=user_id,
        project_code=record.project_code,
        baseline_snapshot=snapshot,
    )
    save_workspace_state(
        user_id=user_id,
        project_id=record.project_id,
        project_code=record.project_code,
        draft_snapshot=snapshot,
        saved_snapshot=snapshot,
        dirty=False,
        governance_state=record.governance_state,
        replay_metadata={"reference_seed_version": 1, "reference_project_id": reference.project_id},
    )

    field_to_code = {field: code for code, field in CAPEX_CATEGORY_TO_FIELD.items()}
    with get_cursor() as cur:
        for field_name in dict.fromkeys(CAPEX_CATEGORY_TO_FIELD.values()):
            item = getattr(pi.capex, field_name)
            amount = float(item.amount_keur)
            if amount == 0:
                continue
            code = field_to_code[field_name]
            create_capex_line(
                cur,
                project_id=record.project_id,
                parent_category_code=code,
                label=item.name,
                amount_keur=amount * ratio,
                source="reference_seed",
                comments="Seeded from canonical reference; edit to override.",
                replay_metadata={
                    "reference_seed": True,
                    "reference_amount_keur": amount,
                    "reference_capacity_mw": reference_capacity,
                    "unit_rate_keur_per_mw": amount / reference_capacity,
                    "scaling_mode": ScalingMode.PER_MW.value,
                },
            )
        for item in pi.opex:
            group = _OPEX_GROUP_BY_REFERENCE_NAME.get(item.name)
            if group is None or float(getattr(item, "percentage_of_opex", 0) or 0):
                continue
            amount = float(item.y1_amount_keur)
            create_opex_line(
                cur,
                project_id=record.project_id,
                parent_group_code=group,
                label=item.name,
                amount_keur=amount * ratio,
                inflation_pct=float(item.annual_inflation) * 100,
                source="reference_seed",
                comments=json.dumps({
                    "reference_seed": True,
                    "reference_amount_keur": amount,
                    "reference_capacity_mw": reference_capacity,
                    "unit_rate_keur_per_mw": amount / reference_capacity,
                    "scaling_mode": ScalingMode.PER_MW.value,
                }, sort_keys=True),
            )
    return record


def rescale_reference_seeded_project(*, user_id: str, project_code: str, capacity_mw: float) -> None:
    """Rescale only untouched PER_MW seed lines after a capacity edit.

    Rows whose ``source`` changed to ``user_override`` are intentionally left
    alone.  The reference unit rates in the stored seed metadata remain the
    authority; no new formula or market assumption is introduced here.
    """
    from app.persistence.projects_repository import get_project_by_code

    record = get_project_by_code(user_id, project_code)
    if record is None or record.template_source not in {"generic_solar_reference", "generic_wind_reference"}:
        return
    ws = get_workspace_state(user_id, record.project_id)
    if ws is None:
        return
    profile = ws.draft_snapshot.get("_reference_seed_profile")
    if not isinstance(profile, dict):
        return
    capex_rates = profile.get("capex_unit_rates_keur_per_mw", {})
    opex_rates = profile.get("opex_unit_rates_keur_per_mw", {})
    with get_cursor() as cur:
        cur.execute(
            "SELECT sub_line_id, replay_metadata_json FROM capex_sub_lines "
            "WHERE project_id=? AND is_active=1 AND source='reference_seed'",
            (record.project_id,),
        )
        for row in cur.fetchall():
            metadata = json.loads(row["replay_metadata_json"] or "{}")
            rate = metadata.get("unit_rate_keur_per_mw")
            if rate is not None and metadata.get("scaling_mode") == ScalingMode.PER_MW.value:
                cur.execute(
                    "UPDATE capex_sub_lines SET amount_keur=?, updated_at=datetime('now') "
                    "WHERE project_id=? AND sub_line_id=?",
                    (float(rate) * capacity_mw, record.project_id, row["sub_line_id"]),
                )
        cur.execute(
            "SELECT sub_line_id, comments FROM opex_sub_lines "
            "WHERE project_id=? AND is_active=1 AND source='reference_seed'",
            (record.project_id,),
        )
        for row in cur.fetchall():
            try:
                metadata = json.loads(row["comments"] or "{}")
            except (TypeError, ValueError):
                metadata = {}
            rate = metadata.get("unit_rate_keur_per_mw")
            if rate is not None and metadata.get("scaling_mode") == ScalingMode.PER_MW.value:
                cur.execute(
                    "UPDATE opex_sub_lines SET amount_keur=?, updated_at=datetime('now') "
                    "WHERE project_id=? AND sub_line_id=?",
                    (float(rate) * capacity_mw, record.project_id, row["sub_line_id"]),
                )
    snapshot = dict(ws.draft_snapshot)
    snapshot["capacity_mw"] = f"{capacity_mw:.12g}"
    snapshot["total_capex_keur"] = f"{sum(float(v) for v in capex_rates.values()) * capacity_mw:.12g}"
    snapshot["opex_y1_keur"] = f"{sum(float(v) for v in opex_rates.values()) * capacity_mw:.12g}"
    profile = dict(profile)
    profile["seed_capacity_mw"] = capacity_mw
    snapshot["_reference_seed_profile"] = profile
    save_workspace_state(
        user_id=user_id,
        project_id=record.project_id,
        project_code=record.project_code,
        draft_snapshot=snapshot,
        saved_snapshot=ws.saved_snapshot,
        dirty=True,
        governance_state=ws.governance_state,
        replay_metadata=ws.replay_metadata,
    )
