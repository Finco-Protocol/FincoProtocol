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
from app.reference_detail_catalog import (
    PUBLIC_GENERIC_DETAIL_V1,
    OPEX_PARENT_BY_CANONICAL_KEY,
    allocate_parent_amount,
    capex_children,
    opex_children,
)


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


_OPEX_GROUP_BY_REFERENCE_NAME = OPEX_PARENT_BY_CANONICAL_KEY


def _primary_capex_category_by_field() -> dict[str, str]:
    """Return the deterministic owner category for each canonical CAPEX field.

    ``CAPEX_CATEGORY_TO_FIELD`` intentionally contains aliases (C.08/C.11).
    The first mapping is the established UI owner; aliases never create a
    second reference-seed row or a second contribution to the summary total.
    """
    owners: dict[str, str] = {}
    for category_code, field_name in CAPEX_CATEGORY_TO_FIELD.items():
        owners.setdefault(field_name, category_code)
    return owners


def _canonical_capex_items(pi: Any, *, include_zero: bool = False) -> dict[str, dict[str, Any]]:
    """Return canonical CAPEX economic items, optionally including zero taxonomy.

    The default is deliberately positive-only: it is the public A3 economic
    reference contract.  Workspace seeding opts into zero rows explicitly so
    a complete public-generic editing taxonomy never changes that API.
    """
    reference_capacity = float(pi.technical.capacity_mw)
    owners = _primary_capex_category_by_field()
    items: dict[str, dict[str, Any]] = {}
    for field_name, category_code in owners.items():
        item = getattr(pi.capex, field_name)
        amount = float(item.amount_keur)
        if amount == 0 and not include_zero:
            continue
        items[field_name] = {
            "canonical_field": field_name,
            "owner_category_code": category_code,
            "canonical_label": item.name,
            "reference_amount_keur": amount,
            "unit_rate_keur_per_mw": amount / reference_capacity,
            "scaling_mode": ScalingMode.PER_MW.value,
        }
    return items


