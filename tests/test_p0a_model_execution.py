"""P0-A — runtime execution isolation: bounded, off-event-loop, CAS-preserving model execution."""
from __future__ import annotations

import ast
import asyncio
import copy
import json
import os
import socket
import threading
import time
import uuid
from pathlib import Path
from unittest import mock

import httpx
import pytest

import p0_exec_helpers as helpers
from app.runtime import model_execution as me
from app.runtime.model_execution import (
    ModelExecutionBusy, ModelExecutionConfig, ModelExecutionConfigError, ModelExecutionFailed,
    ModelExecutionTimeout, ModelExecutor, ModelWorkerError,
)

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _executor_isolation():
    yield
    me.reset_model_executor_for_tests(None)


def make(concurrency=2, mode="process", timeout=60) -> ModelExecutor:
    executor = ModelExecutor(ModelExecutionConfig(concurrency, mode, timeout))
    me.reset_model_executor_for_tests(executor)
    return executor


# ══ configuration ═════════════════════════════════════════════════════════════════════
def test_config_defaults_bounds_and_typed_errors_without_values():
    cfg = ModelExecutionConfig.from_env({})
    assert (cfg.concurrency, cfg.mode) == (me.DEFAULT_CONCURRENCY, "process")
    assert 1 <= cfg.concurrency <= me.MAX_CONCURRENCY and cfg.timeout_seconds == me.DEFAULT_TIMEOUT_SECONDS
    assert ModelExecutionConfig.from_env({me.ENV_CONCURRENCY: "4", me.ENV_MODE: "thread"}).concurrency == 4
    for bad in ("0", "-1", "9", "abc", "1.5"):
        with pytest.raises(ModelExecutionConfigError) as exc:
            ModelExecutionConfig.from_env({me.ENV_CONCURRENCY: bad})
        assert me.CONFIG_INVALID_CODE in str(exc.value) and bad not in str(exc.value).replace(me.ENV_CONCURRENCY, "")
    with pytest.raises(ModelExecutionConfigError):
        ModelExecutionConfig.from_env({me.ENV_MODE: "gpu"})
    with pytest.raises(ModelExecutionConfigError):
        ModelExecutionConfig.from_env({me.ENV_TIMEOUT: "0"})
    assert me.validate_model_execution_config({}).concurrency == me.DEFAULT_CONCURRENCY


def test_bound_scope_is_process_local_and_documented():
    stats = make(3, "thread").stats()
    assert stats["scope"] == "PROCESS_LOCAL" and stats["concurrency"] == 3
    assert "PROCESS-LOCAL" in me.__doc__ and "workers x FINCO_MODEL_EXECUTION_CONCURRENCY" in me.__doc__
    dossier = (REPO / "docs/review/P0_PUBLIC_BETA_RUNTIME_GATE.md").read_text(encoding="utf-8")
    assert "effective_host_max" in dossier and "PROCESS_LOCAL" in dossier


# ══ admission / capacity ══════════════════════════════════════════════════════════════
@pytest.mark.parametrize("mode", ["process", "thread"])
def test_within_capacity_is_admitted_and_runs(mode):
    executor = make(2, mode)

    async def go():
        return await asyncio.gather(executor.run_process(helpers.add, 1, 2), executor.run_process(helpers.add, 3, 4))

    assert asyncio.run(go()) == [3, 7]
    stats = executor.stats()
    assert stats["admitted"] == 2 and stats["completed"] == 2 and stats["active"] == 0


@pytest.mark.parametrize("mode", ["process", "thread"])
def test_above_capacity_fails_fast_typed_busy_with_no_queue(mode):
    executor = make(1, mode)

    async def go():
        running = asyncio.create_task(executor.run_process(helpers.spin, 1.5))
        await asyncio.sleep(0.3)
        started = time.monotonic()
        rejected = 0
        for _ in range(5):  # a burst above capacity: every extra request is rejected at once
            with pytest.raises(ModelExecutionBusy) as exc:
                await executor.run_process(helpers.add, 1, 1)
            assert exc.value.code == "MODEL_EXECUTION_BUSY" and exc.value.retry_after_seconds == 5
            rejected += 1
        assert time.monotonic() - started < 0.5          # rejection is immediate: nothing waits
        await running
        return rejected

    assert asyncio.run(go()) == 5
    stats = executor.stats()
    assert stats["busy_rejected"] == 5 and stats["admitted"] == 1 and stats["active"] == 0
    assert asyncio.run(executor.run_process(helpers.add, 2, 2)) == 4      # capacity is back


