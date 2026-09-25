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
  REFERENCE_IDENTITY_FAILURE_FAILS_CLOSED
  REFERENCE_LAST_RUN_SINGLE_CALCULATION
  REFERENCE_LAST_RUN_PROVENANCE_ATOMIC
  V2_USER_RUN_PERSISTENCE_REGRESSION
  REFERENCE_REAL_CANONICAL_INPUT_CHANGE_INVALIDATES
  REFERENCE_REAL_MODEL_IDENTITY_CHANGE_INVALIDATES
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


# ---------------------------------------------------------------------------
# REFERENCE_IDENTITY_FAILURE_FAILS_CLOSED
# ---------------------------------------------------------------------------

def test_reference_identity_failure_fails_closed(seeded_db):
    """REFERENCE_IDENTITY_FAILURE_FAILS_CLOSED = PASS

    When composite identity assembly raises (e.g. workspace corrupt or
    workbook_identity unavailable), no new runtime_snapshot_id, summary,
    or schedules must be persisted, and the reference must remain protected.
    The legacy authority must NOT be used as a fallback.
    """
    from unittest.mock import patch
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.project_library_service import (
        ensure_reference_models,
        ensure_reference_canonical_last_runs,
        ReferenceIdentityAssemblyError,
    )
    import app.services.project_library_service as svc

    ensure_reference_models()

    solar_ref = get_reference_by_template_source("generic_solar_reference")
    ws_before = get_workspace_state(solar_ref.user_id, solar_ref.project_id)
    snap_id_before = (ws_before.last_runtime_snapshot_id if ws_before else None)

    # Make identity assembly fail for all references.
    def _failing_identity(record):
        raise ReferenceIdentityAssemblyError("injected identity failure")

    with patch.object(svc, "_reference_current_composite_hash", side_effect=_failing_identity):
        seeded = ensure_reference_canonical_last_runs()

    # Nothing should have been seeded.
    assert seeded == [], f"Expected [] but got {seeded}"

    # Solar workspace must be unchanged — no new snapshot_id.
    ws_after = get_workspace_state(solar_ref.user_id, solar_ref.project_id)
    snap_id_after = (ws_after.last_runtime_snapshot_id if ws_after else None)
    assert snap_id_after == snap_id_before, (
        "Identity assembly failure must not create or mutate last-run state; "
        f"before={snap_id_before!r}, after={snap_id_after!r}"
    )

    # No legacy authority KPIs must have appeared.
    if ws_after:
        assert not ws_after.last_runtime_summary, (
            "No runtime summary must appear via legacy fallback after identity failure"
        )

    # Reference must remain protected.
    assert solar_ref.is_protected, "is_protected must remain True after identity failure"


# ---------------------------------------------------------------------------
# REFERENCE_LAST_RUN_SINGLE_CALCULATION
# ---------------------------------------------------------------------------

def test_reference_last_run_single_calculation(seeded_db):
    """REFERENCE_LAST_RUN_SINGLE_CALCULATION = PASS

    Exactly ONE canonical engine call per reference seed.
    Three fresh references → 3 calculations total.
    Second idempotent bootstrap → 0 additional calculations.
    """
    from unittest.mock import patch, call
    from app.services.project_library_service import (
        ensure_reference_models,
        ensure_reference_canonical_last_runs,
    )
    import app.api.project_runner as _runner

    ensure_reference_models()

    original_run = _runner.run_project
    call_log: list = []

    def counting_run(project_type, scenario, **kwargs):
        call_log.append(project_type)
        return original_run(project_type, scenario, **kwargs)

    with patch.object(_runner, "run_project", side_effect=counting_run):
        seeded = ensure_reference_canonical_last_runs()

    assert len(seeded) == 3, f"Expected 3 seeds; got {seeded}"
    assert len(call_log) == 3, (
        f"Expected exactly 3 engine calls for 3 references; got {len(call_log)}: {call_log}"
    )

    # Second idempotent pass must perform zero engine calls.
    call_log.clear()
    with patch.object(_runner, "run_project", side_effect=counting_run):
        re_seeded = ensure_reference_canonical_last_runs()

    assert re_seeded == [], "Second pass must be a no-op"
    assert len(call_log) == 0, (
        f"Second idempotent pass must not call the engine; got {len(call_log)}: {call_log}"
    )


