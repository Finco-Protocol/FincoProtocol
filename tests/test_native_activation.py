"""V10 native Run activation (``app.runtime.native_activation``): default OFF, exact replay through the production
ModelExecutor worker process, native evidence recorded in the parent, fail-closed settings and rollback, canonical
fallback for every refusal, and native code confined to isolated worker processes.

Exactness is asserted on the complete Run result (digest of every leaf), never with a numerical tolerance."""
from __future__ import annotations

import asyncio
import ast
import json
import threading
from pathlib import Path

import pytest

from app.runtime import model_execution as me
from app.runtime import native_activation as na
from tests.native_v10_support import acceptance

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "financial_engine/native_v10/fk_v10_manifest.json").read_text())


def _digest(result) -> str:
    acc = acceptance()
    return acc.digest(acc.flatten(result))


def run_uncached(project: str, scenario: str):
    """One production run_project with the worker's Run cache cleared first (a real cache-miss Run)."""
    from app.api.project_runner import run_project
    from app.services import production_financial_authority as pfa

    pfa._POLICY_RUN_CACHE.clear()
    return run_project(project, scenario)


def rejected_run():
    raise ValueError("canonical rejection (fixture)")


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    for name in (na.ENV_RUN, na.ENV_BUILD_ID):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(na.ENV_KILL_SWITCH, str(tmp_path / "native_v10_run.disabled"))
    na._reset_for_tests()
    yield
    na._reset_for_tests()


@pytest.fixture
def process_executor():
    me.reset_model_executor_for_tests(me.ModelExecutor(me.ModelExecutionConfig(mode="process", concurrency=1)))
    yield
    assert me.reset_model_executor_for_tests(None) == []


def _run(fn, *args):
    """Exactly the production call shape of every activated site."""
    async def go():
        return na.native_result(await me.run_model_process(na.activated(fn), *args))
    return asyncio.run(go())


# ── settings (no native code involved) ─────────────────────────────────────────────

@pytest.mark.parametrize("raw,mode,reason", [(None, "off", "SETTING_OFF"), ("off", "off", "SETTING_OFF"),
                                             ("stage1", "stage1", None), (" STAGE1+2 ", "stage1+2", None),
                                             ("on", "off", "INVALID_SETTING"), ("stage2", "off", "INVALID_SETTING"),
                                             ("", "off", "INVALID_SETTING")])
def test_setting_is_off_unless_exactly_enabled(raw, mode, reason):
    env = {} if raw is None else {na.ENV_RUN: raw}
    env[na.ENV_KILL_SWITCH] = "/nonexistent/native_v10_run.disabled"
    assert na.setting(env) == (mode, reason)


def test_run_config_is_the_existing_candidate_boundary():
    from financial_engine.native_v10.config import NativeConfig

    off = {na.ENV_KILL_SWITCH: "/nonexistent/x"}
    assert na.run_config(off) is None
    assert na.run_config({**off, na.ENV_RUN: "stage1"}) == NativeConfig(mode="candidate")
    assert na.run_config({**off, na.ENV_RUN: "stage1+2", na.ENV_BUILD_ID: " abc "}) == \
        NativeConfig(mode="candidate", stage2_experimental=True, require_build_id="abc")
    assert NativeConfig() == NativeConfig(mode="off", stage2_experimental=False, require_build_id=None)  # default


def test_kill_switch_file_turns_every_new_run_canonical(tmp_path):
    switch = tmp_path / "disabled"
    env = {na.ENV_RUN: "stage1+2", na.ENV_KILL_SWITCH: str(switch)}
    assert na.setting(env) == ("stage1+2", None)
    switch.write_text("")
    assert na.setting(env) == ("off", "KILL_SWITCH")
    switch.unlink()
    switch.symlink_to(tmp_path / "dangling")                      # even a dangling link disables (lexists)
    assert na.setting(env) == ("off", "KILL_SWITCH")


def test_off_is_the_unchanged_canonical_call():
    assert na.activated(len) is len                                 # the identical callable is submitted
    value = object()
    assert na.native_result(value) is value                         # identity on every non-activated value
    assert na.snapshot()["totals"] == {}


def test_enabled_but_not_process_isolated_is_canonical(monkeypatch):
    monkeypatch.setenv(na.ENV_RUN, "stage1+2")
    me.reset_model_executor_for_tests(me.ModelExecutor(me.ModelExecutionConfig(mode="thread", concurrency=1)))
    try:
        assert not na.isolated()                                    # executor in dev/test thread mode
        assert na.activated(len) is len
        assert _run(len, (1, 2, 3)) == 3
        assert na.snapshot()["totals"] == {"runs_not_isolated": 2}
    finally:
        assert me.reset_model_executor_for_tests(None) == []


# ── real native execution in the production worker process ──────────────────────────

