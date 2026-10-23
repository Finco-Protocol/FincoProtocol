"""Issue #348: Python 3.10 compatibility of the application lifecycle (PR #346) and the CAPEX treatment enums.

The repository declares ``requires-python >= 3.10``. On Python >= 3.11 the code uses the builtin ``ExceptionGroup`` /
``enum.StrEnum`` unchanged; on Python 3.10 it uses minimal, semantically equivalent fallbacks. CI runs a newer interpreter, so
these tests load the 3.10 fallback branches explicitly (builtin hidden) on every interpreter and compare them with the builtin
behaviour; a real 3.10 interpreter additionally runs this file in full.
"""
from __future__ import annotations

import asyncio
import builtins
import enum
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_fallback(relpath: str, name: str, monkeypatch, hide: tuple):
    """Execute a module from source into a FRESH module object with the given builtin/enum attribute hidden."""
    owner, attr = hide
    monkeypatch.delattr(owner, attr, raising=False)
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.undo()
    return module


@pytest.fixture
def fallback_lifecycle(monkeypatch):
    module = _load_fallback("app/background_lifecycle.py", "_bl_py310", monkeypatch, (builtins, "ExceptionGroup"))
    assert module.LifecycleErrors.__name__ == "LifecycleErrors"           # the 3.10 branch really was taken
    return module


def test_builtin_exception_group_is_used_where_available():
    from app.background_lifecycle import LifecycleErrors
    if sys.version_info >= (3, 11):
        assert LifecycleErrors is builtins.ExceptionGroup
    else:
        assert LifecycleErrors.__name__ == "LifecycleErrors"


def test_fallback_keeps_every_error_observable(fallback_lifecycle):
    errors = [RuntimeError("demo"), fallback_lifecycle.ShutdownIncomplete("warmer"), ValueError("native")]
    group = fallback_lifecycle.LifecycleErrors("application background shutdown incomplete", errors)
    assert group.message == "application background shutdown incomplete"
    assert group.exceptions == tuple(errors) and isinstance(group, Exception)
    assert str(group) == "application background shutdown incomplete (3 sub-exceptions)"
    if sys.version_info >= (3, 11):
        assert str(group) == str(builtins.ExceptionGroup(group.message, errors))
    one = fallback_lifecycle.LifecycleErrors("m", [RuntimeError("x")])
    assert str(one) == "m (1 sub-exception)"


@pytest.mark.parametrize("args,error", [(("m", []), ValueError), ((1, [RuntimeError()]), TypeError),
                                        (("m", [KeyboardInterrupt()]), TypeError)])
def test_fallback_validates_like_exception_group(fallback_lifecycle, args, error):
    with pytest.raises(error):
        fallback_lifecycle.LifecycleErrors(*args)
    if sys.version_info >= (3, 11):
        with pytest.raises(error):
            builtins.ExceptionGroup(*args)


def _coordinator(namespace_extra):
    import ast
    tree = ast.parse((ROOT / "main_web.py").read_text())
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_shutdown_background_services")
    node.decorator_list = []
    namespace = dict(namespace_extra)
    exec(compile(ast.Module(body=[node], type_ignores=[]), "main_web.py", "exec"), namespace)
    return namespace["_shutdown_background_services"]


def test_all_simultaneous_shutdown_errors_are_reported():
    from app.background_lifecycle import LifecycleErrors, ShutdownIncomplete
    called = []

    def failing(name):
        async def stop():
            called.append(name)
            raise ShutdownIncomplete(name + " still owns resources")
        return stop

    coordinator = _coordinator({"_stop_demo_cleanup": failing("demo"), "_stop_r_live_snapshot_warmer": failing("warmer"),
                                "_stop_native_v10_shadow": failing("native")})
    with pytest.raises(LifecycleErrors) as group:
        asyncio.run(coordinator())
    assert called == ["demo", "warmer", "native"]
    assert [str(e) for e in group.value.exceptions] == [
        "demo still owns resources", "warmer still owns resources", "native still owns resources"]
    assert all(isinstance(e, ShutdownIncomplete) for e in group.value.exceptions)


def test_clean_shutdown_raises_nothing():
    called = []

    def ok(name):
        async def stop():
            called.append(name)
        return stop

    asyncio.run(_coordinator({"_stop_demo_cleanup": ok("demo"), "_stop_r_live_snapshot_warmer": ok("warmer"),
                              "_stop_native_v10_shadow": ok("native")})())
    assert called == ["demo", "warmer", "native"]