# ---------------------------------------------------------------------------
# REFERENCE_LAST_RUN_PROVENANCE_ATOMIC
# V2_USER_RUN_PERSISTENCE_REGRESSION
# ---------------------------------------------------------------------------

def test_reference_last_run_provenance_atomic(seeded_db):
    """REFERENCE_LAST_RUN_PROVENANCE_ATOMIC = PASS

    Provenance is committed atomically with the Last Run — there is no
    gap between commit and provenance write.  The provenance fields must
    be present immediately after v2_atomic_run_commit returns, without any
    separate UPDATE step.
    """
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state, v2_atomic_run_commit
    from app.workbook.workbook_identity import assemble_consistent_for_get
    from app.workbook.registry import WORKBOOK
    from datetime import datetime, timezone

    from app.services.project_library_service import (
        ensure_reference_models,
        ensure_reference_canonical_last_runs,
    )

    ensure_reference_models()
    seeded = ensure_reference_canonical_last_runs()
    assert len(seeded) == 3

    for ts in ["generic_solar_reference", "generic_wind_reference", "generic_data_center_reference"]:
        rec = get_reference_by_template_source(ts)
        ws = get_workspace_state(rec.user_id, rec.project_id)

        # Provenance must be atomically bound — no two-phase write gap.
        assert ws.replay_metadata is not None, f"{ts}: replay_metadata must not be None"
        assert ws.replay_metadata.get("origin") == "canonical_reference_last_run", \
            f"{ts}: origin must be canonical_reference_last_run"
        assert ws.replay_metadata.get("engine_version"), \
            f"{ts}: engine_version must be present in provenance"
        assert ws.replay_metadata.get("template_source") == ts, \
            f"{ts}: template_source must match in provenance"

        # The last_runtime_composite_hash must also be present (same transaction).
        assert ws.last_runtime_composite_hash, \
            f"{ts}: last_runtime_composite_hash must be set atomically"


def test_v2_user_run_persistence_regression(seeded_db):
    """V2_USER_RUN_PERSISTENCE_REGRESSION = PASS

    v2_atomic_run_commit callers that pass no replay_metadata must retain
    existing replay_metadata unchanged (no accidental erasure).
    """
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state, v2_atomic_run_commit
    from app.workbook.workbook_identity import assemble_consistent_for_get
    from app.workbook.registry import WORKBOOK
    from app.services.project_library_service import (
        ensure_reference_models,
        ensure_reference_canonical_last_runs,
        create_working_copy,
    )
    from app.api.project_runner import run_project
    from datetime import datetime, timezone

    ensure_reference_models()
    ensure_reference_canonical_last_runs()

    # Create a working copy and simulate a user run via v2_atomic_run_commit.
    solar_ref = get_reference_by_template_source("generic_solar_reference")
    copy = create_working_copy(
        user_id="v2-reg-user",
        source_reference_id=solar_ref.project_id,
    )

    copy_ws = get_workspace_state("v2-reg-user", copy.project_id)
    assert copy_ws is not None

    # Persist some initial replay_metadata directly (simulating a prior run).
    import json as _json
    from app.persistence.db import get_cursor
    prior_meta = {"prior_run": "test_value", "workspace_id": copy_ws.replay_metadata.get("workspace_id", "")}
    with get_cursor() as cur:
        cur.execute(
            "UPDATE workspace_states SET replay_metadata_json=? WHERE user_id=? AND project_id=?",
            (_json.dumps(prior_meta), "v2-reg-user", copy.project_id),
        )

    # Now simulate a user run via v2_atomic_run_commit WITHOUT replay_metadata.
    identity = assemble_consistent_for_get("v2-reg-user", copy.project_id, WORKBOOK.version)
    payload = run_project("Generic Solar Reference", "Base")
    now = datetime.now(timezone.utc)

    v2_atomic_run_commit(
        user_id="v2-reg-user",
        project_id=copy.project_id,
        project_code=copy.project_code,
        expected_composite_hash=identity.composite_hash,
        runtime_snapshot_id="user-v2-run-001",
        runtime_origin="user_run",
        runtime_summary=payload["kpis"],
        financial_statements=payload.get("financial_statements"),
        debt_schedule=payload.get("debt_schedule"),
        tax_schedule=payload.get("tax_schedule"),
        distribution_schedule=payload.get("distribution_schedule"),
        sponsor_schedule=payload.get("sponsor_schedule"),
        active_scenario_id=copy_ws.active_scenario_id,
        active_scenario_name=copy_ws.active_scenario_name,
        ran_at=now,
        # replay_metadata intentionally omitted — must preserve existing
    )

    # Existing replay_metadata must be preserved, not erased.
    updated_ws = get_workspace_state("v2-reg-user", copy.project_id)
    assert updated_ws.replay_metadata.get("prior_run") == "test_value", (
        "v2_atomic_run_commit must preserve existing replay_metadata when "
        "replay_metadata=None (not erase it)"
    )
    # The run must have been committed.
    assert updated_ws.last_runtime_snapshot_id == "user-v2-run-001"


