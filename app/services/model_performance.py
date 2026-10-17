"""Opt-in, request-local Model timings. Never records inputs, identities or SQL."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json
import logging
import os
from time import perf_counter

LOG = logging.getLogger("finco.model_performance")
_current: ContextVar[dict | None] = ContextVar("model_performance", default=None)
STAGES = frozenset({"workspace_read", "input_build", "diagnostics", "statements", "other_projection",
                    "template_render", "json_serialization", "response_assembly", "worker_roundtrip",
                    "run_commit", "run_prepare", "post_engine", "snapshot_capture", "coherence_check"})


@contextmanager
def span(name):
    data = _current.get()
    if data is None or name not in STAGES:
        yield
        return
    start = perf_counter()
    try:
        yield
    finally:
        data["durations"][name] = data["durations"].get(name, 0.0) + (perf_counter() - start) * 1000


def observed(name):
    def decorate(function):
        @wraps(function)
        def measured(*args, **kwargs):
            if _current.get() is None:
                return function(*args, **kwargs)
            with span(name):
                return function(*args, **kwargs)
        return measured
    return decorate


def run_mark(stage):
    """Observe existing Run marks; worker time includes dispatch/IPC, not pure engine CPU."""
    data = _current.get()
    if data is None:
        return
    now = perf_counter()
    marks = data["run_marks"]
    marks[stage] = now
    pairs = {"model_entered": ("run_prepare", "project_workspace_resolved"),
             "model_completed": ("worker_roundtrip", "model_entered"),
             "persistence_completed": ("run_commit", "model_completed"),
             "response_generated": ("post_engine", "persistence_completed")}
    if stage in pairs:
        name, before = pairs[stage]
        if before in marks:
            data["durations"][name] = (now - marks[before]) * 1000


class ModelPerformanceMiddleware:
    """ASGI observation only; default off, no debug endpoint or transaction changes."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or os.getenv("FINCO_MODEL_PERF_ENABLED") != "1"
                or not scope.get("path", "").startswith(("/v2/workbook", "/v2/capex", "/v2/opex"))):
            return await self.app(scope, receive, send)
        started = perf_counter()
        data = {"durations": {}, "run_marks": {}}
        token = _current.set(data)
        async def timed_send(message):
            if message["type"] == "http.response.start":
                durations = {**data["durations"], "server": (perf_counter() - started) * 1000}
                value = ", ".join(f"{key};dur={value:.3f}" for key, value in sorted(durations.items()))
                message = {**message, "headers": [*message.get("headers", []), (b"server-timing", value.encode("ascii"))]}
            await send(message)
        try:
            await self.app(scope, receive, timed_send)
        finally:
            # Fixed metric labels only. No path, query, account, project or exception content.
            LOG.info("model_timing %s", json.dumps({**data["durations"], "server_total":
                     (perf_counter() - started) * 1000}, sort_keys=True))
            _current.reset(token)
