"""V11 Stage 3 native Run activation (``app.runtime.native_activation``, ``FINCO_NATIVE_V11_RUN``): fail-closed settings,
both kill switches without restart, exact replay through the production ModelExecutor worker PROCESS for the four
verticals with V11 alone and combined with V10 Stage 1+2, native evidence (models served, declines, build ID) recorded
in the parent, canonical fallback for a missing / rejected / unpinned binary, concurrency, native code confined to
isolated worker processes, and the release transaction (``tools.native_release``): exact manifest identity, atomic
install, loader + exact replay self-test, unit check, the permanent activation file, refusal leaving nothing behind.

Exactness is asserted on the complete Run result (digest of every leaf), never with a numerical tolerance."""
from __future__ import annotations

import asyncio
import json
import pickle
import threading
from pathlib import Path

import pytest

from app.runtime import model_execution as me
from app.runtime import native_activation as na
from tests.native_v10_support import acceptance

ROOT = Path(__file__).resolve().parents[1]
S1 = json.loads((ROOT / "financial_engine/native_v10/fk_v10_manifest.json").read_text())
S3 = json.loads((ROOT / "financial_engine/native_v11/fk_v11_stage3_manifest.json").read_text())
VERTICALS = ("Solar", "Wind", "Generic Data Center Reference", "Generic EV Charging Reference")
PRODUCTION = {"off": {}, "v10": {na.ENV_RUN: "stage1+2"}, "v11": {na.ENV_V11_RUN: "on"},
              "combined": {na.ENV_RUN: "stage1+2", na.ENV_BUILD_ID: S1["build_id"],
                           na.ENV_V11_RUN: "on", na.ENV_V11_BUILD_ID: S3["build_id"]}}


def _digest(result) -> str:
    acc = acceptance()
    return acc.digest(acc.flatten(result))


def run_uncached(project: str, scenario: str):
    from app.api.project_runner import run_project
    from app.services import production_financial_authority as pfa

    pfa._POLICY_RUN_CACHE.clear()
    return run_project(project, scenario)


def rejected_run():
    raise ValueError("canonical rejection (fixture)")


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    for name in (na.ENV_RUN, na.ENV_BUILD_ID, na.ENV_V11_RUN, na.ENV_V11_BUILD_ID):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(na.ENV_KILL_SWITCH, str(tmp_path / "native_v10_run.disabled"))
    monkeypatch.setenv(na.ENV_V11_KILL_SWITCH, str(tmp_path / "native_v11_run.disabled"))
    na._reset_for_tests()
    yield
    na._reset_for_tests()


@pytest.fixture
def process_executor():
    me.reset_model_executor_for_tests(me.ModelExecutor(me.ModelExecutionConfig(mode="process", concurrency=4)))
    yield
    assert me.reset_model_executor_for_tests(None) == []


def _set(monkeypatch, arm):
    for name in (na.ENV_RUN, na.ENV_BUILD_ID, na.ENV_V11_RUN, na.ENV_V11_BUILD_ID):
        monkeypatch.delenv(name, raising=False)
    for name, value in PRODUCTION[arm].items():
        monkeypatch.setenv(name, value)


def _run(fn, *args):
    """Exactly the production call shape of every activated site."""
    async def go():
        return na.native_result(await me.run_model_process(na.activated(fn), *args))
    return asyncio.run(go())


# ── settings (no native code involved) ─────────────────────────────────────────────

NO_SWITCH = {na.ENV_KILL_SWITCH: "/nonexistent/v10", na.ENV_V11_KILL_SWITCH: "/nonexistent/v11"}


@pytest.mark.parametrize("raw,mode,reason", [(None, "off", "SETTING_OFF"), ("off", "off", "SETTING_OFF"),
                                             ("on", "on", None), (" ON ", "on", None), ("true", "off", "INVALID_SETTING"),
                                             ("1", "off", "INVALID_SETTING"), ("candidate", "off", "INVALID_SETTING"),
                                             ("", "off", "INVALID_SETTING")])
def test_v11_setting_is_off_unless_exactly_on(raw, mode, reason):
    env = dict(NO_SWITCH) if raw is None else {**NO_SWITCH, na.ENV_V11_RUN: raw}
    assert na.v11_setting(env) == (mode, reason)
    assert na.setting(env) == ("off", "SETTING_OFF")                      # V11 never enables V10


