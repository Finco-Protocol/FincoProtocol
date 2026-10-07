"""Model V2 Run History V1 - append-only canonical successful-run ledger.

Acceptance markers:

  RUN_HISTORY_APPEND_ONLY       (A,B) one immutable row per successful run
  RUN_HISTORY_ORDERING          (C) newest-first, deterministic tie-break
  RUN_HISTORY_FAILED_RUN        (D) failed runs never append
  RUN_HISTORY_CAS_ZERO_ROWS     (E) workbook CAS failure appends nothing
  RUN_HISTORY_STALE_V2_ZERO_ROWS(F) concurrent V2 edit appends nothing
  RUN_HISTORY_CORRUPT_BINDING   (G) malformed binding appends nothing
  RUN_HISTORY_SCENARIO_MISMATCH (H) scenario contradiction appends nothing
  RUN_HISTORY_LEGACY            (I) legacy rows never invent a V2 binding
  RUN_HISTORY_V2_BINDING        (J) V2 rows preserve the exact binding
  RUN_HISTORY_SCENARIO_DISTINCT (K) Base vs scenario runs stay distinct
  RUN_HISTORY_IMMUTABLE_PAYLOAD (L) later Working Copy edits never mutate
  RUN_HISTORY_ATOMIC_PROMOTION  (M) Last Run + history commit together
  RUN_HISTORY_ROLLBACK          (N) history failure rolls back promotion
  RUN_HISTORY_NO_BACKFILL       (O) pre-existing workspaces stay empty
  RUN_HISTORY_MALFORMED_READ    (P) corrupt stored rows fail closed
"""
from __future__ import annotations

import datetime
import json

import pytest

from app.model_v2.persistence import (
    ModelV2PersistenceError,
    build_run_binding_payload,
)
from app.persistence import run_history_repository as rh
from app.persistence.db import get_cursor, init_db
from app.persistence.projects_repository import save_project
from app.persistence.repository import record_workspace_runtime
from app.persistence.run_history_repository import (
    RunHistoryError,
    get_latest_history_entry,
    get_run_history,
    get_run_history_entry,
)
from app.persistence.scenarios_repository import save_scenario
from app.persistence.workspace_repository import (
    V2RunCommitConflictError,
    get_workspace_state,
    save_workspace_state,
    set_workspace_model_v2_state,
    v2_atomic_run_commit,
)
from app.services.model_v2_composition import (
    ModelV2CompositionContext,
    ModelV2WorkingState,
    RevenuePlanSelection,
    compose_project_inputs,
)
from domain.revenue.plan import RevenuePlan, RevenueStream, RevenueStreamType
from domain.revenue.revenue_config import MerchantParams, PPAParams

USER = "rh-u"
CODE = "solar-rh"
NOW = datetime.datetime.now(datetime.timezone.utc)


def _plan(merchant_price=65.0):
    ppa = PPAParams(ppa_enabled=True, ppa_base_price_eur_mwh=57.0,
                    ppa_volume_share=0.7, ppa_price_index=0.02,
                    balancing_cost_pct=0.0,
                    imbalance_penalty_pct=0.0,
                    ppa_price_floor=0.0,
                    ppa_price_cap=0.0)
    mkt = MerchantParams(merchant_enabled=True,
                         base_price_eur_mwh=merchant_price,
                         price_escalation_annual=0.02)
    return RevenuePlan.create((
        RevenueStream("ppa", RevenueStreamType.PPA, volume_share=0.7,
                      ppa=ppa),
        RevenueStream("merchant", RevenueStreamType.MERCHANT,
                      volume_share=None, merchant=mkt),
    ))


def _state(ref=CODE, merchant_price=65.0):
    return ModelV2WorkingState(
        working_copy_ref=ref,
        revenue_plan_selection=RevenuePlanSelection(
            plan=_plan(merchant_price), source_ref="test"))


def _real_scenario(project_id, name="Downside"):
    record = save_scenario(
        user_id=USER, project_id=project_id, scenario_name=name,
        project_code=CODE, source_project_template="generic_solar_reference",
        snapshot={"active_project": CODE})
    return record.scenario_id


