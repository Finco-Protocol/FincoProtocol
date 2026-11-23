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
| `finance` | F01: 4-vertical real-browser rate round-trip (exactly 4 passing cases), 20 native V10/V11 cases in the approved no-network image (exactly 20), independent FIN-V2.3 oracle workbook |
| `tests (1..16/16)` | the **whole** active pytest suite (≈20.7k nodes, finance, security, persistence, API, React contracts, Radar/Yield, browser) with real Chromium in every group |
| `acceptance` | outputs workspace and statements-tree Chromium acceptance programs |
| `required` | all of the above concluded `success` (skipped/cancelled/missing = failure) and the groups add up to the full collection |

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
* Hard job timeouts: tests 40 min, finance 45 min, static 20 min. Target: PR wall time ≤ 25 min.