def test_v11_run_config_is_the_reviewed_stage3_boundary():
    from financial_engine.native_v11.config import Stage3Config

    assert na.v11_run_config(NO_SWITCH) is None
    assert na.v11_run_config({**NO_SWITCH, na.ENV_V11_RUN: "on"}) == Stage3Config(mode="candidate")
    assert na.v11_run_config({**NO_SWITCH, na.ENV_V11_RUN: "on", na.ENV_V11_BUILD_ID: " abc "}) == \
        Stage3Config(mode="candidate", require_build_id="abc")
    assert Stage3Config() == Stage3Config(mode="off", require_build_id=None)    # the engine default stays off


def test_either_kill_switch_disables_v11_without_restart_and_only_v10s_disables_v10(tmp_path):
    v10, v11 = tmp_path / "v10", tmp_path / "v11"
    env = {na.ENV_RUN: "stage1+2", na.ENV_V11_RUN: "on", na.ENV_KILL_SWITCH: str(v10), na.ENV_V11_KILL_SWITCH: str(v11)}
    assert na.setting(env) == ("stage1+2", None) and na.v11_setting(env) == ("on", None)
    v11.write_text("")
    assert na.setting(env) == ("stage1+2", None) and na.v11_setting(env) == ("off", "KILL_SWITCH")
    v11.unlink()
    v10.symlink_to(tmp_path / "dangling")                                    # even a dangling link disables
    assert na.setting(env) == ("off", "KILL_SWITCH") and na.v11_setting(env) == ("off", "KILL_SWITCH")
    v10.unlink()
    assert na.v11_setting(env) == ("on", None)
    assert na.v11_setting({na.ENV_V11_RUN: "on", na.ENV_KILL_SWITCH: str(v10),
                           na.ENV_V11_KILL_SWITCH: "bad\0path"}) == ("off", "KILL_SWITCH_UNREADABLE")


def test_default_kill_switch_paths_are_the_documented_ones():
    assert na.DEFAULT_KILL_SWITCH == "/var/lib/finco/native_v10_run.disabled"
    assert na.DEFAULT_V11_KILL_SWITCH == "/var/lib/finco/native_v11_run.disabled"
    unit = (ROOT / "deploy/systemd/finco-web.service").read_text()
    assert "-/var/lib/finco" in unit                                          # writable for the operator, no restart
    assert na.DEFAULT_KILL_SWITCH in unit and na.DEFAULT_V11_KILL_SWITCH in unit


def test_activated_v11_run_is_one_immutable_picklable_configuration(monkeypatch):
    from financial_engine.native_v10.config import NativeConfig
    from financial_engine.native_v11.config import Stage3Config

    monkeypatch.setattr(na, "isolated", lambda: True)
    _set(monkeypatch, "v11")
    run = na.activated(run_uncached)
    assert run == na.NativeActivatedRun(run_uncached, None, Stage3Config(mode="candidate"))
    assert pickle.loads(pickle.dumps(run)) == run
    _set(monkeypatch, "combined")
    run = na.activated(run_uncached)
    assert run == na.NativeActivatedRun(run_uncached,
                                        NativeConfig(mode="candidate", stage2_experimental=True, require_build_id=S1["build_id"]),
                                        Stage3Config(mode="candidate", require_build_id=S3["build_id"]))
    with pytest.raises(Exception):
        run.stage3 = None                                                     # frozen: the Run cannot change it


def test_v11_enabled_but_not_process_isolated_is_canonical(monkeypatch):
    _set(monkeypatch, "combined")
    me.reset_model_executor_for_tests(me.ModelExecutor(me.ModelExecutionConfig(mode="thread", concurrency=1)))
    try:
        assert not na.isolated()
        assert na.activated(len) is len                                       # never native in the web server process
        assert _run(len, (1, 2, 3)) == 3
        assert na.snapshot()["totals"] == {"runs_not_isolated": 2}
    finally:
        assert me.reset_model_executor_for_tests(None) == []


# ── real native execution in the production worker process ──────────────────────────

@pytest.mark.usefixtures("stage3_artifacts", "process_executor")
@pytest.mark.parametrize("project", VERTICALS)
def test_v11_alone_and_combined_with_v10_are_exact_and_really_native(monkeypatch, project):
    _set(monkeypatch, "off")
    off = _run(run_uncached, project, "Base")
    assert na.snapshot()["totals"] == {}
    for arm in ("v11", "combined"):
        _set(monkeypatch, arm)
        na._reset_for_tests()
        result = _run(run_uncached, project, "Base")
        assert _digest(result) == _digest(off), arm                           # the complete Run result, bit for bit
        snap = na.snapshot()
        last = snap["last_run"]
        assert snap["totals"]["v11_runs_with_native_models"] == 1 and last["outcome"] == "ok", snap
        assert last["v11"]["native_models"] > 0 and last["v11"]["build_id"] == S3["build_id"]
        assert last["v11"]["loader_reason"] is None
        if arm == "combined":           # Stage 3 serves every senior-debt evaluation; V10 serves the rest (Stage 2 SHL)
            assert last["native_calls"] > 0 and last["loader_reason"] is None and last["stage2"] is True
        else:
            assert last["stage2"] is None and "native_solves" not in last         # V10 not configured