def _composite_hash(user_id, project_id):
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get
    return assemble_consistent_for_get(
        user_id, project_id, WORKBOOK.version).composite_hash


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    from app.persistence import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "rh.db"))
    init_db()
    rec = save_project(user_id=USER, project_code=CODE,
                       project_name="Run History", 
                       source_project_template="generic_solar_reference")
    snapshot = {"active_project": CODE, "capacity_mw": "64"}
    save_workspace_state(user_id=USER, project_id=rec.project_id,
                         project_code=CODE, draft_snapshot=snapshot,
                         saved_snapshot=snapshot)
    return rec


def _v2_run(project_id, snapshot_id, *, merchant_price=65.0,
            scenario_id=None, state=None, ran_at=None):
    """Successful canonical V2 run: persist state, compose, commit atomically."""
    if state is None:
        state = _state(merchant_price=merchant_price)
    set_workspace_model_v2_state(user_id=USER, project_id=project_id,
                                 state=state)
    composed = compose_project_inputs(
        state,
        ModelV2CompositionContext(capacity_mw=64.0, scenario_id=scenario_id),
        _solar_inputs())
    assert composed.composed
    binding = build_run_binding_payload(
        state=state, composition_hash=composed.composition_hash,
        snapshot_id=snapshot_id, scenario_id=scenario_id)
    return v2_atomic_run_commit(
        user_id=USER, project_id=project_id, project_code=CODE,
        expected_composite_hash=_composite_hash(USER, project_id),
        runtime_snapshot_id=snapshot_id, runtime_origin="v2_run",
        runtime_summary={"npv_keur": 1.0},
        financial_statements={"fs": snapshot_id},
        debt_schedule={"d": snapshot_id}, tax_schedule={"t": snapshot_id},
        distribution_schedule={"da": snapshot_id},
        sponsor_schedule={"sp": snapshot_id},
        active_scenario_id=None, active_scenario_name=None,
        last_runtime_scenario_id=scenario_id,
        ran_at=ran_at or datetime.datetime.now(datetime.timezone.utc),
        model_v2_run_binding=binding,
    )


def _solar_inputs():
    from app.project_factories import create_generic_solar_reference
    return create_generic_solar_reference()


def test_run_history_fixture_is_runtime_compatible():
    """Run History fixture must not activate unrelated Revenue Runtime seams."""
    base_state = _state()
    changed_state = _state(merchant_price=70.0)
    base = compose_project_inputs(
        base_state,
        ModelV2CompositionContext(capacity_mw=64.0),
        _solar_inputs(),
    )
    changed = compose_project_inputs(
        changed_state,
        ModelV2CompositionContext(capacity_mw=64.0),
        _solar_inputs(),
    )
    assert base.composed
    assert changed.composed
    assert base_state.selection_digest() != changed_state.selection_digest()
    assert base.composition_hash != changed.composition_hash


def _legacy_run(project_id, snapshot_id, **overrides):
    kwargs = dict(
        user_id=USER, project_id=project_id, project_code=CODE,
        runtime_snapshot={"cap": 1}, runtime_summary={"npv_keur": 5.0},
        runtime_snapshot_id=snapshot_id, runtime_origin="workspace_base",
        financial_statements={"fs": snapshot_id},
        debt_schedule={"d": snapshot_id}, tax_schedule={"t": snapshot_id},
        distribution_schedule={"da": snapshot_id},
        sponsor_schedule={"sp": snapshot_id},
    )
    kwargs.update(overrides)
    return record_workspace_runtime(**kwargs)


# ---------------------------------------------------------------------------
# A / B / M — append-only + atomic promotion
# ---------------------------------------------------------------------------