def test_no_unbounded_queue_exactly_capacity_is_admitted():
    executor = make(2, "thread")

    async def go():
        tasks = [asyncio.create_task(executor.run_process(helpers.spin, 0.8)) for _ in range(6)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results

    results = asyncio.run(go())
    assert sum(isinstance(r, ModelExecutionBusy) for r in results) == 4
    assert sum(isinstance(r, int) for r in results) == 2
    assert executor.stats()["active"] == 0


def test_busy_error_exposes_no_internals():
    text = json.dumps({"code": ModelExecutionBusy.code, "message": me.BUSY_MESSAGE})
    for internal in ("pid", "thread", "Traceback", "/home", "executor", "semaphore", "worker"):
        assert internal not in text.lower()
    assert me.BUSY_MESSAGE == "Calculation capacity is currently busy. Please retry."


# ══ release on every exit path ════════════════════════════════════════════════════════
def test_capacity_released_after_success_and_after_engine_failure_process_mode():
    executor = make(1, "process")
    assert asyncio.run(executor.run_process(helpers.add, 1, 1)) == 2 and executor.stats()["active"] == 0
    with pytest.raises(ModelWorkerError) as exc:
        asyncio.run(executor.run_process(helpers.raise_weird))
    # The custom exception did NOT have to survive pickling: only a plain envelope crossed.
    assert exc.value.error_type == "WeirdError" and exc.value.reason_code == "ENGINE_EXPLODED"
    assert exc.value.detail == "kaboom" and executor.stats()["active"] == 0
    assert asyncio.run(executor.run_process(helpers.add, 5, 5)) == 10      # the pool is NOT broken
    stats = executor.stats()
    assert stats["failed"] == 1 and stats["completed"] == 2


def test_capacity_released_after_engine_failure_thread_mode():
    executor = make(1, "thread")
    with pytest.raises(helpers.WeirdError):
        asyncio.run(executor.run_thread(helpers.raise_weird))
    assert executor.stats()["active"] == 0 and asyncio.run(executor.run_thread(helpers.add, 1, 2)) == 3


def test_worker_crash_is_typed_pool_recovers_and_capacity_is_released():
    executor = make(1, "process")
    with pytest.raises(ModelExecutionFailed):
        asyncio.run(executor.run_process(helpers.die_hard))
    assert executor.stats()["active"] == 0
    assert asyncio.run(executor.run_process(helpers.add, 20, 22)) == 42   # fresh pool


def test_timeout_is_typed_and_the_slot_stays_honest_until_the_work_ends():
    executor = make(1, "process", timeout=1)

    async def go():
        with pytest.raises(ModelExecutionTimeout):
            await executor.run_process(helpers.spin, 3.0)
        # The caller gave up but the calculation is still using the CPU: capacity is NOT released.
        assert executor.stats()["active"] == 1
        with pytest.raises(ModelExecutionBusy):
            await executor.run_process(helpers.add, 1, 1)
        await asyncio.sleep(3.5)                       # the worker finishes; the slot frees itself
        return executor.stats()

    stats = asyncio.run(go())
    assert stats["active"] == 0 and stats["timed_out"] == 1
    assert asyncio.run(executor.run_process(helpers.add, 1, 1)) == 2


def test_client_disconnect_never_leaks_capacity_and_discards_the_result():
    executor = make(1, "process")

    async def go():
        task = asyncio.create_task(executor.run_process(helpers.spin, 1.5))
        await asyncio.sleep(0.4)
        task.cancel()                                  # the client went away
        with pytest.raises(asyncio.CancelledError):
            await task
        assert executor.stats()["active"] == 1         # the calculation was NOT interrupted mid-engine
        await asyncio.sleep(1.8)
        return executor.stats()

    stats = asyncio.run(go())
    assert stats["active"] == 0                        # released when the calculation actually ended
    assert asyncio.run(executor.run_process(helpers.add, 1, 1)) == 2


def test_inline_admission_context_counts_against_the_same_gate_and_always_releases():
    executor = make(1, "thread")
    with pytest.raises(RuntimeError):
        with executor.admit_inline():
            assert executor.stats()["active"] == 1
            with pytest.raises(ModelExecutionBusy):
                with executor.admit_inline():
                    pass
            raise RuntimeError("route body failed")
    assert executor.stats()["active"] == 0
    with executor.admit_inline():
        pass
    assert executor.stats()["completed"] == 1 and executor.stats()["failed"] == 1


def test_sync_process_path_shares_the_gate_and_translates_failures():
    executor = make(1, "process")
    assert executor.run_process_sync(helpers.add, 4, 5) == 9
    with pytest.raises(ModelWorkerError):
        executor.run_process_sync(helpers.raise_weird)
    assert executor.stats()["active"] == 0


# ══ the event loop stays responsive (would FAIL against the pre-fix architecture) ══════
def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _serve(app):
    import uvicorn
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started and time.time() < deadline:
        time.sleep(0.02)
    assert server.started
    return server, thread, f"http://127.0.0.1:{port}"


def _probe_latency(base: str, heavy_path: str, *, duration: float) -> tuple[float, int]:
    """Fire the heavy request, then measure /ping latency while it is executing."""
    result: dict = {}

    def heavy():
        result["r"] = httpx.post(base + heavy_path, timeout=120)

    thread = threading.Thread(target=heavy)
    thread.start()
    time.sleep(0.4)
    worst, samples = 0.0, 0
    deadline = time.time() + duration
    while time.time() < deadline and thread.is_alive():
        started = time.perf_counter()
        assert httpx.get(base + "/ping", timeout=30).status_code == 200
        worst = max(worst, time.perf_counter() - started)
        samples += 1
        time.sleep(0.05)
    thread.join(60)
    return worst, samples


def _mini_app():
    from fastapi import FastAPI

    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    @app.post("/heavy-executor")
    async def heavy_executor():
        pid = await me.run_model_process(helpers.spin, 3.0)
        return {"pid_differs": pid != os.getpid()}

    @app.post("/heavy-inline-prefix-architecture")
    async def heavy_inline():
        helpers.spin(3.0)  # exactly what an async handler did before the fix
        return {"ok": True}

    return app


def test_event_loop_responsive_during_model_run_and_control_proves_the_old_architecture_blocked():
    make(2, "process")
    server, thread, base = _serve(_mini_app())
    try:
        worst_fixed, samples = _probe_latency(base, "/heavy-executor", duration=2.5)
        assert samples >= 5 and worst_fixed < 0.6, f"loop stalled {worst_fixed:.2f}s"   # EVENT_LOOP_RESPONSIVE
        worst_old, _ = _probe_latency(base, "/heavy-inline-prefix-architecture", duration=6)
        assert worst_old > 1.5, "control failed: the pre-fix architecture should block the loop"
    finally:
        server.should_exit = True
        thread.join(10)


def test_real_model_run_in_worker_keeps_the_loop_responsive_and_returns_unchanged_output():
    """A REAL production model run (~20 s) executes in a worker process while /ping stays fast."""
    from fastapi import FastAPI
    from app.api.router import router as api_router
    from app.api.project_runner import run_project

    make(2, "process", timeout=180)
    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    app.include_router(api_router, prefix="/api")
    server, thread, base = _serve(app)
    try:
        holder: dict = {}

        def call():
            holder["r"] = httpx.post(base + "/api/run", timeout=240,
                                     json={"project_type": "Solar", "scenario": "Base"})

        t = threading.Thread(target=call)
        t.start()
        time.sleep(1.0)
        worst, samples = 0.0, 0
        while t.is_alive():
            started = time.perf_counter()
            assert httpx.get(base + "/ping", timeout=30).status_code == 200
            worst = max(worst, time.perf_counter() - started)
            samples += 1
            time.sleep(0.1)
        t.join()
        assert holder["r"].status_code == 200, holder["r"].text[:200]
        assert samples >= 20 and worst < 1.0, f"loop stalled {worst:.2f}s over {samples} probes"
        served = holder["r"].json()["kpis"]
        direct = run_project("Solar", "Base")["kpis"]
        assert served == json.loads(json.dumps(direct, default=str))        # REFERENCE_OUTPUTS_UNCHANGED
    finally:
        server.should_exit = True
        thread.join(10)


# ══ typed BUSY at the real routes ═════════════════════════════════════════════════════
@pytest.fixture()
def client():
    import main_web
    from starlette.testclient import TestClient
    return TestClient(main_web.app, raise_server_exceptions=False)


class _Occupant:
    """Holds every execution slot of a THREAD-mode executor until released (deterministic)."""

    def __init__(self, executor: ModelExecutor) -> None:
        helpers.RELEASE.clear()
        self.executor = executor
        self.thread = threading.Thread(
            target=lambda: asyncio.run(executor.run_thread(helpers.hold_until_released)))
        self.thread.start()
        deadline = time.time() + 10
        while executor.stats()["active"] < 1 and time.time() < deadline:
            time.sleep(0.01)

    def release(self) -> None:
        helpers.RELEASE.set()
        self.thread.join(15)


def _saturate(executor: ModelExecutor, seconds: float = 0.0) -> _Occupant:
    return _Occupant(executor)


@pytest.fixture()
def api_client():
    """The app that actually serves the public /api/run route (main_api)."""
    import main_api
    from starlette.testclient import TestClient
    return TestClient(main_api.app, raise_server_exceptions=False)


def test_public_api_run_returns_429_busy_and_recovers(api_client):
    executor = make(1, "thread")
    occupant = _saturate(executor, 1.5)
    try:
        r = api_client.post("/api/v1/run", json={"project_type": "Solar", "scenario": "Base"})
        assert r.status_code == 429 and r.headers["retry-after"] == "5"
        body = r.json()["detail"]
        assert body == {"state": "MODEL_EXECUTION_BUSY", "message": me.BUSY_MESSAGE}
        assert "Traceback" not in r.text and "/home" not in r.text
    finally:
        occupant.release()
    assert executor.stats()["active"] == 0


def test_reference_model_run_route_returns_typed_429_when_busy(client):
    executor = make(1, "thread")
    occupant = _saturate(executor, 1.5)
    try:
        r = client.post("/api/v1/model/references/generic_solar_reference/run", json={"capacity_mw": 64.0})
        assert r.status_code == 429 and r.json()["error"] == "MODEL_EXECUTION_BUSY"
        assert r.json()["detail"] == me.BUSY_MESSAGE
    finally:
        occupant.release()


def test_lightweight_public_routes_stay_available_while_model_capacity_is_saturated(client):
    """Model saturation must not break Radar, Verify, public verification or static navigation."""
    executor = make(1, "thread")
    occupant = _saturate(executor, 2.0)
    try:
        for path in ("/api/v1.1/radar/r-live/assets", "/protocol", "/radar/r-live"):
            started = time.perf_counter()
            r = client.get(path, follow_redirects=True)
            assert r.status_code < 500, (path, r.status_code)
            assert time.perf_counter() - started < 1.5, path
        assert client.post("/api/v1/model/references/generic_solar_reference/run",
                           json={"capacity_mw": 64.0}).status_code == 429
    finally:
        occupant.release()


# ══ V2 workbook run: CAS, no partial state, capacity ══════════════════════════════════
def _v2_project():
    import main_web
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence.projects_repository import create_project_record
    from app.persistence.workspace_repository import save_workspace_state

    owner = "p0a-" + uuid.uuid4().hex[:10]
    code = "p0a-" + uuid.uuid4().hex[:10]
    snapshot = main_web._project_baseline_snapshot("Solar", "generic_solar")
    snapshot.update({"active_project": code, "project_name": "P0A", "project_type": "Solar",
                     "project_origin": "user_created", "country_market": "Synthetic Market", "scenario": "Base"})
    record = create_project_record(user_id=owner, project_code=code, project_name="P0A", project_type="Solar",
                                   project_origin="user_created", template_source="generic_solar",
                                   baseline_snapshot=snapshot)
    save_workspace_state(user_id=owner, project_id=record.project_id, project_code=code,
                         draft_snapshot=snapshot, saved_snapshot=snapshot, dirty=False)
    token = create_session_token(user_id=owner, username=owner)
    return {"owner": owner, "code": code, "record": record, "snapshot": snapshot,
            "headers": {"Cookie": f"{COOKIE_NAME}={token}", "HX-Request": "true"}}


def _identity(p):
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get
    return assemble_consistent_for_get(user_id=p["owner"], project_id=p["record"].project_id,
                                       workbook_version=WORKBOOK.version)


def _post_run(client, p, content_hash=None):
    from app.workbook.registry import WORKBOOK
    return client.post("/v2/workbook/run", headers=p["headers"], data={
        "project": p["code"], "workbook_version": WORKBOOK.version,
        "content_hash": content_hash or _identity(p).composite_hash})


def _ws(p):
    from app.persistence.workspace_repository import get_workspace_state
    return get_workspace_state(user_id=p["owner"], project_id=p["record"].project_id)


@pytest.fixture(scope="module")
def real_payload():
    """One REAL production run, reused as the calculation result in the routing tests below."""
    from app.api.project_runner import run_project
    return run_project("Solar", "Base")


def test_stale_calculation_never_overwrites_a_newer_working_copy_cas_preserved(client, real_payload):
    """Calculation starts -> Working Copy changes before completion -> commit MUST fail closed."""
    from app.api import project_runner
    from app.persistence.workspace_repository import save_workspace_state

    executor = make(2, "thread")
    p = _v2_project()
    started_hash = _identity(p).composite_hash
    changed = dict(p["snapshot"], country_market="Edited During The Calculation")

    def racing_run_project(*args, **kwargs):
        # the user edits the Working Copy while the (off-event-loop) calculation is running
        save_workspace_state(user_id=p["owner"], project_id=p["record"].project_id, project_code=p["code"],
                             draft_snapshot=changed, saved_snapshot=p["snapshot"], dirty=True)
        return copy.deepcopy(real_payload)

    with mock.patch.object(project_runner, "run_project", racing_run_project):
        response = _post_run(client, p, started_hash)
    assert response.status_code == 200
    ws = _ws(p)
    assert not ws.last_runtime_snapshot_id and not ws.last_runtime_summary      # PARTIAL_LAST_RUN_COMMIT = NO
    assert ws.dirty is True and ws.draft_snapshot["country_market"] == "Edited During The Calculation"
    assert _identity(p).composite_hash != started_hash
    assert executor.stats()["active"] == 0


def test_engine_failure_leaves_no_partial_state_and_releases_capacity(client):
    from app.api import project_runner

    executor = make(1, "thread")
    p = _v2_project()
    before = _ws(p)

    def failing(*args, **kwargs):
        raise RuntimeError("engine exploded /secret/path")

    with mock.patch.object(project_runner, "run_project", failing):
        response = _post_run(client, p)
    assert response.status_code == 200
    assert "Engine run failed" in response.text and "/secret/path" not in response.text
    after = _ws(p)
    assert not after.last_runtime_snapshot_id and after.draft_snapshot == before.draft_snapshot
    assert after.dirty == before.dirty
    assert executor.stats()["active"] == 0 and executor.stats()["failed"] == 1


def test_executor_failure_and_timeout_leave_no_partial_state(client):
    p = _v2_project()
    make(1, "thread")
    for exc in (ModelExecutionFailed(), ModelExecutionTimeout()):
        with mock.patch.object(ModelExecutor, "run_process", mock.AsyncMock(side_effect=exc)):
            response = _post_run(client, p)
        assert response.status_code == 200 and "could not be completed" in response.text
        assert not _ws(p).last_runtime_snapshot_id


def test_busy_workbook_run_is_429_with_banner_changes_nothing_then_recovers(client, real_payload):
    from app.api import project_runner

    executor = make(1, "thread")
    p = _v2_project()
    before = _ws(p)
    occupant = _saturate(executor, 2.0)
    try:
        response = _post_run(client, p)
    finally:
        occupant.release()
    assert response.status_code == 429 and response.headers["x-finco-model-busy"] == "1"
    assert response.headers["retry-after"] == "5" and me.BUSY_MESSAGE in response.text
    assert "MODEL_EXECUTION_FAILED" not in response.text and "Engine run failed" not in response.text
    assert _ws(p).draft_snapshot == before.draft_snapshot and not _ws(p).last_runtime_snapshot_id
    with mock.patch.object(project_runner, "run_project", lambda *a, **k: copy.deepcopy(real_payload)):
        ok = _post_run(client, p)                     # capacity is free again; the run commits
    assert ok.status_code == 200 and _ws(p).last_runtime_snapshot_id
    assert executor.stats()["active"] == 0


def test_successful_run_commits_through_the_executor_and_releases_capacity(client, real_payload):
    from app.api import project_runner

    executor = make(2, "thread")
    p = _v2_project()
    threads: list[str] = []

    def fake(*args, **kwargs):
        threads.append(threading.current_thread().name)
        return copy.deepcopy(real_payload)

    with mock.patch.object(project_runner, "run_project", fake):
        assert _post_run(client, p).status_code == 200
    assert threads and all(name.startswith("finco-model") for name in threads)   # never the loop thread
    assert _ws(p).last_runtime_snapshot_id and executor.stats()["active"] == 0


def test_js_swaps_only_a_marked_429_so_busy_is_visible_to_the_user():
    js = (REPO / "static/js/workbook_v2.js").read_text(encoding="utf-8")
    assert "v2ShouldSwapModelBusyResponse" in js and "X-Finco-Model-Busy" in js and "xhr.status === 429" in js


# ══ sensitivity: bounded, ordered, single admission ═══════════════════════════════════
def test_sensitivity_grid_is_bounded_with_a_typed_error():
    from app.services.sensitivity_execution import (
        MAX_SENSITIVITY_EVALUATIONS, sensitivity_grid_size_error)
    assert MAX_SENSITIVITY_EVALUATIONS == 49                   # the legacy default 8 x 6 + 1 grid
    assert sensitivity_grid_size_error(49) is None
    error = sensitivity_grid_size_error(50)
    assert error and error.startswith("SENSITIVITY_GRID_TOO_LARGE") and "49" in error


def test_legacy_sensitivity_route_rejects_an_oversized_grid_before_admitting_any_work(client):
    executor = make(2, "thread")
    p = _v2_project()
    levels = ",".join(str(i) for i in range(1, 60))
    r = client.get(f"/scenarios/sensitivity?project={p['code']}&levels={levels}",
                   headers={"Cookie": p["headers"]["Cookie"]})
    assert r.status_code == 422 and r.json()["state"] == "SENSITIVITY_GRID_TOO_LARGE"
    assert executor.stats()["admitted"] == 0


def test_v2_sensitivity_runs_as_one_admitted_ordered_task_off_the_event_loop(client, real_payload):
    from app.api import project_runner

    executor = make(2, "thread")
    p = _v2_project()
    calls: list[tuple[str, float | None]] = []

    def fake(key, scenario, *args, project_inputs_override=None, **kwargs):
        calls.append((threading.current_thread().name, getattr(project_inputs_override.financing, "target_dscr", None)))
        return copy.deepcopy(real_payload)

    with mock.patch.object(project_runner, "run_project", fake):
        r = client.post("/v2/workbook/scenarios/sensitivity/run", headers=p["headers"],
                        data={"project": p["code"], "driver": "gearing"})
    assert r.status_code == 200, r.text[:300]
    assert len(calls) == 5 and all(name.startswith("finco-model") for name, _ in calls)
    assert len({name for name, _ in calls}) == 1                      # one worker, run sequentially
    assert executor.stats()["admitted"] == 1 and executor.stats()["active"] == 0


def test_v2_sensitivity_busy_is_a_typed_429_not_five_uncontrolled_runs(client):
    executor = make(1, "thread")
    p = _v2_project()
    occupant = _saturate(executor, 2.0)
    try:
        r = client.post("/v2/workbook/scenarios/sensitivity/run", headers=p["headers"],
                        data={"project": p["code"], "driver": "gearing"})
    finally:
        occupant.release()
    assert r.status_code == 429 and r.headers["x-finco-model-busy"] == "1" and me.BUSY_MESSAGE in r.text
    assert executor.stats()["admitted"] == 1                           # only the occupant ever ran


def test_sensitivity_worker_preserves_order_and_isolates_a_failing_point():
    from app.services.sensitivity_execution import run_sensitivity_points

    class PI:
        def __init__(self, n):
            self.n = n

    calls = []

    def fake_run(key, scenario, *a, project_inputs_override=None, **k):
        calls.append(project_inputs_override.n)
        if project_inputs_override.n == 2:
            raise RuntimeError("point 2 failed")
        return {"kpis": {"n": project_inputs_override.n}}

    with mock.patch("app.api.project_runner.run_project", fake_run):
        out = run_sensitivity_points("Solar", [PI(1), PI(2), PI(3)])
    assert calls == [1, 2, 3]
    assert out[0] == {"kpis": {"n": 1}} and "error" in out[1] and out[2] == {"kpis": {"n": 3}}


# ══ structural guards: the heavy handlers never run the engine inline ═════════════════
def _async_handler_calls(path: str, handler: str) -> set[str]:
    tree = ast.parse((REPO / path).read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == handler:
            direct = set()
            for call in ast.walk(node):
                if isinstance(call, ast.Call):
                    fn = call.func
                    direct.add(fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else "")
            return direct
    raise AssertionError(f"{handler} not found")


@pytest.mark.parametrize("path,handler", [
    ("app/v2/router.py", "v2_workbook_run"),
    ("app/v2/router.py", "v2_scenario_sensitivity_run"),
    ("app/api/router.py", "post_run"),
    ("app/v2/router.py", "v2_trust_validation_fragment"),
])
def test_async_handlers_do_not_call_the_engine_inline(path, handler):
    calls = _async_handler_calls(path, handler)
    for inline in ("run_project", "run_clean_production", "execute_production_waterfall",
                   "build_validation_fragment"):
        assert inline not in calls, f"{handler} calls {inline} directly on the event loop"
    assert calls & {"run_model_process", "run_model_thread", "_run_proc"}


def test_main_web_legacy_async_routes_offload_every_direct_model_call():
    source = (REPO / "main_web.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in {
                        "run_sensitivity", "run_lender_case", "execute_production_waterfall", "_run_base_result",
                        "build_runtime_summary_csv_export", "build_institutional_workbook_export", "run_project"}:
                    offenders.append((node.name, call.func.id))
    assert offenders == [], offenders


def test_frozen_engine_and_core_are_untouched_by_this_stream():
    # Branch-owned changes only (merge-base boundary), never raw `git diff origin/main`.
    from model_v2_governance import changed_paths_vs_main
    changed = [p for p in changed_paths_vs_main()
               if p.startswith(("financial_engine/", "finco_core/"))]
    # Explicitly authorized Model V2 epic engine files are governed by the
    # Model V2 scope contract (tests/model_v2_governance.py), not this stream.
    from model_v2_governance import approved_by_active_model_v2_scope
    changed = [p for p in changed if not approved_by_active_model_v2_scope(p)]
    assert changed == []