@pytest.mark.usefixtures("stage3_artifacts", "process_executor")
def test_v11_build_id_pin_mismatch_declines_to_the_identical_canonical_result(monkeypatch):
    off = _run(run_uncached, "Solar", "Base")
    monkeypatch.setenv(na.ENV_V11_RUN, "on")
    monkeypatch.setenv(na.ENV_V11_BUILD_ID, "0" * 64)
    result = _run(run_uncached, "Solar", "Base")
    snap = na.snapshot()
    assert _digest(result) == _digest(off)
    assert snap["last_run"]["v11"]["native_models"] == 0
    assert set(snap["last_run"]["v11"]["declines"]) == {"BUILD_ID_PIN_MISMATCH"}
    assert snap["totals"]["v11_runs_without_native_models"] == 1


@pytest.mark.usefixtures("stage3_artifacts", "process_executor")
def test_kill_switch_file_turns_the_next_run_canonical_without_restart(monkeypatch, tmp_path):
    _set(monkeypatch, "combined")
    first = _run(run_uncached, "Wind", "Base")
    assert na.snapshot()["last_run"]["v11"]["native_models"] > 0
    (tmp_path / "native_v11_run.disabled").write_text("")
    na._reset_for_tests()
    second = _run(run_uncached, "Wind", "Base")                               # same pool, no restart
    assert na.snapshot()["last_run"]["v11"] is None and na.snapshot()["last_run"]["native_calls"] > 0
    (tmp_path / "native_v10_run.disabled").write_text("")
    na._reset_for_tests()
    third = _run(run_uncached, "Wind", "Base")
    assert na.snapshot()["totals"] == {}                                      # the unchanged canonical call
    assert _digest(first) == _digest(second) == _digest(third)


@pytest.mark.usefixtures("stage3_artifacts", "process_executor")
def test_canonical_rejection_propagates_unchanged_with_v11(monkeypatch):
    _set(monkeypatch, "combined")
    with pytest.raises(me.ModelWorkerError) as activated:
        _run(rejected_run)
    assert na.snapshot()["last_run"] == {}                                     # recorded only in the worker
    _set(monkeypatch, "off")
    with pytest.raises(me.ModelWorkerError) as canonical:
        _run(rejected_run)
    assert (activated.value.error_type, str(activated.value)) == (canonical.value.error_type, str(canonical.value))


@pytest.mark.usefixtures("stage3_artifacts", "process_executor")
def test_concurrent_activated_runs_in_the_worker_pool_are_exact(monkeypatch):
    _set(monkeypatch, "off")
    expected = {p: _digest(_run(run_uncached, p, "Base")) for p in VERTICALS[:2]}
    _set(monkeypatch, "combined")
    na._reset_for_tests()

    async def go():
        jobs = [me.run_model_process(na.activated(run_uncached), p, "Base") for p in VERTICALS[:2] * 2]
        return [na.native_result(v) for v in await asyncio.gather(*jobs)]
    results = asyncio.run(go())
    assert [_digest(r) for r in results] == [expected[p] for p in VERTICALS[:2] * 2]
    totals = na.snapshot()["totals"]
    assert totals["runs"] == totals["v11_runs_with_native_models"] == 4


# ── refusals inside the Run (in-process wrapper; no isolation needed to prove the fallback) ──────

def _wrapped(project="Solar", v10=True, pin=None):
    from financial_engine.native_v10.config import NativeConfig
    from financial_engine.native_v11.config import Stage3Config

    run = na.NativeActivatedRun(run_uncached, NativeConfig(mode="candidate", stage2_experimental=True) if v10 else None,
                                Stage3Config(mode="candidate", require_build_id=pin))
    return run(project, "Base")