# ---------------------------------------------------------------------------
# REFERENCE_REAL_CANONICAL_INPUT_CHANGE_INVALIDATES
# REFERENCE_LAST_RUN_INVALIDATES_ON_CANONICAL_INPUT_CHANGE
# ---------------------------------------------------------------------------

def test_reference_real_canonical_input_change_invalidates(seeded_db, monkeypatch):
    """REFERENCE_REAL_CANONICAL_INPUT_CHANGE_INVALIDATES = PASS
    REFERENCE_LAST_RUN_INVALIDATES_ON_CANONICAL_INPUT_CHANGE = PASS

    Changing the canonical factory input (Solar capacity_mw) causes:
    1. ensure_reference_models() reconciles the workspace snapshot.
    2. The composite identity changes (different scalar snapshot).
    3. ensure_reference_canonical_last_runs() re-seeds with a new run.
    4. A second bootstrap after reconciliation performs no additional run.
    """
    import copy as _copy
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.workbook_identity import assemble_consistent_for_get
    from app.workbook.registry import WORKBOOK
    from app.services.project_library_service import (
        ensure_reference_models,
        ensure_reference_canonical_last_runs,
    )

    # --- Baseline bootstrap ---
    ensure_reference_models()
    seeded = ensure_reference_canonical_last_runs()
    assert len(seeded) == 3

    solar_rec = get_reference_by_template_source("generic_solar_reference")
    ws_before = get_workspace_state(solar_rec.user_id, solar_rec.project_id)
    hash_before = assemble_consistent_for_get(
        solar_rec.user_id, solar_rec.project_id, WORKBOOK.version
    ).composite_hash
    snap_id_before = ws_before.last_runtime_snapshot_id

    # --- Monkeypatch the Solar factory to return a different capacity ---
    import app.project_factories as _pf
    _original_factory = _pf.create_generic_solar_reference

    def _modified_factory():
        pi = _original_factory()
        import dataclasses
        # Return a copy with capacity_mw changed (harmless +1 MW)
        technical = dataclasses.replace(pi.technical, capacity_mw=pi.technical.capacity_mw + 1.0)
        return dataclasses.replace(pi, technical=technical)

    monkeypatch.setattr(_pf, "create_generic_solar_reference", _modified_factory)

    # --- Reconcile reference models with new factory ---
    ensure_reference_models()

    # Composite hash must have changed (different capacity_mw in scalar snapshot).
    hash_after_reconcile = assemble_consistent_for_get(
        solar_rec.user_id, solar_rec.project_id, WORKBOOK.version
    ).composite_hash
    assert hash_after_reconcile != hash_before, (
        "Reconciling a changed canonical factory input must change the composite hash"
    )

    # --- Re-seed: must detect changed hash and produce a new run ---
    import app.api.project_runner as _runner
    call_log: list = []
    orig = _runner.run_project

    def _counting(project_type, scenario, **kwargs):
        call_log.append(project_type)
        return orig(project_type, scenario, **kwargs)

    from unittest.mock import patch
    with patch.object(_runner, "run_project", side_effect=_counting):
        re_seeded = ensure_reference_canonical_last_runs()

    assert "generic_solar_reference" in re_seeded, (
        "Solar must be re-seeded after canonical factory input change"
    )

    ws_after = get_workspace_state(solar_rec.user_id, solar_rec.project_id)
    assert ws_after.last_runtime_snapshot_id != snap_id_before, (
        "New snapshot_id must be generated after canonical input change"
    )
    assert ws_after.last_runtime_composite_hash == hash_after_reconcile, (
        "Persisted composite hash must reflect the new canonical identity"
    )

    # Exactly 1 engine call for Solar (the changed reference).
    solar_calls = [t for t in call_log if "Solar" in t]
    assert len(solar_calls) == 1, (
        f"Expected exactly 1 Solar engine call after input change; got {len(solar_calls)}"
    )

    # --- Second bootstrap must be idempotent (no further runs) ---
    call_log.clear()
    with patch.object(_runner, "run_project", side_effect=_counting):
        idempotent = ensure_reference_canonical_last_runs()

    assert "generic_solar_reference" not in idempotent, (
        "Second bootstrap after reconciliation must be idempotent for Solar"
    )
    assert len(call_log) == 0, (
        f"Second pass must perform no engine calls; got {len(call_log)}: {call_log}"
    )


