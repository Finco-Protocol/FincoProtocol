"""Workflow C0 — the atomic intake contract is an independent financial gate.

Synthetic working copies only.  Incomplete snapshots intentionally stay
incomplete; the update contract must not invent missing model assumptions.
"""
from __future__ import annotations

import pytest

from app.persistence import db
from app.persistence.db import init_db
from app.persistence.projects_repository import save_project
from app.persistence.workspace_repository import get_workspace_state, save_workspace_state
from app.workbook.registry import WORKBOOK
from app.workbook.update_service import (
    BatchApplyError, FieldValidationError, StaleContentError,
    WorkbookUpdateService,
)
from app.workbook.workbook_identity import assemble_consistent_for_get

USER = "synthetic-c0-owner"
CODE = "synthetic-c0-solar"
BASE = {
    "active_project": CODE,
    "template_source": "generic_solar_reference",
    "project_origin": "working_copy",
    "project_type": "solar_pv",
    "p50_hours": "1700",
    "construction_months": "18",
    "horizon_years": "25",
}


@pytest.fixture()
def working_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "synthetic-c0.db"))
    init_db()
    project = save_project(
        user_id=USER, project_code=CODE, project_name="Synthetic Solar",
        source_project_template="generic_solar_reference",
        template_source="generic_solar_reference",
        project_type="Solar", project_origin="working_copy",
        project_role="working_copy",
    )
    save_workspace_state(
        user_id=USER, project_id=project.project_id, project_code=CODE,
        draft_snapshot=BASE, saved_snapshot=BASE,
        last_runtime_snapshot=BASE, last_runtime_summary={"old_run": True},
        last_runtime_snapshot_id="synthetic-last-run",
    )
    return project


def _hash(project):
    return assemble_consistent_for_get(USER, project.project_id, WORKBOOK.version).composite_hash


def _apply(project, updates, **override):
    ws = get_workspace_state(USER, project.project_id)
    options = {
        "ws": ws, "updates": updates,
        "content_hash": _hash(project),
        "workbook_version": WORKBOOK.version,
        "expected_scenario_id": ws.active_scenario_id,
        "project_record": project,
        "actor_user_id": USER,
    }
    options.update(override)
    return WorkbookUpdateService.apply_batch_draft_update(**options)


def test_one_and_multiple_fields_saved_in_one_cas(working_copy):
    p = working_copy
    _apply(p, [("project_setup.technical.p50_hours", "1900")])
    _apply(p, [
        ("project_setup.technical.construction_months", "20"),
        ("project_setup.technical.horizon_years", "28"),
    ])
    ws = get_workspace_state(USER, p.project_id)
    assert ws.draft_snapshot["p50_hours"] == "1900.0"
    assert ws.draft_snapshot["construction_months"] == "20"
    assert ws.draft_snapshot["horizon_years"] == "28"
    assert ws.saved_snapshot == BASE
    assert ws.last_runtime_snapshot_id == "synthetic-last-run"
    assert ws.last_runtime_summary == {"old_run": True}
    assert ws.dirty
    assert ws.draft_snapshot != ws.saved_snapshot


def test_invalid_last_field_rolls_back_everything(working_copy):
    p = working_copy
    before = get_workspace_state(USER, p.project_id)
    with pytest.raises(FieldValidationError):
        _apply(p, [
            ("project_setup.technical.p50_hours", "1850"),
            ("project_setup.technical.construction_months", "19"),
            ("project_setup.technical.horizon_years", "0"),
        ])
    after = get_workspace_state(USER, p.project_id)
    assert after.draft_snapshot == before.draft_snapshot
    assert after.saved_snapshot == before.saved_snapshot
    assert after.last_runtime_snapshot_id == before.last_runtime_snapshot_id
    assert after.dirty == before.dirty


def test_duplicate_and_unauthorized_cascade_fail_closed(working_copy):
    p = working_copy
    before = get_workspace_state(USER, p.project_id)
    with pytest.raises(BatchApplyError, match="BATCH_DUPLICATE_FIELD"):
        _apply(p, [
            ("project_setup.technical.p50_hours", "1900"),
            ("project_setup.technical.p50_hours", "2100"),
        ])
    with pytest.raises(BatchApplyError, match="project_setup.technical.capacity_mw"):
        _apply(p, [("project_setup.technical.capacity_mw", "50")])
    assert get_workspace_state(USER, p.project_id).draft_snapshot == before.draft_snapshot


def test_concurrent_content_token_and_scenario_switch(working_copy):
    p = working_copy
    stale = _hash(p)
    _apply(p, [("project_setup.technical.p50_hours", "2500")])
    with pytest.raises(StaleContentError):
        _apply(
            p, [("project_setup.technical.construction_months", "24")],
            content_hash=stale,
        )
    with pytest.raises(StaleContentError, match="BATCH_SCENARIO_MISMATCH"):
        _apply(
            p, [("project_setup.technical.construction_months", "24")],
            expected_scenario_id="another-scenario",
        )
    assert get_workspace_state(USER, p.project_id).draft_snapshot["construction_months"] == "18"


