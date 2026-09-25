"""Canonical last-run tests for Solar, Wind, and Data Center reference models.

Acceptance markers (all must PASS for PR merge):
  SOLAR_REFERENCE_CANONICAL_LAST_RUN
  WIND_REFERENCE_CANONICAL_LAST_RUN
  DATA_CENTER_REFERENCE_CANONICAL_LAST_RUN
  REFERENCE_LAST_RUN_IDEMPOTENT
  REFERENCE_LAST_RUN_INVALIDATES_ON_CANONICAL_INPUT_CHANGE
  REFERENCE_LAST_RUN_INVALIDATES_ON_MODEL_IDENTITY_CHANGE
  REFERENCE_LAST_RUN_MODERN_FRESHNESS_AUTHORITY
  REFERENCE_LAST_RUN_FROM_CANONICAL_ENGINE
  REFERENCE_LAST_RUN_FULL_RUNTIME_PAYLOAD
  REFERENCE_RETURNS_HYDRATE_FROM_LAST_RUN
  REFERENCE_CHARTS_HYDRATE_FROM_LAST_RUN
  REFERENCE_LAST_RUN_PROVENANCE_BOUND
  REFERENCE_LAST_RUN_READ_ONLY
  REFERENCE_WORKING_COPY_IDENTITY_SEPARATION
  REFERENCE_EDIT_DOES_NOT_MUTATE_REFERENCE_RUN
  REFERENCE_USER_RUN_CREATES_USER_LAST_RUN
  REFERENCE_LIBRARY_KPI_FROM_LAST_RUN
  REFERENCE_WORKBOOK_NOT_NEVER_RUN
  REFERENCE_DC_GEARING_SEMANTICS
  REFERENCE_LAST_RUN_FAILURE_FAILS_CLOSED
  DATA_CENTER_REFERENCE_ECONOMICS_SANITY_CHECK
"""
from __future__ import annotations

import pytest


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    from app.persistence import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "canonical-last-run.db"))
    db.init_db()
    yield


def _bootstrap(seeded_db):
    """Run both bootstrap steps and return seeded template sources."""
    from app.services.project_library_service import (
        ensure_reference_canonical_last_runs,
        ensure_reference_models,
    )

    ensure_reference_models()
    return ensure_reference_canonical_last_runs()


# ---------------------------------------------------------------------------
# SOLAR_REFERENCE_CANONICAL_LAST_RUN
# WIND_REFERENCE_CANONICAL_LAST_RUN
# DATA_CENTER_REFERENCE_CANONICAL_LAST_RUN
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("template_source", [
    "generic_solar_reference",
    "generic_wind_reference",
    "generic_data_center_reference",
])
def test_reference_canonical_last_run_seeded(seeded_db, template_source):
    """SOLAR/WIND/DATA_CENTER_REFERENCE_CANONICAL_LAST_RUN = PASS"""
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state

    _bootstrap(seeded_db)

    record = get_reference_by_template_source(template_source)
    assert record is not None, f"reference record missing for {template_source}"

    ws = get_workspace_state(record.user_id, record.project_id)
    assert ws is not None, "workspace state missing"
    assert ws.last_runtime_snapshot_id, "last_runtime_snapshot_id must be set after seeding"
    assert ws.last_runtime_summary, "last_runtime_summary must be non-empty after seeding"
    # Core KPIs must be present
    assert ws.last_runtime_summary.get("project_irr") is not None
    assert ws.last_runtime_summary.get("min_dscr") is not None


# ---------------------------------------------------------------------------
# REFERENCE_LAST_RUN_IDEMPOTENT
# ---------------------------------------------------------------------------

def test_canonical_last_run_idempotent(seeded_db):
    """REFERENCE_LAST_RUN_IDEMPOTENT = PASS — second call is a no-op."""
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.project_library_service import (
        ensure_reference_canonical_last_runs,
        ensure_reference_models,
    )

    ensure_reference_models()
    first_seeded = ensure_reference_canonical_last_runs()
    assert len(first_seeded) == 3  # solar, wind, dc

    # Capture snapshot IDs
    snap_ids = {}
    for ts in first_seeded:
        rec = get_reference_by_template_source(ts)
        ws = get_workspace_state(rec.user_id, rec.project_id)
        snap_ids[ts] = ws.last_runtime_snapshot_id

    second_seeded = ensure_reference_canonical_last_runs()
    assert second_seeded == [], "second call must return [] (idempotent)"

    # Snapshot IDs must be unchanged
    for ts, sid in snap_ids.items():
        rec = get_reference_by_template_source(ts)
        ws = get_workspace_state(rec.user_id, rec.project_id)
        assert ws.last_runtime_snapshot_id == sid, f"{ts}: snapshot_id changed on second call"


