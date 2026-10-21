# Phase 1 implementation report

**PHASE 1 COMPLETE — OFFLINE SPLIT PROTOTYPE READY FOR INDEPENDENT REVIEW**

This verdict covers the requested offline machinery, historical reconciliation and local controls. It does not establish actual multi-process test isolation, hosted performance, an approved policy or CI acceptance. All unresolved risks below remain Phase 2 prerequisites.

## Source and branch

- Live main independently verified: `b28a05723967df590f6a684c64504d845e576508`.
- Main tree: `f0a0224d21b89b731d8b6c93137ee5dd94db3b0f`.
- Isolated local branch: `research/ci-v3-parallel-partition-prototype`.
- Local checkout: `FincoProtocol-ci-v3-phase1`.
- Final commit and exact changed-file inventory are recorded in the external delivery's `GIT_STATUS.json`, avoiding a self-referential commit hash inside its own content.
- #332 remains open/draft at `32b9478f0e137e586df665aefd00c59a960c55d8`; #327 and #328 remain open/draft at `2f6f6626d0d981d8278ecde9785361ac0c3775a5` and `e42d15ee60343b3153aa74a9821669a75e87790b`.
- #335 advanced since Audit V3 to `0a749f61d652ef222c298df6b1fda4e24404925a` and remains open. That new source is not substituted for the historical failed audit run.

The complete original ZIP file manifest was verified (2,650 entries), and the builder verifies every input covered by Audit V3's SHA-256 evidence manifest. Reports A/B/C, dependency closures, ownership candidates, weights, full node inventories, JUnit and timing records were inspected. Existing workflow, single-gate, inventory, supervisor, progress, acceptance and RC3/RC5/CI200 guard sources were read and preserved. No test inventory from different trees is merged.

## Baseline identity and multiplicity

| Run | HEAD | Tree | Outcome | Nodes/modules/collection skips |
|---|---|---|---|---|
| 39510669730 | `9ad70e9c2e926b02392604781c87ca7f0f01b667` | `f0a0224d21b89b731d8b6c93137ee5dd94db3b0f` | 15,399 passed, 41 node skips; successful normal exit | 15,440 / 469 / 68 |
| 39547632809 | `b28a05723967df590f6a684c64504d845e576508` | `f0a0224d21b89b731d8b6c93137ee5dd94db3b0f` | 15,399 passed, 41 node skips; successful normal exit | 15,440 / 469 / 68 |
| 39554954313 | `5c7bebb68204269129d36c735d67b970ce2ba28f` | `4fd0c22581f6ec2f54379b09749367c2cc76c3ac` | 15,398 passed, 41 node skips, one failure; not acceptance | 15,440 / 469 / 68 |

The importer checks the **full original node strings and multiplicity** against timing and JUnit case identities, not just counts. Node collection is unique, selected equals collected, and collection errors/deselection are absent. All 68 collection-skip records are reconciled separately to JUnit. The original JUnit digest must match the process evidence. The failed run is retained in `historical-and-performance.json` as unsuccessful diagnostics; no successful worker bundle is generated from it.

Ownership is reproduced exactly: Model 7 modules/1,424 nodes; Radar 14/752; Shared 0/0; Cross-domain 2/241; Governance 52/1,981; **F 394/11,042**. These are the audit's unapproved candidates, not new proven product boundaries. Every node remains mandatory. In particular, F is not relabeled as Model merely because most slow tests appear financial.

## Implementation and changed files

New tools only:

- `tools/ci_v3_schema.py`: canonical encoding, versioned contracts, data validation and fail-closed fresh-collection reconciliation.
- `tools/ci_v3_partition_plan.py`: deterministic 2/3/4-worker whole-module planner and performance summaries.
- `tools/ci_v3_evidence_verify.py`: independent offline evidence/JUnit/process/lineage verifier, with no planner import.
- `tools/ci_v3_audit_prototype.py`: historical evidence importer and explicitly simulated data producer, with no test scheduler.

New local controls: `tests/ci_v3_synthetic_evidence.py`, `tests/test_ci_v3_partition_plan.py`, `tests/test_ci_v3_evidence_verify.py`.

New documentation: `docs/ci_v3/README.md`, `SCHEMA_AND_VERIFIER.md`, `PHASE1_REPORT.md`, `PHASE2_PROPOSAL.md`, `performance_summary.json`.

No existing file, workflow, production module, financial/security golden, accepted pin or governance guard is edited. Raw historical manifests and worker simulations stay outside the public repository. No GitHub artifact or run is created by these tools.

