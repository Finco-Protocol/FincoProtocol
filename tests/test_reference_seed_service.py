from __future__ import annotations

import json

import pytest


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    from app.persistence import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "reference-seed.db"))
    db.init_db()
    yield


@pytest.mark.parametrize(
    ("template_source", "reference_capacity", "requested_capacity"),
    [
        ("generic_solar_reference", 64.0, 64.0),
        ("generic_wind_reference", 48.0, 96.0),
    ],
)
def test_reference_seed_creation_preserves_lineage_and_scales_per_mw(
    seeded_db, template_source, reference_capacity, requested_capacity
):
    from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
    from app.persistence.opex_sub_lines import get_active_sub_lines_for_project as get_opex
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.reference_seed_service import create_reference_seeded_project

    record = create_reference_seeded_project(
        user_id="seed-test-user",
        template_source=template_source,
        requested_name="Reference Project",
        capacity_mw=requested_capacity,
    )
    reference = get_reference_by_template_source(template_source)
    assert record.project_role == "working_copy"
    assert record.source_project_id == reference.project_id
    assert record.is_protected is False
    assert record.is_readonly is False

    ws = get_workspace_state("seed-test-user", record.project_id)
    profile = ws.draft_snapshot["_reference_seed_profile"]
    assert float(ws.draft_snapshot["capacity_mw"]) == requested_capacity
    assert profile["reference_capacity_mw"] == reference_capacity
    assert profile["seed_capacity_mw"] == requested_capacity
    assert "PER_MW" in profile["scaling_modes"]

    capex_lines = get_active_sub_lines_for_project(record.project_id)
    opex_lines = get_opex(record.project_id)
    assert capex_lines and opex_lines
    assert all(line.source == "reference_seed" for line in capex_lines + opex_lines)
    for line in capex_lines:
        rate = line.replay_metadata["unit_rate_keur_per_mw"]
        assert line.amount_keur == pytest.approx(rate * requested_capacity)
    for line in opex_lines:
        rate = line.replay_metadata["unit_rate_keur_per_mw"]
        assert line.amount_keur == pytest.approx(rate * requested_capacity)
        assert line.replay_metadata["canonical_key"] in profile["opex_items"]


def test_capacity_rescale_preserves_user_override(seeded_db):
    from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
    from app.persistence.db import get_cursor
    from app.persistence.opex_sub_lines import get_active_sub_lines_for_project as get_opex
    from app.services.reference_seed_service import (
        create_reference_seeded_project,
        rescale_reference_seeded_project,
    )

    record = create_reference_seeded_project(
        user_id="override-user",
        template_source="generic_solar_reference",
        requested_name="Override Project",
        capacity_mw=64.0,
    )
    capex = get_active_sub_lines_for_project(record.project_id)
    opex = get_opex(record.project_id)
    held_capex = capex[0]
    held_opex = opex[0]
    with get_cursor() as cur:
        cur.execute(
            "UPDATE capex_sub_lines SET amount_keur=1234, source='user_override' WHERE sub_line_id=?",
            (held_capex.sub_line_id,),
        )
        cur.execute(
            "UPDATE opex_sub_lines SET amount_keur=321, source='user_override' WHERE sub_line_id=?",
            (held_opex.sub_line_id,),
        )

    rescale_reference_seeded_project(
        user_id="override-user", project_code=record.project_code, capacity_mw=128.0
    )
    capex_after = {x.sub_line_id: x for x in get_active_sub_lines_for_project(record.project_id)}
    opex_after = {x.sub_line_id: x for x in get_opex(record.project_id)}
    assert capex_after[held_capex.sub_line_id].amount_keur == 1234
    assert opex_after[held_opex.sub_line_id].amount_keur == 321
    assert any(x.amount_keur != y.amount_keur for x, y in zip(capex[1:], list(capex_after.values())[1:]))


def test_storage_is_not_supported_by_reference_seed_service(seeded_db):
    from app.services.reference_seed_service import create_reference_seeded_project

    with pytest.raises(ValueError, match="Solar and Wind only"):
        create_reference_seeded_project(
            user_id="storage-user",
            template_source="generic_storage_reference",
            requested_name="No Storage",
            capacity_mw=10.0,
        )


@pytest.mark.parametrize(
    ("template_source", "capacity"),
    [("generic_solar_reference", 64.0), ("generic_wind_reference", 48.0)],
)
def test_same_mw_materialization_reproduces_reference_economic_inputs(
    seeded_db, template_source, capacity
):
    from app.input_adapter import build_projectinputs_from_snapshot
    from app.persistence.workspace_repository import get_workspace_state
    from app.project_factories import create_generic_solar_reference, create_generic_wind_reference
    from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
    from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex
    from app.services.reference_seed_service import create_reference_seeded_project

    reference = (create_generic_solar_reference() if "solar" in template_source else create_generic_wind_reference())
    record = create_reference_seeded_project(
        user_id=f"same-mw-{template_source}", template_source=template_source,
        requested_name="Same MW", capacity_mw=capacity,
    )
    ws = get_workspace_state(f"same-mw-{template_source}", record.project_id)
    materialized = build_projectinputs_from_snapshot(ws.draft_snapshot)
    capex = apply_user_sub_lines_replacing_base(materialized.capex, project_id=record.project_id)
    opex = apply_user_sub_lines_to_opex(materialized.opex, project_id=record.project_id)
    assert capex.total_capex == pytest.approx(reference.capex.total_capex)
    assert sum(x.y1_amount_keur for x in opex) == pytest.approx(sum(x.y1_amount_keur for x in reference.opex))
    assert materialized.financing.target_dscr == reference.financing.target_dscr
