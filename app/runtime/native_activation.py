"""V10 native Run activation: the production switch that lets an eligible Model Run be served by the verified V10
exact-replay kernels (Stage 1 senior debt solve / finalisation / tax; optionally Stage 2 SHL). Default OFF.

Call shape at every activated site: ``native_result(await run_model_process(activated(fn), *args, **kwargs))``. While
activation is off ``activated(fn)`` is ``fn`` itself and ``native_result`` is the identity, so the call is exactly the
canonical ``await run_model_process(fn, ...)``. Otherwise the worker process executes a picklable ``NativeActivatedRun``
that binds ONE immutable ``NativeConfig(mode="candidate")`` to the Run's own context and calls ``fn`` with the same
arguments; ``native_result`` records that Run's native evidence (calls served, declines by reason, build ID) in this
process and returns only the Run's value.

Native code only ever runs in an isolated model worker PROCESS: while the executor is in its dev/test ``thread`` mode a
Run is canonical, and thread-submitted Runs are never wired, so a native fault can never take down the web server
process. Every admission, loader, ABI, build-ID and source-authentication check stays in ``financial_engine.native_v10``;
any call the kernels do not admit is served by canonical Python (a decline, counted with its reason). Results,
exceptions, CAS, fingerprints and persistence are exactly those of the canonical Run - the kernels claim exact replay and
nothing here compares or rewrites values.

Production settings (read per Run, at submission):

``FINCO_NATIVE_V10_RUN``                ``off`` (default) | ``stage1`` | ``stage1+2``; any other value is ``off``.
``FINCO_NATIVE_V10_RUN_BUILD_ID``       optional: serve only by the Stage 1 binary with exactly this build ID.
``FINCO_NATIVE_V10_KILL_SWITCH_FILE``   immediate rollback file (default ``/var/lib/finco/native_v10_run.disabled``):
                                        while it exists every new Run is canonical, without a restart and regardless
                                        of whether native code is available.

Kernels are never compiled at runtime: they are built and verified offline (``deploy/scripts/build_native_v10.sh``);
missing or unverified artifacts make every call decline to canonical Python.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

ENV_RUN = "FINCO_NATIVE_V10_RUN"
ENV_BUILD_ID = "FINCO_NATIVE_V10_RUN_BUILD_ID"
ENV_KILL_SWITCH = "FINCO_NATIVE_V10_KILL_SWITCH_FILE"
DEFAULT_KILL_SWITCH = "/var/lib/finco/native_v10_run.disabled"
MODES = {"off": None, "stage1": False, "stage1+2": True}       # value: stage2_experimental

LOG = logging.getLogger("finco.native_v10.run")
_LOCK = threading.Lock()
_TOTALS: Counter = Counter()
_DECLINES: Counter = Counter()
_LAST: dict = {}
_WARNED: set = set()


def _warn_once(key: str, message: str, *args: Any) -> None:
    with _LOCK:
        if key in _WARNED:
            return
        _WARNED.add(key)
    LOG.warning(message, *args)


def setting(environ=None) -> tuple[str, str | None]:
    """(effective mode, reason) for a new Run. Fail closed: anything but a valid enabled mode is ``off``."""
    env = os.environ if environ is None else environ
    raw = env.get(ENV_RUN)
    mode = "off" if raw is None else str(raw).strip().lower()
    if mode not in MODES:
        _warn_once(f"invalid:{mode}", "native_v10 run activation: invalid %s value; treating as off", ENV_RUN)
        return "off", "INVALID_SETTING"
    if mode == "off":
        return "off", "SETTING_OFF"
    try:
        if os.path.lexists(env.get(ENV_KILL_SWITCH) or DEFAULT_KILL_SWITCH):
            return "off", "KILL_SWITCH"
    except (OSError, ValueError):
        return "off", "KILL_SWITCH_UNREADABLE"
    return mode, None


def run_config(environ=None):
    """The immutable ``NativeConfig`` a new Run gets, or ``None`` when activation is off for it."""
    mode, _reason = setting(environ)
    if mode == "off":
        return None
    from financial_engine.native_v10.config import NativeConfig

    env = os.environ if environ is None else environ
    build_id = (env.get(ENV_BUILD_ID) or "").strip() or None
    return NativeConfig(mode="candidate", stage2_experimental=MODES[mode], require_build_id=build_id)


def isolated() -> bool:
    """True only while the model executor runs submitted Runs in separate worker PROCESSES."""
    from app.runtime import model_execution as me

    return me.get_model_executor().config.mode == "process"


def activated(fn: Callable[..., Any], environ=None) -> Callable[..., Any]:
    """The callable to submit to ``run_model_process`` for one Model Run, with the activation decided now.

    Off, refused or not process-isolated: ``fn`` itself (the unchanged canonical call). On: a picklable
    ``NativeActivatedRun``; pass the awaited value through ``native_result``. Use ONLY as the callable of
    ``run_model_process`` (the model worker process), never of a thread submission."""
    config = run_config(environ)
    if config is not None and not isolated():
        _warn_once("not-isolated", "native_v10 run activation: the model executor is not process-isolated; "
                   "Runs are served by canonical Python")
        with _LOCK:
            _TOTALS["runs_not_isolated"] += 1
        config = None
    return fn if config is None else NativeActivatedRun(fn, config)


def native_result(value: Any) -> Any:
    """The Run's own value: an activated Run's native evidence is recorded here and stripped; anything else is
    returned unchanged (identity)."""
    if isinstance(value, NativeRunOutcome):
        _record(value.config, value.stats, "ok", value.wall_s)
        return value.value
    return value


@dataclass(frozen=True)
class NativeRunOutcome:
    """The Run's own return value plus the native counters of exactly that Run (picklable)."""

    value: Any
    stats: dict
    wall_s: float
    config: Any


