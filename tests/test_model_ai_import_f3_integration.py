"""Integrated PR #239: canonical F3 scalar authority × C0 atomic Import.

Only synthetic Working Copies. Real F3 activation and canonical model Runs;
no golden refresh, no financing-engine mocks, no separate financial writer.
"""
from __future__ import annotations

import json
from io import BytesIO

import pytest
from openpyxl import Workbook

from app.model_import.intake import extract_proposals
from app.model_import.review import (
    resolve_review, seal_approved, seal_preview, unseal_approved,
)
from app.persistence.run_history_repository import get_run_history
from app.persistence.workspace_repository import get_workspace_state
from app.services.export_service import resolve_canonical_last_run_from_workspace
from app.workbook.input_set import ProjectInputSet
from app.workbook.registry import WORKBOOK
from app.workbook.update_service import (
    BatchApplyError, StaleContentError, WorkbookUpdateService,
)
from app.workbook.workbook_identity import assemble_consistent_for_get
from tests.test_model_decision_workspace_v2 import env
from tests.test_model_financing_f2 import run, save
from tests.test_model_financing_f3_workspace import (
    collection_for_inputs, state as f3_state,
)
from app.workbook.multisenior_config import (
    FIELD_ID as F3_FIELD, SNAPSHOT_KEY as F3_KEY, parse_state,
)

OWNER = "decision-user"
F3_FORBIDDEN = "debt.senior.interest_rate_pct"


def _ws(project):
    return get_workspace_state(OWNER, project.project_id)


def _hash(project):
    return assemble_consistent_for_get(OWNER, project.project_id, WORKBOOK.version).composite_hash


def _evidence(project):
    ws = _ws(project)
    return (
        ws.draft_snapshot, ws.saved_snapshot, ws.dirty,
        ws.active_scenario_id, ws.active_scenario_name,
        ws.last_runtime_snapshot_id, ws.last_runtime_identity,
        ws.last_runtime_summary, _hash(project),
        tuple((x.history_id, x.runtime_snapshot_id) for x in get_run_history(
            OWNER, project.project_id)),
        ws.draft_snapshot.get(F3_KEY),
    )


def _batch(project, fields, *, owner=OWNER, content_hash=None,
           scenario_id="__current__", project_record=None):
    ws = _ws(project)
    return WorkbookUpdateService.apply_batch_draft_update(
        ws=ws, updates=list(fields),
        content_hash=content_hash if content_hash is not None else _hash(project),
        workbook_version=WORKBOOK.version,
        expected_scenario_id=ws.active_scenario_id if scenario_id == "__current__" else scenario_id,
        project_record=project if project_record is None else project_record,
        actor_user_id=owner,
    )


def _active(env, kind="solar", *, active=True):
    project = env.create(kind)
    pi = ProjectInputSet.from_snapshot(_ws(project).draft_snapshot).to_projectinputs()
    raw = f3_state(active=active, collection=collection_for_inputs(pi))
    response = save(env, project, raw, field=F3_FIELD)
    assert response.status_code == 200
    assert "field-error-banner" not in response.text, response.text[:1500]
    assert bool(parse_state(_ws(project).draft_snapshot[F3_KEY])["scopes"]["base"]["activation"]) == active
    return project


def test_active_f3_atomic_rollback_revenue_capex_forbidden_debt(env):
    project = _active(env)
    before = _evidence(project)
    with pytest.raises(ValueError, match="F3_COMPETING_FINANCING_EDITOR_REJECTED"):
        _batch(project, [
            ("revenue.ppa.index", "2"),
            ("capex.C.grid_connection", "1"),
            (F3_FORBIDDEN, "6"),
        ])
    assert _evidence(project) == before


def test_active_f3_structured_collection_rejected_at_batch_backend(env):
    project = _active(env)
    before = _evidence(project)
    payload = _ws(project).draft_snapshot[F3_KEY]
    with pytest.raises(BatchApplyError, match="BATCH_F3_COLLECTION_EDITOR_ONLY"):
        _batch(project, [("revenue.ppa.index", "2"), (F3_FIELD, payload)])
    assert _evidence(project) == before


def test_active_f3_25_fields_last_forbidden_full_rollback(env):
    from app.workbook.specs import BindingStatus, FieldKind, SourceOfTruth
    project = _active(env)
    specs = [
        f for f in WORKBOOK.all_fields()
        if f.field_id.startswith(("capex.", "opex."))
        and f.binding_status == BindingStatus.BOUND
        and f.kind == FieldKind.INPUT
        and f.source_of_truth == SourceOfTruth.INPUT_SET
        and f.editable and f.persisted
        and (f.unit or "").startswith("kEUR")
    ][:24]
    assert len(specs) == 24
    before = _evidence(project)
    with pytest.raises(ValueError, match="F3_COMPETING_FINANCING_EDITOR_REJECTED"):
        _batch(project, [(x.field_id, "1") for x in specs] + [(F3_FORBIDDEN, "6")])
    assert _evidence(project) == before


def test_active_f3_unrelated_batch_succeeds_preserves_facility_authority(env):
    project = _active(env)
    prior = _ws(project).draft_snapshot[F3_KEY]
    _batch(project, [
        ("revenue.ppa.index", "2"),
        ("project_setup.technical.p50_hours", "1850"),
    ])
    ws = _ws(project)
    assert ws.draft_snapshot[F3_KEY] == prior
    assert ws.draft_snapshot["rev_ppa_index"] == "2.0"