def test_user_owner_mismatch_before_any_write(working_copy):
    p = working_copy
    with pytest.raises(BatchApplyError, match="BATCH_OWNER_MISMATCH"):
        _apply(p, [("project_setup.technical.p50_hours", "2100")],
               actor_user_id="foreign-user")
    assert get_workspace_state(USER, p.project_id).draft_snapshot["p50_hours"] == "1700"


def test_protected_reference_rejected(working_copy):
    p = working_copy
    save_project(
        user_id=USER, project_code=CODE, project_name="Synthetic Solar",
        source_project_template="generic_solar_reference",
        template_source="generic_solar_reference",
        project_type="Solar", project_origin="factory_template",
        project_role="reference", is_protected=True,
    )
    from app.persistence.projects_repository import get_project_by_code
    locked = get_project_by_code(USER, CODE)
    from app.workbook.update_service import ProtectedReferenceError
    with pytest.raises(ProtectedReferenceError):
        _apply(locked, [("project_setup.technical.p50_hours", "2500")])


def test_idempotent_same_value_preserves_current(working_copy):
    p = working_copy
    ws_before = get_workspace_state(USER, p.project_id)
    _apply(p, [("project_setup.technical.construction_months", "18")])
    ws_after = get_workspace_state(USER, p.project_id)
    assert ws_after.draft_snapshot == ws_before.draft_snapshot
    assert ws_after.dirty == ws_before.dirty
    assert ws_after.last_runtime_snapshot_id == ws_before.last_runtime_snapshot_id


def test_25_approved_fields_and_25th_invalid_rolls_back(working_copy):
    from app.workbook.specs import BindingStatus, FieldKind, SourceOfTruth
    p = working_copy
    specs = [
        field for field in WORKBOOK.all_fields()
        if field.field_id.startswith(("capex.", "opex."))
        and field.binding_status == BindingStatus.BOUND
        and field.kind == FieldKind.INPUT
        and field.source_of_truth == SourceOfTruth.INPUT_SET
        and field.editable
        and field.persisted
        and (field.unit or "").startswith("kEUR")
    ][:25]
    assert len(specs) == 25
    updates = [(s.field_id, "1") for s in specs]
    before = get_workspace_state(USER, p.project_id)
    with pytest.raises(FieldValidationError):
        _apply(p, updates[:-1] + [("project_setup.technical.horizon_years", "-1")])
    assert get_workspace_state(USER, p.project_id).draft_snapshot == before.draft_snapshot
    result = _apply(p, updates)
    assert all(result.get(s.field_id) == 1 for s in specs)
    assert get_workspace_state(USER, p.project_id).last_runtime_snapshot_id == "synthetic-last-run"



@pytest.mark.parametrize("technology,template,input_type,field_id,raw", [
    ("Solar", "generic_solar_reference", "solar_pv",
     "project_setup.technical.p50_hours", "1900"),
    ("Wind", "generic_wind_reference", "wind_onshore",
     "project_setup.technical.p50_hours", "2850"),
    ("Data Center", "generic_data_center_reference", "data_center",
     "revenue.data_center.occupancy_y1", "62"),
    ("EV Charging", "generic_ev_charging_reference", "ev_charging",
     "revenue.ev_charging.charging_price", "0.38"),
])
def test_four_vertical_atomic_scalar_gates(
        working_copy, technology, template, input_type, field_id, raw):
    """Every supported vertical shares the one owner-scoped C0 writer."""
    from app.persistence.projects_repository import save_project
    from app.persistence.workspace_repository import save_workspace_state
    code = technology.lower().replace(" ", "-") + "-synthetic-c0"
    project = save_project(
        user_id=USER, project_code=code, project_name=code,
        source_project_template=template, template_source=template,
        project_type=technology, project_origin="working_copy",
        project_role="working_copy",
    )
    initial = {
        "active_project": code, "template_source": template,
        "project_origin": "working_copy", "project_type": input_type,
    }
    save_workspace_state(
        user_id=USER, project_id=project.project_id,
        project_code=code, draft_snapshot=initial, saved_snapshot=initial,
    )
    initial_hash = _hash(project)
    WorkbookUpdateService.apply_batch_draft_update(
        ws=get_workspace_state(USER, project.project_id),
        updates=[(field_id, raw)], content_hash=initial_hash,
        workbook_version=WORKBOOK.version, expected_scenario_id=None,
        project_record=project, actor_user_id=USER,
    )
    current = get_workspace_state(USER, project.project_id)
    assert WORKBOOK.field(field_id).snapshot_key in current.draft_snapshot
    assert current.saved_snapshot == initial
    assert _hash(project) != initial_hash
