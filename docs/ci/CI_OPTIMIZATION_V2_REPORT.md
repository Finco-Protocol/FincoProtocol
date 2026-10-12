# FINCO PROTOCOL — CI Optimization V2: remove redundant fan-out

Scope: CI workflows, CI-only verification tools/tests, this report. No application, persistence, financial, production, fixtures or golden changes.

Baseline verified live on 2026-10-11: main `607db110928859bf37f6dde1195e50c4b80cde12`; merged PR #247 created the extra fan-out. Branch protection GET returned HTTP 403 (app lacks administration permission); repository rulesets GET returned an empty list. **An independent reviewer must verify branch-protection required status contexts before approval.** Existing stable aggregate contexts are retained, but obsolete per-matrix contexts, if required externally, require an explicit migration.

## A. Before and after workflow DAG

### Before (#247 code at main; actual PR #250)

- Governance Full History: 1 job.
- Dependency Security Audit: 1 job.
- PR Compile and Safety Gate: 1 job.
- Public Safety: `source-safety` + full exact-head control + full synthetic-merge integration + 2 shadow shards + mandatory aggregate = **6 jobs**.
- Browser: six mandatory exact-head roles + six duplicate merge-result roles + default optional F3 + mandatory aggregate = **14 jobs**.
- **TOTAL 23 jobs** on PR #250 (or 21 before consolidation was added as a sixth browser role).

### After V2 (ordinary PR)

- Governance Full History: **1 unchanged job**.
- Dependency Security Audit: **1 unchanged job**.
- PR Compile and Safety Gate: **1 unchanged job**, plus focused V2 contract tests in the SAME runner.
- Public Safety: `source-safety`, `safety-and-smoke / tests` FULL UNSHARDED, and `mandatory-evidence` = **3 jobs**.
- Protocol UI Browser Acceptance: `mandatory-browser-evidence` runs the six mandatory roles in **six independent supervised Python/pytest processes on ONE runner**; one dependency install + one Chromium install; integrity proof and artifacts in the same job = **1 job**.
- **TOTAL 7 jobs.** Optional F3 is removed from the default PR matrix and exposed through a separately dispatched targeted workflow. Extra path-filtered/domain-specific CI remains unchanged and may appear for PRs touching their paths.

The browser 1-runner approach prioritizes runner-minutes and simpler evidence over browser wall-clock parallelism. It may take longer than a parallel browser matrix; that is an accepted, explicitly measurable tradeoff. Overall PR wall is dominated by the full unsharded Public Safety control.

## B. Exact test/evidence contract

1. Public: one unsharded pytest invocation using the SAME `tools/ci_pytest_runner.py` supervisor and `tools.ci_pytest_inventory` inventory; no test list exclusions, shards, changed skip policy, deselection or financial tolerances.
2. Mandatory Public proof: exact HEAD/tree, event-pinned synthetic-merge commit/tree equality, source safety scan+compile records, complete inventory and collection skips, successful JUnit hash/zero failures, pytest rc=0, supervisor child exit=0, normal interpreter exit, dependency/environment digest and artifact upload.
3. Browser: all six previously mandatory selections `protocol, import, grid, q4, outputs, consolidation`, each with a fresh test process, a distinct temp directory, the unchanged role-level screenshots/inventory/JUnit/manifest/process evidence, with per-role SHA/tree attestation and normal exits enforced by the existing aggregator.
4. Browser artifacts: `browser-mandatory-suite-evidence` (all six role bundles and proof), the stable `browser-mandatory-proof` alias, the existing consolidation screenshot alias, plus the pinned tested-source and merge-tree records.
5. No second synthetic-merge execution unless trees are different—in that case the control/browser gate FAILS CLOSED, requiring normal sync with current main and fresh PR-head CI rather than silently executing potentially different financial/app code.
6. No implicit acceptance of targeted F3: it must be explicitly dispatched and its own failure is visible.
7. Automatic cancellation remains scoped to each workflow/PR via the pre-existing per-PR concurrency keys; no global cross-workflow cancellation.

## C. Measured before; after is not yet measured

All durations below from GitHub Actions **actual job started/completed timestamps**, not runner estimates. For runner-minutes, sum each job's elapsed time; wall-clock uses the workflow run_started/updated bounds.

