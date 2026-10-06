"""Model V2 Workflow 07 — canonical run binding + staleness lifecycle.

Acceptance markers:

  MODEL_V2_RUN_BINDING_SUCCESS_A    — a successful canonical run binds the
                                      exact V2 Working Copy economic state
  MODEL_V2_RUN_BINDING_STALENESS    — Working Copy economic edits make the
                                      Last Run stale; revert restores CURRENT
  MODEL_V2_RUN_BINDING_FAILED_RUN_PRESERVATION — composition failure, engine
                                      failure and commit failure never
                                      overwrite the prior successful Last Run
  MODEL_V2_RUN_BINDING_SCENARIO_DISTINCTION — scenario identity rides the
                                      binding without replacing base identity
  MODEL_V2_RUN_BINDING_LEGACY_ISOLATION — legacy runs never invent or erase
                                      V2 state and never carry a V2 binding
  MODEL_V2_SAVE_AS_CLONE_SEMANTICS  — Save As / clone creates a fresh
                                      working-copy identity with NO inherited
                                      V2 state and NO shared mutable objects
"""
from __future__ import annotations

import asyncio
import datetime
import json
import re

import pytest

from app.model_v2.persistence import (
    ModelV2PersistenceError,
    ModelV2RunStaleness,
    build_run_binding_payload,
    read_workspace_run_binding,
    resolve_model_v2_staleness,
    resolve_workspace_model_v2_staleness,
    working_state_from_json,
)
from app.persistence.db import init_db
from app.persistence.projects_repository import save_project
from app.persistence.workspace_repository import (
    V2RunCommitConflictError,
    get_workspace_model_v2_state,
    get_workspace_state,
    set_workspace_model_v2_state,
    v2_atomic_run_commit,
)
from app.services.model_v2_composition import (
    CompositionErrorCode,
    CompositionStatus,
    ModelV2CompositionContext,
    ModelV2WorkingState,
    RevenuePlanSelection,
    compose_project_inputs,
)
from domain.revenue.plan import RevenuePlan, RevenueStream, RevenueStreamType
from domain.revenue.revenue_config import MerchantParams, PPAParams

USER = "wf07-u"
CODE = "solar-64"


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def _plan(merchant_price=65.0, ppa_price=57.0):
    ppa = PPAParams(ppa_enabled=True, ppa_base_price_eur_mwh=ppa_price,
                    ppa_term_years=15, ppa_volume_share=0.7, ppa_price_index=0.02)
    mkt = MerchantParams(merchant_enabled=True, base_price_eur_mwh=merchant_price,
                         price_escalation_annual=0.02)
    return RevenuePlan.create((
        RevenueStream("ppa", RevenueStreamType.PPA, volume_share=0.7,
                      ppa=ppa, term_years=15),
        RevenueStream("merchant", RevenueStreamType.MERCHANT,
                      volume_share=None, merchant=mkt),
    ))


def _state(ref=CODE, **plan_kwargs):
    return ModelV2WorkingState(
        working_copy_ref=ref,
        revenue_plan_selection=RevenuePlanSelection(
            plan=_plan(**plan_kwargs), source_ref="test"))


def _composite_hash(user_id: str, project_id: str) -> str:
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get
    return assemble_consistent_for_get(
        user_id, project_id, WORKBOOK.version).composite_hash


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    from app.persistence import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "wf07.db"))
    init_db()
    rec = save_project(user_id=USER, project_code=CODE, project_name="Solar 64",
                       source_project_template="generic_solar_reference")
    from app.persistence.workspace_repository import save_workspace_state
    snapshot = {"active_project": CODE, "capacity_mw": "64"}
    save_workspace_state(user_id=USER, project_id=rec.project_id,
                         project_code=CODE, draft_snapshot=snapshot,
                         saved_snapshot=snapshot)
    return rec


