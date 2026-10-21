"""Hardware/start-up calibration. Reads no secrets and runs no test.

`tests/test_p0a_model_execution.py` assumes a cold process-pool worker starts well inside its fixed sleeps
(2.2 s budget around a 1.5 s calculation, so cold start must stay below 0.7 s). That assumption holds on the hosted
control runner and not on slower hosts. The cold-start ceiling here is derived from those fixed test sleeps, not
tuned; a host above it must not be used for a three-worker shadow worker."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

COLD_START_CEILING_S = 0.6   # test budget 0.7 s minus margin; derived from tests/test_p0a_model_execution.py sleeps

_WORKER_PROBE = r"""
import asyncio, json, sys, time
sys.path[:0] = [sys.argv[1] + "/tests", sys.argv[1]]
import p0_exec_helpers as helpers
from app.runtime import model_execution as me
from app.runtime.model_execution import ModelExecutionConfig, ModelExecutor
async def go(ex):
    t = time.perf_counter(); await ex.run_process(helpers.add, 1, 1); return time.perf_counter() - t
if __name__ == "__main__":
    ex = ModelExecutor(ModelExecutionConfig(1, "process", 60)); me.reset_model_executor_for_tests(ex)
    print(json.dumps({"cold_start_s": round(asyncio.run(go(ex)), 3)}))
"""


def cpu_loop_s(iterations=5_000_000):
    start = time.perf_counter(); total = 0
    for i in range(iterations):
        total += i
    return round(time.perf_counter() - start, 6)   # microsecond resolution: a fast host must not round to zero


def import_asyncio_ms():
    code = "import time;t=time.perf_counter();import asyncio;print(round((time.perf_counter()-t)*1000))"
    return int(subprocess.check_output([sys.executable, "-I", "-c", code], text=True).strip())


def worker_cold_start_s(project, repeats=3):
    values = []
    for _ in range(repeats):
        out = subprocess.check_output([sys.executable, "-c", _WORKER_PROBE, str(Path(project).resolve())], text=True,
                                      env={"PYTHONPATH": str(Path(project).resolve()), "PATH": "/usr/bin:/usr/local/bin", "HOME": "/tmp",
                                           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
        values.append(json.loads(out.strip().splitlines()[-1])["cold_start_s"])
    return sorted(values)[len(values) // 2], values


def verdict(cold_start_s, ceiling=COLD_START_CEILING_S):
    return {"cold_start_s": cold_start_s, "ceiling_s": ceiling, "meets_test_assumption": cold_start_s <= ceiling}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project"); parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    record = {"cpu_loop_5m_s": cpu_loop_s(), "import_asyncio_ms": import_asyncio_ms()}
    if args.project:
        median, values = worker_cold_start_s(args.project)
        record.update(worker_cold_start_samples_s=values, **verdict(median))
    Path(args.output).write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    print(json.dumps(record)); return 0 if record.get("meets_test_assumption", True) else 3


if __name__ == "__main__":
    raise SystemExit(main())