# ---------------------------------------------------------------------------
# REFERENCE_LAST_RUN_FROM_CANONICAL_ENGINE
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("template_source,factory_fn,project_type", [
    ("generic_solar_reference", "create_generic_solar_reference", "Solar"),
    ("generic_wind_reference", "create_generic_wind_reference", "Wind"),
    ("generic_data_center_reference", "create_generic_data_center_reference", "Data Center"),
])
def test_canonical_last_run_matches_engine_output(seeded_db, template_source, factory_fn, project_type):
    """REFERENCE_LAST_RUN_FROM_CANONICAL_ENGINE = PASS — stored KPIs match live engine."""
    from app import project_factories
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.production_financial_authority import run_clean_production
    from app.services.clean_presentation_adapter import build_clean_waterfall_view

    _bootstrap(seeded_db)

    record = get_reference_by_template_source(template_source)
    ws = get_workspace_state(record.user_id, record.project_id)

    pi = getattr(project_factories, factory_fn)()
    clean_run = run_clean_production(pi, "Base", project_type=project_type)
    view = build_clean_waterfall_view(clean_run)

    assert ws.last_runtime_summary["project_irr"] == pytest.approx(view.project_irr, rel=1e-6)
    assert ws.last_runtime_summary["min_dscr"] == pytest.approx(view.actual_min_dscr, rel=1e-6)


# ---------------------------------------------------------------------------
# REFERENCE_LAST_RUN_PROVENANCE_BOUND
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("template_source", [
    "generic_solar_reference",
    "generic_wind_reference",
    "generic_data_center_reference",
])
def test_canonical_last_run_provenance(seeded_db, template_source):
    """REFERENCE_LAST_RUN_PROVENANCE_BOUND = PASS — replay_metadata records origin."""
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state

    _bootstrap(seeded_db)

    record = get_reference_by_template_source(template_source)
    ws = get_workspace_state(record.user_id, record.project_id)

    assert ws.last_runtime_snapshot_id.startswith("canonical_last_run__")
    assert ws.replay_metadata is not None
    meta = ws.replay_metadata
    assert meta.get("origin") == "canonical_reference_last_run"
    assert meta.get("template_source") == template_source
    assert meta.get("reference_project_id") == record.project_id


# ---------------------------------------------------------------------------
# REFERENCE_LAST_RUN_READ_ONLY
# ---------------------------------------------------------------------------

def test_reference_last_run_is_read_only(seeded_db):
    """REFERENCE_LAST_RUN_READ_ONLY = PASS — reference record is still protected."""
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services.project_library_service import assert_project_not_protected, ProtectedProjectError

    _bootstrap(seeded_db)

    for ts in ["generic_solar_reference", "generic_wind_reference", "generic_data_center_reference"]:
        record = get_reference_by_template_source(ts)
        assert record.is_protected, f"{ts}: is_protected must remain True after seeding"
        assert record.is_readonly, f"{ts}: is_readonly must remain True after seeding"
        with pytest.raises(ProtectedProjectError):
            assert_project_not_protected(record)


# ---------------------------------------------------------------------------
# REFERENCE_WORKING_COPY_IDENTITY_SEPARATION
# REFERENCE_EDIT_DOES_NOT_MUTATE_REFERENCE_RUN
# REFERENCE_USER_RUN_CREATES_USER_LAST_RUN
# ---------------------------------------------------------------------------