def _run_and_commit(project_id, *, state, snapshot_id, scenario_id=None,
                    ran_at=None):
    """Successful canonical run: persist the Working Copy state, compose
    (with a real base ProjectInputs), then commit atomically with the
    binding — mirroring the canonical V2 pipeline order."""
    from app.project_factories import create_generic_solar_reference

    set_workspace_model_v2_state(user_id=USER, project_id=project_id, state=state)
    composed = compose_project_inputs(
        state, ModelV2CompositionContext(capacity_mw=64.0,
                                         scenario_id=scenario_id),
        create_generic_solar_reference())
    assert composed.composed
    binding = build_run_binding_payload(
        state=state, composition_hash=composed.composition_hash,
        snapshot_id=snapshot_id, scenario_id=scenario_id)
    return v2_atomic_run_commit(
        user_id=USER, project_id=project_id, project_code=CODE,
        expected_composite_hash=_composite_hash(USER, project_id),
        runtime_snapshot_id=snapshot_id, runtime_origin="v2_run",
        runtime_summary={"npv_keur": 1.0},
        financial_statements={}, debt_schedule={}, tax_schedule={},
        distribution_schedule={}, sponsor_schedule={},
        active_scenario_id=None, active_scenario_name=None,
        ran_at=ran_at or datetime.datetime.now(datetime.timezone.utc),
        model_v2_run_binding=binding,
    ), composed


# ---------------------------------------------------------------------------
# SUCCESS A — successful run binds W1
# ---------------------------------------------------------------------------


class TestSuccessA:
    def test_successful_run_binds_working_copy_state(self, workspace):
        w1 = _state()
        record, composed = _run_and_commit(workspace.project_id, state=w1,
                                           snapshot_id="snap-A")
        binding = read_workspace_run_binding(record.last_runtime_identity)
        assert binding is not None
        assert binding["working_copy_ref"] == CODE
        assert binding["composition_hash"] == composed.composition_hash
        assert binding["economic_identity"] == w1.selection_digest()
        # the run identity stays the canonical authority
        assert record.last_runtime_snapshot_id == "snap-A"
        assert record.last_runtime_composite_hash == _composite_hash(USER, workspace.project_id)
        assert record.any_run_committed is True
        # staleness: not stale right after the run
        current = get_workspace_model_v2_state(USER, workspace.project_id)
        result = resolve_model_v2_staleness(current_state=current, run_binding=binding)
        assert result.state is ModelV2RunStaleness.CURRENT

    def test_engine_version_recorded_alongside_binding(self, workspace):
        from financial_engine.version import ENGINE_VERSION
        record, _ = _run_and_commit(workspace.project_id, state=_state(),
                                    snapshot_id="snap-A2")
        assert record.last_runtime_identity["engine_version"] == str(ENGINE_VERSION)


# ---------------------------------------------------------------------------
# EDIT → STALE; FAILED B → preserved; REVERT → CURRENT; SUCCESS C → atomic
# ---------------------------------------------------------------------------


