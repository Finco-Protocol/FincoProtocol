# CI V3 — 8-worker admission and balancing (Owner CI-only scope)

## Authenticated evidence

- Historical complete sequential: run `39971606511`, HEAD `e96561a220fc6adeb85587eb01d61745a922ab41`, artifact `12516255156`: 17,910 tests / 540 modules, elapsed 6,057 s; 17,867 passed, 42 skipped, 1 xfail and 68 collection skips.
- Accepted source **same tree as main**: `d4cc7dd88b4fa93404793a52471bfa6a025f9413`, tree `a96566a21154fd8e673676c20bd2e4e093599330`; run `40903314205`, aggregate artifact `12915598748`, 21,749 selected / 655 modules; five actual workers and independent aggregate PASS.
- Full original-node comparison against that accepted source: 0 deleted, 3,839 added PASS, **exactly one historical phase change**: `tests/test_trust_readiness_registry.py::test_scope_guard_this_work_touches_no_engine_input_writer_or_radar_code` from SKIPPED ('trust pack not part of this diff') to PASSED.
- PR #399 run `40945211446` selected sequential specifically because prior policy rejected the one already-approved D-029 change. Five workers were not started.
- Actual accepted 5-worker critical path was worker-0, 15:43:27–17:01:28 UTC (78 min); full Public Safety workflow 15:36–17:05 UTC (~88 min). Other worker execution: ~35–48 min. These are **observed**, not estimates.

## Exact admission successor

`validate_reference_policy()` remains unchanged. Only when its strict gate fails does `validate_accepted_reference_successor()` enumerate **all** old/current phase mismatches and allow **exactly** the previously approved D-029 node. It demands native JUnit historical skip/current pass, authentic reference same-run PASS of all D-029 successor nodes, exact Trust state A or B, original approved blobs and historical receipts. Any second difference, missing evidence, source drift or nonhistorical nonpass rejects parallel and preserves sequential fallback. The same successor is rechecked in plan and independent aggregate.

## 8 worker performance contract

- Existing deterministic whole-module LPT and `groups={}` retained. All original and current nodes are selected exactly once; current plan, worker-bound evidence and independent aggregation remain sealed. Plan fails on any missing/empty worker. Browser acceptance remains separate.
- Module weights prefer independently authenticated **accepted-source per-phase actual milliseconds**. When absent, use authenticated historical native JUnit, finally the labeled `node_count*1000ms` estimate for genuinely unmeasured PR-only modules. Provenance and weights are included in plan artifacts; no test result semantics change.
- On accepted-source 21,749-node measurements, model predicts test-execution-only critical paths of ~45.3 min (5), ~37.7 min (6), ~28.3 min (8) and ~25.8 min (10), before per-worker setup/transport and verification. Prediction is not a CI measured result.
- **Critical dominant module** `tests/test_model_react_rcux_goal_seek_targets_v1.py`: 26 nodes / 1,547 seconds, currently indivisible. Do not split it without a separate independent isolation proof; this imposes ~25.8-min floor even at 10 workers.
- Real GitHub execution, not model, decides acceptance: `CI_V3_ROUTE=parallel`, 8 nonempty workers 0–7, all mandatory jobs and independent evidence PASS, no historical deviations except exact D-029.
- Ubuntu runner concurrency / quota and artifact egress may limit actual speed; do not infer measured gains from LPT prediction. Rollback remains the existing operator switch, not a downgrade.

## Governance

No source financial/credit/runtime changes, no altered historical outcomes, no force push, no merge/deploy. `tools/ci_v3_production.py` and routing JSON are narrowly modified under this CI-specific Owner instruction. All protected historical evidence and `validate_reference_policy()` remain immutable.
