"""Run-local, immutable V11 Stage 3 candidate configuration. Default OFF.

Separate from the V10 ``NativeConfig`` (whose source is part of the approved V10 Stage 1 content and
is not modified): a Run opts in to Stage 3 by entering ``stage3_run(Stage3Config(...))``. The
configuration is bound to the current ``contextvars`` context only, so concurrent Runs in other
threads/tasks are unaffected. Stage 3 never changes the V10 configuration: when Stage 3 declines a
senior-debt model evaluation, the canonical path runs exactly as it would without Stage 3 (including
any V10 Stage 1/Stage 2 candidate the same Run has selected).

Per-Run counters (native evaluations, declines by reason) live in a fresh ``Stage3Stats`` owned by
the same context — the non-invasive proof that native code really executed.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Iterator

MODES = ("off", "candidate")


@dataclass(frozen=True)
class Stage3Config:
    """``off``: canonical only. ``candidate``: the Stage 3 native candidate may serve admitted
    senior-debt model evaluations. ``require_build_id`` pins the exact verified binary."""

    mode: str = "off"
    require_build_id: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"NATIVE_V11_UNKNOWN_MODE: {self.mode!r}")
        if self.require_build_id is not None and type(self.require_build_id) is not str:
            raise ValueError("NATIVE_V11_BUILD_ID_NOT_STR")


OFF = Stage3Config()


@dataclass
class Stage3Stats:
    """Mutable counters owned by exactly one stage3_run context."""

    native_models: int = 0            # run_senior_debt_model evaluations served end to end
    native_shl_fixed_points: int = 0  # of which SHL fixed points (one native call each)
    native_plain: int = 0             # of which non-SHL evaluations
    native_full_tax: int = 0          # Stage 3a full tax evaluations
    native_solves: int = 0            # senior solves executed natively (loop + final)
    native_tax_evaluations: int = 0   # lean tax evaluations executed natively
    declines: Counter = field(default_factory=Counter)
    loader_reason: str | None = None
    build_id: str | None = None

    def as_dict(self) -> dict:
        return {"native_models": self.native_models, "native_shl_fixed_points": self.native_shl_fixed_points,
                "native_plain": self.native_plain, "native_full_tax": self.native_full_tax,
                "native_solves": self.native_solves, "native_tax_evaluations": self.native_tax_evaluations,
                "declines": dict(sorted(self.declines.items())), "loader_reason": self.loader_reason,
                "build_id": self.build_id}


_CONFIG: ContextVar[Stage3Config] = ContextVar("finco_native_v11_stage3_config", default=OFF)
_STATS: ContextVar[Stage3Stats | None] = ContextVar("finco_native_v11_stage3_stats", default=None)


def current_config() -> Stage3Config:
    return _CONFIG.get()


def current_stats() -> Stage3Stats | None:
    return _STATS.get()


@contextmanager
def stage3_run(config: Stage3Config) -> Iterator[Stage3Stats]:
    """Bind ``config`` to this Run's context; restore the previous binding on exit (also on error).

    Nested use with a different configuration is refused: a Run's mode is immutable once chosen.
    """
    if not isinstance(config, Stage3Config):
        raise TypeError("stage3_run requires a Stage3Config")
    outer = _CONFIG.get()
    if _STATS.get() is not None and outer != config:
        raise RuntimeError("NATIVE_V11_RUN_MODE_IMMUTABLE: a Run cannot change its Stage 3 configuration")
    stats = _STATS.get() or Stage3Stats()
    t_cfg = _CONFIG.set(config)
    t_stats = _STATS.set(stats)
    try:
        yield stats
    finally:
        _STATS.reset(t_stats)
        _CONFIG.reset(t_cfg)