class TestLifecycleMatrix:
    def test_full_matrix_success_edit_failure_revert_success(self, workspace):
        w1 = _state()
        record_a, composed_a = _run_and_commit(
            workspace.project_id, state=w1, snapshot_id="snap-A")

        # EDIT: Working Copy changes economically to W2
        w2 = _state(merchant_price=70.0)
        set_workspace_model_v2_state(user_id=USER,
                                     project_id=workspace.project_id, state=w2)
        record = get_workspace_state(USER, workspace.project_id)
        assert record.last_runtime_snapshot_id == "snap-A"  # Last Run = A
        assert resolve_model_v2_staleness(
            current_state=w2,
            run_binding=read_workspace_run_binding(record.last_runtime_identity),
        ).state is ModelV2RunStaleness.STALE

        # FAILED B: the run against W2 fails during the commit window (the
        # workbook changed under the run — CAS refuses; nothing is written)
        with pytest.raises(V2RunCommitConflictError):
            v2_atomic_run_commit(
                user_id=USER, project_id=workspace.project_id, project_code=CODE,
                expected_composite_hash="stale" + "0" * 60,
                runtime_snapshot_id="snap-B", runtime_origin="v2_run",
                runtime_summary={}, financial_statements={}, debt_schedule={},
                tax_schedule={}, distribution_schedule={}, sponsor_schedule={},
                active_scenario_id=None, active_scenario_name=None,
                ran_at=datetime.datetime.now(datetime.timezone.utc),
                model_v2_run_binding=build_run_binding_payload(
                    state=w2, composition_hash="b" * 64,
                    snapshot_id="snap-B"),
            )
        record = get_workspace_state(USER, workspace.project_id)
        # Last Run remains A — never a partial or failed run
        assert record.last_runtime_snapshot_id == "snap-A"
        assert record.last_runtime_identity["model_v2"]["composition_hash"] \
            == composed_a.composition_hash
        assert resolve_model_v2_staleness(
            current_state=w2,
            run_binding=read_workspace_run_binding(record.last_runtime_identity),
        ).state is ModelV2RunStaleness.STALE  # stale remains true

        # REVERT: Working Copy economically returns to W1
        set_workspace_model_v2_state(user_id=USER,
                                     project_id=workspace.project_id, state=w1)
        record = get_workspace_state(USER, workspace.project_id)
        assert resolve_model_v2_staleness(
            current_state=get_workspace_model_v2_state(USER, workspace.project_id),
            run_binding=read_workspace_run_binding(record.last_runtime_identity),
        ).state is ModelV2RunStaleness.CURRENT

        # SUCCESS C: W2 successful run atomically becomes the Last Run
        set_workspace_model_v2_state(user_id=USER,
                                     project_id=workspace.project_id, state=w2)
        record_c, composed_c = _run_and_commit(
            workspace.project_id, state=w2, snapshot_id="snap-C")
        assert record_c.last_runtime_snapshot_id == "snap-C"
        assert record_c.last_runtime_identity["model_v2"]["composition_hash"] \
            == composed_c.composition_hash
        assert record_c.last_runtime_identity["model_v2"]["composition_hash"] \
            != composed_a.composition_hash
        assert resolve_model_v2_staleness(
            current_state=w2,
            run_binding=read_workspace_run_binding(record_c.last_runtime_identity),
        ).state is ModelV2RunStaleness.CURRENT

    def test_composition_failure_never_reaches_the_commit(self, workspace):
        """An unsupported revenue stream fails composition BEFORE any engine
        execution; the prior successful Last Run must remain untouched."""
        record_a, _ = _run_and_commit(workspace.project_id, state=_state(),
                                      snapshot_id="snap-A")

        # an enabled FIT_PREMIUM overlay plan composes into a FAILED result
        from domain.revenue.revenue_config import FeedInTariffParams

        mkt = MerchantParams(merchant_enabled=True, base_price_eur_mwh=65.0)
        bad_plan = RevenuePlan.create((
            RevenueStream("merchant", RevenueStreamType.MERCHANT,
                          volume_share=None, merchant=mkt),
            RevenueStream("prem", RevenueStreamType.FIT_PREMIUM,
                          volume_share=1.0,
                          fit=FeedInTariffParams(
                              fit_enabled=True, fit_type="premium",
                              premium_eur_mwh=12.0),
                          reference_stream_id="merchant"),
        ))
        bad_state = ModelV2WorkingState(
            working_copy_ref=CODE,
            revenue_plan_selection=RevenuePlanSelection(plan=bad_plan))
        from app.project_factories import create_generic_solar_reference
        # composition FAILS CLOSED by raising — a failed composition can
        # never produce Last Run inputs, so the pipeline can never commit it
        from app.services.model_v2_composition import RevenuePlanBridgeError
        with pytest.raises(RevenuePlanBridgeError) as excinfo:
            compose_project_inputs(
                bad_state, ModelV2CompositionContext(capacity_mw=64.0),
                create_generic_solar_reference())
        assert excinfo.value.code is CompositionErrorCode.REVENUE_PLAN_STREAM_UNSUPPORTED

        # the pipeline never commits a failed composition
        record = get_workspace_state(USER, workspace.project_id)
        assert record.last_runtime_snapshot_id == "snap-A"
        assert record.last_runtime_identity["model_v2"]["economic_identity"] \
            == _state().selection_digest()

    def test_commit_time_binding_corruption_rolls_back_atomically(self, workspace):
        """A binding that arrives corrupted (or from a foreign working copy)
        aborts the whole commit — the prior successful Last Run survives."""
        _run_and_commit(workspace.project_id, state=_state(),
                        snapshot_id="snap-A")

        binding = build_run_binding_payload(state=_state(merchant_price=70.0),
                                            composition_hash="c" * 64,
                                            snapshot_id="snap-B")
        foreign = dict(binding)
        foreign["working_copy_ref"] = "another-project"
        with pytest.raises(ValueError, match="RUN_BINDING_REF_MISMATCH"):
            v2_atomic_run_commit(
                user_id=USER, project_id=workspace.project_id, project_code=CODE,
                expected_composite_hash=_composite_hash(USER, workspace.project_id),
                runtime_snapshot_id="snap-B", runtime_origin="v2_run",
                runtime_summary={}, financial_statements={}, debt_schedule={},
                tax_schedule={}, distribution_schedule={}, sponsor_schedule={},
                active_scenario_id=None, active_scenario_name=None,
                ran_at=datetime.datetime.now(datetime.timezone.utc),
                model_v2_run_binding=foreign,
            )
        mismatched = dict(build_run_binding_payload(
            state=_state(merchant_price=70.0), composition_hash="c" * 64,
            snapshot_id="snap-OTHER"))
        with pytest.raises(ValueError, match="RUN_BINDING_SNAPSHOT_MISMATCH"):
            v2_atomic_run_commit(
                user_id=USER, project_id=workspace.project_id, project_code=CODE,
                expected_composite_hash=_composite_hash(USER, workspace.project_id),
                runtime_snapshot_id="snap-B", runtime_origin="v2_run",
                runtime_summary={}, financial_statements={}, debt_schedule={},
                tax_schedule={}, distribution_schedule={}, sponsor_schedule={},
                active_scenario_id=None, active_scenario_name=None,
                ran_at=datetime.datetime.now(datetime.timezone.utc),
                model_v2_run_binding=mismatched,
            )
        corrupted = dict(build_run_binding_payload(
            state=_state(merchant_price=70.0), composition_hash="c" * 64,
            snapshot_id="snap-B"))
        corrupted["composition_hash"] = "not-a-digest"
        with pytest.raises(ModelV2PersistenceError):
            v2_atomic_run_commit(
                user_id=USER, project_id=workspace.project_id, project_code=CODE,
                expected_composite_hash=_composite_hash(USER, workspace.project_id),
                runtime_snapshot_id="snap-B", runtime_origin="v2_run",
                runtime_summary={}, financial_statements={}, debt_schedule={},
                tax_schedule={}, distribution_schedule={}, sponsor_schedule={},
                active_scenario_id=None, active_scenario_name=None,
                ran_at=datetime.datetime.now(datetime.timezone.utc),
                model_v2_run_binding=corrupted,
            )
        record = get_workspace_state(USER, workspace.project_id)
        assert record.last_runtime_snapshot_id == "snap-A"
        # dirty flag / saved snapshot not partially mutated by the aborted runs
        assert record.last_runtime_identity["model_v2"]["economic_identity"] \
            == _state().selection_digest()


