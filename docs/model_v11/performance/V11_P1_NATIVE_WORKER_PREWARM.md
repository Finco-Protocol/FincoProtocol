# V11 P1 — Native worker prewarm

**Classification: OWNER_APPROVAL_REQUIRED. Not implemented in this PR.**

## Why it is gated
The worker probe lives in `app/runtime/model_execution.py`, whose blob **`c8c5a0dc184b8901c7cb292b0dbbd248e4cf191a`** is an exact-content pin of the V10 native-shadow approval (`docs/model_v10/v10-native-shadow-content-approval.json` → `application_blobs`; `tests/v10_native_shadow_successor.py` `APPLICATION["app/runtime/model_execution.py"] = (22dd596a…, c8c5a0dc…)`; Financial Owner "Decision A"). Any edit changes that blob. The related loaders (`financial_engine/native_v10/loader.py`, `stage2.py`, `native_v11/stage3.py`) are protected and are not touched by the proposal.

### Approval request
1. Exact path: `app/runtime/model_execution.py`; existing blob `c8c5a0dc184b8901c7cb292b0dbbd248e4cf191a`.
2. Proposed minimal change: (a) extend `_worker_warmup_probe` to return a sanitized `native` section after calling the *existing* loaders (`loader.get_native()`, `stage2.get_stage2()`, `stage3.get_stage3()`), gated by `native_activation.setting()` / `v11_setting()` evaluated **inside the worker**, compare each loaded build ID with the configured pin, evict a *failed* result from the loader's per-process cache so the first Run still retries exactly as today; (b) `ModelExecutor.warm_up` records native readiness per distinct PID and continues its bounded second sweep until every PID has reported; (c) `_discard_broken_process_pool` clears native readiness (replacement PIDs are cold); (d) `warm_state()`/`stats()` expose `native_prewarm` (state complete/partial/unavailable/not_configured, per-PID stage readiness, build IDs, seconds). `warm` keeps its current meaning (Python import readiness). Prototype: `p1_native_prewarm_prototype.py.txt`.
3. Contracts preserved: per-Run `activated()` decision, kill switches (read at every submission and again at probe), build-ID pins, canonical fallback, thread mode untouched, no model executed, no loader/ABI/manifest/binary change.
4. Required approval: Financial Owner exact-content approval for a new `model_execution.py` blob plus the source-aware successor update of the pin chain (the V10 approval JSON and `v10_native_shadow_successor.py` pins) — not performed here.

## Source facts (S)
`_worker_warmup_probe` imports Python modules only. Loaders cache both success **and failure** per process (`_RESULT`, `_LIB`); the lazy path verifies on the first Run (≈0.3 + 0.04 + 0.3 s measured for stage 1/2/3 in a fresh interpreter). `warm_up` proves distinct PIDs (`confirmed_pids`). Existing tests: `tests/test_perf_model_runtime_v2.py`, `tests/test_p0a_model_execution.py`.

## Prototype measurements (M; probe swapped from outside the repository, no protected file modified; real `ModelExecutor`, spawn pool of 2, V10 stage 1+2 + V11 pinned, synthetic Solar, cache-miss each Run, 14 pool lifecycles per variant interleaved)
| Metric | Baseline | Prototype | Delta | n |
|---|---|---|---|---|
| `warm_up` duration (median / p95) | 1.594 / 1.746 s | 2.037 / 2.187 s | +0.44 s startup | 14 |
| First Run on a PID, worker wall (median / p95) | 1.935 / 2.156 s | 1.473 / 1.701 s | **−0.46 s (−24 %)** | 28 |
| Later Runs, worker wall | 1.057 / 1.209 s | 1.069 / 1.217 s | none | 28 |
| Executor RSS after warm-up | 93.5 MB | 97.8 MB | +4.3 MB per worker | 28 |
| Executor RSS after 4 Runs | 107.0 MB | 106.4 MB | none | 28 |
| V11 models served | 68 | 68 | — | all |
Distinct PIDs reached: 2/2 in every lifecycle for both variants. Remaining first-Run premium after prewarm ≈0.4 s (1.473 vs 1.069) — lazy imports and per-process caches outside the native libraries; extending the import set is part of the same approval.

## Respawn and failure behaviour (M)
A replaced worker is a new PID and is **not** warmed in either variant (14/14); the first Run on the replacement pool took 2.6–2.7 s. The stale `warm` flag stays `True` after a pool is discarded (14/14) — the proposal clears native readiness at that point. Failure cases (tampered/missing binary, wrong build ID, ABI mismatch, kill switches, thread mode, off modes) are specified in the proposal and need the tests that accompany the approved change; they were not run against the repository because the file is gated.

## Separate finding (existing behaviour, not a P1 regression)
If an **idle** executor process dies, `ModelExecutor._submit` receives `BrokenProcessPool` at `submit()`, converts it to `ModelExecutionFailed` and does **not** discard the pool, so every later submission fails (14/14 lifecycles: two consecutive `ModelExecutionFailed`). `_translate` (which does discard) only runs for failures raised through the future. Same protected file; reported for the owner, not changed.