@pytest.mark.usefixtures("native_artifacts", "process_executor")
@pytest.mark.parametrize("project", ["Solar", "Wind"])
def test_activated_run_is_exact_and_really_native(monkeypatch, project):
    off = _run(run_uncached, project, "Base")
    assert na.snapshot()["totals"] == {}
    for mode, stage2 in (("stage1", False), ("stage1+2", True)):
        monkeypatch.setenv(na.ENV_RUN, mode)
        na._reset_for_tests()
        result = _run(run_uncached, project, "Base")
        assert _digest(result) == _digest(off), mode                # the complete Run result, bit for bit
        snap = na.snapshot()
        last = snap["last_run"]
        assert snap["totals"]["runs_with_native_calls"] == 1 and last["outcome"] == "ok"
        assert last["native_solves"] > 0 and last["native_finalisations"] > 0
        assert (last["stage2_native_calls"] > 0) is stage2
        assert last["build_id"] == MANIFEST["build_id"] and last["loader_reason"] is None
        assert all(k == "STAGE2:KERNEL_STATUS_1" for k in last["declines"]), last["declines"]


@pytest.mark.usefixtures("native_artifacts", "process_executor")
def test_build_id_pin_mismatch_declines_to_the_identical_canonical_result(monkeypatch):
    off = _run(run_uncached, "Solar", "Base")
    monkeypatch.setenv(na.ENV_RUN, "stage1")
    monkeypatch.setenv(na.ENV_BUILD_ID, "0" * 64)
    result = _run(run_uncached, "Solar", "Base")
    last = na.snapshot()["last_run"]
    assert _digest(result) == _digest(off)
    assert last["native_calls"] == 0 and set(last["declines"]) == {"BUILD_ID_PIN_MISMATCH"}
    assert na.snapshot()["totals"]["runs_without_native_calls"] == 1


@pytest.mark.usefixtures("native_artifacts", "process_executor")
def test_canonical_rejection_propagates_unchanged(monkeypatch):
    monkeypatch.setenv(na.ENV_RUN, "stage1+2")
    with pytest.raises(me.ModelWorkerError) as activated:
        _run(rejected_run)
    monkeypatch.setenv(na.ENV_RUN, "off")
    with pytest.raises(me.ModelWorkerError) as canonical:
        _run(rejected_run)
    assert (activated.value.error_type, str(activated.value)) == (canonical.value.error_type, str(canonical.value))


# ── refusals inside the Run (in-process wrapper; no isolation needed to prove the fallback) ──────

def _wrapped(project="Solar", stage2=True):
    from financial_engine.native_v10.config import NativeConfig

    run = na.NativeActivatedRun(run_uncached, NativeConfig(mode="candidate", stage2_experimental=stage2))
    return run(project, "Base")


@pytest.mark.usefixtures("native_artifacts")
def test_missing_or_rejected_artifacts_serve_the_identical_canonical_result(monkeypatch, caplog):
    from financial_engine.native_v10 import loader, stage2

    off = run_uncached("Solar", "Base")
    monkeypatch.setattr(loader, "get_native", lambda *a, **k: (None, "LOADER_ARTIFACT_SHA256_MISMATCH"))
    stage2._reset_for_tests()                                       # Stage 2 re-verifies (it requires Stage 1)
    try:
        with caplog.at_level("WARNING", logger="finco.native_v10.run"):
            outcome = _wrapped()
            outcome2 = _wrapped()
    finally:
        stage2._reset_for_tests()
    assert _digest(outcome.value) == _digest(off) == _digest(outcome2.value)
    assert outcome.stats["native_solves"] == outcome.stats["stage2_native_calls"] == 0
    assert outcome.stats["loader_reason"] == "LOADER_ARTIFACT_SHA256_MISMATCH"
    assert all(k.startswith(("LOADER:", "STAGE2:")) for k in outcome.stats["declines"])
    with caplog.at_level("WARNING", logger="finco.native_v10.run"):
        for o in (outcome, outcome2):                               # what the parent records for each Run
            na._record(na.run_config({na.ENV_RUN: "stage1+2", na.ENV_KILL_SWITCH: "/nonexistent/x"}), o.stats, "ok", 0.0)
    warnings = [r for r in caplog.records if "kernels unavailable" in r.getMessage()]
    assert len(warnings) == 1                                       # reported once, never silent
    assert na.snapshot()["totals"]["runs_without_native_calls"] == 2


@pytest.mark.usefixtures("native_artifacts")
def test_unsupported_runtime_serves_the_identical_canonical_result(monkeypatch):
    from financial_engine.native_v10 import eligibility, loader, stage2

    off = run_uncached("Wind", "Base")
    monkeypatch.setattr(eligibility, "runtime_key", lambda: ("Linux", "x86_64", "cpython", (3, 11)))
    loader._reset_for_tests()
    stage2._reset_for_tests()
    try:
        outcome = _wrapped("Wind")
    finally:
        loader._reset_for_tests()
        stage2._reset_for_tests()
    assert _digest(outcome.value) == _digest(off)
    assert outcome.stats["native_solves"] == 0 and outcome.stats["loader_reason"].startswith("RUNTIME_NOT_VALIDATED")


