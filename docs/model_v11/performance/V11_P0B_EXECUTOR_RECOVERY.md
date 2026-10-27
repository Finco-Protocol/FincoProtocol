# V11 P0-B — ModelExecutor process-pool recovery (generation-aware)

Scope: `app/runtime/model_execution.py` only (Financial Owner exact-path authorization for this path), plus new regression tests.
Base: `main` `6f10f3927b33a5715ac6313da200d0f96c023524` (PR #384 and #385 merged). Executor blob before: `c8c5a0dc184b8901c7cb292b0dbbd248e4cf191a`.
Evidence legend: **MEASURED** (run in this study) · **INFERRED** · **UNMEASURED**.

## 1. Root cause (MEASURED, reproduced on unmodified main with a real spawned worker)
`data/p0_repro_idle_kill.py.txt`: warm a 1-worker process pool, SIGKILL the **idle** worker, submit three Runs.

| Run | main (`6f10f392`) | this change |
|---|---|---|
| after idle kill #1 | `ModelExecutionFailed` | `ModelExecutionFailed` (the call that observes the break) |
| after idle kill #2 | `ModelExecutionFailed` | served by a new worker |
| after idle kill #3 | `ModelExecutionFailed` | served |
| `warm_state()` after the kill | `warm=True`, `warm_pids=[<dead pid>]` | `warm=False`, `warm_pids=[]` |

Defects in `main`:
1. `_submit`: `pool.submit()` on a broken pool raises `BrokenProcessPool`; the generic `except BaseException` released the slot and raised `ModelExecutionFailed` **without invalidating the pool**, so every later Run hit the same broken pool (path 2; this is the previously reported 14/14 reproduction).
2. `_translate`: `_discard_broken_process_pool()` dropped *whatever pool was current*, so a late failure from an old generation could discard a newer healthy pool.
3. Warm evidence (`_warm`, `_warm_pids`) was never cleared when a pool was discarded: destroyed workers stayed "warm".
4. `shutdown()` could be raced by a recovery that created a fresh pool after shutdown.

## 2. Change (minimal, one file)
* `_pool_lock` (order `_pool_lock → _lock`, never reversed) makes **pool selection + `submit()` atomic**: a pool cannot be retired between being chosen and used.
* `_retire_process_pool(pool)` retires by **identity**: exactly one retirement per generation; a stale observer finds the pool already replaced and does nothing; the new pool is never touched. The old pool is unpublished first and then `shutdown(wait=False, cancel_futures=True)`, so it accepts no further submission.
* `_submit` retires the pool on a **submit-time** `BrokenProcessPool` (path 2). `_translate(exc, future)` retires the generation the failed **future** was submitted to (`future.finco_pool`) (path 1).
* Warm state, including PID evidence, is cleared with the retired generation. `warm_up` publishes readiness only if the pool it probed is still current, and retires **its own** pool on failure (no second competing pool).
* Replacement is **demand-driven** (the next deliberately submitted calculation creates it, lazily) and bounded by a circuit breaker: after `MAX_POOL_RETIREMENTS = 8` retirements within `POOL_RETIREMENT_WINDOW_SECONDS = 60` no further pool is created until the window passes (`ModelExecutionFailed`).
* `shutdown()` / `shutdown_and_join()` set `_closed`; no pool can be created afterwards.
* Not changed: `ModelExecutionBusy` (non-blocking admission), `ModelExecutionFailed`, `ModelExecutionTimeout` contracts; `_process_entry`, `_finish` (slot released exactly once by the future's done-callback), cancel/timeouts, the thread mode, native shadow lifecycle. **A submitted calculation is never retried**; a submit-time failure also fails that call (it is not silently re-submitted) — only *later* calls are served by the replacement.

Diff: `app/runtime/model_execution.py` +113 / −35; new stat keys `pool_generation`, `pools_created`.

## 3. Pool generation and recovery state
```
            create (lazy, under _pool_lock)                       retire(pool)  [identity; once per generation]
 (none) ───────────────────────────────▶ GEN n  ACTIVE  ─────────────────────────────────────────▶ (none)
   ▲        breaker closed, not _closed        │  submit() atomic with selection                       │ shutdown(cancel_futures)
   │                                           │  BrokenProcessPool at submit()  ─▶ retire(GEN n)      │ warm state cleared
   │                                           │  BrokenProcessPool on a future  ─▶ retire(future.pool)│
   │                                           └─ warm_up failure ─▶ retire(own pool)                  │
   └───────────────────────────────────────── next deliberate submit creates GEN n+1 ◀─────────────────┘
 refused (ModelExecutionFailed): breaker open (≥8 retirements/60 s) or executor _closed
```
Concurrent failures: callers A and B both observe GEN n broken → A retires GEN n (returns True), B finds `_process_pool is not pool` (False) and does nothing; the next submit creates exactly one GEN n+1; a late failure still attributed to GEN n cannot retire GEN n+1.

## 4. Fault-injection matrix (real spawned OS processes; MEASURED, all pass)
| # | Scenario | Test | Result |
|---|---|---|---|
| 1 | Idle worker killed before any Run | `test_idle_worker_killed_before_any_run_recovers_for_the_next_run`, D-029 `…idle_workers_killed…` | observing call fails (typed), next Runs served; warm cleared |
| 2 | Worker killed during calculation | `…killed_during_calculation…` (unit + D-029) | that Run fails; slot released; D-029 intent FAILED, no history row |
| 3 | Pool broken before `submit()` | `…broken_pool_detected_directly_by_submit_is_invalidated` | pool unpublished, old pool rejects `submit`, next Run creates GEN n+1 |
| 4 | Simultaneous callers, same broken pool | `…simultaneous_callers_replace…exactly_once` | ≤ 1 replacement per broken generation, accounting exact |
| 5 | Replacement pool fails at startup | `…replacement_pool_failing_at_startup…` | typed failure, failed generation retired, recovers afterwards |
| 6 | Replacement worker fails native prewarm | **not applicable: native prewarm (P1) is not part of this PR** | see P1 evidence document |
| 7 | Concurrent replacement attempts | `…retirement_is_per_generation…` (8 threads) | exactly one `True`; newer pool untouched; stale-future test |
| 8 | Recovery then a new legitimate Run | every test | served by a new PID |
| 9 | Previous D-029 intent unresolved | D-029 `…killed_during_calculation…` | concurrent request sees `IN_PROGRESS` and starts no second engine; after the kill the intent is terminal FAILED; retry of the same key is **not** re-executed (executor `admitted` unchanged) |
| 10 | Lost HTTP response after committed Run | D-029 `…lost_response_after_commit…` | replayed from the ledger; executor untouched (`admitted`, `pools_created` unchanged) with a broken pool |
| 11 | Graceful shutdown during recovery | `…shutdown_during_recovery…` | no pool created after shutdown; every worker PID seen is gone |
| 12 | Repeated worker crashes | `…repeated_crashes…` (breaker), D-029 `…repeated_crashes…` | spawning bounded; 4 committed rows, 7 distinct intents, no duplicate history |

D-029 tests use the real Run route, real SQLite, real history; security gates (authorization, CSRF, protected-reference refusal, final CAS) are the route's own and run before the ledger in every request.

## 5. Lifecycle / resource-leak proof (MEASURED invariants asserted in every test)
After each scenario: `active == 0`; `admitted == completed + failed`; the admission semaphore is back at full capacity (every admitted future released its slot exactly once, including failed/cancelled ones); after shutdown no model worker PID survives; `pools_created` equals the number of generations the scenario required. Structural negative tests (AST, independent of any byte pin) reject removal of: non-blocking admission and the Busy contract, per-generation identity retirement, retirement on submit-time break, `cancel_futures` shutdown, the closed flag, the circuit breaker, and any additional submission site (no resubmission).

## 6. Governance (MEASURED)
Changing the executor blob (`c8c5a0dc… → b926e487…`) leaves every V10/V11/D-029/SEC/FIN-VAL/RC governance test green (see the CI report). The chain judges the V10 content at its immutable checkpoint, and the V11 activation-surface guard does not flag this file after P0 (it contains no V11 reference). **No successor layer was required**, so `tests/model_mutation_security_successor.py` and its test file were not modified. The original V10/V11 pins and every approved successor are untouched.

## 7. Financial identity and test results (MEASURED; CPython 3.12.3 + CI pins; Xeon family 6 model 85, 4 vCPU; NOT the VPS)
* **Through the real process executor** (`data/executor_identity.py.txt`, result `data/executor_identity_result.json`): Solar, Wind, Data Center, EV × {canonical, V10 stage 1+2, V10+V11} × 3 inputs = 36 cases, each compared executor vs in-process: payload digest (every float as its hex form), V11 served/declined counters, V10 stage 2 calls/declines. **36/36 identical, 0 mismatches.** (A first run showed 12 differences caused by my harness reusing the in-process policy memo for the direct arm; fixed by clearing the memo before each direct run, as the V11 benchmark does.)
* Representative SHL/tax/debt/scenario identity (P8, W25, S16, DC, ODR and canonical authorities): `tests/test_native_v11_stage3_identity.py` and the V10 identity/stage 2/activation/loader/reproducible-build suites are part of the governance subset below (all pass).
* Governance/executor/D-029/trust subset on the final head (154 test files: V10/V11 successors and release authority, RC-SEC/FIN-VAL/mutation successors, RC3/RC7 inventories, finance integrity, trust readiness incl. claims scan, native identity/activation/loader, P0A executor, perf runtime V2, native shadow, D-029 idempotency + new recovery tests): **3,6xx passed, 0 failed except 3 `test_ci_v3_*` tests that fail identically on pristine `main` in this sandbox (container/passwd/credential-environment tests, unrelated).**
* New tests: `tests/test_p0b_executor_recovery.py` (22 tests, real spawned workers + AST guards) and `tests/test_p0b_executor_recovery_d029.py` (4 tests). On unmodified `main` the recovery tests fail.
* Not measured: any VPS item (no SSH client/credentials in this session), HTTP click-to-result, executor oversubscription on the VPS, memory of the VPS host. These remain **UNMEASURED**.