# ---------------------------------------------------------------------------
# SCENARIO distinction
# ---------------------------------------------------------------------------


class TestScenarioDistinction:
    def test_scenario_run_binding_is_distinct_from_base_run(self, workspace):
        base_record, base_composed = _run_and_commit(
            workspace.project_id, state=_state(), snapshot_id="snap-base")
        scenario_record, scenario_composed = _run_and_commit(
            workspace.project_id, state=_state(), snapshot_id="snap-sc",
            scenario_id="sc-9")
        base_binding = read_workspace_run_binding(
            base_record.last_runtime_identity)
        scenario_binding = read_workspace_run_binding(
            scenario_record.last_runtime_identity)
        # scenario runs through the SAME economic state produce the SAME
        # economic identity (composition hash differs only through the
        # carried scenario context)
        assert scenario_binding["economic_identity"] == \
            base_binding["economic_identity"]
        assert scenario_binding["composition_hash"] != \
            base_binding["composition_hash"]
        assert scenario_binding["scenario_id"] == "sc-9"
        assert base_binding["scenario_id"] is None
        # the base Working Copy state is never mutated by a scenario run
        assert get_workspace_model_v2_state(USER, workspace.project_id) \
            .selection_digest() == _state().selection_digest()

    def test_scenario_distinction_in_documented_payload_shape(self, workspace):
        record, _ = _run_and_commit(workspace.project_id, state=_state(),
                                    snapshot_id="snap-s")
        binding = read_workspace_run_binding(record.last_runtime_identity)
        assert set(binding.keys()) == {
            "_schema", "schema_version", "working_copy_ref",
            "composition_hash", "economic_identity", "scenario_id",
            "snapshot_id",
        }
        assert binding["snapshot_id"] == "snap-s"


