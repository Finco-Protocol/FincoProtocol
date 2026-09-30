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

## H. Radar live RPC inventory (P0-B)

| Path | Before | Now |
|---|---|---|
| `GET /api/v1.1/radar/r-live/current` (all assets, NDJSON) | coordinated | coordinated (+ per-client control) |
| `GET /api/v1.1/radar/r-live/{uid}` and the v1.1 router twin | direct RPC | `institutional.get_r_live` → coordinator |
| `GET /radar/crypto/rwa/r-live/aapl/snapshot` | direct RPC in a thread | coordinator (+ per-client control) |
| MCP `finco_r_live` | direct RPC via `get_r_live` | coordinator (busy → typed unavailable) |
| JEV intelligence provider (`default_current_provider`) | direct RPC via `get_r_live` | coordinator (busy → `R_LIVE_SERVICE_BUSY`) |
| `collect_all_approved` (systemd timer) | offline process, own RPC | unchanged: a separate process, never a web request |

The coordination lives inside `institutional.get_r_live`, the single per-asset entry point, so every
reader gets admission and coalescing at once. There is no second gate.

## I. Coordinator and in-flight coalescing

`acquire_single_current(canonical_id, rpc_url)` uses the existing `PublicAcquisitionCoordinator`
(process gate, coalescing, `CURRENT_CACHE = NONE`). Key: `("asset-current-v1", canonical_id, sha256(rpc_url))`.
Identical concurrent reads share one upstream acquisition; a distinct read beyond capacity raises
`RLiveServiceBusy`, which is an operational typed overload (HTTP 429 `SERVICE_BUSY`, `Retry-After: 5`),
never a market state. Completed results are not retained, so stale evidence can never be served as current
and no evidence timestamp is rewritten. Authority is untouched: the producer is the unchanged
`collect_r_live` / `collect_aapl_r_live` with `persist_history=False`.
JEV VISIBLE performs exactly **one** coordinated canonical read per request (tested); it has no second
canonical read and no independent RPC path. The R-LIVE canonical authority (`finco_radar/authority/**`)
is untouched.

## J. Per-client amplification control

`app/runtime/client_rate_limit.py`: fixed-window counter per (route family, client host), default 30 per
minute (`FINCO_CLIENT_REFRESH_LIMIT_PER_MINUTE`, 1–600, invalid value fails with a value-free error).
Bounded memory (4096 keys), in-process only, no persistence, no logging of keys. Applied only to the
expensive live routes (R-LIVE current, per-asset, AAPL snapshot, JEV intelligence). **Scope:
`PROCESS_LOCAL`**: with N workers one client can reach about N × the limit. It is amplification control,
not identity, not billing, and not distributed. `PER_CLIENT_RATE_LIMIT` changed from `NOT_IMPLEMENTED` to
`PROCESS_LOCAL` and its test was updated accordingly.

## K. Collector Health liveness (M-7)

The collector stamps `last_attempt_at` at the start of every run; that is the heartbeat. Health is now
computed at **read time**: `apply_liveness` compares the heartbeat age with the 5-minute timer cadence.
Under 15 minutes: stored state kept (`LIVE`). 15 minutes to 1 hour: `DEGRADED` (`STALE`). Over 1 hour:
`UNHEALTHY` (`STOPPED`). A missing or corrupt heartbeat is never healthy. Liveness can only make the
state worse than the stored outcome, never better. The public dict gains `liveness`,
`heartbeat_age_seconds` and `stored_health_state`. Per-asset failure isolation is unchanged and now tested:
one asset raising does not stop the remaining assets.

## L. systemd hardening

`deploy/systemd/finco-web.service` now sets `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`,
`ProtectKernel{Tunables,Modules,Logs}`, `ProtectControlGroups`, `ProtectClock`, `ProtectHostname`,
`LockPersonality`, `RestrictRealtime`, `RestrictSUIDSGID`, `RestrictNamespaces`,
`RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`, `SystemCallArchitectures=native`, an empty
`CapabilityBoundingSet`/`AmbientCapabilities`, `UMask=0077`, and explicit `ReadWritePaths` limited to
`storage/`, `data/` and `/var/lib/finco`. **Deliberate omissions** (each named in the unit file):
`PrivateDevices` (the worker-process pool needs POSIX semaphores in `/dev/shm`), `MemoryDenyWriteExecute`
(CPython extension modules may need W+X mappings), `SystemCallFilter` (not validated against the full
dependency set on the host), `PrivateNetwork` (the service must reach the network). These were not
enabled because they could not be proven safe without the target host; validate with
`systemd-analyze security finco-web.service` before adding any of them.

