"""Correction A: immutable OPEX identity and alias-safe CAPEX authority."""
from __future__ import annotations

from dataclasses import replace

import pytest


@pytest.fixture
def correction_db(tmp_path, monkeypatch):
    from app.persistence import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "reference-correction-a.db"))
    db.init_db()


def _factory(template_source: str):
    from app.project_factories import create_generic_solar_reference, create_generic_wind_reference

    return (
        create_generic_solar_reference()
        if template_source == "generic_solar_reference"
        else create_generic_wind_reference()
    )


def _materialize(user_id: str, record):
    """Mirror the canonical user-created Run materialization boundary."""
    from app.input_adapter import _resolve_user_inputs, _snapshot_to_dict
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
    from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex
    from app.services.reference_seed_service import restore_reference_seed_technical_authority

    ws = get_workspace_state(user_id, record.project_id)
    base = _factory(record.template_source)
    inputs = _resolve_user_inputs(base_inputs=base, **_snapshot_to_dict(ws.draft_snapshot))
    inputs = restore_reference_seed_technical_authority(inputs, ws.draft_snapshot)
    inputs = replace(
        inputs,
        capex=apply_user_sub_lines_replacing_base(inputs.capex, project_id=record.project_id),
        opex=apply_user_sub_lines_to_opex(inputs.opex, project_id=record.project_id),
    )
    return inputs


def _run(template_source: str, inputs):
    from app.api.project_runner import run_project

    project_key = "Solar" if template_source == "generic_solar_reference" else "Wind"
    return run_project(project_key, "Base", project_inputs_override=inputs)


@pytest.mark.parametrize(
    ("template_source", "capacity"),
    [
        ("generic_solar_reference", 50.0),
        ("generic_solar_reference", 100.0),
        ("generic_solar_reference", 150.0),
        ("generic_wind_reference", 24.0),
        ("generic_wind_reference", 72.0),
        ("generic_wind_reference", 120.0),
    ],
)
def test_alias_safe_capex_scaling_reconciles_summary_and_detail(
    correction_db, template_source, capacity
):
    from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.reference_seed_service import create_reference_seeded_project

    user_id = f"alias-{template_source}-{capacity}"
    record = create_reference_seeded_project(
        user_id=user_id,
        template_source=template_source,
        requested_name="Alias Safe",
        capacity_mw=capacity,
    )
    reference = _factory(template_source)
    ratio = capacity / float(reference.technical.capacity_mw)
    lines = get_active_sub_lines_for_project(record.project_id)
    ws = get_workspace_state(user_id, record.project_id)
    profile = ws.draft_snapshot["_reference_seed_profile"]

    canonical_fields = [line.replay_metadata["canonical_field"] for line in lines]
    assert len(canonical_fields) == len(set(canonical_fields))
    assert canonical_fields.count("audit_legal") == 1
    audit_line = next(line for line in lines if line.replay_metadata["canonical_field"] == "audit_legal")
    assert audit_line.parent_category_code == "C.08"
    assert profile["capex_items"]["audit_legal"]["owner_category_code"] == "C.08"

    expected = float(reference.capex.total_capex) * ratio
    assert sum(line.amount_keur for line in lines) == pytest.approx(expected)
    assert float(ws.draft_snapshot["total_capex_keur"]) == pytest.approx(expected)
    assert _materialize(user_id, record).capex.total_capex == pytest.approx(expected)


@pytest.mark.parametrize(
    ("template_source", "capacity"),
    [("generic_solar_reference", 64.0), ("generic_wind_reference", 48.0)],
)
def test_same_mw_actual_run_has_full_economic_parity(
    correction_db, template_source, capacity
):
    from app.services.reference_seed_service import create_reference_seeded_project

    user_id = f"parity-{template_source}"
    reference = _factory(template_source)
    record = create_reference_seeded_project(
        user_id=user_id,
        template_source=template_source,
        requested_name="Run Parity",
        capacity_mw=capacity,
    )
    materialized = _materialize(user_id, record)
    canonical_result = _run(template_source, reference)
    working_result = _run(template_source, materialized)

    for metric in (
        "project_irr",
        "equity_irr",
        "project_npv_keur",
        "min_dscr",
        "avg_dscr",
        "min_llcr",
    ):
        assert working_result["kpis"][metric] == pytest.approx(
            canonical_result["kpis"][metric], rel=1e-10, abs=1e-8
        )
    assert materialized.capex.total_capex == pytest.approx(reference.capex.total_capex)
    assert sum(item.y1_amount_keur for item in materialized.opex) == pytest.approx(
        sum(item.y1_amount_keur for item in reference.opex)
    )