def _canonical_opex_items(pi: Any) -> dict[str, dict[str, Any]]:
    reference_capacity = float(pi.technical.capacity_mw)
    items: dict[str, dict[str, Any]] = {}
    for item in pi.opex:
        if float(getattr(item, "percentage_of_opex", 0) or 0):
            continue
        canonical_key = str(item.name)
        amount = float(item.y1_amount_keur)
        items[canonical_key] = {
            "canonical_key": canonical_key,
            "canonical_label": str(item.name),
            "reference_amount_keur": amount,
            "unit_rate_keur_per_mw": amount / reference_capacity,
            "annual_inflation": float(item.annual_inflation),
            "scaling_mode": ScalingMode.PER_MW.value,
        }
    return items


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
    capex_items = _canonical_capex_items(pi, include_zero=True)
    opex_items = _canonical_opex_items(pi)
    return {
        "version": 3,
        "detail_catalog_authority": PUBLIC_GENERIC_DETAIL_V1,
        "reference_project_id": reference.project_id,
        "reference_template_source": template_source,
        "reference_capacity_mw": reference_capacity,
        "seed_capacity_mw": capacity_mw,
        "scaling_modes": [mode.value for mode in ScalingMode],
        "reference_total_capex_keur": float(pi.capex.total_capex),
        "reference_opex_y1_keur": sum(float(x.y1_amount_keur) for x in pi.opex),
        "technical_inputs": {
            "operating_hours_p50": float(pi.technical.operating_hours_p50),
            "operating_hours_p90_10y": (
                float(pi.technical.operating_hours_p90_10y)
                if pi.technical.operating_hours_p90_10y is not None else None
            ),
            "operating_hours_p99_1y": (
                float(pi.technical.operating_hours_p99_1y)
                if pi.technical.operating_hours_p99_1y is not None else None
            ),
        },
        "capex_items": capex_items,
        "opex_items": opex_items,
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
        "operating_hours_p90_10y": pi.technical.operating_hours_p90_10y,
        "operating_hours_p99_1y": pi.technical.operating_hours_p99_1y,
        "rev_co2_enabled": bool(pi.revenue.co2_enabled),
        "rev_co2_price_eur_mwh": float(pi.revenue.co2_certificate_price_eur_per_mwh),
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
        replay_metadata={"reference_seed_version": 3, "reference_project_id": reference.project_id,
                         "detail_catalog_authority": PUBLIC_GENERIC_DETAIL_V1},
    )

    profile = snapshot["_reference_seed_profile"]
    with get_cursor() as cur:
        technology = "solar" if template_source == "generic_solar_reference" else "wind"
        for field_name, seed in profile["capex_items"].items():
            amount = float(seed["reference_amount_keur"])
            children = capex_children(technology, seed["owner_category_code"])
            for child_index, (child, child_amount) in enumerate(allocate_parent_amount(amount, children)):
                create_capex_line(
                    cur,
                    project_id=record.project_id,
                    parent_category_code=seed["owner_category_code"],
                    business_code=child.code,
                    label=child.label,
                    amount_keur=child_amount * ratio,
                    source="reference_seed",
                    comments="Public generic detail; edit to override.",
                    replay_metadata={
                        "reference_seed": True,
                        # Retain the historical canonical_field contract for the
                        # owning first child; subsequent children have their own
                        # stable identity and carry canonical_parent_field.
                        "canonical_field": field_name if child_index == 0 else f"{field_name}:{child.code}",
                        "canonical_parent_field": field_name,
                        "canonical_key": f"{field_name}:{child.code}",
                        "owner_category_code": seed["owner_category_code"],
                        "canonical_label": seed["canonical_label"],
                        "reference_amount_keur": child_amount,
                        "reference_capacity_mw": reference_capacity,
                        "unit_rate_keur_per_mw": child_amount / reference_capacity,
                        "scaling_mode": ScalingMode.PER_MW.value,
                        "detail_catalog_authority": PUBLIC_GENERIC_DETAIL_V1,
                        "detail_code": child.code,
                        "allocation_weight": float(child.weight),
                    },
                )
        for canonical_key, seed in profile["opex_items"].items():
            group = _OPEX_GROUP_BY_REFERENCE_NAME.get(canonical_key)
            if group is None:
                continue
            amount = float(seed["reference_amount_keur"])
            for child, child_amount in allocate_parent_amount(amount, opex_children(group, technology)):
                create_opex_line(
                    cur,
                    project_id=record.project_id,
                    parent_group_code=group,
                    business_code=child.code,
                    label=child.label,
                    amount_keur=child_amount * ratio,
                    inflation_pct=float(seed["annual_inflation"]) * 100,
                    source="reference_seed",
                    comments="Public generic detail; edit to override.",
                    replay_metadata={
                        "reference_seed": True,
                        # Parent identity remains stable across every child so
                        # the materializer removes the canonical OPEX parent
                        # exactly once.  The child identity is separate and
                        # immutable; an editable label is never either key.
                        "canonical_key": canonical_key,
                        "canonical_parent_key": canonical_key,
                        "detail_canonical_key": f"{canonical_key}:{child.code}",
                        "canonical_label": seed["canonical_label"],
                        "reference_amount_keur": child_amount,
                        "reference_capacity_mw": reference_capacity,
                        "unit_rate_keur_per_mw": child_amount / reference_capacity,
                        "annual_inflation": seed["annual_inflation"],
                        "scaling_mode": ScalingMode.PER_MW.value,
                        "detail_catalog_authority": PUBLIC_GENERIC_DETAIL_V1,
                        "detail_code": child.code,
                        "allocation_weight": float(child.weight),
                    },
                )
    return record


def restore_reference_seed_technical_authority(inputs: Any, snapshot: dict[str, Any]) -> Any:
    """Restore typed P90/P99 values after the generic snapshot resolver.

    The generic resolver derives P90/P99 whenever capacity or P50 is present.
    Reference-driven working copies instead carry those values from the
    canonical reference.  Explicit later snapshot edits still win.
    """
    profile = _resolve_seed_profile(snapshot)
    if profile is None:
        return inputs
    technical_seed = profile.get("technical_inputs")
    if not isinstance(technical_seed, dict):
        return inputs
    from dataclasses import replace

    p90 = snapshot.get(
        "operating_hours_p90_10y", technical_seed.get("operating_hours_p90_10y")
    )
    p99 = snapshot.get(
        "operating_hours_p99_1y", technical_seed.get("operating_hours_p99_1y")
    )
    return replace(
        inputs,
        technical=replace(
            inputs.technical,
            operating_hours_p90_10y=float(p90) if p90 not in (None, "") else None,
            operating_hours_p99_1y=float(p99) if p99 not in (None, "") else None,
        ),
    )


