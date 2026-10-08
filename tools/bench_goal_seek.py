"""Goal Seek V1 benchmark — Solar and Wind representative solves.

Runs the full deterministic bracketed solve against the REAL canonical
model and reports: model evaluations, wall time, candidate median/p95.
No strict CI wall-clock gate — the suite's deterministic guard is
max_evaluations/max_iterations (tests/test_goal_seek_v1.py).
"""
from __future__ import annotations

import asyncio
import statistics
import time

from app.api.project_runner import run_project
from app.project_factories import (
    create_generic_solar_reference,
    create_generic_wind_reference,
)
from app.services.goal_seek import (
    GoalSeekStatus,
    make_canonical_evaluator,
    resolve_metric,
    solve_tariff_for_metric,
)


def _bench(name: str, project_type: str, runtime_key: str, base, metric_key: str,
           delta: float) -> dict:
    current = float(base.revenue.ppa_base_tariff)
    metric = resolve_metric(metric_key)
    evaluator = make_canonical_evaluator(runtime_key, base, metric)

    timings: list[float] = []

    async def timed_evaluator(tariffs):
        t0 = time.perf_counter()
        values = await evaluator(tariffs)
        timings.append(time.perf_counter() - t0)
        return values

    current_irr = asyncio.run(timed_evaluator([current]))[0]
    target = current_irr + delta

    t0 = time.perf_counter()
    result = asyncio.run(solve_tariff_for_metric(
        project_type=project_type, current_tariff=current,
        target_value=target, metric_key=metric_key,
        evaluate_batch=timed_evaluator))
    wall = time.perf_counter() - t0

    per_candidate = [t / max(1, len(c)) for t, c in
                     zip(timings, [[1]] * len(timings))]  # batches are 1 in bisection
    median = statistics.median(per_candidate) if per_candidate else 0.0
    p95 = sorted(per_candidate)[int(0.95 * (len(per_candidate) - 1))] if per_candidate else 0.0

    print(f"--- {name}: solve {metric.label} target "
          f"{target * 100:.2f}% (current {current_irr * 100:.2f}% @ {current:.2f})")
    print(f"    status={result.status} solved_tariff="
          f"{result.solved_input_value:.2f} achieved={result.achieved_metric_value * 100:.4f}%")
    print(f"    model_evaluations={result.model_evaluations} iterations={result.iterations}")
    print(f"    wall={wall:.1f}s candidate_median={median:.2f}s candidate_p95={p95:.2f}s")
    assert result.status == GoalSeekStatus.SOLVED.value, result.message
    return {"name": name, "status": result.status,
            "evaluations": result.model_evaluations, "wall": wall,
            "median": median, "p95": p95}


def main() -> None:
    print("Goal Seek V1 benchmark (real canonical model, this machine)")
    _bench("Solar", "solar", "Solar", create_generic_solar_reference(),
           "project_irr", +0.01)
    _bench("Wind", "wind", "Wind", create_generic_wind_reference(),
           "pure_equity_irr", -0.02)


if __name__ == "__main__":
    main()
