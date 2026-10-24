"""Native Run activation: the production switch that lets an eligible Model Run be served by the verified V10
exact-replay kernels (Stage 1 senior debt solve / finalisation / tax; optionally Stage 2 SHL) and/or the verified V11
Stage 3 kernel (Stage 3a native tax + Stage 3b full senior-debt model evaluation). Off unless configured.

Call shape at every activated site: ``native_result(await run_model_process(activated(fn), *args, **kwargs))``. While
activation is off ``activated(fn)`` is ``fn`` itself and ``native_result`` is the identity, so the call is exactly the
canonical ``await run_model_process(fn, ...)``. Otherwise the worker process executes a picklable ``NativeActivatedRun``
that binds ONE immutable ``NativeConfig(mode="candidate")`` and/or ONE immutable ``Stage3Config(mode="candidate")`` to
the Run's own context and calls ``fn`` with the same arguments (Stage 3 serves on top of V10 Stage 1+2: every senior-debt
evaluation Stage 3 declines runs the canonical path exactly as without Stage 3, including the V10 candidate); ``native_result`` records that Run's native evidence (calls served, declines by reason, build ID) in this
process and returns only the Run's value.

Native code only ever runs in an isolated model worker PROCESS: while the executor is in its dev/test ``thread`` mode a
Run is canonical, and thread-submitted Runs are never wired, so a native fault can never take down the web server
process. Every admission, loader, ABI, build-ID and source-authentication check stays in ``financial_engine.native_v10``
and ``financial_engine.native_v11`` (both unchanged by this module);
any call the kernels do not admit is served by canonical Python (a decline, counted with its reason). Results,
exceptions, CAS, fingerprints and persistence are exactly those of the canonical Run - the kernels claim exact replay and
nothing here compares or rewrites values.

Production settings (read per Run, at submission):

``FINCO_NATIVE_V10_RUN``                ``off`` (default) | ``stage1`` | ``stage1+2``; any other value is ``off``.
``FINCO_NATIVE_V10_RUN_BUILD_ID``       optional: serve only by the Stage 1 binary with exactly this build ID.
``FINCO_NATIVE_V10_KILL_SWITCH_FILE``   immediate rollback file (default ``/var/lib/finco/native_v10_run.disabled``):
                                        while it exists every new Run is canonical (V10 AND V11), without a restart and
                                        regardless of whether native code is available.
``FINCO_NATIVE_V11_RUN``                ``off`` (default) | ``on``; any other value is ``off``.
``FINCO_NATIVE_V11_RUN_BUILD_ID``       optional: serve only by the Stage 3 binary with exactly this build ID.
``FINCO_NATIVE_V11_KILL_SWITCH_FILE``   immediate V11 rollback file (default ``/var/lib/finco/native_v11_run.disabled``):
                                        while it exists no new Run uses Stage 3 (V10 stays as configured).

Production enables these through the release transaction (``deploy/scripts/release_native.sh install``), which writes
the activation file that ``deploy/systemd/finco-web.service`` loads only after every kernel was built, verified against
its committed manifest, installed and accepted by the production loaders. Kernels are never compiled at runtime; missing
or unverified artifacts make every call decline to canonical Python.
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
ENV_V11_RUN = "FINCO_NATIVE_V11_RUN"
ENV_V11_BUILD_ID = "FINCO_NATIVE_V11_RUN_BUILD_ID"
ENV_V11_KILL_SWITCH = "FINCO_NATIVE_V11_KILL_SWITCH_FILE"
DEFAULT_V11_KILL_SWITCH = "/var/lib/finco/native_v11_run.disabled"
V11_MODES = ("off", "on")

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


def _switched(env, name: str, default: str) -> str | None:
    """Reason when the kill-switch file ``name`` (or its default path) exists or cannot be checked, else ``None``."""
    try:
        os.lstat(env.get(name) or default)                       # lstat: even a dangling link disables
    except FileNotFoundError:
        return None
    except (OSError, ValueError):                                # cannot prove absence: fail closed
        return "KILL_SWITCH_UNREADABLE"
    return "KILL_SWITCH"


def _mode(env, name: str, modes) -> tuple[str, str | None]:
    raw = env.get(name)
    mode = "off" if raw is None else str(raw).strip().lower()
    if mode not in modes:
        _warn_once(f"invalid:{name}:{mode}", "native run activation: invalid %s value; treating as off", name)
        return "off", "INVALID_SETTING"
    return mode, "SETTING_OFF" if mode == "off" else None


def setting(environ=None) -> tuple[str, str | None]:
    """(effective V10 mode, reason) for a new Run. Fail closed: anything but a valid enabled mode is ``off``."""
    env = os.environ if environ is None else environ
    mode, reason = _mode(env, ENV_RUN, MODES)
    if mode == "off":
        return "off", reason
    switched = _switched(env, ENV_KILL_SWITCH, DEFAULT_KILL_SWITCH)
    return ("off", switched) if switched else (mode, None)


def v11_setting(environ=None) -> tuple[str, str | None]:
    """(effective V11 Stage 3 mode, reason) for a new Run. Fail closed like ``setting``; either kill switch disables it."""
    env = os.environ if environ is None else environ
    mode, reason = _mode(env, ENV_V11_RUN, V11_MODES)
    if mode == "off":
        return "off", reason
    switched = (_switched(env, ENV_KILL_SWITCH, DEFAULT_KILL_SWITCH)
                or _switched(env, ENV_V11_KILL_SWITCH, DEFAULT_V11_KILL_SWITCH))
    return ("off", switched) if switched else (mode, None)


def run_config(environ=None):
    """The immutable ``NativeConfig`` a new Run gets, or ``None`` when activation is off for it."""
    mode, _reason = setting(environ)
    if mode == "off":
        return None
    from financial_engine.native_v10.config import NativeConfig

    env = os.environ if environ is None else environ
    build_id = (env.get(ENV_BUILD_ID) or "").strip() or None
    return NativeConfig(mode="candidate", stage2_experimental=MODES[mode], require_build_id=build_id)


def v11_run_config(environ=None):
    """The immutable ``Stage3Config`` a new Run gets, or ``None`` when V11 activation is off for it."""
    mode, _reason = v11_setting(environ)
    if mode == "off":
        return None
    from financial_engine.native_v11.config import Stage3Config

    env = os.environ if environ is None else environ
    return Stage3Config(mode="candidate", require_build_id=(env.get(ENV_V11_BUILD_ID) or "").strip() or None)


def isolated() -> bool:
    """True only while the model executor runs submitted Runs in separate worker PROCESSES."""
    from app.runtime import model_execution as me

    return me.get_model_executor().config.mode == "process"


def activated(fn: Callable[..., Any], environ=None) -> Callable[..., Any]:
    """The callable to submit to ``run_model_process`` for one Model Run, with the activation decided now.

    Off, refused or not process-isolated: ``fn`` itself (the unchanged canonical call). On: a picklable
    ``NativeActivatedRun``; pass the awaited value through ``native_result``. Use ONLY as the callable of
    ``run_model_process`` (the model worker process), never of a thread submission."""
    config, stage3 = run_config(environ), v11_run_config(environ)
    if (config is not None or stage3 is not None) and not isolated():
        _warn_once("not-isolated", "native run activation: the model executor is not process-isolated; "
                   "Runs are served by canonical Python")
        with _LOCK:
            _TOTALS["runs_not_isolated"] += 1
        config = stage3 = None
    return fn if config is None and stage3 is None else NativeActivatedRun(fn, config, stage3)


def native_result(value: Any) -> Any:
    """The Run's own value: an activated Run's native evidence is recorded here and stripped; anything else is
    returned unchanged (identity)."""
    if isinstance(value, NativeRunOutcome):
        _record(value.config, value.stats, "ok", value.wall_s, value.stage3, value.stage3_stats)
        return value.value
    return value


@dataclass(frozen=True)
class NativeRunOutcome:
    """The Run's own return value plus the native counters of exactly that Run (picklable)."""

    value: Any
    stats: dict | None
    wall_s: float
    config: Any
    stage3: Any = None
    stage3_stats: dict | None = None


