"""Run-local, immutable V10 candidate configuration (V10-07). Default OFF.

There is no process-global mode and no monkey patching. A Run opts in by entering
``native_run(NativeConfig(...))``; the configuration is bound to the current ``contextvars``
context only, so concurrent Runs in other threads/tasks (which start from their own context) are
unaffected. Per-Run counters (actual native executions, declines by reason) live in a fresh
``NativeRunStats`` object owned by the same context and are returned to the caller - they are the
non-invasive proof that native code really executed (V10-10).
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Iterator

MODES = ("off", "candidate")


@dataclass(frozen=True)
class NativeConfig:
    """``off``: canonical only. ``candidate``: Stage 1 native candidate may serve admitted calls.

    ``stage2_experimental`` gates the separately evaluated Stage 2 block (research, default False).
    ``require_build_id`` pins the exact verified binary (rollback/worker-generation pin).
    """

    mode: str = "off"
    stage2_experimental: bool = False
    require_build_id: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"NATIVE_V10_UNKNOWN_MODE: {self.mode!r}")
        if not isinstance(self.stage2_experimental, bool):
            raise ValueError("NATIVE_V10_STAGE2_FLAG_NOT_BOOL")


OFF = NativeConfig()


@dataclass
class NativeRunStats:
    """Mutable counters owned by exactly one native_run context."""

    native_solves: int = 0
    native_finalisations: int = 0
    native_tax_evaluations: int = 0
    stage2_native_calls: int = 0
    declines: Counter = field(default_factory=Counter)
    loader_reason: str | None = None
    build_id: str | None = None

    def as_dict(self) -> dict:
        return {"native_solves": self.native_solves, "native_finalisations": self.native_finalisations,
                "native_tax_evaluations": self.native_tax_evaluations,
                "stage2_native_calls": self.stage2_native_calls,
                "declines": dict(sorted(self.declines.items())), "loader_reason": self.loader_reason,
                "build_id": self.build_id}


_CONFIG: ContextVar[NativeConfig] = ContextVar("finco_native_v10_config", default=OFF)
_STATS: ContextVar[NativeRunStats | None] = ContextVar("finco_native_v10_stats", default=None)


def current_config() -> NativeConfig:
    return _CONFIG.get()


def current_stats() -> NativeRunStats | None:
    return _STATS.get()


@contextmanager
def native_run(config: NativeConfig) -> Iterator[NativeRunStats]:
    """Bind ``config`` to this Run's context; restore the previous binding on exit (also on error).

    Nested use with a different configuration is refused: a Run's mode is immutable once chosen.
    """
    if not isinstance(config, NativeConfig):
        raise TypeError("native_run requires a NativeConfig")
    outer = _CONFIG.get()
    if _STATS.get() is not None and outer != config:
        raise RuntimeError("NATIVE_V10_RUN_MODE_IMMUTABLE: a Run cannot change its native configuration")
    stats = _STATS.get() or NativeRunStats()
    t_cfg = _CONFIG.set(config)
    t_stats = _STATS.set(stats)
    try:
        yield stats
    finally:
        _STATS.reset(t_stats)
        _CONFIG.reset(t_cfg)
