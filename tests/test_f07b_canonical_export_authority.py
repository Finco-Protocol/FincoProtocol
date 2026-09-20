"""F07-B: Canonical Export Authority and Run-Bound Lineage tests.

Verifies:
- EXPORT_AUTHORITY_* constants exist
- Factory path → FACTORY_REFERENCE authority in CSV rows
- PREVIEW_WORKING authority propagated through export service
- working_changed_since_run is "true" when snapshots differ, "false" when equal
- run_id and run_at in CSV rows
- export_authority in workbook bundle
- _metric_value OPEX no longer falls back to snapshot
- Authority mode in both CSV and workbook metadata
- No financial value changes (IRR/revenue/EBITDA unchanged)
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_export_authority_constants_exist():
    from app.services.export_service import (
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        EXPORT_AUTHORITY_FACTORY_REFERENCE,
        EXPORT_AUTHORITY_PREVIEW_WORKING,
    )
    assert EXPORT_AUTHORITY_CANONICAL_LAST_RUN == "CANONICAL_LAST_RUN"
    assert EXPORT_AUTHORITY_FACTORY_REFERENCE == "FACTORY_REFERENCE"
    assert EXPORT_AUTHORITY_PREVIEW_WORKING == "PREVIEW_WORKING"


# ---------------------------------------------------------------------------
# ResolvedExportAuthority fields
# ---------------------------------------------------------------------------


def test_resolved_export_authority_has_new_fields():
    from app.services.export_service import (
        ResolvedExportAuthority,
        EXPORT_AUTHORITY_FACTORY_REFERENCE,
    )
    auth = ResolvedExportAuthority(
        project_inputs=None,
        current_snapshot=None,
        runtime_origin=None,
    )
    assert auth.authority_mode == EXPORT_AUTHORITY_FACTORY_REFERENCE
    assert auth.run_id is None
    assert auth.run_at is None
    assert auth.working_changed_since_run is None


# ---------------------------------------------------------------------------
# Runtime summary CSV — factory path → FACTORY_REFERENCE
# ---------------------------------------------------------------------------


def test_factory_path_runtime_summary_authority_mode():
    from app.export.runtime_summary import build_runtime_summary_rows

    rows = build_runtime_summary_rows("generic_wind_reference")
    assert rows, "expected at least one row"
    for row in rows:
        assert row["export_authority"] == "FACTORY_REFERENCE"


def test_factory_path_runtime_summary_run_fields_not_applicable():
    from app.export.runtime_summary import build_runtime_summary_rows

    rows = build_runtime_summary_rows("generic_wind_reference")
    for row in rows:
        assert row["run_id"] == "not_applicable"
        assert row["run_at"] == "not_applicable"
        assert row["working_changed_since_run"] == "not_applicable"


# ---------------------------------------------------------------------------
# working_changed_since_run encoding
# ---------------------------------------------------------------------------


def test_working_changed_since_run_true():
    from app.export.runtime_summary import build_runtime_summary_rows

    rows = build_runtime_summary_rows(
        "generic_wind_reference",
        working_changed_since_run=True,
    )
    for row in rows:
        assert row["working_changed_since_run"] == "true"


def test_working_changed_since_run_false():
    from app.export.runtime_summary import build_runtime_summary_rows

    rows = build_runtime_summary_rows(
        "generic_wind_reference",
        working_changed_since_run=False,
    )
    for row in rows:
        assert row["working_changed_since_run"] == "false"


def test_working_changed_since_run_none_is_not_applicable():
    from app.export.runtime_summary import build_runtime_summary_rows

    rows = build_runtime_summary_rows(
        "generic_wind_reference",
        working_changed_since_run=None,
    )
    for row in rows:
        assert row["working_changed_since_run"] == "not_applicable"


# ---------------------------------------------------------------------------
# run_id and run_at pass-through
# ---------------------------------------------------------------------------


def test_run_id_and_run_at_pass_through():
    from app.export.runtime_summary import build_runtime_summary_rows

    rows = build_runtime_summary_rows(
        "generic_wind_reference",
        run_id="run-abc-123",
        run_at="2026-01-01T00:00:00+00:00",
    )
    for row in rows:
        assert row["run_id"] == "run-abc-123"
        assert row["run_at"] == "2026-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# export_authority pass-through for explicit authority
# ---------------------------------------------------------------------------


def test_explicit_export_authority_preview_working():
    from app.export.runtime_summary import build_runtime_summary_rows

    rows = build_runtime_summary_rows(
        "generic_wind_reference",
        export_authority="PREVIEW_WORKING",
    )
    for row in rows:
        assert row["export_authority"] == "PREVIEW_WORKING"


# ---------------------------------------------------------------------------
# RUNTIME_SUMMARY_COLUMNS includes new columns
# ---------------------------------------------------------------------------


def test_runtime_summary_columns_include_new_fields():
    from app.export.runtime_summary import RUNTIME_SUMMARY_COLUMNS

    for col in ("export_authority", "working_changed_since_run", "run_id", "run_at"):
        assert col in RUNTIME_SUMMARY_COLUMNS, f"missing column: {col}"
    # notes must come after the new columns
    assert RUNTIME_SUMMARY_COLUMNS.index("notes") > RUNTIME_SUMMARY_COLUMNS.index("run_at")


# ---------------------------------------------------------------------------
# WorkbookExportBundle has new fields
# ---------------------------------------------------------------------------


def test_workbook_export_bundle_has_authority_fields():
    from app.export.institutional_workbook import WorkbookExportBundle
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(WorkbookExportBundle)}
    for name in ("export_authority", "working_changed_since_run", "run_id", "run_at"):
        assert name in field_names, f"WorkbookExportBundle missing field: {name}"


def test_workbook_bundle_factory_default_authority():
    from app.export.institutional_workbook import _build_export_bundle

    bundle = _build_export_bundle("generic_wind_reference")
    assert bundle.export_authority == "FACTORY_REFERENCE"
    assert bundle.working_changed_since_run == "not_applicable"
    assert bundle.run_id == "not_applicable"
    assert bundle.run_at == "not_applicable"


# ---------------------------------------------------------------------------
# _metric_value OPEX no longer falls back to snapshot
# ---------------------------------------------------------------------------


def test_metric_value_opex_no_snapshot_fallback():
    """OPEX must come from last_run_summary only, never from snapshot fallback."""
    from app.persistence._helpers import _metric_value

    class FakeRecord:
        snapshot = {"opex_y1_keur": 999.0}
        last_run_summary = {}  # no total_opex_keur

    record = FakeRecord()
    result = _metric_value(record, "OPEX")
    # Must be None (no fallback to snapshot), NOT 999.0
    assert result is None, f"OPEX must not fall back to snapshot; got {result}"


def test_metric_value_opex_uses_summary():
    from app.persistence._helpers import _metric_value

    class FakeRecord:
        snapshot = {"opex_y1_keur": 999.0}
        last_run_summary = {"total_opex_keur": 1234.5}

    record = FakeRecord()
    result = _metric_value(record, "OPEX")
    assert result == 1234.5


# ---------------------------------------------------------------------------
# snapshots_equal and working_changed_since_run logic in resolve_export_authority
# ---------------------------------------------------------------------------


def test_snapshots_equal_identical():
    from app.persistence._helpers import snapshots_equal

    assert snapshots_equal({"a": 1}, {"a": 1}) is True


def test_snapshots_equal_different():
    from app.persistence._helpers import snapshots_equal

    assert snapshots_equal({"a": 1}, {"a": 2}) is False


def test_snapshots_equal_none_equivalence():
    from app.persistence._helpers import snapshots_equal

    assert snapshots_equal(None, {}) is True
    assert snapshots_equal({}, None) is True
    assert snapshots_equal(None, None) is True


# ---------------------------------------------------------------------------
# export_metadata build_export_metadata includes authority fields
# ---------------------------------------------------------------------------


def test_build_export_metadata_includes_authority():
    from app.export_metadata import build_export_metadata

    meta = build_export_metadata(
        project_id="test-proj",
        export_authority="CANONICAL_LAST_RUN",
        working_changed_since_run="false",
    )
    assert meta["export_authority"] == "CANONICAL_LAST_RUN"
    assert meta["working_changed_since_run"] == "false"


def test_build_export_metadata_authority_default():
    from app.export_metadata import build_export_metadata

    meta = build_export_metadata(project_id="test-proj")
    assert meta["export_authority"] == "FACTORY_REFERENCE"
    assert meta["working_changed_since_run"] == "not_applicable"


# ---------------------------------------------------------------------------
# metadata_rows order: export_authority and working_changed_since_run
# ---------------------------------------------------------------------------


def test_metadata_rows_includes_authority_fields():
    from app.export_metadata import build_export_metadata, metadata_rows

    meta = build_export_metadata(
        project_id="test-proj",
        export_authority="PREVIEW_WORKING",
        working_changed_since_run="true",
    )
    rows = metadata_rows(meta)
    labels = [label for label, _ in rows]
    assert "Export authority" in labels
    assert "Working changed since run" in labels


# ---------------------------------------------------------------------------
# No financial value change: factory reference IRR is still numeric
# ---------------------------------------------------------------------------


def test_factory_irr_not_changed_by_f07b():
    from app.export.runtime_summary import build_runtime_summary_rows

    rows = build_runtime_summary_rows("generic_wind_reference")
    irr_row = next((r for r in rows if r["metric"] == "project_irr"), None)
    assert irr_row is not None
    val = float(irr_row["value"])
    assert val > 0.0, "project_irr must still be a positive number"


# ---------------------------------------------------------------------------
# State-transition tests — authority mode dispatch and identity correctness
# ---------------------------------------------------------------------------


def _make_ws(
    *,
    draft_snapshot=None,
    last_runtime_snapshot=None,
    last_runtime_at=None,
    last_runtime_scenario_id=None,
    last_runtime_snapshot_id=None,
    active_scenario_id=None,
    active_scenario_name=None,
    any_run_committed=False,
):
    """Build a minimal WorkspaceStateRecord-like stub for testing."""

    class FakeWS:
        pass

    ws = FakeWS()
    ws.draft_snapshot = draft_snapshot or {}
    ws.last_runtime_snapshot = last_runtime_snapshot
    ws.last_runtime_at = last_runtime_at
    ws.last_runtime_scenario_id = last_runtime_scenario_id
    ws.last_runtime_snapshot_id = last_runtime_snapshot_id
    ws.active_scenario_id = active_scenario_id
    ws.active_scenario_name = active_scenario_name
    ws.any_run_committed = any_run_committed
    return ws


def _make_project_record(project_origin="user_created", project_id="proj-1"):
    class FakeProjectRecord:
        pass

    pr = FakeProjectRecord()
    pr.project_origin = project_origin
    pr.project_id = project_id
    return pr


# Test A: unknown authority_mode raises ValueError (FAIL CLOSED)

def test_unknown_authority_mode_fails_closed(monkeypatch):
    from app.services.export_service import resolve_export_authority
    import app.persistence.workspace_repository as ws_repo

    ws = _make_ws(draft_snapshot={"a": 1}, any_run_committed=True)
    monkeypatch.setattr(ws_repo, "get_workspace_state", lambda uid, pid: ws)

    pr = _make_project_record()
    with pytest.raises(ValueError, match="Unknown authority_mode"):
        resolve_export_authority(pr, "user-1", authority_mode="INVALID_MODE")


# Test B: CANONICAL_LAST_RUN fails closed when no run committed

def test_canonical_fails_closed_no_run(monkeypatch):
    from app.services.export_service import resolve_export_authority, EXPORT_AUTHORITY_CANONICAL_LAST_RUN
    import app.persistence.workspace_repository as ws_repo

    ws = _make_ws(draft_snapshot={"a": 1}, any_run_committed=False)
    monkeypatch.setattr(ws_repo, "get_workspace_state", lambda uid, pid: ws)

    pr = _make_project_record()
    with pytest.raises(ValueError, match="CANONICAL_LAST_RUN_UNAVAILABLE"):
        resolve_export_authority(pr, "user-1", authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN)


# Test C: CANONICAL_LAST_RUN fails closed when snapshot missing even if run committed

def test_canonical_fails_closed_missing_snapshot(monkeypatch):
    from app.services.export_service import resolve_export_authority, EXPORT_AUTHORITY_CANONICAL_LAST_RUN
    import app.persistence.workspace_repository as ws_repo

    ws = _make_ws(draft_snapshot={"a": 1}, any_run_committed=True, last_runtime_snapshot=None)
    monkeypatch.setattr(ws_repo, "get_workspace_state", lambda uid, pid: ws)

    pr = _make_project_record()
    with pytest.raises(ValueError, match="CANONICAL_LAST_RUN_UNAVAILABLE"):
        resolve_export_authority(pr, "user-1", authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN)


# Test D: PREVIEW_WORKING returns PREVIEW authority with no run identity

def test_preview_working_clears_run_identity(monkeypatch):
    from app.services.export_service import (
        resolve_export_authority,
        EXPORT_AUTHORITY_PREVIEW_WORKING,
    )
    import app.persistence.workspace_repository as ws_repo
    import app.workbook.service as wb_svc
    import app.services.export_service as export_svc

    snap = {"irr": 0.1}
    ws = _make_ws(
        draft_snapshot=snap,
        any_run_committed=True,
        last_runtime_snapshot_id="20260101T000000.000000+0000",
        last_runtime_at=None,
    )
    monkeypatch.setattr(ws_repo, "get_workspace_state", lambda uid, pid: ws)

    sentinel = object()

    class FakePIS:
        def to_projectinputs(self):
            return sentinel

    monkeypatch.setattr(wb_svc.WorkbookService, "build_draft_input_set_from_workspace", staticmethod(lambda _ws: FakePIS()))
    monkeypatch.setattr(export_svc, "_apply_capex_opex_folds", lambda pi, project_id, sc_overrides: pi)

    pr = _make_project_record()
    auth = resolve_export_authority(pr, "user-1", authority_mode=EXPORT_AUTHORITY_PREVIEW_WORKING)

    assert auth.authority_mode == EXPORT_AUTHORITY_PREVIEW_WORKING
    # PREVIEW must NOT inherit last-run identity
    assert auth.run_id is None
    assert auth.run_at is None
    # None → "not_applicable" in CSV
    assert auth.working_changed_since_run is None


# Test E: CANONICAL uses last_runtime_snapshot, not draft

def test_canonical_uses_last_runtime_snapshot(monkeypatch):
    from app.services.export_service import (
        resolve_export_authority,
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
    )
    import app.persistence.workspace_repository as ws_repo
    import app.workbook.service as wb_svc
    import app.services.export_service as export_svc

    last_snap = {"source": "last_run", "irr": 0.12}
    draft_snap = {"source": "draft", "irr": 0.08}
    from datetime import datetime, timezone

    run_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ws = _make_ws(
        draft_snapshot=draft_snap,
        last_runtime_snapshot=last_snap,
        last_runtime_at=run_at,
        any_run_committed=True,
    )
    monkeypatch.setattr(ws_repo, "get_workspace_state", lambda uid, pid: ws)

    captured = {}
    sentinel = object()

    class FakePIS:
        def to_projectinputs(self):
            return sentinel

    def fake_build_input_set(snapshot, **kw):
        captured["snapshot"] = snapshot
        return FakePIS()

    monkeypatch.setattr(wb_svc.WorkbookService, "build_input_set", staticmethod(fake_build_input_set))
    monkeypatch.setattr(export_svc, "_apply_capex_opex_folds", lambda pi, project_id, sc_overrides: pi)

    pr = _make_project_record()
    auth = resolve_export_authority(pr, "user-1", authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN)

    # Must have built from last_runtime_snapshot, not draft
    assert captured["snapshot"] is last_snap
    assert auth.authority_mode == EXPORT_AUTHORITY_CANONICAL_LAST_RUN
    assert auth.run_id is None  # UUID unavailable — snapshot_id ≠ run UUID
    assert auth.run_at == "2026-01-01T00:00:00+00:00"
    assert auth.current_snapshot == last_snap


# Test F: working_changed_since_run is True when draft differs from last-run snapshot

def test_canonical_working_changed_since_run_true(monkeypatch):
    from app.services.export_service import resolve_export_authority, EXPORT_AUTHORITY_CANONICAL_LAST_RUN
    import app.persistence.workspace_repository as ws_repo
    import app.workbook.service as wb_svc
    import app.services.export_service as export_svc

    last_snap = {"capex": 1000}
    draft_snap = {"capex": 1200}  # edited after run → stale
    ws = _make_ws(
        draft_snapshot=draft_snap,
        last_runtime_snapshot=last_snap,
        any_run_committed=True,
    )
    monkeypatch.setattr(ws_repo, "get_workspace_state", lambda uid, pid: ws)

    sentinel = object()

    class FakePIS:
        def to_projectinputs(self):
            return sentinel

    monkeypatch.setattr(wb_svc.WorkbookService, "build_input_set", staticmethod(lambda snap, **kw: FakePIS()))
    monkeypatch.setattr(export_svc, "_apply_capex_opex_folds", lambda pi, project_id, sc_overrides: pi)

    pr = _make_project_record()
    auth = resolve_export_authority(pr, "user-1", authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN)

    assert auth.working_changed_since_run is True


# Test G: working_changed_since_run is False when draft equals last-run snapshot

def test_canonical_working_changed_since_run_false(monkeypatch):
    from app.services.export_service import resolve_export_authority, EXPORT_AUTHORITY_CANONICAL_LAST_RUN
    import app.persistence.workspace_repository as ws_repo
    import app.workbook.service as wb_svc
    import app.services.export_service as export_svc

    snap = {"capex": 1000}
    ws = _make_ws(
        draft_snapshot=dict(snap),
        last_runtime_snapshot=dict(snap),
        any_run_committed=True,
    )
    monkeypatch.setattr(ws_repo, "get_workspace_state", lambda uid, pid: ws)

    sentinel = object()

    class FakePIS:
        def to_projectinputs(self):
            return sentinel

    monkeypatch.setattr(wb_svc.WorkbookService, "build_input_set", staticmethod(lambda snap, **kw: FakePIS()))
    monkeypatch.setattr(export_svc, "_apply_capex_opex_folds", lambda pi, project_id, sc_overrides: pi)

    pr = _make_project_record()
    auth = resolve_export_authority(pr, "user-1", authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN)

    assert auth.working_changed_since_run is False


# Test H: run_id is never the snapshot_id (compact timestamp)

def test_canonical_run_id_not_snapshot_id(monkeypatch):
    """run_id must be None; it must not be aliased from last_runtime_snapshot_id."""
    from app.services.export_service import resolve_export_authority, EXPORT_AUTHORITY_CANONICAL_LAST_RUN
    import app.persistence.workspace_repository as ws_repo
    import app.workbook.service as wb_svc
    import app.services.export_service as export_svc

    ws = _make_ws(
        draft_snapshot={"x": 1},
        last_runtime_snapshot={"x": 1},
        any_run_committed=True,
        last_runtime_snapshot_id="20260101T120000.000000+0000",  # compact timestamp
    )
    monkeypatch.setattr(ws_repo, "get_workspace_state", lambda uid, pid: ws)

    sentinel = object()

    class FakePIS:
        def to_projectinputs(self):
            return sentinel

    monkeypatch.setattr(wb_svc.WorkbookService, "build_input_set", staticmethod(lambda snap, **kw: FakePIS()))
    monkeypatch.setattr(export_svc, "_apply_capex_opex_folds", lambda pi, project_id, sc_overrides: pi)

    pr = _make_project_record()
    auth = resolve_export_authority(pr, "user-1", authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN)

    # The compact timestamp must NOT be used as run_id
    assert auth.run_id is None
    assert auth.run_id != "20260101T120000.000000+0000"


# Test I: factory-path project always returns FACTORY_REFERENCE regardless of requested mode

def test_factory_project_always_factory_reference():
    from app.services.export_service import (
        resolve_export_authority,
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        EXPORT_AUTHORITY_FACTORY_REFERENCE,
    )

    pr = _make_project_record(project_origin="factory_reference")
    auth = resolve_export_authority(pr, "user-1", authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN)
    assert auth.authority_mode == EXPORT_AUTHORITY_FACTORY_REFERENCE
    assert auth.project_inputs is None


# Test J: PREVIEW active_scenario_id uses current Working scenario (not last-run)

def test_preview_uses_working_scenario(monkeypatch):
    from app.services.export_service import (
        resolve_export_authority,
        EXPORT_AUTHORITY_PREVIEW_WORKING,
    )
    import app.persistence.workspace_repository as ws_repo
    import app.workbook.service as wb_svc
    import app.services.export_service as export_svc
    import app.persistence.scenarios_repository as sc_repo

    ws = _make_ws(
        draft_snapshot={"x": 1},
        active_scenario_id="sc-B",
        active_scenario_name="Scenario B",
        last_runtime_scenario_id="sc-A",  # last run was on scenario A
        any_run_committed=True,
    )
    monkeypatch.setattr(ws_repo, "get_workspace_state", lambda uid, pid: ws)

    class FakeScenario:
        scenario_name = "Scenario B"
        archived = False
        project_id = "proj-1"
        overrides = None

    monkeypatch.setattr(sc_repo, "get_scenario", lambda scenario_id, user_id: FakeScenario())

    sentinel = object()

    class FakePIS:
        def to_projectinputs(self):
            return sentinel

    monkeypatch.setattr(wb_svc.WorkbookService, "build_draft_input_set_from_workspace", staticmethod(lambda _ws: FakePIS()))
    monkeypatch.setattr(export_svc, "_apply_capex_opex_folds", lambda pi, project_id, sc_overrides: pi)

    pr = _make_project_record()
    auth = resolve_export_authority(pr, "user-1", authority_mode=EXPORT_AUTHORITY_PREVIEW_WORKING)

    # PREVIEW must show current Working scenario
    assert auth.active_scenario_id == "sc-B"
    assert auth.active_scenario_name == "Scenario B"


# Test K: CANONICAL active_scenario_id uses last-run scenario (not current Working)

def test_canonical_uses_last_run_scenario(monkeypatch):
    from app.services.export_service import (
        resolve_export_authority,
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
    )
    import app.persistence.workspace_repository as ws_repo
    import app.workbook.service as wb_svc
    import app.services.export_service as export_svc

    ws = _make_ws(
        draft_snapshot={"x": 1},
        last_runtime_snapshot={"x": 1},
        active_scenario_id="sc-B",
        last_runtime_scenario_id=None,  # base run (no scenario)
        any_run_committed=True,
    )
    monkeypatch.setattr(ws_repo, "get_workspace_state", lambda uid, pid: ws)

    sentinel = object()

    class FakePIS:
        def to_projectinputs(self):
            return sentinel

    monkeypatch.setattr(wb_svc.WorkbookService, "build_input_set", staticmethod(lambda snap, **kw: FakePIS()))
    monkeypatch.setattr(export_svc, "_apply_capex_opex_folds", lambda pi, project_id, sc_overrides: pi)

    pr = _make_project_record()
    auth = resolve_export_authority(pr, "user-1", authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN)

    # CANONICAL must bind to last-run scenario, NOT current Working scenario
    assert auth.active_scenario_id is None  # base run
    assert auth.authority_mode == EXPORT_AUTHORITY_CANONICAL_LAST_RUN


# ---------------------------------------------------------------------------
# Correction B: run-bound effective inputs (no live-table reads for canonical)
# ---------------------------------------------------------------------------


def _make_ws_with_identity(
    *,
    draft_snapshot=None,
    last_runtime_snapshot=None,
    last_runtime_at=None,
    last_runtime_scenario_id=None,
    last_runtime_snapshot_id=None,
    active_scenario_id=None,
    active_scenario_name=None,
    any_run_committed=False,
    last_runtime_composite_hash=None,
    last_runtime_identity=None,
):
    """Build a WorkspaceStateRecord-like stub that carries Correction B fields."""

    class FakeWS:
        pass

    ws = FakeWS()
    ws.draft_snapshot = draft_snapshot or {}
    ws.last_runtime_snapshot = last_runtime_snapshot
    ws.last_runtime_at = last_runtime_at
    ws.last_runtime_scenario_id = last_runtime_scenario_id
    ws.last_runtime_snapshot_id = last_runtime_snapshot_id
    ws.active_scenario_id = active_scenario_id
    ws.active_scenario_name = active_scenario_name
    ws.any_run_committed = any_run_committed
    ws.last_runtime_composite_hash = last_runtime_composite_hash
    ws.last_runtime_identity = last_runtime_identity
    return ws


# Test L: canonical path uses persisted identity — _apply_capex_opex_folds NOT called

def test_canonical_with_identity_skips_live_fold(monkeypatch):
    """When last_runtime_identity is set, canonical path must NOT call _apply_capex_opex_folds."""
    from app.services.export_service import resolve_export_authority, EXPORT_AUTHORITY_CANONICAL_LAST_RUN
    import app.persistence.workspace_repository as ws_repo
    import app.workbook.service as wb_svc
    import app.services.export_service as export_svc

    identity = {
        "capex_rows": [],
        "opex_rows": [],
        "scenario_overrides": {},
        "scenario_name": None,
    }
    ws = _make_ws_with_identity(
        draft_snapshot={"x": 1},
        last_runtime_snapshot={"x": 1},
        any_run_committed=True,
        last_runtime_identity=identity,
    )
    monkeypatch.setattr(ws_repo, "get_workspace_state", lambda uid, pid: ws)

    live_fold_called = []

    def _guard_live_fold(pi, project_id, sc_overrides):
        live_fold_called.append(True)
        return pi

    monkeypatch.setattr(export_svc, "_apply_capex_opex_folds", _guard_live_fold)

    sentinel = object()

    class FakePIS:
        def to_projectinputs(self):
            return sentinel

    monkeypatch.setattr(wb_svc.WorkbookService, "build_input_set", staticmethod(lambda snap, **kw: FakePIS()))

    pr = _make_project_record()
    resolve_export_authority(pr, "user-1", authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN)

    assert not live_fold_called, "canonical path must NOT call _apply_capex_opex_folds when identity is present"


# Test M: canonical path uses persisted identity — get_scenario NOT called

def test_canonical_with_identity_skips_get_scenario(monkeypatch):
    """When last_runtime_identity is set, canonical path must NOT call get_scenario."""
    from app.services.export_service import resolve_export_authority, EXPORT_AUTHORITY_CANONICAL_LAST_RUN
    import app.persistence.workspace_repository as ws_repo
    import app.workbook.service as wb_svc
    import app.persistence.scenarios_repository as sc_repo

    identity = {
        "capex_rows": [],
        "opex_rows": [],
        "scenario_overrides": {"key": "val"},
        "scenario_name": "Scenario At Run",
    }
    ws = _make_ws_with_identity(
        draft_snapshot={"x": 1},
        last_runtime_snapshot={"x": 1},
        last_runtime_scenario_id="sc-run",
        any_run_committed=True,
        last_runtime_identity=identity,
    )
    monkeypatch.setattr(ws_repo, "get_workspace_state", lambda uid, pid: ws)

    get_scenario_called = []

    def _guard_get_scenario(scenario_id, user_id):
        get_scenario_called.append(scenario_id)
        return None  # would fail _validate_scenario

    monkeypatch.setattr(sc_repo, "get_scenario", _guard_get_scenario)

    sentinel = object()

    class FakePIS:
        def to_projectinputs(self):
            return sentinel

    import app.workbook.service as wb_svc2
    monkeypatch.setattr(wb_svc2.WorkbookService, "build_input_set", staticmethod(lambda snap, **kw: FakePIS()))
    import app.services.export_service as export_svc
    monkeypatch.setattr(export_svc, "_apply_capex_opex_folds_from_identity", lambda pi, pid, ri: pi)

    pr = _make_project_record()
    auth = resolve_export_authority(pr, "user-1", authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN)

    assert not get_scenario_called, "canonical path must NOT call get_scenario when identity is present"
    # Scenario name from identity, not from live DB
    assert auth.active_scenario_name == "Scenario At Run"


# Test N: legacy canonical path (no identity) still resolves via live tables

def test_canonical_legacy_path_uses_live_fold(monkeypatch):
    """When last_runtime_identity is None (pre-CorrB row), canonical falls back to live fold."""
    from app.services.export_service import resolve_export_authority, EXPORT_AUTHORITY_CANONICAL_LAST_RUN
    import app.persistence.workspace_repository as ws_repo
    import app.workbook.service as wb_svc
    import app.services.export_service as export_svc

    ws = _make_ws_with_identity(
        draft_snapshot={"x": 1},
        last_runtime_snapshot={"x": 1},
        any_run_committed=True,
        last_runtime_identity=None,     # legacy — no persisted identity
        last_runtime_composite_hash=None,
    )
    monkeypatch.setattr(ws_repo, "get_workspace_state", lambda uid, pid: ws)

    live_fold_called = []

    def _recording_live_fold(pi, project_id, sc_overrides):
        live_fold_called.append(True)
        return pi

    monkeypatch.setattr(export_svc, "_apply_capex_opex_folds", _recording_live_fold)

    sentinel = object()

    class FakePIS:
        def to_projectinputs(self):
            return sentinel

    monkeypatch.setattr(wb_svc.WorkbookService, "build_input_set", staticmethod(lambda snap, **kw: FakePIS()))

    pr = _make_project_record()
    resolve_export_authority(pr, "user-1", authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN)

    assert live_fold_called, "legacy canonical path must still call _apply_capex_opex_folds when identity absent"


# Test O: composite staleness uses last_runtime_composite_hash when available

def test_composite_staleness_uses_hash(monkeypatch):
    """When last_runtime_composite_hash is set, staleness comparison uses composite identity."""
    from app.services.export_service import resolve_export_authority, EXPORT_AUTHORITY_CANONICAL_LAST_RUN
    import app.persistence.workspace_repository as ws_repo
    import app.workbook.service as wb_svc
    import app.services.export_service as export_svc
    import app.workbook.workbook_identity as wi

    run_hash = "aabbccdd" * 8  # 64-char hash

    ws = _make_ws_with_identity(
        draft_snapshot={"x": 1},
        last_runtime_snapshot={"x": 1},
        any_run_committed=True,
        last_runtime_identity={"capex_rows": [], "opex_rows": [], "scenario_overrides": {}, "scenario_name": None},
        last_runtime_composite_hash=run_hash,
    )
    monkeypatch.setattr(ws_repo, "get_workspace_state", lambda uid, pid: ws)

    class FakeCurrentIdentity:
        composite_hash = "different_hash_" + "x" * 49  # differs from run_hash

    monkeypatch.setattr(wi, "assemble_for_workspace", lambda ws, user_id, project_id, workbook_version: FakeCurrentIdentity())

    sentinel = object()

    class FakePIS:
        def to_projectinputs(self):
            return sentinel

    monkeypatch.setattr(wb_svc.WorkbookService, "build_input_set", staticmethod(lambda snap, **kw: FakePIS()))
    monkeypatch.setattr(export_svc, "_apply_capex_opex_folds_from_identity", lambda pi, pid, ri: pi)

    pr = _make_project_record()
    auth = resolve_export_authority(pr, "user-1", authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN)

    # Different current hash → working has changed since run
    assert auth.working_changed_since_run is True


# Test P: composite staleness — same hash → not changed

def test_composite_staleness_same_hash_not_changed(monkeypatch):
    """When composite hash matches, working_changed_since_run is False."""
    from app.services.export_service import resolve_export_authority, EXPORT_AUTHORITY_CANONICAL_LAST_RUN
    import app.persistence.workspace_repository as ws_repo
    import app.workbook.service as wb_svc
    import app.services.export_service as export_svc
    import app.workbook.workbook_identity as wi

    run_hash = "aabbccdd" * 8

    ws = _make_ws_with_identity(
        draft_snapshot={"x": 1},
        last_runtime_snapshot={"x": 1},
        any_run_committed=True,
        last_runtime_identity={"capex_rows": [], "opex_rows": [], "scenario_overrides": {}, "scenario_name": None},
        last_runtime_composite_hash=run_hash,
    )
    monkeypatch.setattr(ws_repo, "get_workspace_state", lambda uid, pid: ws)

    class FakeCurrentIdentity:
        composite_hash = run_hash  # same as run

    monkeypatch.setattr(wi, "assemble_for_workspace", lambda ws, user_id, project_id, workbook_version: FakeCurrentIdentity())

    sentinel = object()

    class FakePIS:
        def to_projectinputs(self):
            return sentinel

    monkeypatch.setattr(wb_svc.WorkbookService, "build_input_set", staticmethod(lambda snap, **kw: FakePIS()))
    monkeypatch.setattr(export_svc, "_apply_capex_opex_folds_from_identity", lambda pi, pid, ri: pi)

    pr = _make_project_record()
    auth = resolve_export_authority(pr, "user-1", authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN)

    assert auth.working_changed_since_run is False


# Test Q: scenario_name from identity propagated to authority

def test_canonical_active_scenario_name_from_identity(monkeypatch):
    """active_scenario_name must come from persisted identity, not live DB."""
    from app.services.export_service import resolve_export_authority, EXPORT_AUTHORITY_CANONICAL_LAST_RUN
    import app.persistence.workspace_repository as ws_repo
    import app.workbook.service as wb_svc
    import app.services.export_service as export_svc

    identity = {
        "capex_rows": [],
        "opex_rows": [],
        "scenario_overrides": {},
        "scenario_name": "Run-Time Scenario Name",
    }
    ws = _make_ws_with_identity(
        draft_snapshot={"x": 1},
        last_runtime_snapshot={"x": 1},
        last_runtime_scenario_id="sc-1",
        any_run_committed=True,
        last_runtime_identity=identity,
    )
    monkeypatch.setattr(ws_repo, "get_workspace_state", lambda uid, pid: ws)

    sentinel = object()

    class FakePIS:
        def to_projectinputs(self):
            return sentinel

    monkeypatch.setattr(wb_svc.WorkbookService, "build_input_set", staticmethod(lambda snap, **kw: FakePIS()))
    monkeypatch.setattr(export_svc, "_apply_capex_opex_folds_from_identity", lambda pi, pid, ri: pi)

    pr = _make_project_record()
    auth = resolve_export_authority(pr, "user-1", authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN)

    assert auth.active_scenario_name == "Run-Time Scenario Name"


# Test R: _apply_capex_opex_folds_from_identity returns inputs unchanged for empty rows

def test_identity_fold_noop_for_empty_rows():
    """_apply_capex_opex_folds_from_identity returns project_inputs unchanged when no rows."""
    from app.services.export_service import _apply_capex_opex_folds_from_identity

    sentinel = object()
    result = _apply_capex_opex_folds_from_identity(sentinel, "proj-1", {})
    assert result is sentinel

    result2 = _apply_capex_opex_folds_from_identity(sentinel, "proj-1", None)
    assert result2 is sentinel

    result3 = _apply_capex_opex_folds_from_identity(
        sentinel, "proj-1",
        {"capex_rows": [], "opex_rows": [], "scenario_overrides": {}, "scenario_name": None}
    )
    assert result3 is sentinel


# Test S: WorkspaceStateRecord accepts last_runtime_composite_hash and last_runtime_identity

def test_workspace_state_record_has_correction_b_fields():
    """WorkspaceStateRecord must expose last_runtime_composite_hash and last_runtime_identity."""
    from app.persistence.records import WorkspaceStateRecord
    import dataclasses

    fields = {f.name for f in dataclasses.fields(WorkspaceStateRecord)}
    assert "last_runtime_composite_hash" in fields
    assert "last_runtime_identity" in fields
