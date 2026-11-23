# FINCO Model CI policy (since the 2026-11 normalization)

One workflow, one required check, ordinary tools.

| Item | Value |
|---|---|
| Required status check | **`Model CI / required`** (job `required` in `.github/workflows/model_ci.yml`) |
| Workflows | `model_ci.yml` (PR, push to main, merge queue, nightly, manual, reusable), `model_known_defects.yml` (advisory), `release_gate.yml` (manual release gate) |
| Test runner | plain `pytest` + `pytest-split` (16 fixed duration-balanced groups), Playwright 1.63.0 / Chromium, axe-core 4.10.2 |
| Protected paths | `.github/CODEOWNERS` — CI, tests, finance/security core need a member of `@Finco-Protocol/owners` approval |

## What every PR runs

| Job | What it proves |
|---|---|
| `static` | `compileall`, public safety scan, `pip check`, strict `pip-audit`, React typecheck + build + served bundle identical to `static/react` |
| `boot-smoke` | production command fails closed without config / insecure mode, boots, `/public-health` 200, terminates cleanly (`scripts/ci/production_boot_smoke.sh`) |
| `mode` | STANDARD or FULL for this run (`scripts/ci/ci_mode.py`, see *Modes* below) |
| `finance` | F01: 4-vertical real-browser rate round-trip (exactly 4 passing cases), 20 native V10/V11 cases in the approved no-network image (exactly 20), independent FIN-V2.3 oracle workbook. The image is built from the unchanged `docs/ci_v3/phase4/runtime/Dockerfile` through a BuildKit GitHub-Actions layer cache and then **verified** (`scripts/ci/native_image_identity.py`: frontend lock, pinned gcc-13, Ubuntu 24.04, Python 3.12, every `python.lock` pin); a cache hit is never proof |
| `tests (1..16/16)` | the **whole** active pytest suite except the node(s) DEFERRED_TO_FULL (≈20.7k nodes, finance, security, persistence, API, React contracts, Radar/Yield, browser) with real Chromium in every group |
| `acceptance` | outputs workspace and statements-tree Chromium acceptance programs |
| `full-regression` | FULL mode only: the deferred node(s) in `tests/full_regression_nodes.txt`, unchanged, on the same SHA (must pass; skip = failure) |
| `required` | all of the above concluded `success` (skipped/cancelled/missing = failure; `full-regression` may be skipped **only** in STANDARD mode, `scripts/ci/required_jobs.py`) and `executed + DEFERRED_TO_FULL + known defects == collected` |

## Modes (FINCO 34 owner policy)

| Run | Mode | The deferred node |
|---|---|---|
| ordinary PR / merge group not touching `scripts/ci/full_regression_paths.txt` | STANDARD | DEFERRED_TO_FULL (reported, not run, not PASS) |
| PR / merge group touching a listed path (goal-seek, valuation/NPV, engine/core, their adapters, the deferred test, this mechanism) or with an unreadable diff | FULL | runs on the exact PR head |
| push to `main` | STANDARD | covered by the nightly FULL run on `main` |
| nightly `schedule` (02:17 UTC, `main`) | FULL | must pass; a red nightly is triaged by the owner and **holds releases** until resolved |
| `release_gate.yml` (`workflow_call` with `full_regression: true`) | FULL | must pass on the exact candidate SHA before the `production` approval job can start |
| manual `workflow_dispatch` with `full_regression: true` on any ref | FULL | runs on that exact ref |

Owner-review rule: a PR that changes production goal-seek / valuation / NPV or underlying financial calculation
behaviour must show a green FULL run on its exact final head before merge; for paths not yet in the list, dispatch Model
CI with `full_regression: true` on the PR head and link the run. The deferred node is never skipped, xfailed or listed
as a known defect, and only the exact node id(s) in `tests/full_regression_nodes.txt` may be deferred.

## Rules the gate enforces

* **No silent skip for a missing dependency.** `FINCO_CI_STRICT_SKIPS=1` turns any test/module skip whose reason names a
  missing Python package, Playwright/Chromium or axe-core into a failure (`tests/conftest.py`). Intentional skips and optional external tools (e.g. LibreOffice) stay visible as SKIPPED, never PASS.
* **Collection errors and empty groups fail** (plain pytest exit codes 2 / 5). Fixture-only modules are fine.
* **Every node runs in exactly one group.** Each group records its full collection digest and its selection
  (`FINCO_CI_COUNTS`); `scripts/ci/check_groups.py` requires identical collections, disjoint selections, every
  selected node present in JUnit, and `executed + known defects == collected`.
* **Known baseline defects** (`tests/known_defects.txt`) are the only deselected tests. Each failed identically on
  accepted main when listed. They run in `model_known_defects.yml`, which stays red until they are fixed; the fixing
  PR removes the line. They are never reported as passing.
* **One visible rerun, only for hosted browser flakes.** A test that fails with a Playwright `TimeoutError` or an
  htmx-not-ready `assert 303 == 200` gets exactly one rerun (pytest-rerunfailures); it is reported as `R`/rerun in the
  log and JUnit. Any other failure, or a second failure, fails the gate. Tests that also flake locally on main are
  listed in `tests/known_defects.txt` instead.
* **Unreleased financial candidates stay inactive** (`tests/test_financial_activation_flags_closed.py`).

## What is deliberately gone

The CI V3/V4/V5 machinery (trusted-base selectors, node plugins, exact-source cohorts, successor manifests,
historical byte-equality against the moving head, epoch/attestation chains, performance judge) is archived under
`archive/ci_governance_2026_11/` (see its `README.md`). Historical evidence under `docs/` is unchanged and remains
verifiable against its own immutable commits (`git show <ref>:<path>`); nothing validates it against HEAD any more.

## Changing the policy

Edit `model_ci.yml` / `scripts/ci/` / `tests/` in a normal PR. CODEOWNERS review is required; the PR's own Model CI run
must be green. No manifest, pin or successor is needed for ordinary code changes.

## Timings and maintenance

* `scripts/ci/test_durations.json.gz` (per-node seconds from hosted JUnit, gzipped because the public safety scanner
  hashes every byte window of text files) balances the groups; the job extracts it to `.test_durations`. Refresh it
  occasionally from a green run's JUnit (or `pytest --store-durations --durations-path .test_durations` on a full run,
  then gzip). A stale file only affects balance, never coverage. Groups are contiguous slices of the normal collection
  order (`duration_based_chunks`), so modules keep their usual neighbours and order.
* Hard job timeouts: tests 40 min, finance 45 min, static 20 min, full-regression 60 min (the deferred NPV goal-seek
  parity node measured 1093-1737 s hosted plus install). Target: PR wall time ≤ 25 min.
