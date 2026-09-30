# P0 Public Beta Runtime Gate — review dossier

One PR, three Opus remediation streams: **P0-A** runtime execution isolation, **P0-B** Radar
reliability, **P0-C** secure runtime / deployment. Status: draft, unmerged. This document is
completed section by section as the streams land (§ numbers follow the task brief's dossier list).

Baseline: `main` at `a03104300df00f6c4e3b9c46cbdc00ac73c54e71`, which contains PR #148 (Yield) and
PR #149 (M-2 Signed Run Public Trust). PR #150 (Model ↔ Market Bridge) is separate and untouched.
Every finding below was re-confirmed against this main, not against earlier line numbers.

## Frozen authorities

`financial_engine/**`, `finco_core/**`, `app/model_validation/**`, `app/verified/**`, and
`finco_radar/authority/**` have zero diff. This PR changes when and where a calculation runs and how
operational reads are admitted; it does not change what FINCO calculates, any market authority,
Verify, Signed Run, the Bridge, Yield, JEV question semantics or token utility.

## Gap audit (baseline main)

| Item | Finding on main | Class |
|---|---|---|
| A. Expensive model execution paths | V2 workbook run, V2 sensitivity, public API `/api/run` and several legacy `main_web` routes execute `run_project` or the production waterfall inline in `async def` handlers | NOT DONE |
| B. Sensitivity | V2 sensitivity runs 5 sequential engine calls inline (~100 s of event-loop blocking); the legacy grid takes unbounded shocks × levels | NOT DONE |
| C. Executor / thread / process behaviour | none for model work; three unrelated limiters exist (main_web asyncio semaphore, API `run_limiter`, R-LIVE coordinator) | PARTIAL |
| D. Radar RPC entry points | stream route is coordinated; per-asset read, AAPL snapshot route, MCP tool and the JEV provider call the RPC directly | PARTIAL |
| E. Coordinator usage | `PublicAcquisitionCoordinator` covers only the all-assets stream | PARTIAL |
| F. In-flight coalescing | exists for the stream only | PARTIAL |
| G. Per-client request amplification | `PER_CLIENT_RATE_LIMIT = "NOT_IMPLEMENTED"` | NOT DONE |
| H. Collector Health liveness | `health_state` is written at collection time and read back verbatim, so a stopped collector stays HEALTHY | NOT DONE |
| I. JEV → R-LIVE ordering | SHADOW reuses the served observation; VISIBLE performs its own uncoordinated per-asset read | PARTIAL |
| J. Production app mode | `deploy/env.example` never sets `FINCO_APP_MODE`; unset means `development` | NOT DONE |
| K. Default / admin credentials | the repo-default admin password is accepted unless mode is exactly `pilot`; the default is used when the variable is unset | NOT DONE |
| L. Session / signing secrets | placeholder and missing secrets are rejected in secure modes, warned in development | PARTIAL |
| M. Production startup guards | `run_web.sh` checks presence and a `changeme` prefix only; no mode check | PARTIAL |
| N. systemd hardening | web unit sets only `NoNewPrivileges` | NOT DONE |
| O. Deployment secret handling | example env files exist; permissions and secret-in-argv rules undocumented | PARTIAL |

## A. Opus findings addressed

NEW-H-1 (event-loop blocking), H-7 residual (Radar amplification), M-7 (collector liveness),
NEW-M-2 (deploy default) and H-6 residual (systemd hardening). Each is closed in its section below.

## B. Expensive execution inventory (P0-A)

`EXPENSIVE_MODEL_EXECUTION` (now executed behind the bounded executor):

| Route | Handler kind | Now |
|---|---|---|
| `POST /v2/workbook/run` | async | worker **process** (picklable pure call) |
| `POST /v2/workbook/scenarios/sensitivity/run` | async | one admitted worker-process task for the whole grid |
| `POST /api/run` | async | worker **process** |
| `POST /api/v1/model/references/{key}/run` | sync `def` | worker **process** via the sync path, same gate |
| `GET /v2/workbook/trust/validation` | async | bounded **thread** offload (DB-bound), same gate |
| `GET /api/v1.1/projects/{id}/validation` | sync `def` | same-gate inline admission (typed 429) |
| legacy `main_web`: `/run`, `/compare`, `/save-run`, `/download`, `/scenarios/sensitivity` (+export), `/scenarios/lender-case`, `/scenarios/covenant`, `/scenarios/credit-summary`, `/scenarios/exec-summary`, `/scenarios/ic-pack`, `/scenarios/credit-pack`, `/scenarios/bess-*`, `/scenarios/report/export`, `/exports/*`, `/matrix/scenario/{id}/run` | async | bounded **thread** offload (closure-bound, cannot be pickled), same gate |

`LIGHTWEIGHT` (unchanged, deliberately not routed through the executor): reads of committed Last Run
state, `POST /v2/workbook/export` (canonical Last Run export, no engine execution), Trust Pack and
integrity reads, Verify, Signed Run verification, Radar reads, static and navigation routes.

## C. Chosen executor architecture

```
REQUEST → ADMISSION (one non-blocking gate) → BOUNDED EXECUTOR → CALCULATION → RESULT
        → existing persistence / CAS (unchanged, after the calculation returns)
```

`app/runtime/model_execution.py`. One `BoundedSemaphore` gate shared by every path; no queue. Picklable
pure calls use a spawned `ProcessPoolExecutor` (workers warmed once at pool start); closure-bound
legacy routes use a bounded thread pool behind the **same** gate, so total concurrent expensive
computation is a single number. No Redis, Celery, Kafka or distributed workers.

## D. Thread versus process benchmark

`tools/bench_model_execution.py`, one real Solar run per task (4 CPUs, two runs of the harness agree):

| Option | Event-loop lateness (p95 / max) | Wall time | Per-run time |
|---|---|---|---|
| inline (pre-fix) | 20.8 s / 20.8 s (blocked) | 20.8 s | 20.6 s |
| thread × 2 | 22 ms / 86–108 ms | 44.6 s | 44 s each (GIL serialises) |
| process × 2 (spawn, warm) | 0.3 ms / 3–28 ms | 20.9 s | 20 s each (true parallelism) |

Serialisation overhead: 113 KB pickled result. Pool start plus engine import: about 0.5 s once.
Threads keep the loop alive but two concurrent runs take twice as long; processes keep the loop
alive and run in parallel. Decision: processes for picklable pure calls; threads only for legacy
closure-bound routes (measured loop max ~100 ms, acceptable), all behind one gate.

## E. Computation concurrency semantics

- `FINCO_MODEL_EXECUTION_CONCURRENCY`: positive integer, default 2, maximum 8; invalid values fail
  startup with a typed error that never echoes a value.
- `FINCO_MODEL_EXECUTION_MODE`: `process` (default) or `thread` (dev and test fallback).
- `FINCO_MODEL_EXECUTION_TIMEOUT_SECONDS`: default 180, maximum 900. A timeout stops the caller waiting;
  the calculation is never interrupted, so the slot stays held until the work really ends and
  capacity always reflects real CPU use.
- **Scope: `PROCESS_LOCAL`.** Each Uvicorn worker owns its own gate and pool:
  `effective_host_max = workers × FINCO_MODEL_EXECUTION_CONCURRENCY` (default 2 workers × 2 = 4).
  No host-global limiter is claimed or built. The three older limiters (main_web asyncio semaphore,
  API `run_limiter`, R-LIVE coordinator) are unchanged and remain additional, looser bounds.

## F. BUSY behaviour

At capacity a request fails immediately with `MODEL_EXECUTION_BUSY`: HTTP **429** with `Retry-After: 5`,
copy "Calculation capacity is currently busy. Please retry.", no process, thread, path or trace data.
For HTMX the 429 body is a status banner marked `X-Finco-Model-Busy: 1` and a scoped client rule swaps
that one response. BUSY is not CALCULATION_FAILED: nothing ran and nothing changed.

## G. CAS and Last Run safety

The executor runs only the pure calculation. The final content-hash CAS and the atomic commit
(`v2_atomic_run_commit`) still run after the calculation returns, unchanged. Tests prove: a Working
Copy edited during a running calculation makes the commit fail closed with no Last Run and the newer
draft intact; an engine failure, an executor failure and a timeout leave no partial Last Run, no
Working Copy change and no leaked capacity; BUSY changes nothing. Cancellation semantics: **the
calculation completes and the result is discarded** if the client is gone (no unsafe cancellation
inside the engine); the slot is released by a completion callback, so a disconnect can never leak
capacity. Worker failures cross the process boundary as a plain envelope, never as a pickled
exception (a custom exception can fail to unpickle and would mark the whole pool broken).

Sensitivity: the V2 grid is one admitted, ordered task (5 evaluations); the legacy grid is capped at
49 evaluations (shocks × levels + base, the legacy default) and an oversized request is a typed 422
before any work is admitted. Sensitivity economics are unchanged.

_(Sections H–T for P0-B and P0-C are added below as those streams land.)_
