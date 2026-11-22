"""Hardware/start-up calibration. Reads no secrets and runs no test.

The original request-relative P0A test left 0.7 s for cold readiness around a 1.5 s workload.
The cancellation regression now acknowledges actual worker entry before its unchanged 0.4/1.8 s waits.
Phase 3D retains the separate 0.6 s target-runner readiness requirement: passing the corrected regression
does not waive this calibration or establish hosted environment equivalence. Local samples are not target
runner authorization, and a median does not prove tail stability under target load.

Correction F: the production contract evaluates the same 0.6 s maximum over the samples after the first (steady-state start-up
speed) and bounds the first, cache-cold sample separately; see docs/ci_v3/phase4/CALIBRATION_CONTRACT_V2.md."""
from __future__ import annotations

import argparse
import json
import math
import os
import signal
from pathlib import Path
import subprocess
import sys
import time

COLD_START_CEILING_S = 0.6   # retained pilot readiness contract; no change to the owner admission threshold

# Production contract (Correction F). The 0.6 s ceiling and the "maximum" statistic are unchanged; they now apply to the
# samples taken AFTER the first one, which measure the runner's executor start-up speed with the one-time operating-system
# cache fill already paid. The first sample keeps its own, wider, explicit ceiling. Every raw sample stays in the receipt.
# The legacy all-samples contract stays approved (it is stricter) for the pilot tooling that still requests it.
FIRST_START_CEILING_S = 1.8
LEGACY_CONTRACT = {"ceiling_s": COLD_START_CEILING_S, "statistic": "maximum", "samples": 3}
STEADY_STATE_CONTRACT = {**LEGACY_CONTRACT, "scope": "samples-after-the-first", "first_start_ceiling_s": FIRST_START_CEILING_S}


def approved_contract(contract):
    """Exactly one of the two reviewed contracts; no free parameters."""
    return isinstance(contract, dict) and contract in (LEGACY_CONTRACT, STEADY_STATE_CONTRACT)


def evaluate(samples, contract):
    """Pure verdict over the raw samples; never trusts a recorded verdict. Fails closed on any malformed input."""
    if not approved_contract(contract):
        raise ValueError("unapproved calibration contract")
    valid = (isinstance(samples, (list, tuple)) and len(samples) == contract["samples"]
             and all(not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in samples))
    record = {"contract": dict(contract), "cold_start_s": max(samples) if valid else None, "ceiling_s": contract["ceiling_s"],
              "acceptance_statistic": "maximum"}
    if not valid:
        return {**record, "meets_test_assumption": False}
    if contract == LEGACY_CONTRACT:
        return {**record, "acceptance_scope": "all-samples", "meets_test_assumption": max(samples) <= contract["ceiling_s"]}
    steady = max(samples[1:])
    return {**record, "acceptance_scope": contract["scope"], "first_start_s": samples[0], "first_start_ceiling_s": contract["first_start_ceiling_s"],
            "steady_state_max_s": steady,
            "meets_test_assumption": steady <= contract["ceiling_s"] and samples[0] <= contract["first_start_ceiling_s"]}

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
    try:
        elapsed = asyncio.run(go(ex))
    finally:
        leaks = ex.shutdown_and_join(timeout=5)
    if leaks:
        raise RuntimeError("calibration worker cleanup incomplete: " + repr(leaks))
    print(json.dumps({"cold_start_s": elapsed}))
"""


def cpu_loop_s(iterations=5_000_000):
    start = time.perf_counter(); total = 0
    for i in range(iterations):
        total += i
    return round(time.perf_counter() - start, 6)   # microsecond resolution: a fast host must not round to zero


def import_asyncio_ms():
    code = "import time;t=time.perf_counter();import asyncio;print(round((time.perf_counter()-t)*1000))"
    return int(subprocess.check_output([sys.executable, "-I", "-c", code], text=True, timeout=15).strip())


def describe_group_members(pids):
    """Who exactly survived: pid, state, parent and command line, read from /proc while the process still exists (diagnostic only; never a verdict)."""
    described = []
    for pid in pids:
        record = {"pid": int(pid)}
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            record["state"], record["ppid"] = fields[0], int(fields[1])
            record["cmdline"] = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")[:160]
        except (OSError, ValueError, IndexError):
            record["gone_before_inspection"] = True
        described.append(record)
    return described


def worker_cold_start_s(project, repeats=3, timeout_s=30):
    from tools.ci_v3_process_observer import posix_group_members
    if sys.platform != "linux":
        raise ValueError("target calibration containment requires Linux")
    if type(repeats) is not int or not 3 <= repeats <= 30:
        raise ValueError("calibration requires 3..30 retained samples")
    if not math.isfinite(timeout_s) or not 0 < timeout_s <= 60:
        raise ValueError("calibration timeout must be finite and <=60s")
    values = []
    for _ in range(repeats):
        process = subprocess.Popen([sys.executable, "-c", _WORKER_PROBE, str(Path(project).resolve())],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
            env={**{key: os.environ[key] for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS") if key in os.environ}, "PYTHONPATH": str(Path(project).resolve()), "PATH": "/usr/bin:/usr/local/bin", "HOME": "/tmp",
                 "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
        survivors = []
        survivor_detail = []
        try:
            out, error = process.communicate(timeout=timeout_s)
            if process.returncode:
                raise RuntimeError("calibration child failed: " + error[-2000:])
            sample = json.loads(out.strip().splitlines()[-1])["cold_start_s"]
            if isinstance(sample, bool) or not isinstance(sample, (int, float)) or not math.isfinite(sample) or sample <= 0:
                raise ValueError("invalid calibration sample")
            values.append(sample)
        finally:
            survivors = posix_group_members(process.pid)
            survivor_detail = describe_group_members(survivors) if survivors else []        # read BEFORE the kill removes the evidence
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate(timeout=5)
            deadline = time.monotonic() + 3
            while posix_group_members(process.pid) and time.monotonic() < deadline:
                time.sleep(.02)
            remaining = posix_group_members(process.pid)
            if survivors or remaining:
                # Still a hard failure: nothing is excused or retried. The message names every survivor so a recurrence is attributable.
                raise RuntimeError("calibration left surviving descendants: " + json.dumps(
                    {"observed_at_probe_exit": survivor_detail, "remaining_after_kill": describe_group_members(remaining)}, sort_keys=True))
    return sorted(values)[len(values) // 2], values


def verdict(cold_start_s, ceiling=COLD_START_CEILING_S):
    valid = (not isinstance(cold_start_s, bool) and isinstance(cold_start_s, (int, float))
             and math.isfinite(cold_start_s) and cold_start_s > 0)
    return {"cold_start_s": cold_start_s, "ceiling_s": ceiling,
            "meets_test_assumption": valid and cold_start_s <= ceiling}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True); parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    record = {"cpu_loop_5m_s": cpu_loop_s(), "import_asyncio_ms": import_asyncio_ms()}
    if args.project:
        median, values = worker_cold_start_s(args.project)
        record.update(worker_cold_start_samples_s=values, worker_cold_start_median_s=median,
                      acceptance_statistic="maximum-of-all-retained-samples",
                      target_runner_authorized=False, **verdict(max(values)))
    Path(args.output).write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    print(json.dumps(record)); return 0 if record.get("meets_test_assumption", True) else 3


if __name__ == "__main__":
    raise SystemExit(main())