def test_renamed_opex_override_materializes_once_survives_mw_and_resets(correction_db):
    from app.persistence.db import get_cursor
    from app.persistence.opex_sub_lines import (
        get_active_sub_lines_for_project,
        update_sub_line,
    )
    from app.services.reference_seed_service import (
        create_reference_seeded_project,
        reset_reference_seeded_lines,
        rescale_reference_seeded_project,
    )

    user_id = "opex-identity-user"
    record = create_reference_seeded_project(
        user_id=user_id,
        template_source="generic_solar_reference",
        requested_name="Immutable OPEX Identity",
        capacity_mw=64.0,
    )
    seeded = next(
        line for line in get_active_sub_lines_for_project(record.project_id)
        if line.replay_metadata["canonical_key"] == "Maintenance"
    )
    canonical_rate = seeded.replay_metadata["unit_rate_keur_per_mw"]
    with get_cursor() as cur:
        updated = update_sub_line(
            cur,
            project_id=record.project_id,
            sub_line_id=seeded.sub_line_id,
            label="My renamed maintenance description",
            amount_keur=777.0,
            inflation_pct=seeded.inflation_pct,
            comments="User override",
            row_version=seeded.updated_at,
        )
    assert updated.source == "user_override"
    assert updated.replay_metadata["canonical_key"] == "Maintenance"

    materialized = _materialize(user_id, record)
    fixed_names = [item.name for item in materialized.opex]
    assert "Maintenance" not in fixed_names
    assert fixed_names.count(updated.business_code) == 1
    assert next(item for item in materialized.opex if item.name == updated.business_code).y1_amount_keur == 777.0
    _run("generic_solar_reference", materialized)

    rescale_reference_seeded_project(user_id=user_id, project_code=record.project_code, capacity_mw=100.0)
    held = next(line for line in get_active_sub_lines_for_project(record.project_id) if line.sub_line_id == seeded.sub_line_id)
    assert held.label == "My renamed maintenance description"
    assert held.amount_keur == 777.0
    assert held.source == "user_override"

    reset_reference_seeded_lines(user_id=user_id, project_code=record.project_code)
    reset = next(line for line in get_active_sub_lines_for_project(record.project_id) if line.sub_line_id == seeded.sub_line_id)
    assert reset.label == "My renamed maintenance description"
    assert reset.amount_keur == pytest.approx(canonical_rate * 100.0)
    assert reset.source == "reference_seed"
    assert reset.replay_metadata["canonical_key"] == "Maintenance"
    rematerialized = _materialize(user_id, record)
    assert "Maintenance" not in [item.name for item in rematerialized.opex]
    assert sum(item.name == reset.business_code for item in rematerialized.opex) == 1


def test_capex_override_survives_capacity_then_reset_restores_rate(correction_db):
    from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
    from app.persistence.db import get_cursor
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.reference_seed_service import (
        create_reference_seeded_project,
        reset_reference_seeded_lines,
        rescale_reference_seeded_project,
    )

    user_id = "capex-reset-user"
    record = create_reference_seeded_project(
        user_id=user_id,
        template_source="generic_wind_reference",
        requested_name="CAPEX Reset",
        capacity_mw=48.0,
    )
    line = get_active_sub_lines_for_project(record.project_id)[0]
    rate = line.replay_metadata["unit_rate_keur_per_mw"]
    with get_cursor() as cur:
        cur.execute(
            "UPDATE capex_sub_lines SET amount_keur=999, source='user_override' WHERE sub_line_id=?",
            (line.sub_line_id,),
        )
    rescale_reference_seeded_project(user_id=user_id, project_code=record.project_code, capacity_mw=96.0)
    held = next(x for x in get_active_sub_lines_for_project(record.project_id) if x.sub_line_id == line.sub_line_id)
    assert held.amount_keur == 999.0
    ws = get_workspace_state(user_id, record.project_id)
    assert float(ws.draft_snapshot["total_capex_keur"]) == pytest.approx(
        sum(x.amount_keur for x in get_active_sub_lines_for_project(record.project_id))
    )
    reset_reference_seeded_lines(user_id=user_id, project_code=record.project_code)
    restored = next(x for x in get_active_sub_lines_for_project(record.project_id) if x.sub_line_id == line.sub_line_id)
    assert restored.amount_keur == pytest.approx(rate * 96.0)
    assert restored.source == "reference_seed"


def test_two_working_copies_and_reference_remain_independent(correction_db):
    from app.persistence.db import get_cursor
    from app.persistence.opex_sub_lines import get_active_sub_lines_for_project
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.services.project_library_service import ensure_reference_models

    ensure_reference_models()
    reference = get_reference_by_template_source("generic_solar_reference")
    reference_before = dict(reference.baseline_snapshot)
    first = create_reference_seeded_project(
        user_id="independent-user", template_source="generic_solar_reference",
        requested_name="First Copy", capacity_mw=64.0,
    )
    second = create_reference_seeded_project(
        user_id="independent-user", template_source="generic_solar_reference",
        requested_name="Second Copy", capacity_mw=64.0,
    )
    first_line = get_active_sub_lines_for_project(first.project_id)[0]
    second_before = [(x.label, x.amount_keur, x.source) for x in get_active_sub_lines_for_project(second.project_id)]
    with get_cursor() as cur:
        cur.execute(
            "UPDATE opex_sub_lines SET label='Changed only here', amount_keur=1, source='user_override' "
            "WHERE sub_line_id=?",
            (first_line.sub_line_id,),
        )
    assert [(x.label, x.amount_keur, x.source) for x in get_active_sub_lines_for_project(second.project_id)] == second_before
    reference_after = get_reference_by_template_source("generic_solar_reference")
    assert reference_after.baseline_snapshot == reference_before
