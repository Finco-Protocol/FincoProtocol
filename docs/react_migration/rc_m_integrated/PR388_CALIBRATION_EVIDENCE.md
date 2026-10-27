# PR #388 — Correction D: CI V3 cold-start calibration evidence

Everything below is read from retained hosted artifacts (`public-ci-v3-worker-N`: `execution/child/calibration.json`, `process.json`) and from local measurements; raw samples are retained in the artifacts (30-day retention) and in this file.
The contract is unchanged: ceiling **0.600 s**, statistic **maximum of all three retained samples**, three samples, five workers (`tools/ci_v3_production.py::worker`, `tools/ci_v3_real_child.py`, `tools/ci_v3_calibrate.py`).
No threshold, statistic, sample count, worker count, collection or gate was changed by this PR (`git diff origin/main HEAD -- tools/ci_v3_calibrate.py tools/ci_v3_real_child.py tools/ci_v3_production.py .github/` shows only the D-029 reviewed-set entry in `tools/ci_v3_production.py`, which is unrelated to calibration).

## What was observed on the head under review

Run 40522709690, head `9ac495c83a64b326d6074d2ea2150f112778a5f7` (tree `42a4e2e080772cffd3969ac7b9021235fea0f819`), attempt 1:

| Worker | Calibration samples (s) | Maximum | Gate | `os_exit_code` | pytest | Original nodes |
|---|---|---|---|---|---|---|
| 0 | 0.324 / 0.308 / 0.300 | 0.324 | met | 0 | ran, exit 0, no leaks | 5190 |
| 1 | **0.802** / 0.255 / 0.252 | 0.802 | **refused** | **124** | **never started** (`pytest_return` null, no `native.xml`) | 4665 |
| 2 | 0.320 / 0.302 / 0.299 | 0.320 | met | 0 | ran, exit 0, no leaks | 3211 |
| 3 | **0.704** / 0.243 / 0.242 | 0.704 | **refused** | **124** | **never started** | 3778 |
| 4 | 0.253 / 0.239 / 0.260 | 0.260 | met | 0 | ran, exit 0, no leaks | 3690 |

Workers 1 and 3 are **readiness refusals, not pytest failures, not timeouts and not leaks**: `timed_out=false`, `cancelled=false`, `source_bytes_unchanged=true`, descendant cleanup verified, container removed. `safety-and-smoke / aggregate` and
`tests` failed as the consequence ("fail on any selected worker failure"). Only the first of the three samples exceeded the ceiling in both cases; samples 2 and 3 were 0.24–0.26 s.

## Is the PR the cause? — evidence

1. **The probe does not execute anything this PR changes.** `_WORKER_PROBE` imports `tests/p0_exec_helpers.py` and `app.runtime.model_execution` and times one `ModelExecutor.run_process(helpers.add, 1, 1)`. On `main` and on this branch the parent loads the identical module set
   (4 modules: the two `app.runtime` modules, `app.runtime.model_execution` helpers and `p0_exec_helpers`; diff empty), and `git diff origin/main HEAD -- app/runtime tests/p0_exec_helpers.py tools/ci_v3_calibrate.py tools/ci_v3_real_child.py` is empty.
   The only `app/` change since the head on which all five workers met the gate (`248d9112`) is `app/persistence/db.py`, which the probe never imports.
2. **Hosted population (60 worker calibrations, 12 heads: this branch, `main` pushes, F01 and unrelated PRs; `public_safety_and_smoke.yml`):** first-sample median 0.318 s, 58 of 60 at or below 0.372 s; the only two above 0.6 s are the two refusals above. On this branch: `0ee2f5ec` (5/5 met), `248d9112` (5/5 met, all ≤ 0.333 s), `9ac495c8` (3/5 met).
3. **Local reproduction (Python 3.12, same probe function, 30 samples per tree, alternating):** `main` (`cf7056de`) median 0.350 / 0.349 s, max 0.486 / 0.484 s; this branch median 0.334 / 0.352 s, max 0.404 / 0.389 s. No difference attributable to the PR.
4. **Cold page cache is the mechanism that reproduces the shape.** With the page cache dropped before each probe (`echo 3 > /proc/sys/vm/drop_caches`), the first sample rises by about 0.1 s while samples 2–3 stay at 0.31–0.39 s, identically on `main` (0.427–0.496 s) and on this branch (0.428–0.533 s). The hosted refusals show the same
   shape (first sample high, next two low) on a runner that had just loaded the container image; the hosted tail is larger because that disk is slower. This is consistent with — not a proof of — a first-use filesystem-cache effect on the hosted runner.