def _resolve_seed_profile(snapshot: dict) -> "dict | None":
    """Return the ``_reference_seed_profile`` from a workspace snapshot as a dict.

    Handles two storage forms:
    - dict: stored before any CAS update (initial seed)
    - JSON string: stored after a CAS round-trip through ProjectInputSet
      (from_snapshot serialises dict values with json.dumps so they
      survive the snapshot_origin str-normalisation pass intact)
    """
    profile = snapshot.get("_reference_seed_profile")
    if isinstance(profile, dict):
        return profile
    if isinstance(profile, str) and profile:
        try:
            parsed = json.loads(profile)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, KeyError):
            pass
    return None


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
    profile = _resolve_seed_profile(ws.draft_snapshot)
    if profile is None:
        return
    opex_items = profile.get("opex_items", {})
    reconciled_capex_total = None
    reconciled_opex_total = None
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
            "SELECT sub_line_id, replay_metadata_json FROM opex_sub_lines "
            "WHERE project_id=? AND is_active=1 AND source='reference_seed'",
            (record.project_id,),
        )
        for row in cur.fetchall():
            metadata = json.loads(row["replay_metadata_json"] or "{}")
            canonical_key = metadata.get("canonical_key")
            seed = opex_items.get(canonical_key, {})
            rate = metadata.get("unit_rate_keur_per_mw", seed.get("unit_rate_keur_per_mw"))
            if rate is not None and metadata.get("scaling_mode") == ScalingMode.PER_MW.value:
                cur.execute(
                    "UPDATE opex_sub_lines SET amount_keur=?, updated_at=datetime('now') "
                    "WHERE project_id=? AND sub_line_id=?",
                    (float(rate) * capacity_mw, record.project_id, row["sub_line_id"]),
                )
        cur.execute(
            "SELECT COALESCE(SUM(amount_keur), 0) AS total FROM capex_sub_lines "
            "WHERE project_id=? AND is_active=1",
            (record.project_id,),
        )
        reconciled_capex_total = float(cur.fetchone()["total"])
        cur.execute(
            "SELECT COALESCE(SUM(amount_keur), 0) AS total FROM opex_sub_lines "
            "WHERE project_id=? AND is_active=1",
            (record.project_id,),
        )
        reconciled_opex_total = float(cur.fetchone()["total"])
    snapshot = dict(ws.draft_snapshot)
    snapshot["capacity_mw"] = f"{capacity_mw:.12g}"
    snapshot["total_capex_keur"] = f"{reconciled_capex_total:.12g}"
    snapshot["opex_y1_keur"] = f"{reconciled_opex_total:.12g}"
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


# ── Public read-only helpers (A3 Model Reference API) ─────────────────────────
# These expose pure canonical helpers for external read-only callers.

def get_reference_inputs(template_source: str):
    """Return canonical ProjectInputs for a reference template (read-only, no DB)."""
    return _reference_inputs(template_source)


def canonical_capex_reference_items(pi) -> dict:
    """Return canonical CAPEX items dict for a reference ProjectInputs (read-only)."""
    return _canonical_capex_items(pi)


def canonical_opex_reference_items(pi) -> dict:
    """Return enriched OPEX items with group_code for a reference ProjectInputs (read-only)."""
    raw = _canonical_opex_items(pi)
    enriched = {}
    for key, item in raw.items():
        e = dict(item)
        e["group_code"] = _OPEX_GROUP_BY_REFERENCE_NAME.get(key)
        e["label"] = e.get("canonical_label", key)
        e["annual_inflation_rate"] = e.pop("annual_inflation", None)
        enriched[key] = e
    return enriched


def build_reference_scaling_preview(template_source: str, capacity_mw: float) -> dict:
    """Return pure deterministic scaling preview for a canonical reference at requested capacity.

    Uses the same PER_MW unit-rate authority as create_reference_seeded_project().
    Pure function: no DB calls, no engine execution, no state mutation.
    """
    pi = _reference_inputs(template_source)
    reference_capacity = float(pi.technical.capacity_mw)
    ratio = capacity_mw / reference_capacity

    capex_raw = _canonical_capex_items(pi)
    opex_raw = canonical_opex_reference_items(pi)

    capex_items = []
    for item in capex_raw.values():
        rate = float(item["unit_rate_keur_per_mw"])
        capex_items.append({
            "canonical_field": item["canonical_field"],
            "owner_category_code": item["owner_category_code"],
            "canonical_label": item["canonical_label"],
            "scaling_mode": item["scaling_mode"],
            "reference_amount_keur": float(item["reference_amount_keur"]),
            "unit_rate_keur_per_mw": rate,
            "scaled_amount_keur": rate * capacity_mw,
        })

    opex_items = []
    for item in opex_raw.values():
        rate = float(item["unit_rate_keur_per_mw"])
        opex_items.append({
            "canonical_key": item["canonical_key"],
            "group_code": item.get("group_code"),
            "label": item["label"],
            "scaling_mode": item["scaling_mode"],
            "annual_inflation_rate": item.get("annual_inflation_rate"),
            "reference_amount_keur": float(item["reference_amount_keur"]),
            "unit_rate_keur_per_mw": rate,
            "scaled_amount_keur": rate * capacity_mw,
        })

    reference_total_capex = float(pi.capex.total_capex)
    scaled_total_capex = reference_total_capex * ratio
    reference_seedable_capex = sum(it["reference_amount_keur"] for it in capex_items)
    scaled_seedable_capex = sum(it["scaled_amount_keur"] for it in capex_items)

    reference_opex_y1 = sum(float(x.y1_amount_keur) for x in pi.opex)
    scaled_opex_y1 = reference_opex_y1 * ratio
    reference_seedable_opex = sum(it["reference_amount_keur"] for it in opex_items)
    scaled_seedable_opex = sum(it["scaled_amount_keur"] for it in opex_items)

    return {
        "reference_capacity_mw": reference_capacity,
        "requested_capacity_mw": capacity_mw,
        "ratio": ratio,
        "reference_total_capex_keur": reference_total_capex,
        "scaled_total_capex_keur": scaled_total_capex,
        "reference_seedable_capex_keur": reference_seedable_capex,
        "scaled_seedable_capex_keur": scaled_seedable_capex,
        "capex_items": capex_items,
        "reference_opex_y1_keur": reference_opex_y1,
        "scaled_opex_y1_keur": scaled_opex_y1,
        "reference_seedable_opex_y1_keur": reference_seedable_opex,
        "scaled_seedable_opex_y1_keur": scaled_seedable_opex,
        "opex_items": opex_items,
    }


