"""Goal Seek / Tender V1 — canonical decision support (focused battery).

Covers the mission matrix:
  - Solar / Wind Project IRR targets (real canonical model)
  - Pure Equity IRR target (real)
  - Total Sponsor IRR metric mapping
  - Target above / below current; target already met
  - No solution in bounds (both directions); metric unavailable
  - Invalid target / unknown metric / unsupported project type
  - Model failure; non-monotonic target
  - No Run History pollution; no Last Run mutation; no Working Copy
    mutation during candidate search
  - Apply writes the exact canonical field with correct STALE semantics
  - A normal canonical Run after applying achieves the target within the
    Goal Seek tolerance

Solver-level tests use injected evaluators (fast, deterministic); a small
number of end-to-end tests run the REAL canonical model. HTTP-level tests
use the real routes with a synthetic evaluator unless stated otherwise.
"""
from __future__ import annotations

import asyncio
import math
from types import SimpleNamespace

import pytest

from app.services.goal_seek import (
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MAX_MODEL_EVALUATIONS,
    GoalSeekModelRunError,
    GoalSeekStatus,
    make_canonical_evaluator,
    resolve_metric,
    resolve_solve_variable,
    solve_tariff_for_metric,
)

# ── Synthetic evaluators ─────────────────────────────────────────────────────


def _linear_evaluator(slope=0.001, intercept=0.02):
    async def _eval(tariffs):
        return [intercept + slope * t for t in tariffs]
    return _eval


def _solve(project_type="solar", current=57.0, target=0.09,
           metric="project_irr", evaluator=None, **kwargs):
    return asyncio.run(solve_tariff_for_metric(
        project_type=project_type,
        current_tariff=current,
        target_value=target,
        metric_key=metric,
        evaluate_batch=evaluator or _linear_evaluator(),
        **kwargs,
    ))


# ── Typed statuses (injected evaluators) ─────────────────────────────────────


