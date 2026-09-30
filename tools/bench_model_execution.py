"""Bounded engineering benchmark: where should CPU-heavy FINCO model runs execute?

Compares running one real ``run_project`` inline on the event loop, in a thread, and in a
spawned process while a probe coroutine measures event-loop responsiveness. Not part of CI.

    python tools/bench_model_execution.py
"""
from __future__ import annotations

import asyncio
import dataclasses
import multiprocessing
import os
import pickle
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _inputs(i: int):
    from app import project_factories as pf
    pi = pf.create_generic_solar_reference()
    # A distinct target DSCR per call so the in-process memo cannot answer the run.
    return dataclasses.replace(pi, financing=dataclasses.replace(pi.financing, target_dscr=1.20 + 0.001 * i))


def heavy(i: int):
    from app.api.project_runner import run_project
    t = time.perf_counter()
    payload = run_project("Generic Solar Reference", "Base", project_inputs_override=_inputs(i))
    return payload, time.perf_counter() - t, os.getpid()


def _warm(_=None):
    import app.api.project_runner  # noqa: F401 - import cost paid once per worker
    return os.getpid()


async def probe(stop: asyncio.Event, samples: list[float]) -> None:
    while not stop.is_set():
        t = time.perf_counter()
        await asyncio.sleep(0.02)
        samples.append((time.perf_counter() - t - 0.02) * 1000)  # lateness in ms


async def scenario(name: str, runner, n: int) -> dict:
    samples: list[float] = []
    stop = asyncio.Event()
    task = asyncio.create_task(probe(stop, samples))
    await asyncio.sleep(0.2)
    t0 = time.perf_counter()
    results = await asyncio.gather(*(runner(i) for i in range(n)))
    wall = time.perf_counter() - t0
    stop.set()
    await task
    samples.sort()
    return {
        "scenario": name, "runs": n, "wall_s": round(wall, 1),
        "per_run_s": [round(r[1], 1) for r in results], "pids": len({r[2] for r in results}),
        "loop_lateness_ms": {"p50": round(statistics.median(samples), 1),
                             "p95": round(samples[int(len(samples) * .95)], 1), "max": round(samples[-1], 1)},
        "result_pickle_kb": round(len(pickle.dumps(results[0][0])) / 1024),
    }


async def main() -> None:
    loop = asyncio.get_running_loop()
    out = []
    out.append(await scenario("inline (current: blocks the loop)", lambda i: _inline(i), 1))
    out.append(await scenario("thread x2", lambda i: asyncio.to_thread(heavy, 10 + i), 2))
    ctx = multiprocessing.get_context("spawn")
    t = time.perf_counter()
    pool = ProcessPoolExecutor(max_workers=2, mp_context=ctx)
    await asyncio.gather(*(loop.run_in_executor(pool, _warm) for _ in range(2)))
    startup = time.perf_counter() - t
    out.append(await scenario("process x2 (spawn, warm)", lambda i: loop.run_in_executor(pool, heavy, 20 + i), 2))
    pool.shutdown()
    for row in out:
        print(row)
    print({"process_pool_startup_and_import_s": round(startup, 1), "cpus": os.cpu_count()})


async def _inline(i: int):
    await asyncio.sleep(0)
    return heavy(i)  # deliberately blocking: this is what an async handler does today


if __name__ == "__main__":
    asyncio.run(main())