def test_working_copy_does_not_inherit_reference_last_run(seeded_db):
    """REFERENCE_WORKING_COPY_IDENTITY_SEPARATION = PASS"""
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.project_library_service import create_working_copy

    _bootstrap(seeded_db)

    solar_ref = get_reference_by_template_source("generic_solar_reference")
    copy_record = create_working_copy(
        user_id="wc-sep-user",
        source_reference_id=solar_ref.project_id,
        requested_name="My Solar Copy",
    )

    copy_ws = get_workspace_state("wc-sep-user", copy_record.project_id)
    assert copy_ws is not None
    # Working copy must start with empty last-run state
    assert not copy_ws.last_runtime_snapshot_id, "working copy must NOT inherit reference last-run"

    # Reference must still have its own last-run intact
    ref_ws = get_workspace_state(solar_ref.user_id, solar_ref.project_id)
    assert ref_ws.last_runtime_snapshot_id, "reference last-run must survive working copy creation"


def test_edit_on_working_copy_does_not_mutate_reference_run(seeded_db):
    """REFERENCE_EDIT_DOES_NOT_MUTATE_REFERENCE_RUN = PASS"""
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state, save_workspace_state
    from app.services.project_library_service import create_working_copy

    _bootstrap(seeded_db)

    solar_ref = get_reference_by_template_source("generic_solar_reference")
    ref_ws_before = get_workspace_state(solar_ref.user_id, solar_ref.project_id)
    ref_snap_id_before = ref_ws_before.last_runtime_snapshot_id

    copy_record = create_working_copy(
        user_id="edit-sep-user",
        source_reference_id=solar_ref.project_id,
    )

    # Simulate a draft save on the working copy
    copy_ws = get_workspace_state("edit-sep-user", copy_record.project_id)
    modified_draft = dict(copy_ws.draft_snapshot or {})
    modified_draft["capacity_mw"] = 100.0
    save_workspace_state(
        user_id="edit-sep-user",
        project_id=copy_record.project_id,
        project_code=copy_record.project_code,
        draft_snapshot=modified_draft,
        saved_snapshot=copy_ws.saved_snapshot,
        governance_state=copy_ws.governance_state or {},
    )

    # Reference last-run must be unchanged
    ref_ws_after = get_workspace_state(solar_ref.user_id, solar_ref.project_id)
    assert ref_ws_after.last_runtime_snapshot_id == ref_snap_id_before, \
        "editing working copy draft must not mutate reference last-run"


def test_user_run_on_working_copy_does_not_mutate_reference(seeded_db):
    """REFERENCE_USER_RUN_CREATES_USER_LAST_RUN = PASS"""
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.repository import record_workspace_runtime
    from app.services.project_library_service import create_working_copy

    _bootstrap(seeded_db)

    solar_ref = get_reference_by_template_source("generic_solar_reference")
    ref_ws_before = get_workspace_state(solar_ref.user_id, solar_ref.project_id)
    ref_snap_id_before = ref_ws_before.last_runtime_snapshot_id
    ref_summary_before = dict(ref_ws_before.last_runtime_summary or {})

    copy_record = create_working_copy(
        user_id="run-sep-user",
        source_reference_id=solar_ref.project_id,
    )

    # Simulate a user run on the working copy
    record_workspace_runtime(
        user_id="run-sep-user",
        project_id=copy_record.project_id,
        project_code=copy_record.project_code,
        runtime_snapshot={},
        runtime_summary={"project_irr": 0.0999, "min_dscr": 1.1},
        runtime_snapshot_id="user-run-001",
        runtime_origin="user_run",
    )

    # User run must be visible on the copy
    copy_ws = get_workspace_state("run-sep-user", copy_record.project_id)
    assert copy_ws.last_runtime_snapshot_id == "user-run-001"
    assert copy_ws.last_runtime_summary["project_irr"] == pytest.approx(0.0999)

    # Reference must be completely unaffected
    ref_ws_after = get_workspace_state(solar_ref.user_id, solar_ref.project_id)
    assert ref_ws_after.last_runtime_snapshot_id == ref_snap_id_before, \
        "user run on working copy must not mutate reference snapshot_id"
    assert ref_ws_after.last_runtime_summary.get("project_irr") == pytest.approx(
        ref_summary_before["project_irr"]
    ), "user run on working copy must not mutate reference KPIs"