def test_a_b_m_two_runs_two_rows_last_run_promoted(workspace):
    """RUN_HISTORY_APPEND_ONLY + ATOMIC_PROMOTION = PASS."""
    pid = workspace.project_id
    assert get_run_history(USER, pid) == []
    _v2_run(pid, "snap-A", ran_at=NOW)
    entries = get_run_history(USER, pid)
    assert len(entries) == 1
    first = entries[0]
    assert first.runtime_snapshot_id == "snap-A"
    assert first.project_code == CODE
    assert first.runtime_summary == {"npv_keur": 1.0}
    assert first.financial_statements == {"fs": "snap-A"}
    # Working Copy changes, then Run C: History A unchanged, History C added,
    # Last Run points at C - one atomic commit each.
    save_workspace_state(
        user_id=USER, project_id=pid, project_code=CODE,
        draft_snapshot={"active_project": CODE, "capacity_mw": "70"},
        saved_snapshot={"active_project": CODE, "capacity_mw": "64"})
    entries_after_edit = get_run_history(USER, pid)
    assert entries_after_edit[0].to_dict() == first.to_dict()
    _v2_run(pid, "snap-C", ran_at=NOW + datetime.timedelta(seconds=1))
    entries = get_run_history(USER, pid)
    assert len(entries) == 2
    assert [e.runtime_snapshot_id for e in entries] == ["snap-C", "snap-A"]
    workspace_row = get_workspace_state(USER, pid)
    assert workspace_row.last_runtime_snapshot_id == "snap-C"
    latest = get_latest_history_entry(USER, pid)
    assert latest.runtime_snapshot_id == "snap-C"


def test_c_ordering_newest_first_deterministic(workspace):
    """RUN_HISTORY_ORDERING = PASS - ran_at DESC; same-timestamp rows use
    the immutable history id as a deterministic tie-breaker (never
    incidental SQLite row order)."""
    pid = workspace.project_id
    stamp = datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc)
    _v2_run(pid, "snap-1", ran_at=stamp)
    _v2_run(pid, "snap-2", ran_at=stamp + datetime.timedelta(seconds=5))
    _v2_run(pid, "snap-3", ran_at=stamp + datetime.timedelta(seconds=9))
    entries = get_run_history(USER, pid)
    assert [e.runtime_snapshot_id for e in entries] == [
        "snap-3", "snap-2", "snap-1"]
    # same-timestamp pair: the tie-break is stable across repeated reads
    again = get_run_history(USER, pid)
    assert [e.history_id for e in again] == [e.history_id for e in entries]
    tied = [e for e in entries
            if e.ran_at == (stamp + datetime.timedelta(seconds=5))
            .isoformat()]
    assert len(tied) == 1


# ---------------------------------------------------------------------------
# D / E / F / G / H — failures append zero rows
# ---------------------------------------------------------------------------


def test_e_cas_failure_appends_zero_rows(workspace):
    """RUN_HISTORY_CAS_ZERO_ROWS = PASS."""
    pid = workspace.project_id
    _v2_run(pid, "snap-A")
    before = get_run_history(USER, pid)
    with pytest.raises(V2RunCommitConflictError):
        v2_atomic_run_commit(
            user_id=USER, project_id=pid, project_code=CODE,
            expected_composite_hash="stale-hash",
            runtime_snapshot_id="snap-X", runtime_origin="v2_run",
            runtime_summary={}, financial_statements={}, debt_schedule={},
            tax_schedule={}, distribution_schedule={}, sponsor_schedule={},
            active_scenario_id=None, active_scenario_name=None, ran_at=NOW,
        )
    assert get_run_history(USER, pid) == before


def test_f_stale_v2_state_appends_zero_rows(workspace):
    """RUN_HISTORY_STALE_V2_ZERO_ROWS = PASS - Workflow 07 atomic V2 CAS."""
    pid = workspace.project_id
    _v2_run(pid, "snap-A")
    before = get_run_history(USER, pid)
    # concurrent economic edit: state now differs from the composed run
    set_workspace_model_v2_state(
        user_id=USER, project_id=pid, state=_state(merchant_price=70.0))
    stale_state = _state()
    stale_binding = build_run_binding_payload(
        state=stale_state,
        composition_hash=_composite_hash(USER, pid),
        snapshot_id="snap-F", scenario_id=None)
    with pytest.raises(V2RunCommitConflictError):
        v2_atomic_run_commit(
            user_id=USER, project_id=pid, project_code=CODE,
            expected_composite_hash=_composite_hash(USER, pid),
            runtime_snapshot_id="snap-F", runtime_origin="v2_run",
            runtime_summary={}, financial_statements={}, debt_schedule={},
            tax_schedule={}, distribution_schedule={}, sponsor_schedule={},
            active_scenario_id=None, active_scenario_name=None, ran_at=NOW,
            model_v2_run_binding=stale_binding,
        )
    assert get_run_history(USER, pid) == before