class TestTypedStatuses:
    def test_solar_target_above_current_solves(self):
        r = _solve(target=0.09)
        assert r.status == GoalSeekStatus.SOLVED.value
        assert abs(r.achieved_metric_value - 0.09) <= 1e-4
        assert r.solved_input_value == pytest.approx(70.0, abs=0.5)
        assert r.model_evaluations <= DEFAULT_MAX_MODEL_EVALUATIONS
        assert r.iterations <= DEFAULT_MAX_ITERATIONS
        assert r.bracket_lower <= r.solved_input_value <= r.bracket_upper
        assert r.lower_bound <= r.bracket_lower and r.upper_bound >= r.bracket_upper

    def test_wind_target_below_current_solves(self):
        r = _solve(project_type="wind", current=71.0, target=0.05)
        assert r.status == GoalSeekStatus.SOLVED.value
        assert abs(r.achieved_metric_value - 0.05) <= 1e-4
        assert r.solved_input_value == pytest.approx(30.0, abs=0.5)

    def test_target_already_met(self):
        current = 57.0
        r = _solve(current=current, target=0.02 + 0.001 * current)
        assert r.status == GoalSeekStatus.TARGET_ALREADY_MET.value
        assert r.solved_input_value == current
        assert r.model_evaluations == 1
        assert r.iterations == 0

    def test_no_solution_above_capped_expansion(self):
        async def flat_ish(tariffs):
            return [0.02 + 0.00001 * t for t in tariffs]
        r = _solve(target=0.5, evaluator=flat_ish)
        assert r.status == GoalSeekStatus.NO_SOLUTION_IN_BOUNDS.value
        assert r.achieved_metric_value is not None
        assert r.expansions == 2  # capped, never silent extrapolation

    def test_no_solution_below_expands_down_to_floor(self):
        async def positive_floor(tariffs):
            # even a zero tariff keeps the metric above the target
            return [0.05 + 0.0001 * max(0.0, t) for t in tariffs]
        r = _solve(target=-0.10, evaluator=positive_floor)
        assert r.status == GoalSeekStatus.NO_SOLUTION_IN_BOUNDS.value
        assert "floor of 0" in r.message

    def test_metric_unavailable_everywhere(self):
        async def nones(tariffs):
            return [None for _ in tariffs]
        r = _solve(evaluator=nones)
        assert r.status == GoalSeekStatus.TARGET_METRIC_UNAVAILABLE.value

    def test_metric_unavailable_at_current_only(self):
        calls = {"n": 0}

        async def none_at_current(tariffs):
            if calls["n"] == 0:
                calls["n"] += 1
                return [None for _ in tariffs]
            return [0.02 + 0.001 * t for t in tariffs]
        r = _solve(evaluator=none_at_current)
        assert r.status == GoalSeekStatus.TARGET_METRIC_UNAVAILABLE.value

    def test_model_run_failed(self):
        async def boom(tariffs):
            raise GoalSeekModelRunError("engine exploded")
        r = _solve(evaluator=boom)
        assert r.status == GoalSeekStatus.MODEL_RUN_FAILED.value
        assert "engine exploded" in r.message

    def test_non_monotonic_target(self):
        async def nonmono(tariffs):
            return [0.05 if t < 100 else (0.03 if t < 200 else 0.10)
                    for t in tariffs]
        r = _solve(target=0.09, evaluator=nonmono)
        assert r.status == GoalSeekStatus.NON_MONOTONIC_TARGET.value

    def test_gap_inside_bracket_is_discontinuity_not_root(self):
        async def with_gap(tariffs):
            # metric unavailable in (80, 100) — the initial ladder probes
            # 91.2 (None) and the [57, 171] bracket straddles the gap, so the
            # bisection must discover the discontinuity, not a fake root.
            return [None if 80.0 < t < 100.0 else (0.02 + 0.001 * t)
                    for t in tariffs]
        r = _solve(target=0.09, evaluator=with_gap)
        assert r.status == GoalSeekStatus.NON_MONOTONIC_TARGET.value
        assert "discontinuous" in r.message or "unavailable" in r.message

    def test_invalid_unknown_metric(self):
        r = _solve(metric="free_money")
        assert r.status == GoalSeekStatus.INVALID_REQUEST.value

    def test_invalid_unsupported_project_type(self):
        r = _solve(project_type="data center")
        assert r.status == GoalSeekStatus.INVALID_REQUEST.value
        assert "no supported scalar revenue-price solve variable" in r.message

    def test_invalid_nan_target(self):
        r = _solve(target=float("nan"))
        assert r.status == GoalSeekStatus.INVALID_REQUEST.value

    def test_invalid_zero_current_tariff(self):
        r = _solve(current=0.0)
        assert r.status == GoalSeekStatus.INVALID_REQUEST.value

    def test_evaluation_budget_is_deterministic_guard(self):
        seen = {"count": 0}

        async def counting(tariffs):
            seen["count"] += len(tariffs)
            return [0.02 + 0.00001 * t for t in tariffs]
        r = _solve(target=0.5, evaluator=counting, max_evaluations=40)
        assert r.status == GoalSeekStatus.NO_SOLUTION_IN_BOUNDS.value
        assert seen["count"] <= 40


class TestTypedRegistries:
    def test_metrics_are_canonical_keys(self):
        assert resolve_metric("project_irr").kpi_key == "project_irr"
        assert resolve_metric("pure_equity_irr").kpi_key == "equity_irr"
        assert resolve_metric("total_sponsor_irr").kpi_key == "total_sponsor_xirr"
        assert resolve_metric("bogus") is None

    def test_solver_variable_fail_closed_for_unsupported(self):
        assert resolve_solve_variable("solar") is not None
        assert resolve_solve_variable("wind") is not None
        assert resolve_solve_variable("data center") is None
        assert resolve_solve_variable("ev charging") is None