@pytest.mark.usefixtures("stage3_artifacts")
def test_missing_or_rejected_stage3_binary_serves_the_identical_result(monkeypatch, caplog):
    from financial_engine.native_v11 import stage3

    off = run_uncached("Solar", "Base")
    monkeypatch.setattr(stage3, "get_stage3", lambda *a, **k: (None, "LOADER3_ARTIFACT_MISSING"))
    with caplog.at_level("WARNING", logger="finco.native_v10.run"):
        outcome = _wrapped()
        alone = _wrapped(v10=False)
        for o in (outcome, alone):
            na._record(o.config, o.stats, "ok", 0.0, o.stage3, o.stage3_stats)
    assert _digest(outcome.value) == _digest(off) == _digest(alone.value)
    assert outcome.stage3_stats["native_models"] == 0 and outcome.stage3_stats["loader_reason"] == "LOADER3_ARTIFACT_MISSING"
    assert outcome.stats["native_solves"] > 0                                 # V10 still serves what Stage 3 declined
    warnings = [r for r in caplog.records if "native_v11 run activation: kernels unavailable" in r.getMessage()]
    assert len(warnings) == 1                                                 # reported once, never silent
    assert na.snapshot()["totals"]["v11_runs_without_native_models"] == 2


@pytest.mark.usefixtures("stage3_artifacts")
def test_concurrent_threads_keep_their_own_stage3_configuration():
    from financial_engine.native_v11.config import current_config

    barrier, results = threading.Barrier(2), {}

    def canonical():
        barrier.wait(30)
        results["off_cfg"] = current_config().mode
        results["off"] = run_uncached("Wind", "Base")
        results["off_cfg_after"] = current_config().mode

    def activated():
        barrier.wait(30)
        results["on"] = _wrapped("Wind", v10=False)

    threads = [threading.Thread(target=canonical), threading.Thread(target=activated)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(600)
    assert results["off_cfg"] == results["off_cfg_after"] == "off"
    assert results["on"].stage3_stats["native_models"] > 0
    assert _digest(results["on"].value) == _digest(results["off"])
    assert current_config().mode == "off"


# ── release transaction ─────────────────────────────────────────────────────────────

def test_activation_file_is_the_exact_pinned_production_activation():
    from tools import native_release as rel

    text = rel.activation_text()
    values = dict(line.split("=", 1) for line in text.splitlines() if line and not line.startswith("#"))
    assert values == {na.ENV_RUN: "stage1+2", na.ENV_BUILD_ID: S1["build_id"], na.ENV_V11_RUN: "on",
                      na.ENV_V11_BUILD_ID: S3["build_id"]}
    env = {**values, **NO_SWITCH}
    assert na.setting(env) == ("stage1+2", None) and na.v11_setting(env) == ("on", None)
    assert rel.ACTIVATION_FILE == ROOT / ".env.native" and not rel.ACTIVATION_FILE.exists()   # never in a checkout
    assert "SECRET" not in text and "PASSWORD" not in text
    import subprocess
    assert subprocess.run(["git", "check-ignore", "-q", ".env.native"], cwd=ROOT).returncode == 0


def _release_sandbox(tmp_path, monkeypatch):
    from tools import native_release as rel

    kernels = []
    for directory, module, manifest in rel.KERNELS:
        target = tmp_path / directory.name
        target.mkdir(exist_ok=True)
        (target / manifest).write_bytes((directory / manifest).read_bytes())
        kernels.append((target, module, manifest))
    monkeypatch.setattr(rel, "KERNELS", tuple(kernels))
    monkeypatch.setattr(rel, "ACTIVATION_FILE", tmp_path / ".env.native")
    return rel


def _faithful_build(rel, tamper=None):
    def build(module, out):
        for directory, mod, manifest in rel.KERNELS:
            if mod == module:
                built = json.loads((directory / manifest).read_text())
                if tamper and manifest == tamper:
                    built["artifact_sha256"] = "f" * 64
                (out / manifest).write_text(json.dumps(built))
                (out / built["artifact"]).write_bytes(b"\x7fELF " + manifest.encode())
    return build


def test_release_installs_verifies_and_activates_atomically_and_idempotently(tmp_path, monkeypatch, capsys):
    rel = _release_sandbox(tmp_path, monkeypatch)
    monkeypatch.setattr(rel, "_build", _faithful_build(rel))
    monkeypatch.setattr(rel, "verify", lambda: {"self_test": {"identical": True}})
    monkeypatch.setattr(rel, "unit_loads_activation", lambda: None)
    for _ in range(2):                                                        # idempotent
        assert rel.install() == 0
        assert rel.ACTIVATION_FILE.read_text() == rel.activation_text()
        assert all(p.exists() for p in rel._artifacts())
        assert not list(tmp_path.rglob(".*.staged"))
    assert oct(rel.ACTIVATION_FILE.stat().st_mode & 0o777) == "0o644"
    assert rel.check() == 0
    rel.ACTIVATION_FILE.write_text(rel.activation_text().replace("=on", "=off"))
    assert rel.check() == 1                                                   # an edited activation is not verified
    assert rel.remove() == 0
    assert not rel.ACTIVATION_FILE.exists() and not any(p.exists() for p in rel._artifacts())


@pytest.mark.parametrize("failure", ["manifest", "verify", "unit"])
def test_release_refusal_leaves_no_kernel_and_no_activation(tmp_path, monkeypatch, failure, capsys):
    rel = _release_sandbox(tmp_path, monkeypatch)
    for path in rel._artifacts():
        path.write_bytes(b"previously installed")
    rel.ACTIVATION_FILE.write_text(rel.activation_text())                     # a previous release
    monkeypatch.setattr(rel, "_build", _faithful_build(rel, "fk_v11_stage3_manifest.json" if failure == "manifest" else None))

    def verify():
        if failure == "manifest":
            pytest.fail("a refused kernel must never reach verification")
        if failure == "verify":
            raise RuntimeError("exact replay self-test failed")
        return {}
    monkeypatch.setattr(rel, "verify", verify)
    monkeypatch.setattr(rel, "unit_loads_activation", lambda: "the installed finco-web.service does not load it")
    assert rel.install() == 1
    assert "REFUSED" in capsys.readouterr().err
    assert not rel.ACTIVATION_FILE.exists() and not any(p.exists() for p in rel._artifacts())
    assert not list(tmp_path.rglob(".*.staged"))


def test_unit_check_requires_the_installed_unit_to_load_the_activation_file(monkeypatch):
    from tools import native_release as rel

    monkeypatch.setattr(rel.shutil, "which", lambda _name: None)
    assert "systemctl is unavailable" in rel.unit_loads_activation()

    class Proc:
        def __init__(self, out, code=0):
            self.stdout, self.returncode = out, code
    monkeypatch.setattr(rel.shutil, "which", lambda _name: "/bin/systemctl")
    monkeypatch.setattr(rel.subprocess, "run", lambda *a, **k: Proc("/opt/finco_protocol/.env (ignore_errors=no)"))
    assert "does not load" in rel.unit_loads_activation()
    monkeypatch.setattr(rel.subprocess, "run",
                        lambda *a, **k: Proc(f"/opt/finco_protocol/.env (ignore_errors=no) {rel.ACTIVATION_FILE} (ignore_errors=yes)"))
    assert rel.unit_loads_activation() is None


@pytest.mark.usefixtures("stage3_artifacts")
def test_release_verification_proves_loaders_and_exact_replay_in_a_fresh_interpreter():
    from tools import native_release as rel

    result = rel.verify()
    assert (result["stage1"], result["stage3"]) == (S1["build_id"], S3["build_id"]) and result["runtime"] is None
    test = result["self_test"]
    assert test["identical"] and test["v10_alone_native_calls"] > 0 and test["v11_native_models"] > 0
    assert test["v11_build_id"] == S3["build_id"] and test["v10_build_id"] == S1["build_id"]


def test_release_script_runs_the_release_transaction():
    script = (ROOT / "deploy/scripts/release_native.sh").read_text()
    assert 'exec "$PYTHON_BIN" -m tools.native_release "${1:-install}"' in script
    assert (ROOT / "deploy/scripts/release_native.sh").stat().st_mode & 0o111


@pytest.mark.usefixtures("stage3_artifacts", "process_executor")
@pytest.mark.parametrize("reference,capacity", [("generic_solar_reference", 64.0), ("generic_ev_charging_reference", 8.0)])
def test_public_api_v1_reference_run_is_exact_in_production_configuration(monkeypatch, reference, capacity):
    """POST /api/v1/model/references/{key}/run (plain ``def`` route, ``run_model_process_sync``) through the worker
    process: the JSON response is byte-identical canonical vs the production configuration, and served natively."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.router import router as v1_router
    from app.services import production_financial_authority as pfa

    app = FastAPI()
    app.include_router(v1_router, prefix="/api/v1")
    client = TestClient(app, raise_server_exceptions=False)
    bodies = {}
    for arm in ("off", "combined"):
        _set(monkeypatch, arm)
        na._reset_for_tests()
        pfa._POLICY_RUN_CACHE.clear()
        resp = client.post(f"/api/v1/model/references/{reference}/run", json={"capacity_mw": capacity})
        assert resp.status_code == 200, resp.text
        bodies[arm] = resp.content
        snap = na.snapshot()
        if arm == "off":
            assert snap["totals"] == {}
        else:
            assert snap["totals"]["v11_runs_with_native_models"] == 1, snap
    assert bodies["combined"] == bodies["off"]