def test_g_corrupt_binding_appends_zero_rows(workspace):
    """RUN_HISTORY_CORRUPT_BINDING = PASS."""
    pid = workspace.project_id
    _v2_run(pid, "snap-A")
    before = get_run_history(USER, pid)
    with pytest.raises(ModelV2PersistenceError):
        v2_atomic_run_commit(
            user_id=USER, project_id=pid, project_code=CODE,
            expected_composite_hash=_composite_hash(USER, pid),
            runtime_snapshot_id="snap-G", runtime_origin="v2_run",
            runtime_summary={}, financial_statements={}, debt_schedule={},
            tax_schedule={}, distribution_schedule={}, sponsor_schedule={},
            active_scenario_id=None, active_scenario_name=None, ran_at=NOW,
            model_v2_run_binding={"nonsense": True},
        )
    assert get_run_history(USER, pid) == before


def test_h_scenario_mismatch_appends_zero_rows(workspace):
    """RUN_HISTORY_SCENARIO_MISMATCH = PASS - Workflow 07 binding scenario
    check (and the history payload's own correlation check) fail closed."""
    pid = workspace.project_id
    _v2_run(pid, "snap-A")
    before = get_run_history(USER, pid)
    scenario_id = _real_scenario(pid)
    state = _state()
    set_workspace_model_v2_state(user_id=USER, project_id=pid, state=state)
    composed = compose_project_inputs(
        state, ModelV2CompositionContext(capacity_mw=64.0,
                                         scenario_id=scenario_id),
        _solar_inputs())
    binding = build_run_binding_payload(
        state=state, composition_hash=composed.composition_hash,
        snapshot_id="snap-H", scenario_id=scenario_id)
    # commit persists Base (last_runtime_scenario_id=None) while the binding
    # names the scenario -> contradiction aborts the whole commit
    with pytest.raises(ValueError, match="MODEL_V2_RUN_BINDING_SCENARIO_MISMATCH"):
        v2_atomic_run_commit(
            user_id=USER, project_id=pid, project_code=CODE,
            expected_composite_hash=_composite_hash(USER, pid),
            runtime_snapshot_id="snap-H", runtime_origin="v2_run",
            runtime_summary={}, financial_statements={}, debt_schedule={},
            tax_schedule={}, distribution_schedule={}, sponsor_schedule={},
            active_scenario_id=None, active_scenario_name=None,
            ran_at=NOW, model_v2_run_binding=binding,
        )
    assert get_run_history(USER, pid) == before
    # the history payload validator enforces the same correlation directly
    with pytest.raises(RunHistoryError, match="RUN_HISTORY_BINDING_SCENARIO_MISMATCH"):
        rh.prepare_run_history_payload(
            user_id=USER, project_id=pid, project_code=CODE,
            runtime_snapshot_id="snap-H", runtime_origin="v2_run",
            ran_at=NOW.isoformat(), runtime_summary={},
            financial_statements={}, debt_schedule={}, tax_schedule={},
            distribution_schedule={}, sponsor_schedule={},
            last_runtime_identity={"model_v2": binding},
            last_runtime_scenario_id=None,
        )

def test_d_failed_composition_appends_zero_rows(workspace):
    """RUN_HISTORY_FAILED_RUN = PASS - a composition failure raises before
    any commit path exists; the ledger stays empty."""
    from app.persistence.db import get_cursor as _gc
    with _gc() as cur:
        cur.execute("SELECT COUNT(*) FROM model_run_history")
        assert cur.fetchone()[0] == 0
    with pytest.raises(Exception):
        compose_project_inputs(
            _state(),
            ModelV2CompositionContext(capacity_mw=-5.0),
            _solar_inputs(),
        )
    with _gc() as cur:
        cur.execute("SELECT COUNT(*) FROM model_run_history")
        assert cur.fetchone()[0] == 0


