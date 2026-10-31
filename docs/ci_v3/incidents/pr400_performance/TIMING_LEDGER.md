# PR #400 CI V3: timing ledger

## Run 41115403654 (head `966a725416196495ce1d57a8adc874dc80550a35`, attempt 1)

| Stage | Start (UTC) | End | Wall |
|---|---|---|---|
| run created (after push ~19:16) | 19:27:29 | | GitHub queueing ~11 min (not under repository control) |
| source-safety | 19:29:40 | 19:32:35 | 2.9 min (parallel) |
| route (accepted-source authentication) | 19:29:40 | 19:31:08 | 1.5 min |
| plan: Docker build | 19:31:16 | 19:33:33 | 2.3 min |
| plan: collection + baseline/reference auth + LPT | 19:33:33 | 19:35:38 | 2.1 min |
| plan: seal + plan/runtime upload | 19:35:39 | 19:35:53 | 0.25 min |
| workers (8 in parallel, setup + download ~10–30 s) | 19:35:57 | 20:22:31 | **46.5 min** (critical: worker-4) |
| aggregate / tests | 20:22:34 | 20:22:43 | failed fast (workers 3/4 failed) |

| Worker | Planned s | Measured pytest s | Container s | Job wall min | Tests | Governance-type s | Largest module (s) | Result |
|---|---|---|---|---|---|---|---|---|
| worker-0 | 2036 | 2261 | 2351 | 40.4 | 2289 | 87 | test_model_react_rcux_goal_seek_targets_v1.py (1608) | pass |
| worker-1 | 2036 | 1681 | 1765 | 30.3 | 2334 | 959 | test_v11_stage3_successor.py (868) | pass |
| worker-2 | 2036 | 2152 | 2235 | 38.2 | 2829 | 1372 | test_finance_integrity_governance.py (884) | pass |
| worker-3 | 2036 | 1942 | 2015 | 34.4 | 2850 | 1339 | test_model_mutation_security_successor.py (944) | FAIL (governance expectation) |
| worker-4 | 2036 | 2631 | 2744 | 46.5 | 2805 | 500 | test_native_v11_stage3_identity.py (452) | FAIL (governance expectation) |
| worker-5 | 2036 | 2292 | 2381 | 40.7 | 3055 | 1233 | test_financing_f3_junior_governance.py (391) | pass |
| worker-6 | 2036 | 2494 | 2586 | 43.8 | 2386 | 429 | test_native_v10_identity.py (494) | pass |
| worker-7 | 2036 | 1945 | 2030 | 34.8 | 3822 | 19 | test_model_financing_f2.py (256) | pass |

Totals: 17,399 s of pytest, mean 2175 s/worker, max 2631 s (+21% over the mean). Governance-type modules: 5939 s (34%).
Per-worker overhead outside pytest: about 90 s (container start/finalisation) plus about 30 s (checkout/setup/download).
Evidence: artifacts `public-ci-v3-worker-{0,1,2,5,6,7}-attempt-1` and `ci-v3-diagnostic-worker-{3,4}-attempt-1` of run
41115403654 (`execution/child/adapter.json` phase `duration_ms`, `process.json` `elapsed_ms`).

## Old run 41076288645 (head `cc302e4d`)
Workers finished 38–87 min after the plan; workers 2 and 3 were cut at 5400 s (2299/2731 and 713/2892 tests done). Same
worker-5 module set: 5036 s of pytest then vs 2292 s now (governance dominated).

## Critical path and forecast
```
push ─(GitHub queue ~11m)─> route 1.5m ─> plan 4.75m ─> slowest worker ─> aggregate+verify ─> mandatory-evidence
                                                          └─ floor: goal-seek NPV test 1485 s (module 1608 s) on one worker
```
| Scenario | Slowest worker pytest | Forecast run start → workers done |
|---|---|---|
| today (measured) | 2631 s | 55 min |
| + WS-2 memo (proven −44% on a governance test; governance is 34% of pytest) | about 2000–2200 s (mean ≈ 1900 s; floor 1608 s + other modules on worker-0) | ≈ 44–48 min |
| + further cohort-manifest memo (fin_v2_cohorts.allowed_path), est. similar size | ≈ 1800–2000 s | ≈ 40–45 min |
| any schedule, any worker count (floor) | ≥ 1608 s | ≥ ≈ 36 min, before aggregate/mandatory |

**≤ 30 minutes is not reachable without making the 1485 s goal-seek NPV test faster**, and that is application/solver work
outside CI scope. Achievable with semantics-neutral CI changes alone: about 40–45 min from run start to the end of the workers.