## Isolation inspection and limits

Static inspection found 319 call-decorated fixture declarations: 174 module, 7 class and 138 function scopes; no explicit session-scoped fixture declaration. Bare default-scope fixture decorators are outside that count. Plugin-provided/session machinery still exists; absence of a declared session fixture does not prove independence. There are 414 test-helper imports in the prototype tree.

Concrete risks inspected:

- `tests/conftest.py` has module-autouse Model executor cleanup and session-finish process/thread leak rejection. These are still required in every future worker.
- `tests/wfa_support.py::make_lab` assigns mutable global `LAB`, patches Model DB identity, initializes persistence and creates an authenticated full-app client. Different importing modules may rely on its current value. This is not proved order-independent.
- Monthly CAPEX's module fixture changes `db.DB_PATH`, creates real reference snapshots, then restores the original path. Keep the entire module together.
- Cost workspace consistency uses its own executor cleanup and function-scoped isolated DB; fresh process startup and application import behavior still need comparison.
- F3.9's `real` fixture creates a fresh committed Run for each negative/tamper test. It remains function-scoped and unchanged.
- Shared application imports initialize both product surfaces. Imports across test modules, module globals, database caches, clock sources, inherited environment and plugin state remain unresolved runtime edges.

Each module's isolation status is explicitly `unproven`. Whole-module assignment preserves the declared module boundary, but no claim is made that grouping modules into separate sessions preserves every implicit assumption. The prototype's own tests are newly added nodes and are not represented as if they existed at historical main. Fresh candidate collection must reconcile them in Phase 2; the new-node negative control fails closed today.

## Local validation and reproducibility

Final focused local result: **132 passed, zero failed/errors/skips/xfails**. This includes 76 new prototype controls plus 56 unchanged CI V2/required-topology/RC3-RC5-CI200 controls. The final JUnit is retained externally as `focused-final.xml`.

Configuration: Python 3.12; `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`; explicitly load `pytest_asyncio.plugin`; run the two new test modules, all of `test_ci_optimization_v2.py` and `test_rc5_ci_successor_governance.py`, plus the three existing topology/trigger assertions in `test_ci_acceptance.py`. Use an isolated writable basetemp. The unrelated installed Web3 pytest plugin originally failed before collection. A first sandboxed compatibility run also encountered Windows MSYS process-access errors in three existing tests' temporary **local** bare Git fixtures; repeating the focused run with the needed Windows process access passed. No test was weakened, skipped or xfailed, and no remote GitHub push was made by those local fixture tests.

Two independent producer invocations generated **31 byte-identical files**. Canonical inventory, policy, weights, 2/3/4 plans, assignment CSVs and simulated JUnit/process packages match byte-for-byte. Both successful cohorts' full 15,440-node simulated three-worker evidence pass the independent CLI, always with authoritative acceptance false. Deliberate corruption causes nonzero exit and a rejection proof, not a stale prior success.

The prior audit used floating-point accumulation. Integer milliseconds intentionally eliminate binary floating tie noise:

| Workers | Module memberships differing from old float replay | Old max s | New max s |
|---|---|---|---|
| 2 | 0 | 2768.575 | 2768.575 |
| 3 | 24 | 1845.717 | 1845.717 |
| 4 | 54 | 1384.288 | 1384.288 |

Differences are deterministic near-equal/tiny-weight tie placements, not lost coverage. Maximum workloads reproduce to the recorded millisecond; every module and exact node remains assigned. New plan digests identify these new deterministic memberships rather than pretending they are byte-identical to the old float layouts.

## Partition evidence and runtime model

All values below are **offline predictions**. Occupied runner-minutes include per-worker overhead, source safety and aggregate; queueing and other PR workflows are excluded. Each cohort is modeled from its own measured per-module timings, not used to assert causal source acceleration.