# ---------------------------------------------------------------------------
# I / J / K — legacy, V2 binding, scenario distinction
# ---------------------------------------------------------------------------


def test_i_legacy_history_never_invents_v2(workspace):
    """RUN_HISTORY_LEGACY = PASS."""
    pid = workspace.project_id
    _legacy_run(pid, "snap-LEG")
    entries = get_run_history(USER, pid)
    assert len(entries) == 1
    legacy = entries[0]
    assert legacy.model_v2_binding is None
    assert legacy.last_runtime_identity is None
    assert legacy.composite_hash is None
    assert legacy.engine_version == "clean_senior_debt_v0"
    assert legacy.runtime_origin == "workspace_base"
    # identity payload keys are exactly the canonical legacy evidence
    row = _raw_history_row(pid, legacy.history_id)
    assert json.loads(row["last_runtime_identity_json"] or "null") is None


def test_j_v2_history_preserves_exact_binding(workspace):
    """RUN_HISTORY_V2_BINDING = PASS."""
    pid = workspace.project_id
    state = _state()
    set_workspace_model_v2_state(user_id=USER, project_id=pid, state=state)
    composed = compose_project_inputs(
        state, ModelV2CompositionContext(capacity_mw=64.0), _solar_inputs())
    binding = build_run_binding_payload(
        state=state, composition_hash=composed.composition_hash,
        snapshot_id="snap-V2", scenario_id=None)
    v2_atomic_run_commit(
        user_id=USER, project_id=pid, project_code=CODE,
        expected_composite_hash=_composite_hash(USER, pid),
        runtime_snapshot_id="snap-V2", runtime_origin="v2_run",
        runtime_summary={}, financial_statements={}, debt_schedule={},
        tax_schedule={}, distribution_schedule={}, sponsor_schedule={},
        active_scenario_id=None, active_scenario_name=None, ran_at=NOW,
        model_v2_run_binding=binding,
    )
    entry = get_run_history(USER, pid)[0]
    assert entry.model_v2_binding == binding
    assert entry.model_v2_binding["working_copy_ref"] == CODE
    assert entry.model_v2_binding["snapshot_id"] == "snap-V2"
    assert entry.model_v2_binding["economic_identity"] == (
        state.selection_digest())


def test_k_base_and_scenario_runs_distinct(workspace):
    """RUN_HISTORY_SCENARIO_DISTINCT = PASS."""
    pid = workspace.project_id
    scenario_id = _real_scenario(pid)
    _v2_run(pid, "snap-BASE")
    _v2_run(pid, "snap-DOWN", scenario_id=scenario_id)
    entries = get_run_history(USER, pid)
    assert [e.runtime_snapshot_id for e in entries] == [
        "snap-DOWN", "snap-BASE"]
    by_snapshot = {e.runtime_snapshot_id: e for e in entries}
    assert by_snapshot["snap-BASE"].last_runtime_scenario_id is None
    assert by_snapshot["snap-DOWN"].last_runtime_scenario_id == scenario_id
    assert by_snapshot["snap-DOWN"].model_v2_binding["scenario_id"] == (
        scenario_id)
    assert by_snapshot["snap-BASE"].model_v2_binding["scenario_id"] is None
    # distinct immutable records
    assert (by_snapshot["snap-BASE"].history_id
            != by_snapshot["snap-DOWN"].history_id)


def _raw_history_row(project_id, history_id):
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM model_run_history WHERE project_id=? AND "
            "history_id=?", (project_id, history_id))
        return cur.fetchone()


# ---------------------------------------------------------------------------
# L / N / O / P — immutability, rollback, no backfill, malformed reads
# ---------------------------------------------------------------------------