# ---------------------------------------------------------------------------
# LEGACY isolation
# ---------------------------------------------------------------------------


class TestLegacyIsolation:
    def test_legacy_run_leaves_v2_state_and_binding_alone(self, workspace):
        set_workspace_model_v2_state(user_id=USER,
                                     project_id=workspace.project_id,
                                     state=_state())
        from app.persistence.repository import record_workspace_runtime
        record_workspace_runtime(
            user_id=USER, project_id=workspace.project_id, project_code=CODE,
            runtime_snapshot={"active_project": CODE},
            runtime_summary={"legacy": True},
            runtime_snapshot_id="legacy-snap",
            runtime_origin="saved_state",
        )
        record = get_workspace_state(USER, workspace.project_id)
        # V2 Working Copy state untouched, no V2 binding on the legacy run
        assert get_workspace_model_v2_state(USER, workspace.project_id) is not None
        assert read_workspace_run_binding(record.last_runtime_identity) is None
        assert "model_v2" not in (record.last_runtime_identity or {})
        assert resolve_model_v2_staleness(
            current_state=get_workspace_model_v2_state(USER, workspace.project_id),
            run_binding=read_workspace_run_binding(record.last_runtime_identity),
        ).state is ModelV2RunStaleness.NOT_APPLICABLE

    def test_legacy_run_after_v2_run_does_not_inherit_the_binding(self, workspace):
        """A legacy run that replaces the Last Run evidence must never be
        misattributed to the previous V2-bound run's economic state: the old
        binding stays on the identity payload but no longer correlates with
        the current Last Run — the workspace-level authority reports
        NOT_APPLICABLE (the legacy freshness authorities govern that run)."""
        w1 = _state()
        _run_and_commit(workspace.project_id, state=w1, snapshot_id="snap-A")
        record = get_workspace_state(USER, workspace.project_id)
        assert read_workspace_run_binding(
            record.last_runtime_identity)["snapshot_id"] == "snap-A"
        assert resolve_workspace_model_v2_staleness(
            workspace_record=record,
            current_state=get_workspace_model_v2_state(
                USER, workspace.project_id),
        ).state is ModelV2RunStaleness.CURRENT

        # a legacy run replaces the Last Run evidence (the identity payload,
        # including the old binding, is not part of the legacy write path)
        from app.persistence.repository import record_workspace_runtime
        record_workspace_runtime(
            user_id=USER, project_id=workspace.project_id, project_code=CODE,
            runtime_snapshot={"active_project": CODE},
            runtime_summary={"legacy": True},
            runtime_snapshot_id="legacy-snap",
            runtime_origin="saved_state",
        )
        record = get_workspace_state(USER, workspace.project_id)
        assert record.last_runtime_snapshot_id == "legacy-snap"
        # the stale binding is still on the row but correlation breaks
        assert read_workspace_run_binding(record.last_runtime_identity) is not None
        result = resolve_workspace_model_v2_staleness(
            workspace_record=record,
            current_state=get_workspace_model_v2_state(
                USER, workspace.project_id),
        )
        assert result.state is ModelV2RunStaleness.NOT_APPLICABLE
        assert "older run" in result.reason

    def test_legacy_workspace_never_acquires_v2_state(self, tmp_path, monkeypatch):
        from app.persistence import db
        monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "legacy.db"))
        init_db()
        rec = save_project(user_id="legacy-2", project_code="old-plant",
                           project_name="Old Plant",
                           source_project_template="generic_wind_reference")
        from app.persistence.workspace_repository import save_workspace_state
        save_workspace_state(user_id="legacy-2", project_id=rec.project_id,
                             project_code="old-plant",
                             draft_snapshot={"active_project": "old-plant"},
                             saved_snapshot={"active_project": "old-plant"})
        from app.persistence.repository import record_workspace_runtime
        record_workspace_runtime(
            user_id="legacy-2", project_id=rec.project_id,
            project_code="old-plant", runtime_snapshot={"active_project": "old-plant"},
            runtime_summary={}, runtime_snapshot_id="ls-1",
            runtime_origin="workspace_base")
        assert get_workspace_model_v2_state("legacy-2", rec.project_id) is None
        record = get_workspace_state("legacy-2", rec.project_id)
        assert record.model_v2_working_state_json == ""
        assert "model_v2" not in (record.last_runtime_identity or {})


