# CI V3 worker calibration contract — v2 (Correction F)

Authorization: Financial Owner's standing authorization for in-scope CI V3 performance-contract corrections (Correction F, PR #388). Reviewed by no one yet; **this is a proposal under review, not an approval**.
Raw data: `calibration-samples-2026-10-27.json` (every sample, run and head). Implementation: `tools/ci_v3_calibrate.py` (`evaluate`, `approved_contract`, `STEADY_STATE_CONTRACT`), `tools/ci_v3_real_child.py`, `tools/ci_v3_production.py`.
Tests: `tests/test_ci_v3_calibration_contract_v2.py` (50), `tests/test_ci_v3_production.py` (calibration attacks), `tests/test_ci_v3_calibrate.py`, `tests/test_ci_v3_calibration_boundaries.py` (unchanged).

## What a calibration sample is

Each worker, before running any test, starts three fresh `ModelExecutor` process pools one after another (`tools/ci_v3_calibrate.py::_WORKER_PROBE`). A sample is the time for a fresh pool's first task: process spawn plus the pool initializer's
`import app.api.project_runner` plus one trivial call. Every sample is a **new process**, so any executor/start-up regression raises all three samples; what differs between sample 1 and samples 2–3 is only the operating system's file cache
(the first process reads the interpreter, extension modules and application files cold; the next two find them cached).

## Old contract (unchanged for the legacy pilot tooling)

`max(all 3 samples) <= 0.600 s`, statistic `maximum`, three samples, exit code 124 and no test execution on failure.
Original derivation (`tests/test_p0a_model_execution.py`, cancel at 0.4 s + 1.8 s, 1.5 s workload ⇒ 0.7 s cold start): that test now waits for the actual worker start (`wait_for_worker_start`, "readiness is bounded setup, not part of the cancellation window"),
so test validity no longer depends on the first start; the 0.6 s ceiling is the retained **runner-readiness requirement** that rejects slow hardware (phase 3C: a validation VM 2.4× slower than the hosted runner measured 1.012 s).

## New production contract (v2)

| Part | Rule | Value |
|---|---|---|
| Samples | exactly 3, all retained raw in `calibration.json` (`samples_s`) | unchanged |
| Steady-state start-up speed | `max(samples after the first) <= 0.600 s`, statistic `maximum` | **threshold and statistic unchanged** |
| First (cache-cold) start | `first sample <= 1.8 s` | new explicit ceiling |
| Verdict | both must hold; the aggregate **recomputes** it from the raw samples, requires the exact contract object in the receipt, and ignores any recorded verdict | fail-closed |
| Contract set | exactly two reviewed contracts are approved (legacy and v2); any other `ceiling_s`, statistic, sample count, scope or extra key raises | no free parameters |

Failure behaviour is unchanged: the child returns 124 before importing pytest, no test runs, the worker is red, the aggregate refuses.

## Evidence

* 66 hosted calibrations over 14 `public_safety_and_smoke` runs (this branch, `main` pushes, F01, unrelated PRs, another FIN-V2 branch; heads `0ee2f5ec` … `54453418`).
* **Warm samples (2nd and 3rd), n = 132:** median 0.299 s, p99 0.346 s, **maximum 0.358 s** — 1.7× below the 0.600 s ceiling, including inside the three refused workers (0.218–0.256 s).
* **First samples, n = 66:** median 0.318 s, p90 0.351 s; three outliers 0.610 s, 0.704 s, 0.802 s (all three on this branch's heads; none of 50 first samples on other branches exceeded 0.372 s). In those three workers the same VM's warm samples were 0.22–0.26 s:
  the first sample exceeded its own warm samples by 0.39–0.55 s, whereas the population median excess is 0.016 s. That is a one-time cache fill, not slow start-up.
* The calibration's own first sample warms the cache for everything that runs after it in the worker's container; the tests therefore run on the steady-state start-up the warm samples measure.
* Controlled local measurement (30 samples per tree, `main` vs branch): medians 0.350/0.349 s vs 0.334/0.352 s. Dropping the page cache before each probe raises the first sample by about 0.1 s on both trees, samples 2–3 unchanged.
* The initializer chain is identical: `import app.api.project_runner` loads the same 600 modules on `main` and on this branch (and the parent probe the same 4 application modules), so no code of this PR is on the measured path.
  (An earlier version of this evidence checked only the parent process; the child-level check was added in Correction F and confirms the same conclusion.)

## Regression-detection capability

* A real start-up slowdown (every fresh process slower) lifts the steady-state samples: a 2× slower executor start (≈ 0.6 s warm) is at the ceiling, anything slower fails. Tested with injected real delays of 0.9 s and 2.2 s in the pool initializer: refused by the steady-state gate (`test_a_really_slower_executor_startup_is_refused_by_a_real_measurement`).
  The phase-3C slow-VM class (1.012 s first start, warm ≈ 0.7 s) is still refused.
* A first start above 1.8 s fails regardless of the steady-state samples (3× the steady ceiling, 2.2× the worst hosted first sample ever recorded, 3.3× the worst cache-fill excess).
* Slower-than-ceiling warm sample, malformed/forged receipts, wrong sample counts, `bool`/`NaN`/`inf`/non-positive values, a receipt carrying a looser contract, a missing contract and a forged `meets_test_assumption=true` all fail (`tests/test_ci_v3_production.py`, `tests/test_ci_v3_calibration_contract_v2.py`).

## Limits (stated plainly)

* Detection resolution: a start-up regression smaller than about 2× (warm ≈ 0.3 s → 0.6 s) is not detected by this gate; it was not detected by the old gate either (the old gate's pass/fail on a 0.3 s baseline was driven by cache state, not by such regressions).
  Finer regression detection would need a baseline-relative measurement on matched runners and is not proposed here.
* 1.8 s is a judgement anchored on the data above, not a measured guarantee; the evidence is 66 calibrations on one runner class. It can be tightened by the CI owner once more hosted samples exist.
* The legacy `tools/ci_v3_calibrate.py` command-line record (pilot admission) keeps the all-samples maximum; only the production aggregate uses v2.
* Nothing here certifies the hosted target runner or changes any financial, native, source-identity, review or security control.

## Survivor diagnostics (integration)

The probe's "calibration left surviving descendants" check is unchanged and still a hard failure. Its message now names every survivor (pid, state, parent, command line,
read from `/proc` before the kill) at probe exit and after the kill, so a recurrence is attributable. Background: one hosted worker (PR #393, run 40548432605) raised it
before any calibration sample was written while the container-level cleanup receipt was clean; it did not reproduce in 350 local probes (idle and under CPU load), and the
original message recorded no process identity, so the survivor could not be identified.