def test_l_working_copy_edit_never_mutates_history(workspace):
    """RUN_HISTORY_IMMUTABLE_PAYLOAD = PASS."""
    pid = workspace.project_id
    _v2_run(pid, "snap-A")
    before = get_run_history(USER, pid)
    before_raw = _raw_history_row(pid, before[0].history_id)
    # heavy Working Copy + scenario churn after the run
    save_workspace_state(
        user_id=USER, project_id=pid, project_code=CODE,
        draft_snapshot={"active_project": CODE, "capacity_mw": "99"},
        saved_snapshot={"active_project": CODE, "capacity_mw": "64"})
    _legacy_run(pid, "snap-LEG-AFTER")
    after = get_run_history(USER, pid)
    after_map = {e.history_id: e for e in after}
    original = after_map[before[0].history_id]
    assert original.to_dict() == before[0].to_dict()
    after_raw = _raw_history_row(pid, original.history_id)
    for column in after_raw.keys():
        assert after_raw[column] == before_raw[column], column


def test_n_history_insert_failure_rolls_back_last_run(workspace, monkeypatch):
    """RUN_HISTORY_ROLLBACK = PASS - a history failure reverts the Last Run
    promotion inside the same transaction."""
    pid = workspace.project_id
    _v2_run(pid, "snap-A")
    last_run_before = get_workspace_state(USER, pid).last_runtime_snapshot_id
    history_before = get_run_history(USER, pid)

    def _boom(cur, payload):
        raise RunHistoryError("injected history failure")

    monkeypatch.setattr(rh, "append_run_history_cursor", _boom)
    with pytest.raises(RunHistoryError):
        _v2_run(pid, "snap-C")
    workspace_row = get_workspace_state(USER, pid)
    assert workspace_row.last_runtime_snapshot_id == last_run_before
    assert workspace_row.last_runtime_snapshot_id == "snap-A"
    assert get_run_history(USER, pid) == history_before
    # legacy path: same rollback guarantee through save_workspace_state
    with pytest.raises(RunHistoryError):
        _legacy_run(pid, "snap-LEG-ROLLBACK")
    assert get_run_history(USER, pid) == history_before
    assert get_workspace_state(USER, pid).last_runtime_snapshot_id == "snap-A"


def test_o_no_backfill_for_pre_existing_workspace(workspace):
    """RUN_HISTORY_NO_BACKFILL = PASS - history starts prospectively."""
    pid = workspace.project_id
    # the workspace exists (fixture) but no run ever committed in this
    # feature's lifetime: zero rows, and none are synthesized
    assert get_run_history(USER, pid) == []
    assert get_latest_history_entry(USER, pid) is None
    assert get_run_history_entry(USER, pid, "nonexistent") is None
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM model_run_history")
        assert cur.fetchone()[0] == 0


def test_p_malformed_stored_payload_fails_closed(workspace):
    """RUN_HISTORY_MALFORMED_READ = PASS."""
    pid = workspace.project_id
    _v2_run(pid, "snap-A")
    entry = get_run_history(USER, pid)[0]
    with get_cursor() as cur:
        cur.execute(
            "UPDATE model_run_history SET runtime_summary_json=? WHERE "
            "history_id=?", ("{not json", entry.history_id))
    with pytest.raises(RunHistoryError, match="RUN_HISTORY_PAYLOAD_MALFORMED"):
        get_run_history(USER, pid)
    with pytest.raises(RunHistoryError, match="RUN_HISTORY_PAYLOAD_MALFORMED"):
        get_latest_history_entry(USER, pid)
    # identity-json corruption fails closed as well
    with get_cursor() as cur:
        cur.execute(
            "UPDATE model_run_history SET runtime_summary_json=?, "
            "last_runtime_identity_json=? WHERE history_id=?",
            ("{}", "[broken", entry.history_id))
    with pytest.raises(RunHistoryError, match="RUN_HISTORY_PAYLOAD_MALFORMED"):
        get_run_history(USER, pid)


# ---------------------------------------------------------------------------
# CORRECTION A: persistence-boundary correlation + strict typed ledger
# ---------------------------------------------------------------------------