# ---------------------------------------------------------------------------
# SAVE AS / CLONE semantics
# ---------------------------------------------------------------------------


class TestSaveAsCloneSemantics:
    def _save_as(self, source_code):
        from datetime import datetime, timezone
        from types import SimpleNamespace

        from app.persistence.projects_repository import (
            get_project_by_code, save_project,
        )
        from app.persistence.scenarios_repository import (
            get_or_create_base_case_scenario,
        )
        from app.persistence.workspace_repository import save_workspace_state
        from app.services.project_save_as_service import (
            ProjectSaveAsRouteDeps, execute_project_save_as_route,
        )

        deps = ProjectSaveAsRouteDeps(
            get_project_record=lambda *, user_id, project_code:
                get_project_by_code(user_id, project_code),
            save_project=save_project,
            save_workspace_state=lambda **kwargs: save_workspace_state(**kwargs),
            now_utc=lambda: datetime.now(timezone.utc),
            project_record_creation_governance_state=lambda: {
                "g20": "BLOCKED", "r99_r102": "NOT_APPROVED",
                "lender_ready": False},
            workspace_state_initialization_governance_state=lambda: {
                "g20": "BLOCKED", "r99_r102": "NOT_APPROVED",
                "lender_ready": False},
            build_project_replay_metadata=lambda source, project_code: {
                "export_type": "project_duplicated",
                "source_project_code": project_code},
            build_workspace_replay_metadata=lambda source, project_code: {
                "export_type": "workspace_duplicated",
                "source_project_code": project_code},
            is_already_user_project=lambda source:
                source.project_origin == "user_created",
            get_or_create_base_case_scenario=get_or_create_base_case_scenario,
        )
        outcome = asyncio.run(execute_project_save_as_route(
            request=None, project_code=source_code,
            user=SimpleNamespace(user_id=USER), deps=deps))
        assert outcome.status_code == 302, outcome.payload
        return re.search(r"project=([^&]+)", outcome.redirect_url).group(1)

    def test_save_as_starts_fresh_without_v2_state(self, workspace):
        # source has a V2 Working Copy state AND a bound successful run
        w1 = _state()
        _run_and_commit(workspace.project_id, state=w1, snapshot_id="snap-A")

        new_code = self._save_as(CODE)
        new_record = get_workspace_state(USER, workspace.project_id)
        from app.persistence.projects_repository import get_project_by_code
        copied = get_project_by_code(USER, new_code)
        assert copied.project_id != workspace.project_id
        copied_ws = get_workspace_state(USER, copied.project_id)
        # fresh working-copy identity: no V2 selections, no run binding,
        # no Last Run evidence inherited
        assert copied_ws.model_v2_working_state_json == ""
        assert get_workspace_model_v2_state(USER, copied.project_id) is None
        assert read_workspace_run_binding(copied_ws.last_runtime_identity) is None
        assert copied_ws.any_run_committed is False
        # the source keeps its state and binding untouched
        assert get_workspace_model_v2_state(USER, workspace.project_id) \
            .selection_digest() == w1.selection_digest()
        source_ws = get_workspace_state(USER, workspace.project_id)
        assert source_ws.last_runtime_snapshot_id == "snap-A"
        assert read_workspace_run_binding(source_ws.last_runtime_identity) is not None

    def test_clone_selections_are_independent_no_shared_references(self, workspace):
        """Editing a clone's V2 state can never mutate the source project's
        state; restored objects never share mutable nested references."""
        set_workspace_model_v2_state(user_id=USER,
                                     project_id=workspace.project_id,
                                     state=_state())
        new_code = self._save_as(CODE)
        from app.persistence.projects_repository import get_project_by_code
        copied = get_project_by_code(USER, new_code)

        clone_state = _state(ref=new_code, merchant_price=99.0)
        set_workspace_model_v2_state(user_id=USER,
                                     project_id=copied.project_id,
                                     state=clone_state)
        # source unchanged
        assert get_workspace_model_v2_state(USER, workspace.project_id) \
            .selection_digest() == _state().selection_digest()
        # clone carries its own economics
        assert get_workspace_model_v2_state(USER, copied.project_id) \
            .selection_digest() == clone_state.selection_digest()

        # no shared mutable objects across repeated restores
        first = get_workspace_model_v2_state(USER, workspace.project_id)
        second = get_workspace_model_v2_state(USER, workspace.project_id)
        assert first is not second
        assert first.revenue_plan_selection is not second.revenue_plan_selection

    def test_decoded_state_does_not_share_nested_mutable_objects(self, workspace):
        """Twice-decoded V2 states must not alias nested dicts/lists —
        editing one decoded structure must never corrupt stored state."""
        from app.services.cost_template.materialize import CapexSubLinePlan
        from app.services.model_v2_composition import CostTemplateSelection
        from app.services.cost_template.materialize import MaterializationPlan
        from app.persistence.workspace_repository import (
            set_workspace_model_v2_state as _set,
        )
        plan = MaterializationPlan(
            template_id="T", template_version=1, capex_fields=(),
            capex_sub_lines=(CapexSubLinePlan(
                parent_category_code="C.01", business_code="C.01.U001",
                label="s", amount_keur=5.0,
                replay_metadata={"shared": {"nested": 1}}),),
            opex_items=(), opex_sub_lines=(), contingency=None)
        _set(user_id=USER, project_id=workspace.project_id, state=ModelV2WorkingState(
            working_copy_ref=CODE,
            cost_template_selection=CostTemplateSelection(
                template_id="T", version=1, materialization_plan=plan)))

        first = get_workspace_model_v2_state(USER, workspace.project_id)
        second = get_workspace_model_v2_state(USER, workspace.project_id)
        sub_a = first.cost_template_selection.materialization_plan.capex_sub_lines[0]
        sub_b = second.cost_template_selection.materialization_plan.capex_sub_lines[0]
        assert sub_a.replay_metadata is not sub_b.replay_metadata
        assert sub_a.replay_metadata["shared"] is not sub_b.replay_metadata["shared"]
        # mutating a decoded dict cannot touch the persisted payload
        sub_a.replay_metadata["shared"]["nested"] = 999
        third = get_workspace_model_v2_state(USER, workspace.project_id)
        assert third.cost_template_selection.materialization_plan \
            .capex_sub_lines[0].replay_metadata["shared"]["nested"] == 1


# ---------------------------------------------------------------------------
# Persistence/serialization interplay with the binding
# ---------------------------------------------------------------------------


class TestBindingPersistenceInterplay:
    def test_staleness_follows_persisted_state_not_stale_objects(self, workspace):
        """Staleness compares the PERSISTED Working Copy state (reloaded
        through the typed decoder) against the binding — not the caller's
        in-memory copy."""
        w1 = _state()
        _run_and_commit(workspace.project_id, state=w1, snapshot_id="snap-A")
        set_workspace_model_v2_state(user_id=USER,
                                     project_id=workspace.project_id,
                                     state=_state(merchant_price=71.0))
        record = get_workspace_state(USER, workspace.project_id)
        persisted = working_state_from_json(record.model_v2_working_state_json)
        result = resolve_model_v2_staleness(
            current_state=persisted,
            run_binding=read_workspace_run_binding(record.last_runtime_identity))
        assert result.state is ModelV2RunStaleness.STALE