## M. Secure application mode (NEW-M-2)

`FINCO_APP_MODE=pilot` is the secure mode. `finco-web.service` sets it; `deploy/env.example` declares it;
`run_web.sh` refuses (exit 78, no values printed) unless the **effective** value is exactly `pilot`
(systemd applies `EnvironmentFile` after `Environment=`, so the launcher checks the final value).
An unrecognized mode is also treated as secure by `app/auth.py`. In a secure mode startup fails closed on:
a missing admin credential, the repository-default admin password, a placeholder, a password shorter than
12 characters, a non-bcrypt `FINCO_ADMIN_PASSWORD_HASH`, a missing or placeholder signing secret, a
placeholder CSRF secret, and `FINCO_COOKIE_SECURE=false`. Messages name the variable and the rule, never
a value. `development` and `internal` keep their documented dev workflow. The production boot-smoke
workflow now uses the secure mode with a synthetic strong credential and adds negative launcher checks.
One existing test (unrecognized mode starts with a valid secret) now also supplies an admin credential,
because an unrecognized mode is now stricter, not looser.

## N. Secrets and file permissions

`.env` owned by the service user, mode `0600`; never pass secrets in a command line; never commit `.env`.
Example files contain only placeholders that the startup checks reject, so copying an example unchanged
cannot start a secure deployment (tested). The collector unit already runs with `UMask=0077`.

## O. Debug and documentation surface

`main_web` (the production ASGI app) has no debug mode and `docs_url`, `redoc_url`, `openapi_url` are
`None`. The deliberate public surface is the self-hosted `/api/docs` and `/api/openapi.json`, which list
only `/api/v1` paths (tested). No change was needed. `main_api.py` is a separate composition that is not
the production ASGI target.

## P. Cross-system isolation

Tested (`tests/test_p0_cross_system_isolation.py`): Model saturation leaves Radar, Verify (public
certificate route) and health reads working; Radar saturation returns typed 429 for the extra read while
Model and Verify are unaffected; a Radar RPC outage is typed `UNAVAILABLE` without leaking the upstream
detail and does not affect Model or Verify; a TypeSafe/JEV transport failure is typed and independent.

## Q. Bounded load harness

`tools/load_p0_gate.py` (in-process, synthetic work, about 3 seconds): **A** model burst: 12 callers,
exactly 2 admitted, 10 typed BUSY, capacity fully released, loop lateness about 1 ms. **B** radar burst:
20 identical callers produce 1 upstream call, a distinct read beyond capacity is typed busy. **C** both
together. It proves bounds and isolation; it is not a capacity benchmark.

## R. Observability

Bounded fields only: executor `stats()` (scope, mode, concurrency, active, counters, p50 duration),
`busy_rejected` log lines with the numeric limit, collector `liveness` and `heartbeat_age_seconds`. No
secret, URL, credential, path or trace is logged or returned (tested).

## S. Verification

Focused suites: `test_p0a_model_execution.py`, `test_p0b_radar_reliability.py`,
`test_p0c_secure_runtime.py`, `test_p0_cross_system_isolation.py`, plus the updated M-7, H-7, F04 and
R-LIVE on-chain suites. Full-suite and CI results are recorded in the PR report, not in this file.

## T. Deferred (not in this PR)

- multitenancy and organisation RBAC;
- full DC-native sensitivity semantics;
- financial-engine performance optimisation (the engine is frozen; this PR only moves where it runs);
- final Product Truth reconciliation;
- Model ↔ Market production Verify activation;
- token production metering.

Known honest limits: the model gate and the per-client control are `PROCESS_LOCAL`, not host-global;
an abandoned request lets its calculation finish (semantic A); systemd omissions above are unvalidated
on a real host.