def test_startup_rollback_failure_reports_both_errors(monkeypatch):
    import ast
    from types import SimpleNamespace

    from app.background_lifecycle import LifecycleErrors, ShutdownIncomplete
    from app.radar_rwa import r_live_warming as warming

    tree = ast.parse((ROOT / "main_web.py").read_text())
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_start_r_live_snapshot_warmer")
    node.decorator_list = []

    def foreign(**_kwargs):
        raise ShutdownIncomplete("foreign owner")

    async def rollback():
        raise RuntimeError("demo rollback failed")

    monkeypatch.setattr(warming, "start_background_warmer", foreign)
    namespace = {"app": SimpleNamespace(state=SimpleNamespace()), "_stop_demo_cleanup": rollback}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "main_web.py", "exec"), namespace)
    with pytest.raises(LifecycleErrors) as group:
        asyncio.run(namespace["_start_r_live_snapshot_warmer"]())
    assert [type(e).__name__ for e in group.value.exceptions] == ["ShutdownIncomplete", "RuntimeError"]
    assert group.value.message == "background startup and rollback failed"


# ── enum.StrEnum ────────────────────────────────────────────────────────────────

def _enum_semantics(module) -> dict:
    out = {}
    for name in sorted(dir(module)):
        cls = getattr(module, name)
        if isinstance(cls, type) and issubclass(cls, enum.Enum) and issubclass(cls, str) and cls.__module__ == module.__name__ \
                and cls is not getattr(module, "StrEnum"):
            out[name] = [(m.name, m.value, str(m), f"{m}", format(m, ">40"), m == m.value, isinstance(m, str),
                          json.dumps(m), hash(m) == hash(m.value), cls(m.value) is m, m.value == m.name.lower())
                         for m in cls]
    return out


def test_strenum_fallback_has_identical_semantics(monkeypatch):
    from app.domain.capex import source_model as current
    fallback = _load_fallback("app/domain/capex/source_model.py", "_capex_py310", monkeypatch, (enum, "StrEnum"))
    assert fallback.StrEnum is not getattr(enum, "StrEnum", None)        # the 3.10 branch really was taken
    current_semantics, fallback_semantics = _enum_semantics(current), _enum_semantics(fallback)
    assert len(current_semantics) == 7 and current_semantics == fallback_semantics
    with pytest.raises(TypeError):
        fallback.StrEnum("Bad", {"A": 1})                            # non-str values are rejected like enum.StrEnum


def test_main_web_imports_and_completes_a_lifespan():
    from fastapi.testclient import TestClient

    import main_web
    with TestClient(main_web.app) as client:
        assert client.get("/").status_code == 200


def test_native_v10_declines_on_python_310(monkeypatch):
    from financial_engine.native_v10 import eligibility
    monkeypatch.setattr(eligibility, "runtime_key", lambda: ("Linux", "x86_64", "cpython", (3, 10)))
    assert eligibility.check_runtime().startswith("RUNTIME_NOT_VALIDATED")


# ── R-LIVE lease heartbeat failure at the acquisition boundary (sys.exc_info()[1] == sys.exception()) ─────────────────

def _warmer(tmp_path, monkeypatch, behaviour):
    from app.radar_rwa import r_live_warming as warming

    warmer = warming.RLiveSnapshotWarmer(store_path=str(tmp_path / "snapshot.sqlite"))
    warmer._lease = warming._SnapshotLease(str(tmp_path / "snapshot.sqlite"))

    def warm(rpc, **kwargs):
        warmer._failure = RuntimeError("heartbeat renewal failed (fixture)")
        return behaviour()

    monkeypatch.setattr(warming, "warm_snapshot_once", warm)
    return warmer


def test_heartbeat_failure_during_acquisition_is_reported_as_incomplete(tmp_path, monkeypatch):
    from app.background_lifecycle import ShutdownIncomplete
    warmer = _warmer(tmp_path, monkeypatch, lambda: {"state": "OK", "written": 1})
    try:
        with pytest.raises(ShutdownIncomplete, match="heartbeat failed during acquisition") as raised:
            warmer.run_cycle(rpc_url="fixture")
        assert isinstance(raised.value.__cause__, RuntimeError) and warmer.last_summary is None
    finally:
        with pytest.raises(ShutdownIncomplete):
            warmer.shutdown(2)                                       # a failed cycle is never a clean shutdown


def test_heartbeat_failure_never_masks_an_acquisition_error(tmp_path, monkeypatch):
    from app.background_lifecycle import ShutdownIncomplete

    def boom():
        raise ValueError("acquisition failed (fixture)")

    warmer = _warmer(tmp_path, monkeypatch, boom)
    try:
        with pytest.raises(ValueError, match="acquisition failed"):    # the in-flight error propagates unchanged
            warmer.run_cycle(rpc_url="fixture")
    finally:
        with pytest.raises(ShutdownIncomplete):
            warmer.shutdown(2)