def reset_reference_seeded_lines(*, user_id: str, project_code: str) -> None:
    """Restore all overridden seed rows to their canonical per-MW values."""
    from app.persistence.projects_repository import get_project_by_code

    record = get_project_by_code(user_id, project_code)
    if record is None:
        raise ValueError("Project not found.")
    ws = get_workspace_state(user_id, record.project_id)
    profile = _resolve_seed_profile(ws.draft_snapshot) if ws else None
    if not isinstance(profile, dict):
        raise ValueError("Project has no reference seed profile.")
    capacity = float(ws.draft_snapshot["capacity_mw"])
    opex_items = profile.get("opex_items", {})
    reconciled_capex_total = None
    reconciled_opex_total = None
    with get_cursor() as cur:
        cur.execute(
            "SELECT sub_line_id, replay_metadata_json FROM capex_sub_lines "
            "WHERE project_id=? AND is_active=1 AND source='user_override'",
            (record.project_id,),
        )
        for row in cur.fetchall():
            metadata = json.loads(row["replay_metadata_json"] or "{}")
            rate = metadata.get("unit_rate_keur_per_mw")
            if metadata.get("reference_seed") is True and rate is not None:
                cur.execute(
                    "UPDATE capex_sub_lines SET amount_keur=?, source='reference_seed', updated_at=datetime('now') "
                    "WHERE sub_line_id=?",
                    (float(rate) * capacity, row["sub_line_id"]),
                )
        cur.execute(
            "SELECT sub_line_id, replay_metadata_json FROM opex_sub_lines "
            "WHERE project_id=? AND is_active=1 AND source='user_override'",
            (record.project_id,),
        )
        for row in cur.fetchall():
            metadata = json.loads(row["replay_metadata_json"] or "{}")
            canonical_key = metadata.get("canonical_key")
            seed = opex_items.get(canonical_key, {})
            rate = metadata.get("unit_rate_keur_per_mw", seed.get("unit_rate_keur_per_mw"))
            if rate is not None:
                cur.execute(
                    "UPDATE opex_sub_lines SET amount_keur=?, inflation_pct=?, "
                    "source='reference_seed', updated_at=datetime('now') "
                    "WHERE sub_line_id=?",
                    (
                        float(rate) * capacity,
                        float(metadata.get("annual_inflation", seed.get("annual_inflation", 0))) * 100,
                        row["sub_line_id"],
                    ),
                )
        cur.execute(
            "SELECT COALESCE(SUM(amount_keur), 0) AS total FROM capex_sub_lines "
            "WHERE project_id=? AND is_active=1",
            (record.project_id,),
        )
        reconciled_capex_total = float(cur.fetchone()["total"])
        cur.execute(
            "SELECT COALESCE(SUM(amount_keur), 0) AS total FROM opex_sub_lines "
            "WHERE project_id=? AND is_active=1",
            (record.project_id,),
        )
        reconciled_opex_total = float(cur.fetchone()["total"])
    refreshed_snapshot = dict(ws.draft_snapshot)
    refreshed_snapshot["total_capex_keur"] = f"{reconciled_capex_total:.12g}"
    refreshed_snapshot["opex_y1_keur"] = f"{reconciled_opex_total:.12g}"
    save_workspace_state(
        user_id=user_id,
        project_id=record.project_id,
        project_code=record.project_code,
        draft_snapshot=refreshed_snapshot,
        saved_snapshot=ws.saved_snapshot,
        dirty=True,
        governance_state=ws.governance_state,
        replay_metadata=ws.replay_metadata,
    )
