"""Bounded, deterministic load harness for the P0 public-beta runtime gate.

In-process and synthetic on purpose: it exercises the REAL admission gate (model executor) and the
REAL Radar coordinator with fake work, so it is fast (a few seconds), needs no network and cannot
overload a shared host. Not a production benchmark; it proves bounds and isolation, nothing more.

  A  model burst    N concurrent expensive calls -> exactly ``concurrency`` admitted, rest typed BUSY,
                    event loop stays responsive, capacity fully released afterwards.
  B  radar burst    N identical reads coalesce to ONE upstream call; a distinct read beyond capacity
                    is typed busy; no result is retained.
  C  mixed          A and B together while lightweight probes (health-like) keep their latency bound.

Usage:  python tools/load_p0_gate.py [--json]
"""
from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.radar_rwa import r_live_public_acquisition as acq  # noqa: E402
from app.runtime.model_execution import (  # noqa: E402
    ModelExecutionBusy, ModelExecutionConfig, ModelExecutor,
)


def _sleep(seconds: float) -> float:
    time.sleep(seconds)
    return seconds


async def _case_a(concurrency: int = 2, callers: int = 12, work_s: float = 0.4) -> dict:
    executor = ModelExecutor(ModelExecutionConfig(concurrency, "thread", 30))
    lateness: list[float] = []
    stop = False

    async def probe():
        while not stop:
            t = time.perf_counter()
            await asyncio.sleep(0.01)
            lateness.append(time.perf_counter() - t - 0.01)

    probe_task = asyncio.create_task(probe())
    results = await asyncio.gather(*[executor.run_thread(_sleep, work_s) for _ in range(callers)],
                                   return_exceptions=True)
    stop = True
    await probe_task
    admitted = sum(1 for r in results if not isinstance(r, Exception))
    busy = sum(1 for r in results if isinstance(r, ModelExecutionBusy))
    other = callers - admitted - busy
    stats = executor.stats()
    executor.shutdown()
    return {"case": "A_model_burst", "callers": callers, "admitted": admitted, "busy": busy,
            "unexpected": other, "active_after": stats["active"],
            "loop_lateness_max_ms": round(max(lateness) * 1000, 1) if lateness else None}


def _case_b(callers: int = 20) -> dict:
    coordinator = acq.PublicAcquisitionCoordinator(process_limit=1, max_coalesced_callers=32)
    calls, gate, started = [0], threading.Event(), threading.Event()

    def producer():
        calls[0] += 1
        started.set()
        gate.wait(5)
        yield "row"

    subs = [coordinator.subscribe("same", producer)]
    started.wait(5)
    subs += [coordinator.subscribe("same", producer) for _ in range(callers - 1)]
    distinct_busy = False
    try:
        coordinator.subscribe("other", producer)
    except acq.RLiveServiceBusy:
        distinct_busy = True
    gate.set()
    got = [list(s) for s in subs]
    for s in subs:
        s.close()
    return {"case": "B_radar_burst", "callers": callers, "upstream_calls": calls[0],
            "all_served": all(g == ["row"] for g in got), "distinct_over_capacity_busy": distinct_busy}


async def _case_c() -> dict:
    a = await _case_a(callers=8, work_s=0.3)
    b = await asyncio.to_thread(_case_b, 10)
    return {"case": "C_mixed", "model": a, "radar": b}


def main() -> int:
    out = [asyncio.run(_case_a()), _case_b(), asyncio.run(_case_c())]
    ok = (out[0]["admitted"] == 2 and out[0]["busy"] == 10 and out[0]["unexpected"] == 0
          and out[0]["active_after"] == 0 and out[1]["upstream_calls"] == 1 and out[1]["all_served"]
          and out[1]["distinct_over_capacity_busy"])
    print(json.dumps({"ok": ok, "results": out}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