## What was **not** done (and why)

* No warm-up, no dropped sample, no median in place of the maximum, no change to 0.600 s, and no selection of passing runs. The two refusals are recorded as refusals.
* No re-run of the failed jobs inside run 40522709690: its artifact names are created with `overwrite: false` and every artifact context carries the run attempt, so a mixed-attempt re-run would not be the single consistent evidence set the aggregate verifies.
  The next wave comes from the next push of this PR (a new run, attempt 1, all five workers), and it supersedes run 40522709690 only for the new exact head; run 40522709690's evidence stays recorded here.
* No code optimisation: no needless cold-path operation exists in anything this PR touches, so there is nothing to optimise at its source without touching the shared executor (out of scope, protected and not implicated).

## Honest limitation

The hosted runner's cold first sample has a tail above 0.600 s in 2 of 60 observed worker starts (3 %), independent of this PR. With five workers per wave, the chance that a wave contains at least one refusal is non-trivial even on unmodified code. If the next wave on this PR fails the same way,
that is a **CI performance-contract problem to be decided separately by the CI owner** (for example: measuring cold readiness after the image load completes, or defining the contract on a percentile with a bounded retry that keeps every raw sample), not something this PR may change or certify. Nothing here certifies the hosted target.

## Raw first-sample table (hosted; first sample / worker; all workers per run)

| Run | Head | Kind | First samples (s) | Max of samples 2–3 | Refusals |
|---|---|---|---|---|---|
| 40513286161 | `248d9112` | pr388 | w0 0.320 · w1 0.317 · w2 0.303 · w3 0.325 · w4 0.333 | 0.311 | 0 |
| 40491672946 | `0ee2f5ec` | pr388 | w0 0.312 · w1 0.342 · w2 0.243 · w3 0.314 · w4 0.337 | 0.346 | 0 |
| 40505312580 | `128bf0c2` | main | w0 0.250 · w1 0.199 · w2 0.250 · w3 0.260 · w4 0.342 | 0.317 | 0 |
| 40499195653 | `f2ce5d6a` | f01 | w0 0.322 · w1 0.318 · w2 0.217 · w3 0.318 · w4 0.229 | 0.308 | 0 |
| 40487284039 | `035b73a1` | f01 | w0 0.315 · w1 0.328 · w2 0.320 · w3 0.327 · w4 0.259 | 0.312 | 0 |
| 40478422312 | `45bd6849` | f01 | w0 0.343 · w1 0.249 · w2 0.332 · w3 0.328 · w4 0.241 | 0.331 | 0 |
| 40463817978 | `cf7056de` | main | w0 0.351 · w1 0.350 · w2 0.322 · w3 0.254 · w4 0.228 | 0.340 | 0 |
| 40459556441 | `0d405b27` | other | w0 0.372 · w1 0.324 · w2 0.231 · w3 0.231 · w4 0.324 | 0.358 | 0 |
| 40456108383 | `052252f1` | other | w0 0.261 · w1 0.220 · w2 0.275 · w3 0.321 · w4 0.291 | 0.300 | 0 |
| 40454686337 | `8d9cccc7` | main | w0 0.315 · w1 0.313 · w2 0.325 · w3 0.346 · w4 0.318 | 0.325 | 0 |
| 40451332426 | `6f0c5b61` | other | w0 0.322 · w1 0.240 · w2 0.317 · w3 0.297 · w4 0.324 | 0.308 | 0 |
| 40522709690 | `9ac495c8` | pr388 | w0 0.324 · w1 0.802 · w2 0.320 · w3 0.704 · w4 0.253 | 0.308 | 2 |