@dataclass(frozen=True)
class NativeActivatedRun:
    """One Model Run with its immutable native configuration(s); picklable for the worker process pool.

    ``config`` is the V10 ``NativeConfig`` or ``None``; ``stage3`` the V11 ``Stage3Config`` or ``None`` (at least one is
    set). Exceptions propagate unchanged (the executor transports them exactly as for a canonical Run)."""

    fn: Callable[..., Any]
    config: Any
    stage3: Any = None

    def __call__(self, *args: Any, **kwargs: Any) -> NativeRunOutcome:
        from contextlib import ExitStack

        started = time.perf_counter()
        with ExitStack() as stack:
            stats = s3 = None
            if self.config is not None:
                from financial_engine.native_v10.config import native_run
                stats = stack.enter_context(native_run(self.config))
            if self.stage3 is not None:
                from financial_engine.native_v11.config import stage3_run
                s3 = stack.enter_context(stage3_run(self.stage3))
            try:
                value = self.fn(*args, **kwargs)
            except BaseException:
                _record(self.config, stats and stats.as_dict(), "error", time.perf_counter() - started,
                        self.stage3, s3 and s3.as_dict())
                raise
        return NativeRunOutcome(value, stats and stats.as_dict(), time.perf_counter() - started, self.config,
                                self.stage3, s3 and s3.as_dict())