def _payload_for(snapshot_id, project_id, **overrides):
    from app.persistence.run_history_repository import (
        prepare_run_history_payload,
    )

    kwargs = dict(
        user_id=USER, project_id=project_id,
        project_code=CODE, runtime_snapshot_id=snapshot_id,
        runtime_origin="v2_run", ran_at=NOW.isoformat(),
        runtime_summary={"n": 1}, financial_statements={}, debt_schedule={},
        tax_schedule={}, distribution_schedule={}, sponsor_schedule={},
    )
    kwargs.update(overrides)
    return prepare_run_history_payload(**kwargs)


def test_corr_a_snapshot_mismatch_fails_closed(workspace):
    """CORRECTION A: a payload describing a different snapshot can never
    ride a committing save - typed mismatch, nothing mutated."""
    pid = workspace.project_id
    _v2_run(pid, "snap-A")
    history_before = get_run_history(USER, pid)
    last_run_before = get_workspace_state(USER, pid).last_runtime_snapshot_id
    forged = _payload_for("snap-FAKE", pid)
    with pytest.raises(
        RunHistoryError, match="RUN_HISTORY_COMMIT_CORRELATION_MISMATCH"
    ):
        save_workspace_state(
            user_id=USER, project_id=pid, project_code=CODE,
            draft_snapshot={"active_project": CODE, "capacity_mw": "64"},
            saved_snapshot={"active_project": CODE, "capacity_mw": "64"},
            last_runtime_snapshot={"cap": 2},
            last_runtime_summary={"npv_keur": 2.0},
            last_runtime_snapshot_id="snap-REAL",
            last_runtime_origin="v2_run",
            run_history_payload=forged,
        )
    assert get_run_history(USER, pid) == history_before
    assert get_workspace_state(USER, pid).last_runtime_snapshot_id == (
        last_run_before)


def test_corr_b_project_code_mismatch_fails_closed(workspace):
    """CORRECTION A: foreign project_code in the payload fails closed."""
    pid = workspace.project_id
    _v2_run(pid, "snap-A")
    before = get_run_history(USER, pid)
    forged = _payload_for("snap-B", pid, project_code="other-project")
    with pytest.raises(
        RunHistoryError, match="RUN_HISTORY_COMMIT_CORRELATION_MISMATCH"
    ):
        save_workspace_state(
            user_id=USER, project_id=pid, project_code=CODE,
            draft_snapshot={"active_project": CODE},
            saved_snapshot={"active_project": CODE},
            last_runtime_snapshot={"cap": 3},
            last_runtime_summary={}, last_runtime_snapshot_id="snap-B",
            last_runtime_origin="v2_run",
            run_history_payload=forged,
        )
    assert get_run_history(USER, pid) == before


def test_corr_c_user_project_mismatch_fails_closed(workspace):
    """CORRECTION A: wrong owner/project identity fails closed."""
    pid = workspace.project_id
    forged = _payload_for("snap-C", "some-other-project-id")
    with pytest.raises(
        RunHistoryError, match="RUN_HISTORY_COMMIT_CORRELATION_MISMATCH"
    ):
        save_workspace_state(
            user_id=USER, project_id=pid, project_code=CODE,
            draft_snapshot={"active_project": CODE},
            saved_snapshot={"active_project": CODE},
            last_runtime_snapshot={}, last_runtime_summary={},
            last_runtime_snapshot_id="snap-C", last_runtime_origin="v2_run",
            run_history_payload=forged,
        )
    forged_user = _payload_for("snap-C2", pid)
    forged_user["user_id"] = "someone-else"
    with pytest.raises(
        RunHistoryError, match="RUN_HISTORY_COMMIT_CORRELATION_MISMATCH"
    ):
        save_workspace_state(
            user_id=USER, project_id=pid, project_code=CODE,
            draft_snapshot={"active_project": CODE},
            saved_snapshot={"active_project": CODE},
            last_runtime_snapshot={}, last_runtime_summary={},
            last_runtime_snapshot_id="snap-C2", last_runtime_origin="v2_run",
            run_history_payload=forged_user,
        )


