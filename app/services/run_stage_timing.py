"""Bounded stage timing for the POST /run pipeline (manual-QA correction).

Answers, with measurements and without guesswork, where a model run spends
time: request received → form parsed → project/workspace materialised →
runtime guard → snapshot resolved → model entered → model completed →
persistence completed → response generated.

Design constraints:
- Pure observation. Never changes what the run computes or persists.
- One structured INFO line per run (`finco.run_stages`); per-stage
  milliseconds only. No secrets, no user input values, no payloads.
- Context-local: stages recorded inside the same async task as the /run
  request (contextvars), including the thread-offloaded model call boundary
  marks, which are recorded by the orchestration around the await.
"""
from __future__ import annotations

import contextvars
import logging
import time

LOG = logging.getLogger("finco.run_stages")

# Canonical stage order (subset recorded per path is fine).
STAGE_ORDER = (
    "request_received",
    "form_parsed",
    "project_workspace_resolved",
    "runtime_guard",
    "runtime_snapshot_resolved",
    "model_entered",
    "model_completed",
    "persistence_completed",
    "response_generated",
)

_current: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "finco_run_stage_timing", default=None,
)


class RunStageTimer:
    """Records monotonic stage marks for ONE /run execution."""

    __slots__ = ("stages", "started")

    def __init__(self) -> None:
        self.stages: dict[str, float] = {}
        self.started: float = time.monotonic()

    def mark(self, stage: str) -> None:
        if stage not in STAGE_ORDER or stage in self.stages:
            return
        self.stages[stage] = time.monotonic()

    def breakdown(self) -> dict[str, int]:
        """Per-stage milliseconds from run start + inter-stage deltas."""
        out: dict[str, int] = {}
        previous_t = self.started
        for stage in STAGE_ORDER:
            t = self.stages.get(stage)
            if t is None:
                continue
            out[stage] = int((t - previous_t) * 1000)
            previous_t = t
        out["total"] = int((previous_t - self.started) * 1000)
        return out


def start_run_stages() -> RunStageTimer:
    timer = RunStageTimer()
    _current.set(timer)
    timer.mark("request_received")
    return timer


def current_run_stages() -> RunStageTimer | None:
    return _current.get()


def mark(stage: str) -> None:
    """Record a stage mark on the active run timer (no-op when absent)."""
    timer = _current.get()
    if timer is not None:
        timer.mark(stage)


def log_run_stages(*, user_scoped: bool = True, project_type: str | None = None,
                   origin: str | None = None, outcome: str = "ok") -> None:
    """Emit the single bounded timing summary line for one run.

    Terminal for that run: the context-local timer is cleared here so a
    reused execution context can never inherit stage marks from a prior
    request.  Only stage milliseconds are logged — never secrets or
    payload values.
    """
    timer = _current.get()
    _current.set(None)
    if timer is None:
        return
    breakdown = timer.breakdown()
    LOG.info(
        "run_stages outcome=%s project_type=%s origin=%s scoped_by_user=%s %s",
        outcome,
        project_type or "unknown",
        origin or "unknown",
        "1" if user_scoped else "0",
        " ".join(f"{stage}={ms}ms" for stage, ms in breakdown.items()),
    )