@pytest.mark.usefixtures("native_artifacts")
def test_a_failing_native_admission_falls_back_to_canonical(monkeypatch):
    from financial_engine.native_v10 import dispatch

    off = run_uncached("Solar", "Base")

    def explode(*_a, **_k):
        raise RuntimeError("injected native admission failure")

    monkeypatch.setattr(dispatch, "_build_plan", explode)
    outcome = _wrapped(stage2=False)
    assert _digest(outcome.value) == _digest(off)
    assert outcome.stats["native_solves"] == 0
    assert any(k.startswith("ADMISSION_EXCEPTION:RuntimeError") for k in outcome.stats["declines"])


@pytest.mark.usefixtures("native_artifacts")
def test_concurrent_runs_keep_their_own_configuration_and_evidence():
    """An activated Run and a canonical Run executing at the same time never see each other's context."""
    from financial_engine.native_v10.config import current_config

    barrier, results = threading.Barrier(2), {}

    def canonical():
        barrier.wait(30)
        results["off_cfg"] = current_config().mode
        results["off"] = run_uncached("Wind", "Base")
        results["off_cfg_after"] = current_config().mode

    def activated():
        barrier.wait(30)
        results["on"] = _wrapped("Wind")

    threads = [threading.Thread(target=canonical), threading.Thread(target=activated)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(600)
    assert results["off_cfg"] == results["off_cfg_after"] == "off"
    assert results["on"].stats["native_solves"] > 0
    assert _digest(results["on"].value) == _digest(results["off"])
    assert current_config().mode == "off"


# ── wiring and release closure ───────────────────────────────────────────────────────

ACTIVATED_SITES = {
    "app/v2/router.py": 2, "app/api/router.py": 1, "app/services/goal_seek.py": 1, "app/v2/sensitivity_matrix_router.py": 1,
}
ENGINE_CALLABLES = {"run_project", "run_sensitivity_points", "_run_points", "run_matrix_points"}
PROCESS_SUBMIT = {"run_model_process", "_run_proc"}


def test_every_process_pool_engine_run_goes_through_activation():
    """Every process-pool submission of an engine Run is exactly ``native_result(await run_model_process(activated(fn),
    ...))``; ``activated`` is used nowhere else (never with a thread submission)."""
    def name(node):
        return node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", None)

    bad, counts = [], {}
    for path in sorted((ROOT / "app").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_bytes())                         # bytes: honours a UTF-8 BOM
        wrapped = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and name(node.func) == "native_result" and len(node.args) == 1 \
                    and isinstance(node.args[0], ast.Await) and isinstance(node.args[0].value, ast.Call):
                submit = node.args[0].value
                first = submit.args[0] if submit.args else None
                if name(submit.func) in PROCESS_SUBMIT and isinstance(first, ast.Call) and name(first.func) == "activated":
                    wrapped.add(id(first))
                    counts[rel] = counts.get(rel, 0) + 1
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if name(node.func) == "activated" and id(node) not in wrapped and not rel.endswith("native_activation.py"):
                bad.append(f"{rel}:{node.lineno}: activated() outside native_result(await run_model_process(...))")
            if name(node.func) in PROCESS_SUBMIT and node.args and name(node.args[0]) in ENGINE_CALLABLES:
                bad.append(f"{rel}:{node.lineno}: engine Run submitted without activation")
    assert bad == []
    assert counts == ACTIVATED_SITES


def test_activation_is_off_by_default_everywhere_it_could_be_enabled():
    workflows = "".join(p.read_text() for p in (ROOT / ".github").rglob("*.y*ml"))
    assert na.ENV_RUN not in workflows and na.ENV_BUILD_ID not in workflows
    env_example = (ROOT / "deploy/env.example").read_text()
    assert f"{na.ENV_RUN}=off" in env_example.splitlines()
    for unit in (ROOT / "deploy/systemd").glob("*.service"):
        assert na.ENV_RUN not in unit.read_text()


def test_release_refuses_a_kernel_that_differs_from_the_reviewed_manifest(tmp_path, monkeypatch):
    from tools import native_v10_release as rel

    native = tmp_path / "native_v10"
    native.mkdir()
    for _module, manifest in rel.KERNELS:
        (native / manifest).write_bytes((ROOT / "financial_engine/native_v10" / manifest).read_bytes())
        artifact = json.loads((native / manifest).read_text())["artifact"]
        (native / artifact).write_bytes(b"previously installed")

    def tampered_build(module, out):
        for mod, manifest in rel.KERNELS:
            if mod == module:
                built = json.loads((native / manifest).read_text())
                built["artifact_sha256"] = "f" * 64
                (out / manifest).write_text(json.dumps(built))
                (out / built["artifact"]).write_bytes(b"\x7fELF tampered")

    monkeypatch.setattr(rel, "NATIVE", native)
    monkeypatch.setattr(rel, "_build", tampered_build)
    monkeypatch.setattr(rel, "verify", lambda: pytest.fail("a refused kernel must never reach verification"))
    assert rel.install() == 1
    assert sorted(p.name for p in native.iterdir()) == sorted(m for _mod, m in rel.KERNELS)   # nothing installed
    assert rel.remove() == 0