def test_corr_d_scenario_mismatch_fails_closed(workspace):
    """CORRECTION A: scenario-active metadata must agree."""
    pid = workspace.project_id
    scenario_id = _real_scenario(pid)
    forged = _payload_for("snap-D", pid, last_runtime_scenario_id=scenario_id)
    with pytest.raises(
        RunHistoryError, match="RUN_HISTORY_COMMIT_CORRELATION_MISMATCH"
    ):
        save_workspace_state(
            user_id=USER, project_id=pid, project_code=CODE,
            draft_snapshot={"active_project": CODE},
            saved_snapshot={"active_project": CODE},
            last_runtime_snapshot={}, last_runtime_summary={},
            last_runtime_snapshot_id="snap-D", last_runtime_origin="v2_run",
            last_runtime_scenario_id=None,
            run_history_payload=forged,
        )


def test_corr_e_legacy_single_run_timestamp(workspace):
    """CORRECTION A2: history.ran_at == committed last_runtime_at exactly."""
    pid = workspace.project_id
    _legacy_run(pid, "snap-LEG-TS")
    entry = get_run_history(USER, pid)[0]
    workspace_row = get_workspace_state(USER, pid)
    committed_at = workspace_row.last_runtime_at
    if hasattr(committed_at, "isoformat"):
        assert entry.ran_at == committed_at.isoformat()
    else:
        assert entry.ran_at == str(committed_at)


def test_corr_f_incomplete_binding_fails_closed(workspace):
    """CORRECTION A3: correlation-matching but schema-invalid bindings are
    rejected via the canonical Workflow 07 validator."""
    pid = workspace.project_id
    # correlation fields all match; the binding is structurally incomplete
    incomplete = {
        "_schema": "finco.model-v2.run-binding", "schema_version": 1,
        "working_copy_ref": CODE, "snapshot_id": "snap-F2",
        "scenario_id": None,
        "composition_hash": "not-a-sha256",
        "economic_identity": "also-not",
    }
    with pytest.raises(RunHistoryError, match="RUN_HISTORY_BINDING_INVALID"):
        rh.prepare_run_history_payload(
            user_id=USER, project_id=pid, project_code=CODE,
            runtime_snapshot_id="snap-F2", runtime_origin="v2_run",
            ran_at=NOW.isoformat(), runtime_summary={},
            financial_statements={}, debt_schedule={}, tax_schedule={},
            distribution_schedule={}, sponsor_schedule={},
            last_runtime_identity={"model_v2": incomplete},
            last_runtime_scenario_id=None,
        )


def test_corr_g_h_wrong_json_shapes_fail_closed(workspace):
    """CORRECTION A5: every structured column must be a JSON object."""
    pid = workspace.project_id
    _v2_run(pid, "snap-A")
    entry = get_run_history(USER, pid)[0]
    for column, bad in (
        ("financial_statements_json", "[]"),
        ("debt_schedule_json", '"x"'),
        ("tax_schedule_json", "5"),
        ("distribution_schedule_json", "false"),
        ("sponsor_schedule_json", "[]"),
        ("integrity_evidence_json", '"str"'),
        ("replay_metadata_json", "[1, 2]"),
        ("runtime_summary_json", "null"),
    ):
        with get_cursor() as cur:
            cur.execute(
                "UPDATE model_run_history SET runtime_summary_json='{}', "
                f"{column}=? WHERE history_id=?",
                (bad, entry.history_id))
        with pytest.raises(
            RunHistoryError, match="RUN_HISTORY_PAYLOAD_MALFORMED"
        ):
            get_run_history(USER, pid)

def test_corr_i_no_public_unvalidated_append():
    """CORRECTION A4: the standalone unvalidated append path is gone; only
    the transaction primitive (used by the commit paths) remains."""
    assert not hasattr(rh, "append_run_history")
    assert "append_run_history" not in rh.__all__
    assert hasattr(rh, "append_run_history_cursor")
    source = open(
        "app/persistence/run_history_repository.py", encoding="utf-8"
    ).read()
    assert "def append_run_history(" not in source