@dataclass(frozen=True)
class NativeActivatedRun:
    """One Model Run with its immutable native configuration; picklable for the worker process pool.

    Exceptions propagate unchanged (the executor transports them exactly as for a canonical Run)."""

    fn: Callable[..., Any]
    config: Any

    def __call__(self, *args: Any, **kwargs: Any) -> NativeRunOutcome:
        from financial_engine.native_v10.config import native_run

        started = time.perf_counter()
        with native_run(self.config) as stats:
            try:
                value = self.fn(*args, **kwargs)
            except BaseException:
                _record(self.config, stats.as_dict(), "error", time.perf_counter() - started)
                raise
        return NativeRunOutcome(value, stats.as_dict(), time.perf_counter() - started, self.config)


def _record(config, stats: dict, outcome: str, wall: float) -> None:
    """Count one activated Run; a Run whose every native call declined is reported, never hidden."""
    served = (stats["native_solves"] + stats["native_finalisations"] + stats["native_tax_evaluations"]
              + stats["stage2_native_calls"])
    declined = sum(stats["declines"].values())
    with _LOCK:
        _TOTALS["runs"] += 1
        # "without": every call declined, or the worker answered from its Run cache
        _TOTALS["runs_with_native_calls" if served else "runs_without_native_calls"] += 1
        _TOTALS["native_calls"] += served
        _TOTALS["declined_calls"] += declined
        _DECLINES.update(stats["declines"])
        _LAST.clear()
        _LAST.update({"stage2": config.stage2_experimental, "outcome": outcome, "wall_s": round(wall, 6),
                      "native_calls": served, **stats})
    if stats["loader_reason"]:
        _warn_once(f"loader:{stats['loader_reason']}", "native_v10 run activation: kernels unavailable (%s); "
                   "Runs are served by canonical Python", stats["loader_reason"])
    LOG.info("native_v10 run outcome=%s stage2=%s native_calls=%d declined_calls=%d build=%s wall_s=%.3f declines=%s",
             outcome, config.stage2_experimental, served, declined, stats["build_id"], wall,
             dict(sorted(stats["declines"].items())))


def snapshot() -> dict:
    """Process-local totals of activated Runs (operations / tests)."""
    with _LOCK:
        return {"totals": dict(_TOTALS), "declines": dict(sorted(_DECLINES.items())), "last_run": dict(_LAST)}


def _reset_for_tests() -> None:
    with _LOCK:
        _TOTALS.clear()
        _DECLINES.clear()
        _LAST.clear()
        _WARNED.clear()