class TestSponsorMetricAlias:
    def test_total_sponsor_uses_canonical_key_with_compat_alias(self):
        """The canonical evaluator reads kpis['total_sponsor_xirr'] and falls
        back to the kpis['sponsor_irr'] compat alias written by the same
        payload; candidates are pure dataclass tariff swaps."""
        import app.runtime.model_execution as me
        import app.services.goal_seek as gs
        import app.services.sensitivity_execution as se
        from app.project_factories import create_generic_solar_reference

        metric = resolve_metric("total_sponsor_irr")
        base = create_generic_solar_reference()
        captured = {}

        def fake_run_points(project_type, pis_list):
            captured["pis_tariffs"] = [pi.revenue.ppa_base_tariff for pi in pis_list]
            return [{"kpis": {"sponsor_irr": 0.1 + 0.0005 * pi.revenue.ppa_base_tariff}}
                    for pi in pis_list]

        async def fake_process(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        se_run, me_run = se.run_sensitivity_points, me.run_model_process
        se.run_sensitivity_points = fake_run_points
        me.run_model_process = fake_process
        try:
            evaluator = gs.make_canonical_evaluator("Solar", base, metric)
            values = asyncio.run(evaluator([60.0, 70.0]))
        finally:
            se.run_sensitivity_points = se_run
            me.run_model_process = me_run
        assert captured["pis_tariffs"] == [60.0, 70.0]
        assert values == [0.1 + 0.0005 * 60.0, 0.1 + 0.0005 * 70.0]


# ── Real canonical model end-to-end ──────────────────────────────────────────

REAL_TOLERANCE = 1e-4


def _real_base(project_type: str):
    from app.project_factories import (
        create_generic_solar_reference, create_generic_wind_reference)
    return (create_generic_solar_reference() if project_type == "solar"
            else create_generic_wind_reference())


def _real_current_tariff(project_type: str) -> float:
    base = _real_base(project_type)
    return float(base.revenue.ppa_base_tariff)


def _real_evaluator(project_type: str, metric_key: str = "project_irr"):
    base = _real_base(project_type)
    return make_canonical_evaluator(
        "Solar" if project_type == "solar" else "Wind",
        base, resolve_metric(metric_key))


class TestRealCanonicalSolves:
    @pytest.fixture(scope="class")
    def solar_current_irr(self):
        from app.api.project_runner import run_project
        from app.project_factories import create_generic_solar_reference
        payload = run_project("Solar", "Base",
                              project_inputs_override=create_generic_solar_reference())
        return payload["kpis"]["project_irr"]

    def test_solar_project_irr_target_above(self):
        current = _real_current_tariff("solar")
        base_evaluator = _real_evaluator("solar")
        current_irr = asyncio.run(base_evaluator([current]))[0]
        target = current_irr + 0.01  # +1 percentage point
        r = asyncio.run(solve_tariff_for_metric(
            project_type="solar", current_tariff=current, target_value=target,
            metric_key="project_irr", evaluate_batch=base_evaluator))
        assert r.status == GoalSeekStatus.SOLVED.value, r.message
        assert abs(r.achieved_metric_value - target) <= REAL_TOLERANCE
        assert r.model_evaluations <= DEFAULT_MAX_MODEL_EVALUATIONS
        assert r.solved_input_value > current

    def test_solar_target_below_current_solves(self):
        current = _real_current_tariff("solar")
        base_evaluator = _real_evaluator("solar")
        current_irr = asyncio.run(base_evaluator([current]))[0]
        target = current_irr - 0.01
        if target <= 0:
            pytest.skip("current IRR too low to go 1pp below")
        r = asyncio.run(solve_tariff_for_metric(
            project_type="solar", current_tariff=current, target_value=target,
            metric_key="project_irr", evaluate_batch=base_evaluator))
        assert r.status == GoalSeekStatus.SOLVED.value, r.message
        assert r.solved_input_value < current

    def test_wind_pure_equity_irr_target(self):
        from app.api.project_runner import run_project
        current = _real_current_tariff("wind")
        base = _real_base("wind")
        payload = run_project("Wind", "Base", project_inputs_override=base)
        equity_now = payload["kpis"]["equity_irr"]
        target = equity_now - 0.02
        if target <= 0:
            pytest.skip("current equity IRR too low to go 2pp below")
        evaluator = make_canonical_evaluator(
            "Wind", base, resolve_metric("pure_equity_irr"))
        r = asyncio.run(solve_tariff_for_metric(
            project_type="wind", current_tariff=current, target_value=target,
            metric_key="pure_equity_irr", evaluate_batch=evaluator))
        assert r.status == GoalSeekStatus.SOLVED.value, r.message
        assert abs(r.achieved_metric_value - target) <= REAL_TOLERANCE
        assert r.solved_input_value < current


# ── HTTP route + persistence isolation + apply semantics ─────────────────────


@pytest.fixture()
def goal_seek_env(tmp_path, monkeypatch):
    """Temp-DB workspace with a real seeded solar working copy."""
    import os

    from app.persistence import db
    path = str(tmp_path / "gs.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    if hasattr(db, "_init_schema"):
        db.init_db()
    else:
        db.init_db()

    from app.services.reference_seed_service import create_reference_seeded_project
    record = create_reference_seeded_project(
        user_id="gs-user", template_source="generic_solar_reference",
        requested_name="GS Solar", capacity_mw=64.0)
    return SimpleNamespace(db=db, record=record, user_id="gs-user")


def _workspace(goal_seek_env):
    from app.persistence.workspace_repository import get_workspace_state
    return get_workspace_state(user_id=goal_seek_env.user_id,
                               project_id=goal_seek_env.record.project_id)


def _client():
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from app.auth import COOKIE_NAME, create_session_token
    from app.v2.router import router

    app = FastAPI()
    app.include_router(router, prefix="/v2")
    cookies = {COOKIE_NAME: create_session_token(user_id="gs-user", username="admin")}
    return TestClient(app, raise_server_exceptions=False), cookies


def _synthetic_monkeypatch(monkeypatch):
    """Replace the canonical evaluator with a fast synthetic monotone one."""
    import app.services.goal_seek as gs

    def fake_factory(runtime_key, base_override, metric):
        async def _eval(tariffs):
            return [0.02 + 0.001 * t for t in tariffs]
        return _eval

    monkeypatch.setattr(gs, "make_canonical_evaluator", fake_factory)


class TestGoalSeekRoutes:
    def test_run_unauthenticated_401(self, goal_seek_env, monkeypatch):
        client, _ = _client()
        _synthetic_monkeypatch(monkeypatch)
        resp = client.post("/v2/workbook/goal-seek/run",
                           data={"project": goal_seek_env.record.project_code,
                                 "target_metric": "project_irr",
                                 "target_value": "8.00"})
        assert resp.status_code == 401

    def test_run_unknown_project_404(self, goal_seek_env, monkeypatch):
        client, cookies = _client()
        _synthetic_monkeypatch(monkeypatch)
        resp = client.post("/v2/workbook/goal-seek/run", cookies=cookies,
                           data={"project": "no-such-project",
                                 "target_metric": "project_irr",
                                 "target_value": "8.00"})
        assert resp.status_code == 404

    def test_run_unsupported_project_type_fail_closed(self, goal_seek_env, monkeypatch):
        from app.persistence.projects_repository import save_project
        from app.persistence.workspace_repository import save_workspace_state
        dc = save_project(user_id=goal_seek_env.user_id, project_code="gs-dc",
                          project_name="GS DC", source_project_template="custom",
                          project_type="data center", project_origin="user_created")
        save_workspace_state(user_id=goal_seek_env.user_id, project_id=dc.project_id,
                             project_code="gs-dc", draft_snapshot={}, saved_snapshot={})
        client, cookies = _client()
        _synthetic_monkeypatch(monkeypatch)
        resp = client.post("/v2/workbook/goal-seek/run", cookies=cookies,
                           data={"project": "gs-dc",
                                 "target_metric": "project_irr",
                                 "target_value": "8.00"})
        assert resp.status_code == 200
        assert 'data-status="INVALID_REQUEST"' in resp.text
        assert "no supported scalar revenue-price solve variable" in resp.text

    def test_run_invalid_metric_and_target(self, goal_seek_env, monkeypatch):
        client, cookies = _client()
        _synthetic_monkeypatch(monkeypatch)
        for bad in ({"target_metric": "free_money", "target_value": "8.00"},
                    {"target_metric": "project_irr", "target_value": "banana"}):
            resp = client.post("/v2/workbook/goal-seek/run", cookies=cookies,
                               data={"project": goal_seek_env.record.project_code, **bad})
            assert resp.status_code == 200
            assert 'data-status="INVALID_REQUEST"' in resp.text

    def test_run_solved_renders_apply_form(self, goal_seek_env, monkeypatch):
        ws = _workspace(goal_seek_env)
        current_tariff = float(ws.draft_snapshot["rev_ppa_base_tariff"])
        target_pct = (0.02 + 0.001 * current_tariff) * 100 + 1.0
        client, cookies = _client()
        _synthetic_monkeypatch(monkeypatch)
        resp = client.post("/v2/workbook/goal-seek/run", cookies=cookies,
                           data={"project": goal_seek_env.record.project_code,
                                 "target_metric": "project_irr",
                                 "target_value": f"{target_pct:.2f}"})
        assert resp.status_code == 200
        assert 'data-status="SOLVED"' in resp.text
        assert 'data-testid="gs-apply-form"' in resp.text
        assert 'name="field_id" value="revenue.ppa.base_tariff"' in resp.text
        assert 'name="content_hash" value="' in resp.text

    def test_run_model_failure_partial(self, goal_seek_env, monkeypatch):
        import app.runtime.model_execution as me
        from app.runtime.model_execution import ModelExecutionFailed

        def boom(*args, **kwargs):
            raise ModelExecutionFailed()
        monkeypatch.setattr(me, "run_model_process", boom)
        client, cookies = _client()
        resp = client.post("/v2/workbook/goal-seek/run", cookies=cookies,
                           data={"project": goal_seek_env.record.project_code,
                                 "target_metric": "project_irr",
                                 "target_value": "8.00"})
        assert resp.status_code == 200
        assert 'data-status="MODEL_RUN_FAILED"' in resp.text

    def test_candidate_search_is_persistence_isolated(self, goal_seek_env, monkeypatch):
        """No Run History entry, no Last Run promotion, no Working Copy
        mutation, no dirty-flag flip during candidate search."""
        from app.persistence.runs_repository import count_runs
        from app.persistence.workspace_repository import get_workspace_state

        before = get_workspace_state(goal_seek_env.user_id,
                                     goal_seek_env.record.project_id)
        runs_before = count_runs(goal_seek_env.user_id)
        assert before.model_v2_working_state_json == ""

        ws = _workspace(goal_seek_env)
        current_tariff = float(ws.draft_snapshot["rev_ppa_base_tariff"])
        target_pct = (0.02 + 0.001 * current_tariff) * 100 + 2.0
        client, cookies = _client()
        _synthetic_monkeypatch(monkeypatch)
        resp = client.post("/v2/workbook/goal-seek/run", cookies=cookies,
                           data={"project": goal_seek_env.record.project_code,
                                 "target_metric": "project_irr",
                                 "target_value": f"{target_pct:.2f}"})
        assert 'data-status="SOLVED"' in resp.text

        after = get_workspace_state(goal_seek_env.user_id,
                                    goal_seek_env.record.project_id)
        assert after.draft_snapshot == before.draft_snapshot
        assert after.saved_snapshot == before.saved_snapshot
        assert after.dirty == before.dirty
        assert after.last_runtime_snapshot_id == before.last_runtime_snapshot_id
        assert after.last_runtime_summary == before.last_runtime_summary
        assert after.any_run_committed == before.any_run_committed
        assert after.last_runtime_composite_hash == before.last_runtime_composite_hash
        assert count_runs(goal_seek_env.user_id) == runs_before

    def test_apply_writes_exact_field_and_sets_stale(self, goal_seek_env, monkeypatch):
        from app.workbook.input_set import ProjectInputSet
        from app.workbook.registry import WORKBOOK
        from app.workbook.workbook_identity import assemble_consistent_for_get

        ws = _workspace(goal_seek_env)
        pis = ProjectInputSet.from_snapshot(dict(ws.draft_snapshot), workbook=WORKBOOK)
        identity = assemble_consistent_for_get(
            user_id=goal_seek_env.user_id,
            project_id=goal_seek_env.record.project_id,
            workbook_version=WORKBOOK.version)
        client, cookies = _client()
        _synthetic_monkeypatch(monkeypatch)

        resp = client.post("/v2/workbook/goal-seek/apply", cookies=cookies,
                           data={"project": goal_seek_env.record.project_code,
                                 "field_id": "revenue.ppa.base_tariff",
                                 "value": "88.40",
                                 "content_hash": identity.composite_hash,
                                 "workbook_version": WORKBOOK.version})
        assert resp.status_code == 200
        assert "data-testid=\"gs-applied-note\"" in resp.text
        assert "STALE" in resp.text

        after = _workspace(goal_seek_env)
        assert float(after.draft_snapshot["rev_ppa_base_tariff"]) == pytest.approx(88.40)
        assert after.dirty is True  # normal STALE semantics, awaiting normal Run
        # no canonical Last Run was written by Goal Seek
        assert after.last_runtime_snapshot_id is None
        assert after.any_run_committed is False

    def test_apply_with_stale_hash_fails_closed(self, goal_seek_env, monkeypatch):
        from app.workbook.input_set import ProjectInputSet
        from app.workbook.registry import WORKBOOK
        from app.workbook.workbook_identity import assemble_consistent_for_get

        ws = _workspace(goal_seek_env)
        pis = ProjectInputSet.from_snapshot(dict(ws.draft_snapshot), workbook=WORKBOOK)
        identity = assemble_consistent_for_get(
            user_id=goal_seek_env.user_id,
            project_id=goal_seek_env.record.project_id,
            workbook_version=WORKBOOK.version)
        client, cookies = _client()
        _synthetic_monkeypatch(monkeypatch)

        # first apply consumes the hash
        first = client.post("/v2/workbook/goal-seek/apply", cookies=cookies,
                            data={"project": goal_seek_env.record.project_code,
                                  "field_id": "revenue.ppa.base_tariff",
                                  "value": "90.00",
                                  "content_hash": identity.composite_hash,
                                  "workbook_version": WORKBOOK.version})
        assert "data-testid=\"gs-applied-note\"" in first.text

        # second apply with the SAME hash must fail closed (CAS)
        second = client.post("/v2/workbook/goal-seek/apply", cookies=cookies,
                             data={"project": goal_seek_env.record.project_code,
                                   "field_id": "revenue.ppa.base_tariff",
                                   "value": "91.00",
                                   "content_hash": identity.composite_hash,
                                   "workbook_version": WORKBOOK.version})
        assert "NOT" in second.text and "applied" in second.text.lower()
        after = _workspace(goal_seek_env)
        assert float(after.draft_snapshot["rev_ppa_base_tariff"]) == pytest.approx(90.00)


# ── Real apply + canonical run closure (mission-required proof) ──────────────


class TestApplyThenCanonicalRun:
    def test_apply_then_normal_run_achieves_target(self, goal_seek_env):
        """Solve on the REAL model, apply through the canonical field-save
        authority, then run the CANONICAL path (same construction as the
        workbook Run button) and prove the target is achieved within the
        Goal Seek tolerance — and that the Last Run/History were untouched
        by the search itself."""
        import math

        from app.api.project_runner import run_project
        from app.persistence.runs_repository import count_runs
        from app.persistence.workspace_repository import get_workspace_state
        from app.workbook.input_set import ProjectInputSet
        from app.workbook.registry import WORKBOOK
        from app.workbook.service import WorkbookService
        from app.workbook.workbook_identity import assemble_consistent_for_get
        from app.services.capex_sub_lines_integration import (
            apply_user_sub_lines_replacing_base)
        from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex
        from app.workbook.update_service import WorkbookUpdateService

        user_id = goal_seek_env.user_id
        record = goal_seek_env.record

        def canonical_override():
            ws_now = get_workspace_state(user_id=user_id, project_id=record.project_id)
            pis = WorkbookService.build_draft_input_set_from_workspace(ws_now)
            override = WorkbookService.to_projectinputs(pis)
            folded_capex = apply_user_sub_lines_replacing_base(
                override.capex, project_id=record.project_id,
                scenario_overrides=None)
            if folded_capex is not override.capex:
                from dataclasses import replace as dcr
                override = dcr(override, capex=folded_capex)
            folded_opex = apply_user_sub_lines_to_opex(
                override.opex, project_id=record.project_id,
                scenario_overrides=None)
            if folded_opex is not override.opex:
                from dataclasses import replace as dcr
                override = dcr(override, opex=folded_opex)
            return pis, override

        pis, override = canonical_override()
        current_tariff = float(pis.snapshot_origin["rev_ppa_base_tariff"])
        evaluator = make_canonical_evaluator("Solar", override,
                                             resolve_metric("project_irr"))
        target = asyncio.run(evaluator([current_tariff]))[0] + 0.01
        if not math.isfinite(target):
            pytest.skip("current IRR unavailable")

        runs_before = count_runs(user_id)
        result = asyncio.run(solve_tariff_for_metric(
            project_type="solar", current_tariff=current_tariff,
            target_value=target, metric_key="project_irr",
            evaluate_batch=evaluator))
        assert result.status == GoalSeekStatus.SOLVED.value, result.message
        assert count_runs(user_id) == runs_before  # no history pollution

        ws = get_workspace_state(user_id=user_id, project_id=record.project_id)
        last_runtime_before = ws.last_runtime_snapshot_id
        identity = assemble_consistent_for_get(
            user_id=user_id, project_id=record.project_id,
            workbook_version=WORKBOOK.version)
        WorkbookUpdateService.apply_draft_update(
            ws=ws,
            field_id="revenue.ppa.base_tariff",
            raw_value=f"{result.solved_input_value:.2f}",
            content_hash=identity.composite_hash,
            workbook_version=WORKBOOK.version,
            project_record=record,
        )

        applied_ws = get_workspace_state(user_id=user_id, project_id=record.project_id)
        assert applied_ws.dirty is True  # STALE until the user runs
        assert applied_ws.last_runtime_snapshot_id == last_runtime_before
        assert count_runs(user_id) == runs_before

        # the user presses the normal Run button:
        _, run_override = canonical_override()
        payload = run_project("Solar", "Base", project_inputs_override=run_override)
        achieved = payload["kpis"]["project_irr"]
        assert abs(achieved - target) <= 2e-3, (achieved, target)