def _v10_counts(stats: dict | None) -> tuple[int, int]:
    if stats is None:
        return 0, 0
    return (stats["native_solves"] + stats["native_finalisations"] + stats["native_tax_evaluations"]
            + stats["stage2_native_calls"]), sum(stats["declines"].values())


def _v11_counts(stats: dict | None) -> tuple[int, int]:
    return (0, 0) if stats is None else (stats["native_models"], sum(stats["declines"].values()))


def _record(config, stats: dict | None, outcome: str, wall: float, stage3=None, stage3_stats: dict | None = None) -> None:
    """Count one activated Run; a Run whose every native call declined is reported, never hidden."""
    served, declined = _v10_counts(stats)
    served3, declined3 = _v11_counts(stage3_stats)
    with _LOCK:
        _TOTALS["runs"] += 1
        # "without": every call declined, or the worker answered from its Run cache
        _TOTALS["runs_with_native_calls" if served or served3 else "runs_without_native_calls"] += 1
        _TOTALS["native_calls"] += served
        _TOTALS["declined_calls"] += declined
        _DECLINES.update(stats["declines"] if stats else {})
        if stage3 is not None:
            _TOTALS["v11_runs"] += 1
            _TOTALS["v11_runs_with_native_models" if served3 else "v11_runs_without_native_models"] += 1
            _TOTALS["v11_native_models"] += served3
            _TOTALS["v11_declined_models"] += declined3
            _DECLINES.update({f"V11:{k}": v for k, v in stage3_stats["declines"].items()})
        _LAST.clear()
        _LAST.update({"stage2": None if config is None else config.stage2_experimental, "outcome": outcome,
                      "wall_s": round(wall, 6), "native_calls": served, **(stats or {}),
                      "v11": None if stage3 is None else {"native_models": served3, **stage3_stats}})
    for label, st in (("native_v10", stats), ("native_v11", stage3_stats)):
        if st and st["loader_reason"]:
            _warn_once(f"loader:{label}:{st['loader_reason']}", "%s run activation: kernels unavailable (%s); "
                       "Runs are served by canonical Python", label, st["loader_reason"])
    if config is not None:
        LOG.info("native_v10 run outcome=%s stage2=%s native_calls=%d declined_calls=%d build=%s wall_s=%.3f declines=%s",
                 outcome, config.stage2_experimental, served, declined, stats["build_id"], wall,
                 dict(sorted(stats["declines"].items())))
    if stage3 is not None:
        LOG.info("native_v11 run outcome=%s native_models=%d declined_models=%d build=%s wall_s=%.3f declines=%s",
                 outcome, served3, declined3, stage3_stats["build_id"], wall, stage3_stats["declines"])


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
