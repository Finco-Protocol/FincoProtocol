"""V10 native candidate is dormant by default (V10-07 / V10-08).

Default OFF means: no native mode outside an explicit Run-local ``native_run``; every engine hook returns
None without importing native code; the model executor's OFF path neither imports the shadow observer nor
does any work beyond one environment lookup; no compiled artifact is tracked in Git.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from financial_engine.native_v10.config import NativeConfig, current_config, current_stats, native_run
from tests.native_v10_support import git_tracked

ROOT = Path(__file__).resolve().parents[1]
NATIVE_MODULES = ("financial_engine.native_v10.dispatch", "financial_engine.native_v10.loader",
                  "financial_engine.native_v10.stage2", "financial_engine.native_v10.provenance",
                  "financial_engine.native_v10.isolation", "app.runtime.native_shadow")


def _fresh_interpreter(code: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("FINCO_NATIVE_V10")}
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run([sys.executable, "-c", textwrap.dedent(code)], capture_output=True, text=True,
                          cwd=str(ROOT), env=env, timeout=600)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_default_configuration_is_off_and_immutable():
    assert NativeConfig().mode == "off" and NativeConfig().stage2_experimental is False
    assert current_config() == NativeConfig() and current_stats() is None
    with pytest.raises(ValueError):
        NativeConfig(mode="replace")
    with pytest.raises(ValueError):
        NativeConfig(mode="candidate", stage2_experimental=1)


def test_native_run_binds_only_the_current_context_and_restores_it():
    with native_run(NativeConfig(mode="candidate")) as stats:
        assert current_config().mode == "candidate" and current_stats() is stats
        with pytest.raises(RuntimeError, match="NATIVE_V10_RUN_MODE_IMMUTABLE"):
            with native_run(NativeConfig()):
                pass
        assert current_config().mode == "candidate"
    assert current_config() == NativeConfig() and current_stats() is None
    with pytest.raises(RuntimeError):
        with native_run(NativeConfig(mode="candidate")):
            raise RuntimeError("boom")
    assert current_config() == NativeConfig()


def test_engine_hooks_return_none_when_off_and_stage2_needs_its_own_flag():
    import financial_engine.senior_debt.solver as solver
    import financial_engine.shl.production as shl

    assert solver._native_v10_candidate() is None
    assert shl._native_v10_stage2() is None
    with native_run(NativeConfig(mode="candidate")):
        assert solver._native_v10_candidate() is not None
        assert shl._native_v10_stage2() is None                    # Stage 2 stays off by default
    with native_run(NativeConfig(mode="candidate", stage2_experimental=True)):
        assert shl._native_v10_stage2() is not None


def test_off_run_never_imports_native_code_or_the_shadow_observer():
    """A complete canonical production Run plus the executor OFF path, in a clean interpreter."""
    seen = _fresh_interpreter(f"""
        import asyncio, json, sys
        from app.services import production_financial_authority as pfa
        from app import project_factories as pf
        from app.runtime.model_execution import ModelExecutor, ModelExecutionConfig

        result = pfa.run_clean_production(pf.create_generic_solar_reference(), project_type="Solar")
        ex = ModelExecutor(ModelExecutionConfig(mode="thread", concurrency=1))
        value = asyncio.run(ex.run_process(len, (1, 2, 3)))
        ex.shutdown_and_join()
        print(json.dumps({{"loaded": sorted(m for m in {NATIVE_MODULES!r} if m in sys.modules),
                          "value": value, "observer": ex.native_shadow_observer() is None}}))
    """)
    assert seen == {"loaded": [], "value": 3, "observer": True}


def test_executor_off_path_does_not_enter_the_shadow(monkeypatch):
    import asyncio

    from app.runtime.model_execution import ModelExecutionConfig, ModelExecutor

    monkeypatch.delenv("FINCO_NATIVE_V10_SHADOW", raising=False)
    ex = ModelExecutor(ModelExecutionConfig(mode="thread", concurrency=1))

    async def forbidden(*_a, **_k):
        raise AssertionError("shadow entered while OFF")

    monkeypatch.setattr(ex, "_native_shadow_begin", forbidden)
    try:
        assert asyncio.run(ex.run_process(sum, (1.5, 2.5))) == 4.0
        assert ex.stats()["native_shadow"] is None
    finally:
        assert ex.shutdown_and_join() == []


def test_no_compiled_native_artifact_is_tracked_and_artifacts_are_ignored():
    assert git_tracked("*.so") == []
    for name in ("_fk_v10.so", "_fk_v10_stage2.so"):
        proc = subprocess.run(["git", "check-ignore", "-q", f"financial_engine/native_v10/{name}"], cwd=str(ROOT))
        assert proc.returncode == 0, name