| Sample | Browser jobs | Public jobs | Other mandatory jobs | Browser runner-min | Public runner-min | Browser wall | Public wall | Setup/install steps |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| PR #247 final: browser 38131813660 / Public 38131813659 | 12 | 6 | 3 | 19.30 | 127.85 | 316 s | 2520 s | Browser 400 s in 22 repeated install steps; Public 91 s in 4 dependency steps |
| PR #250: browser 38173228262 / Public 38173228308 | 14 | 6 | 3 | 24.85 | 132.02 | 386 s | 2597 s | Browser 616 s in 26 repeated install steps; Public 98 s in 4 dependency steps |
| V2 architecture target | 1 | 3 | 3 | **Not yet measured** | **Not yet measured** | **Not yet measured** | **Not yet measured** | Browser one dependency+one Chromium install; Public one dependency install |

PR #250 browser+Public measured sum: **156.87 runner-minutes**; before V2, source-safety job runs alongside four Public Test jobs. Browser repeated setup alone accounted for 10.27 runner-minutes (616 s). The new architecture removes 3 expensive Public pytest executions and 12 browser runner installations, but its measured savings MUST come from exact V2 run artifacts. Predicted durations are not acceptance results.

The PR #247 trial had one shadow outcome mismatch (`tests/test_p6_demo_isolation.py::test_demo_cleanup_removes_demo_data_only`); its own report classified optimization as PARTIAL_OR_BLOCKED. Keeping one full suite, rather than relying on shards, avoids this unproven equivalence.

PR #250 executed **9,932 selected Public Safety nodes**, plus 27 collection-skipped modules (see exact-head control inventory artifact `11716191320`); full control failed 1 unrelated changed-JS static test (`test_new_module_reuses_existing_transport_and_adds_none`), not a V2 timing defect. PR #250 browser role and screenshots passed; V2 must retain all same six role selections and IDs in its new per-role inventories.

## D. Security and failure boundaries

- Repository-protected application/finance/domain/persistence/schema files are untouched.
- Synthetic merge mismatch is a **failed check**, not a green skip. The merge-result commit SHA is pinned to the event and fetched through the exact PR merge ref before tree equality; a moved merge ref fails closed.
- Public Safety is single unsharded, source-pinned, still subject to process-level time budget, normal-exit supervision and JUnit verification.
- The browser runner still uses separate pytest children for each role with temporary-directory isolation; no test selection contract changes.
- Artifacts are immutable after upload and verified by SHA-256 manifest at acceptance. A missing role, missing PNG, failed JUnit or incomplete outcome fails the gate.
- Legacy stable job names preserved: `source-safety`, `safety-and-smoke / tests`, `mandatory-evidence`, `mandatory-browser-evidence`; Governance, Dependency Security, and Compile/Safety job names unchanged.
- **Potential required-status migration:** old `browser-suites (role) / browser`, `merge-result-browser (role) / browser`, `f3-evidence / browser`, `merge-result-integration / tests`, and `shadow-shards (...) / tests` are removed from ordinary PR runs. Branch-protection administration endpoint was inaccessible (403), so a maintainer must explicitly audit required status settings and migrate only obsolete per-role statuses to the stable aggregate gates BEFORE merge. No status-setting changes were performed by this PR.

## E. Acceptance / handoff

1. Focused `tests/test_ci_optimization_v2.py` runs in the existing PR Compile and Safety Gate runner (not a new Actions job).
2. Verify exact branch diff contains ONLY CI workflow/tool/test/report files.
3. Check GitHub main, PR HEAD, merge-base, ahead/behind, DRAFT and mergeability live.
4. Run exact-head required CI once; verify every mandatory gate completes green, upload artifacts and check role inventories for missing/duplicate IDs. No extra full pytest benchmark executions.
5. Re-measure runner-minutes, wall, setup durations and reliability from that first run and compare using the same timestamp boundaries; report if wall is slower even if runners cost less.
6. **NO MERGE** until independent final review confirms exact-head green gates, accurate evidence, and any required-check migration.

No self-approval, no merge/deploy, no rebase/squash/force push.