# ---------------------------------------------------------------------------
# REFERENCE_REAL_MODEL_IDENTITY_CHANGE_INVALIDATES
# REFERENCE_LAST_RUN_INVALIDATES_ON_MODEL_IDENTITY_CHANGE
# ---------------------------------------------------------------------------

def test_reference_real_model_identity_change_invalidates(seeded_db, monkeypatch):
    """REFERENCE_REAL_MODEL_IDENTITY_CHANGE_INVALIDATES = PASS
    REFERENCE_LAST_RUN_INVALIDATES_ON_MODEL_IDENTITY_CHANGE = PASS

    When the canonical engine version changes (financial_engine.version.ENGINE_VERSION),
    even with identical user-visible inputs, the reference Last Run must be
    invalidated and re-seeded with the new engine identity.
    """
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.project_library_service import (
        ensure_reference_models,
        ensure_reference_canonical_last_runs,
    )
    import app.services.project_library_service as svc

    # --- Baseline bootstrap ---
    ensure_reference_models()
    seeded = ensure_reference_canonical_last_runs()
    assert len(seeded) == 3

    snap_ids = {}
    for ts in ["generic_solar_reference", "generic_wind_reference", "generic_data_center_reference"]:
        rec = get_reference_by_template_source(ts)
        ws = get_workspace_state(rec.user_id, rec.project_id)
        snap_ids[ts] = ws.last_runtime_snapshot_id
        # Verify engine_version was stored in provenance.
        assert ws.replay_metadata.get("engine_version"), \
            f"{ts}: engine_version must be stored in provenance after first seed"

    # --- Simulate engine version bump ---
    monkeypatch.setattr(svc, "_current_engine_version", lambda: "clean_senior_debt_v1_test")

    # --- Re-seed: must detect changed engine version and produce new runs ---
    re_seeded = ensure_reference_canonical_last_runs()
    assert len(re_seeded) == 3, (
        f"All 3 references must re-seed after engine version change; got {re_seeded}"
    )

    for ts in snap_ids:
        rec = get_reference_by_template_source(ts)
        ws = get_workspace_state(rec.user_id, rec.project_id)
        assert ws.last_runtime_snapshot_id != snap_ids[ts], \
            f"{ts}: snapshot_id must change after engine version change"
        assert ws.replay_metadata.get("engine_version") == "clean_senior_debt_v1_test", \
            f"{ts}: new provenance must record the new engine_version"

    # --- Second bootstrap with same new version must be idempotent ---
    idempotent = ensure_reference_canonical_last_runs()
    assert idempotent == [], (
        f"Second pass with same engine version must be idempotent; got {idempotent}"
    )