# ---------------------------------------------------------------------------
# REFERENCE_LIBRARY_KPI_FROM_LAST_RUN
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("template_source", [
    "generic_solar_reference",
    "generic_wind_reference",
    "generic_data_center_reference",
])
def test_reference_library_kpi_populated(seeded_db, template_source):
    """REFERENCE_LIBRARY_KPI_FROM_LAST_RUN = PASS — project_irr non-null in workspace."""
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state

    _bootstrap(seeded_db)

    record = get_reference_by_template_source(template_source)
    ws = get_workspace_state(record.user_id, record.project_id)
    assert ws.last_runtime_summary.get("project_irr") is not None, \
        f"{template_source}: project_irr must be set for library card"


# ---------------------------------------------------------------------------
# REFERENCE_WORKBOOK_NOT_NEVER_RUN
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("template_source", [
    "generic_solar_reference",
    "generic_wind_reference",
    "generic_data_center_reference",
])
def test_reference_workbook_not_never_run(seeded_db, template_source):
    """REFERENCE_WORKBOOK_NOT_NEVER_RUN = PASS — RuntimeResult is non-None after seeding."""
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.runtime_result import RuntimeResult

    _bootstrap(seeded_db)

    record = get_reference_by_template_source(template_source)
    ws = get_workspace_state(record.user_id, record.project_id)
    result = RuntimeResult.from_workspace_state(ws)
    assert result is not None, \
        f"{template_source}: RuntimeResult.from_workspace_state must be non-None (not 'Never run')"


# ---------------------------------------------------------------------------
# DATA_CENTER_REFERENCE_ECONOMICS_SANITY_CHECK
# Classification A: first-year revenue ramp causes DSCR < 1.0 in periods 1-2.
# Debt is sized to 1.30x on stabilized periods (period 3+). No model defect.
# ---------------------------------------------------------------------------

def test_dc_dscr_ramp_classification_a(seeded_db):
    """DATA_CENTER_REFERENCE_ECONOMICS_SANITY_CHECK = PASS (Classification A).

    Year-1 DSCR < 1.0 is expected: DC revenue ramps up over three stages
    (Y1 ~40%, Y2 ~65%, Y3+ ~100%). Fixed OPEX runs from COD. Debt service
    is sculpted lower in Y1 but not enough to compensate for the revenue
    shortfall. Debt is correctly sized to 1.30x in stabilized periods.
    """
    from app.project_factories import create_generic_data_center_reference
    from app.services.production_financial_authority import run_clean_production

    pi = create_generic_data_center_reference()
    result = run_clean_production(pi, "Base", project_type="Data Center")
    g2c = result.g2c_result
    fr = g2c.financing_result
    pmr = fr.project_model_result
    sd = pmr.senior_debt

    dscr_all = list(sd.senior_dscr)
    # Ramp periods: first two operating periods (period indices 4-5 in full timeline)
    ramp_dscr = dscr_all[:2]
    stable_dscr = dscr_all[2:-1]  # exclude final period (balloon payment effect)

    # Ramp periods are below target — expected
    assert all(d < 1.0 for d in ramp_dscr), \
        f"Expected ramp-period DSCR < 1.0; got {ramp_dscr}"

    # Stabilized periods hit the target DSCR (1.30)
    target = pi.financing.target_dscr
    assert all(abs(d - target) < 0.001 for d in stable_dscr), \
        f"Stabilized DSCRs must equal target {target}; got {stable_dscr}"

    # Classification A: there are exactly 2 ramp periods (one operating year)
    assert len(ramp_dscr) == 2, f"Expected 2 ramp-period entries, got {len(ramp_dscr)}"

    # Revenue in ramp periods is lower than in stabilized periods
    ops = pmr.operating_schedules
    rev = list(ops.revenue_keur)
    # First 4 entries are construction (0.0), then operating starts
    operating_rev = [r for r in rev if r > 0]
    assert operating_rev[0] < operating_rev[4], \
        "Year-1 revenue must be lower than stabilized revenue (ramp-up confirmed)"


# ---------------------------------------------------------------------------
# REFERENCE_LAST_RUN_INVALIDATES_ON_CANONICAL_INPUT_CHANGE
# REFERENCE_LAST_RUN_INVALIDATES_ON_MODEL_IDENTITY_CHANGE
# ---------------------------------------------------------------------------