def test_inactive_f3_proposal_is_not_modified_by_normal_import(env):
    project = _active(env, active=False)
    original = _ws(project).draft_snapshot[F3_KEY]
    _batch(project, [("project_setup.technical.p50_hours", "1900")])
    assert _ws(project).draft_snapshot[F3_KEY] == original


def test_scope_owner_stale_duplicate_guards_in_F3_transaction(env):
    project = _active(env)
    before = _evidence(project)
    for overrides in (
        {"scenario_id": "not-the-selected-scenario"},
        {"owner": "synthetic-foreign-user"},
        {"content_hash": "0" * 64},
    ):
        with pytest.raises(ValueError):
            _batch(project, [("revenue.ppa.index", "2")], **overrides)
        assert _evidence(project) == before
    with pytest.raises(BatchApplyError, match="BATCH_DUPLICATE_FIELD"):
        _batch(project, [
            ("revenue.ppa.index", "2"), ("revenue.ppa.index", "3")])
    assert _evidence(project) == before


def _review_apply(project, field_id: str, value: str, unit: str, *, xlsx=False):
    ws = _ws(project)
    if xlsx:
        workbook = Workbook()
        page = workbook.active
        page.title = "Assumptions"
        page.append(["Assumption", "Value", "Unit"])
        page.append([field_id, float(value), unit])
        out = BytesIO()
        workbook.save(out)
        file_data, filename = out.getvalue(), "synthetic.xlsx"
    else:
        file_data = (
            f"Assumption,Value,Unit\n{field_id},{value},{unit}\n"
        ).encode()
        filename = "synthetic.csv"

    record = extract_proposals(
        file_data, filename,
        project_type=project.project_type or "",
        template_source=project.template_source or "",
    )
    assert len(record["proposals"]) == 1
    proposal = record["proposals"][0]
    assert proposal["status"] == "ready", proposal
    token = seal_preview(
        owner=OWNER, project_id=project.project_id,
        scenario_id=ws.active_scenario_id,
        content_hash=_hash(project), workbook_version=WORKBOOK.version,
        digest="1" * 64, proposals=record["proposals"],
    )
    preview, approved = resolve_review(
        ticket=token, owner=OWNER, project_id=project.project_id,
        selections={
            "keep_0": "on", "field_0": field_id,
            "unit_0": unit, "manual_0": "",
        },
        project_type=project.project_type or "",
        template_source=project.template_source or "",
    )
    signed = unseal_approved(
        seal_approved(preview, approved),
        owner=OWNER, project_id=project.project_id,
    )
    assert signed["scenario_id"] == ws.active_scenario_id
    return _batch(
        project,
        [(x["field_id"], x["value"]) for x in signed["approved"]],
        content_hash=signed["content_hash"],
        scenario_id=signed["scenario_id"],
    )


@pytest.mark.parametrize("kind,field_id,value,unit,xlsx", [
    ("solar", "project_setup.technical.p50_hours", "1840", "h", False),
    ("wind", "project_setup.technical.p50_hours", "2800", "h", True),
    ("data_center", "revenue.data_center.occupancy_y1", "62", "%", False),
    ("ev_charging", "revenue.ev_charging.charging_price", "0.38", "EUR/kWh", True),
])
def test_four_vertical_real_baseline_import_stale_rerun_current_history_export(
        env, kind, field_id, value, unit, xlsx):
    project = _active(env, kind) if kind in ("solar", "wind") else env.create(kind)
    baseline, old = run(env, project)
    baseline_hash = _hash(project)
    initial_history = tuple(get_run_history(OWNER, project.project_id))
    old_identity = baseline.last_runtime_identity
    old_id = baseline.last_runtime_snapshot_id
    old_summary = baseline.last_runtime_summary
    old_f3 = baseline.draft_snapshot.get(F3_KEY)
    old_facilities = (
        old.runtime_summary.get("financing_evidence", {}).get("facility_schedules")
        if kind in ("solar", "wind") else None
    )
    _review_apply(project, field_id, value, unit, xlsx=xlsx)
    stale = _ws(project)
    changed_raw_keys = {
        key for key in set(baseline.draft_snapshot) | set(stale.draft_snapshot)
        if baseline.draft_snapshot.get(key) != stale.draft_snapshot.get(key)
    }
    assert changed_raw_keys == {WORKBOOK.field(field_id).snapshot_key}, changed_raw_keys
    assert stale.dirty
    assert stale.last_runtime_snapshot_id == old_id
    assert stale.last_runtime_identity == old_identity
    assert stale.last_runtime_summary == old_summary
    assert _hash(project) != baseline_hash
    assert len(get_run_history(OWNER, project.project_id)) == len(initial_history)
    assert stale.draft_snapshot.get(F3_KEY) == old_f3
    original_export = resolve_canonical_last_run_from_workspace(project, OWNER, stale)
    assert original_export is not None
    if old_facilities is not None:
        assert original_export.project_inputs.financing_collection.content_digest() == (
            old.runtime_summary["financing_evidence"]["collection_digest"]
        )
    current, newer = run(env, project)
    assert not current.dirty
    assert current.last_runtime_snapshot_id != old_id
    assert len(get_run_history(OWNER, project.project_id)) == len(initial_history) + 1
    assert tuple(get_run_history(OWNER, project.project_id))[-1].runtime_snapshot_id is not None
    assert current.draft_snapshot.get(F3_KEY) == old_f3
    # Reapplying an unchanged value cannot create synthetic STALE.
    _batch(project, [(field_id, ProjectInputSet.from_snapshot(
        current.draft_snapshot).get(field_id).__str__())])
    assert not _ws(project).dirty