| Cohort run | Workers | Worker weights s | Mean s | Imbalance | Modules per worker | Nodes per worker | Critical min | Public runner-min |
|---|---|---|---|---|---|---|---|---|
| 39510669730 | 2 | 2768.575,2768.575 | 2768.575 | 0.00000000% | 236,233 | 8654,6786 | 48.157 | 97.847 |
| 39510669730 | 3 | 1845.717,1845.717,1845.716 | 1845.717 | 0.00001806% | 155,156,158 | 6333,4476,4631 | 32.776 | 99.712 |
| 39510669730 | 4 | 1384.288,1384.288,1384.287,1384.287 | 1384.287 | 0.00003612% | 117,117,119,116 | 3853,3611,4681,3295 | 25.086 | 101.576 |
| 39547632809 | 2 | 1675.871,1675.870 | 1675.870 | 0.00002984% | 227,242 | 7119,8321 | 29.302 | 61.371 |
| 39547632809 | 3 | 1117.247,1117.247,1117.247 | 1117.247 | 0.00000000% | 167,151,151 | 4977,4480,5983 | 19.992 | 62.609 |
| 39547632809 | 4 | 837.936,837.935,837.935,837.935 | 837.935 | 0.00008951% | 114,129,113,113 | 4171,5163,3227,2879 | 15.337 | 63.846 |

Slow successful cohort: 5,537.150 seconds of phase work, 111.850 seconds non-phase overhead per worker, 101-second source job and 9-second aggregate. Faster cohort: 3,351.741 seconds of phase work, 74.259 seconds per-worker overhead, 174-second source job and 8-second aggregate. Overhead is the measured full-job duration minus phase work, encompassing installation, collection/import, reporting, shutdown and uploads; it is not an isolated startup measurement. Installation alone measured 21 and 14 seconds; pure collection/import is unmeasured.

Three workers remain the starting candidate. Four reduce the ideal slow-cohort critical path by about 7.69 minutes, but add another environment, collection/session boundary, artifact set and runner slot; actual queueing, memory and native-thread contention are unknown. No evidence yet proves four a better sustainable configuration. Three is a research choice, not a proven optimum.

### Domain distribution per worker

Candidate counts are supplied below. Most expensive real financial work remains F, so these counts must not be described as the final financial workload distribution. Shared count zero reflects unresolved classification, not absence of shared infrastructure.

| Cohort | Workers | Worker | Model candidate | Radar candidate | Shared candidate | Cross-domain candidate | Governance candidate | F mandatory |
|---|---|---|---|---|---|---|---|---|
| 39510669730 | 2 | worker-0 | 1405 | 482 | 0 | 186 | 1114 | 5467 |
| 39510669730 | 2 | worker-1 | 19 | 270 | 0 | 55 | 867 | 5575 |
| 39510669730 | 3 | worker-0 | 1305 | 421 | 0 | 186 | 572 | 3849 |
| 39510669730 | 3 | worker-1 | 108 | 75 | 0 | 0 | 829 | 3464 |
| 39510669730 | 3 | worker-2 | 11 | 256 | 0 | 55 | 580 | 3729 |
| 39510669730 | 4 | worker-0 | 18 | 212 | 0 | 0 | 582 | 3041 |
| 39510669730 | 4 | worker-1 | 30 | 136 | 0 | 0 | 581 | 2864 |
| 39510669730 | 4 | worker-2 | 1298 | 245 | 0 | 55 | 392 | 2691 |
| 39510669730 | 4 | worker-3 | 78 | 159 | 0 | 186 | 426 | 2446 |
| 39547632809 | 2 | worker-0 | 70 | 413 | 0 | 186 | 852 | 5598 |
| 39547632809 | 2 | worker-1 | 1354 | 339 | 0 | 55 | 1129 | 5444 |
| 39547632809 | 3 | worker-0 | 88 | 144 | 0 | 241 | 711 | 3793 |
| 39547632809 | 3 | worker-1 | 30 | 410 | 0 | 0 | 546 | 3494 |
| 39547632809 | 3 | worker-2 | 1306 | 198 | 0 | 0 | 724 | 3755 |
| 39547632809 | 4 | worker-0 | 97 | 468 | 0 | 0 | 814 | 2792 |
| 39547632809 | 4 | worker-1 | 1297 | 144 | 0 | 0 | 400 | 3322 |
| 39547632809 | 4 | worker-2 | 30 | 128 | 0 | 241 | 241 | 2587 |
| 39547632809 | 4 | worker-3 | 0 | 12 | 0 | 0 | 526 | 2341 |

### Sensitivity and heavy workloads

Using the slow three-worker workload, an additional 120 seconds cold startup per worker predicts about 34.78 minutes. A 25% phase-time increase plus that cold-start penalty predicts about 42.47 minutes. A 50% phase increase with that penalty predicts about 50.16 minutes. These are sensitivity cases, not confidence intervals or upper guarantees. The original 34–45-minute planning range is plausible only under moderate overhead/variation; the observed same-tree cohort variation is larger and can exceed it.