def test_canonical_last_run_invalidates_on_composite_hash_change(seeded_db):
    """REFERENCE_LAST_RUN_INVALIDATES_ON_CANONICAL_INPUT_CHANGE = PASS
    REFERENCE_LAST_RUN_INVALIDATES_ON_MODEL_IDENTITY_CHANGE = PASS

    Simulates a workbook version bump by writing a stale hash into
    last_runtime_composite_hash in the DB, then verifies that
    ensure_reference_canonical_last_runs re-seeds all three references.
    """
    from app.persistence.db import get_cursor
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.project_library_service import (
        ensure_reference_canonical_last_runs,
        ensure_reference_models,
    )

    ensure_reference_models()
    first_seeded = ensure_reference_canonical_last_runs()
    assert len(first_seeded) == 3

    # Capture original snapshot IDs
    snap_ids = {}
    for ts in first_seeded:
        rec = get_reference_by_template_source(ts)
        ws = get_workspace_state(rec.user_id, rec.project_id)
        snap_ids[ts] = ws.last_runtime_snapshot_id

    # Corrupt stored composite hash to simulate a workbook version bump or factory change.
    # The live hash hasn't changed, but stored says "old_model_version" → triggers re-seed.
    for ts in first_seeded:
        rec = get_reference_by_template_source(ts)
        with get_cursor() as cur:
            cur.execute(
                "UPDATE workspace_states SET last_runtime_composite_hash=? "
                "WHERE user_id=? AND project_id=?",
                ("__stale_hash_simulating_version_bump__", rec.user_id, rec.project_id),
            )

    re_seeded = ensure_reference_canonical_last_runs()

    # All three must have been re-seeded because the stored hash didn't match live
    assert len(re_seeded) == 3, f"Expected 3 re-seeded, got {re_seeded}"

    # Snapshot IDs must have changed
    for ts in snap_ids:
        rec = get_reference_by_template_source(ts)
        ws = get_workspace_state(rec.user_id, rec.project_id)
        assert ws.last_runtime_snapshot_id != snap_ids[ts], \
            f"{ts}: snapshot_id must change after invalidation"


# ---------------------------------------------------------------------------
# REFERENCE_LAST_RUN_MODERN_FRESHNESS_AUTHORITY
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("template_source", [
    "generic_solar_reference",
    "generic_wind_reference",
    "generic_data_center_reference",
])
def test_canonical_last_run_freshness_is_current(seeded_db, template_source):
    """REFERENCE_LAST_RUN_MODERN_FRESHNESS_AUTHORITY = PASS

    After seeding, resolve_runtime_freshness must return CURRENT using the
    composite hash path — not the legacy scalar fallback.
    """
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.registry import WORKBOOK
    from app.workbook.runtime_authority import resolve_runtime_freshness, RuntimeAuthorityState
    from app.workbook.workbook_identity import assemble_consistent_for_get

    _bootstrap(seeded_db)

    record = get_reference_by_template_source(template_source)
    ws = get_workspace_state(record.user_id, record.project_id)

    assert ws.last_runtime_composite_hash, "last_runtime_composite_hash must be set after v2 seeding"

    current_hash = assemble_consistent_for_get(
        record.user_id, record.project_id, WORKBOOK.version
    ).composite_hash

    freshness = resolve_runtime_freshness(ws, current_composite_hash=current_hash)
    assert freshness.state == RuntimeAuthorityState.CURRENT, \
        f"{template_source}: expected CURRENT, got {freshness.state} " \
        f"(stored={ws.last_runtime_composite_hash[:8]}, current={current_hash[:8]})"


# ---------------------------------------------------------------------------
# REFERENCE_LAST_RUN_FULL_RUNTIME_PAYLOAD
# REFERENCE_RETURNS_HYDRATE_FROM_LAST_RUN
# REFERENCE_CHARTS_HYDRATE_FROM_LAST_RUN
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("template_source", [
    "generic_solar_reference",
    "generic_wind_reference",
    "generic_data_center_reference",
])
def test_canonical_last_run_full_payload_persisted(seeded_db, template_source):
    """REFERENCE_LAST_RUN_FULL_RUNTIME_PAYLOAD = PASS
    REFERENCE_RETURNS_HYDRATE_FROM_LAST_RUN = PASS
    REFERENCE_CHARTS_HYDRATE_FROM_LAST_RUN = PASS
    """
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state

    _bootstrap(seeded_db)

    record = get_reference_by_template_source(template_source)
    ws = get_workspace_state(record.user_id, record.project_id)

    # Full schedule payloads must be non-empty dicts
    assert ws.last_financial_statements, \
        f"{template_source}: last_financial_statements must be non-empty"
    assert ws.last_debt_schedule, \
        f"{template_source}: last_debt_schedule must be non-empty"
    assert ws.last_tax_schedule, \
        f"{template_source}: last_tax_schedule must be non-empty"
    assert ws.last_distribution_schedule, \
        f"{template_source}: last_distribution_schedule must be non-empty"
    assert ws.last_sponsor_schedule, \
        f"{template_source}: last_sponsor_schedule must be non-empty"


# ---------------------------------------------------------------------------
# REFERENCE_DC_GEARING_SEMANTICS
# ---------------------------------------------------------------------------

def test_dc_gearing_semantics(seeded_db):
    """REFERENCE_DC_GEARING_SEMANTICS = PASS

    actual_gearing_pct must be distinct from gearing_cap_pct and approximately
    0.4022 (not 0.65, which is the maximum gearing cap).
    """
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state

    _bootstrap(seeded_db)

    record = get_reference_by_template_source("generic_data_center_reference")
    ws = get_workspace_state(record.user_id, record.project_id)
    summary = ws.last_runtime_summary

    actual = summary.get("actual_gearing_pct")
    cap = summary.get("gearing_cap_pct")

    assert actual is not None, "actual_gearing_pct must be persisted for DC reference"
    assert cap is not None, "gearing_cap_pct must be persisted for DC reference"
    assert abs(actual - cap) > 0.10, \
        f"actual_gearing_pct ({actual:.4f}) must be materially lower than cap ({cap:.4f})"
    assert actual == pytest.approx(0.4022, abs=0.005), \
        f"DC actual gearing should be ~40.22%; got {actual:.4%}"
    assert cap == pytest.approx(0.65, abs=0.01), \
        f"DC gearing cap should be ~65%; got {cap:.4%}"


# ---------------------------------------------------------------------------
# REFERENCE_LAST_RUN_FAILURE_FAILS_CLOSED
# ---------------------------------------------------------------------------

def test_canonical_last_run_failure_fails_closed(seeded_db):
    """REFERENCE_LAST_RUN_FAILURE_FAILS_CLOSED = PASS

    If the engine raises during seeding, no partial last-run state must be
    persisted, and the reference must remain protected.
    """
    from unittest.mock import patch
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.project_library_service import (
        ensure_reference_models,
        ensure_reference_canonical_last_runs,
    )
    import app.services.project_library_service as svc

    ensure_reference_models()
    # Confirm no last-run yet
    solar_ref = get_reference_by_template_source("generic_solar_reference")
    ws_before = get_workspace_state(solar_ref.user_id, solar_ref.project_id)
    assert not (ws_before and ws_before.last_runtime_snapshot_id), \
        "precondition: no last-run before seeding"

    # Patch run_project to raise for solar only
    original_run = svc._seed_reference_last_run

    def _failing_seed(record, defn, *, current_composite_hash):
        if defn["template_source"] == "generic_solar_reference":
            raise RuntimeError("Injected engine failure")
        return original_seed(record, defn, current_composite_hash=current_composite_hash)

    original_seed = original_run
    with patch.object(svc, "_seed_reference_last_run", side_effect=_failing_seed):
        seeded = ensure_reference_canonical_last_runs()

    # Solar must NOT have been seeded
    assert "generic_solar_reference" not in seeded, \
        "failed seed must not appear in seeded list"

    # Solar workspace must remain without last-run state
    ws_after = get_workspace_state(solar_ref.user_id, solar_ref.project_id)
    assert not (ws_after and ws_after.last_runtime_snapshot_id), \
        "partial last-run must not be persisted after engine failure"

    # Reference must still be protected
    assert solar_ref.is_protected, "is_protected must remain True after failure"