Native numerical threads and nested solver/process parallelism can contend for CPU, memory and IO. Three independent jobs need equivalent environment/thread settings and measured host metadata. Do not combine three workers on one constrained host and assume independent-runner scaling. Do not weaken numerical checks or change solver threads/production policy as part of this prototype.

Top 20 modules account for **42.33%** of recorded slow-cohort phase work; the largest alone is **3.32%**. The top 50 account for **66.99%**. Work is concentrated but no single indivisible module explains the whole critical path. These are candidates for later measurement/rebalancing, not permission to split module fixtures or remove independent financial Runs:

| Rank | Module | Measured s |
|---|---|---|
| 1 | tests/test_model_financing_f2.py | 183.628 |
| 2 | tests/test_wfa_impact_validation.py | 181.730 |
| 3 | tests/test_m3_two_driver_sensitivity.py | 173.716 |
| 4 | tests/test_f39_four_vertical_acceptance.py | 164.514 |
| 5 | tests/test_wf04_f0b_numeric_precision.py | 153.085 |
| 6 | tests/test_financing_f37_instrument_su.py | 132.477 |
| 7 | tests/test_model_rc7_capex_monthly_binding.py | 129.732 |
| 8 | tests/test_goal_seek_v1.py | 127.165 |
| 9 | tests/test_cost_workspace_parity_v1.py | 121.157 |
| 10 | tests/test_p6_correction_a.py | 119.232 |
| 11 | tests/test_cost_workspace_consistency_v1.py | 115.748 |
| 12 | tests/test_perf_model_runtime_v2.py | 91.116 |
| 13 | tests/test_staging_acceptance_a.py | 86.317 |
| 14 | tests/test_rc7_institutional_reporting_v2.py | 84.847 |
| 15 | tests/test_rc5_scenario_effective_input_safety.py | 84.627 |
| 16 | tests/test_developer_economics_persistence_v1.py | 83.260 |
| 17 | tests/test_ppa01_save_scenario_run_chain.py | 82.089 |
| 18 | tests/test_financing_f38_trace.py | 79.531 |
| 19 | tests/test_model_decision_support_v1.py | 75.850 |
| 20 | tests/test_rc2_integration_acceptance.py | 73.939 |

## Security evidence and known limits

The independent verifier checks exact worker/node multisets, explicit overlap policy, full collection and collection skips, per-node outcomes, complete identity-bearing JUnit, checksums, environment, trusted expected digests, exact source/synthetic tree, repository/run/attempt/evaluator lineage and normal process markers. It rejects each mandatory negative case. A green aggregate label cannot override a failed worker.

All simulations remain labeled simulated. Digests do not authenticate an observed process or independently approve a policy. Actual pytest V3 JUnit identity production, trustworthy fresh discovery, trusted GitHub evaluator distribution, artifact transport integrity and runtime isolation are future work. The current single gate is not replaced. Current historical skip reasons are an offline baseline policy, not new permission to omit tests on a different environment/tree.

### Source-safety validation

All 12 new files pass the unchanged scanner's `scan_file`; all seven new Python sources compile. The full existing working-copy scan returned 1 on the **unchanged baseline** `static/vendor/swagger-ui/swagger-ui-bundle.js` email-like finding. Its physical Windows bytes have SHA-256 `94d5341abf945c05b5dc2a4ee599be6adee30503790b998540795e766d8aea02`; original Git blob `763a116685857a4bd02251ea8d97d815e9f9889a` has canonical SHA-256 `fd76294e33356ab3fd111ddaeeb10d3f79de8ae1a4d34dbf777f5eef224648d9`, exactly the scanner's existing approved digest. The unchanged scanner accepts that canonical asset. Baseline and staged Git bytes are identical. No asset, attributes, exemption or rule was modified, and no full working-copy scan PASS is claimed. Evidence is in `full-source-safety.json`.

Scope validation also compares all 30 workflow blobs and ten existing gate/governance source blobs against the baseline: all 40 remain byte-identical. The full financial, Model, Radar and application namespaces have no delta. This offline phase does not waive the baseline Windows-byte finding or substitute a local focused run for authoritative full CI.

## Delivery status

Local implementation only. No remote push, new PR, hosted CI run/rerun, shadow job, merge or deployment was started. No active PR branch was modified. The previous sequential gate and all historical authority remain unchanged. Publication and hosted Phase 2 require subsequent authorization and a separately reviewed exact-content successor.
