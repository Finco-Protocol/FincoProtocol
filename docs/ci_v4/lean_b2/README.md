# CI V4 Lean B2 — bounded U1 provenance test-runtime optimisation

**Status: one narrow, semantic-preserving runtime change. No test is demoted, deleted, skipped or moved.** B2 changes no selector, policy, aggregator,
scheduler, workflow, timeout, product, financial or UI source: `FROZEN` pins every CI V4 control file to its accepted-main blob. `B2_LEAN_NOT_COMPLETE`:
moving any test from PR to FULL remains a separate owner decision and is **not** part of this change (zero nodes are proven redundant).

## What changes
Three READ-ONLY nodes of `tests/test_u1_scope.py` (`test_positive_cohort_is_exact_registered_and_closed`,
`test_integration_reference_is_main_after_414_and_everything_unowned_equals_it`,
`test_no_path_outside_the_superseded_set_is_ever_admitted_by_supersession`) re-derived the same many-cohort exact-source verdict dozens of times
(each call spawns Git processes). The public test is now `with C.call_scope(): _body()`; `_body()` is the **byte-identical original body** and takes no
fixture. `call_scope()` is the existing bounded per-call memo: it lives only for the outer block and is dropped on exit; nothing is cached across test
cases, refs, trees, worktrees, commits or mutations. Every tamper node (worktree mutation) stays outside any scope, and
`tests/test_ci_v4_lean_b2_scope.py` proves it by AST: the three bodies contain no mutation primitive, every other node is unchanged, and a later
mutation is judged fresh.

## Finite governance (the owned set — see `SOURCE_SUCCESSOR.json`)
B2 is ONE successor after the accepted B1 leaf (the acyclic forward-hook pattern B1 used for C06). It owns its module, manifest, README and test, and moves
by reviewed literal one-occurrence substitutions over accepted main the shared paths a successor must touch: the registry, the U1 discovery entry, the U1
provenance tests, the B1 and C06 forward hooks, the exact-tail scope tests and the current maps (only the registry, U1 and U1-test keys move).

## Evidence labels
Measured on one machine, not hosted: `MEASURED_LOCAL`. A local run is not hosted acceptance; skipped, cancelled or not-run is never PASS.

| Node (accepted main) | wall before | wall after |
|---|---|---|
| `test_integration_reference_is_main_after_414…` | ~2600 s | seconds |
| `test_positive_cohort_is_exact_registered_and_closed` | ~430–510 s | seconds |
| `test_no_path_outside_the_superseded_set…` | ~250 s | < 1 s |

## Rollback
One `git revert` of the B2 merge removes the new files and restores the registry, B1/C06 leaves, `tests/u1_scope.py`, `tests/test_u1_scope.py`, the
exact-tail tests and the current maps to their accepted-main bytes. No data, workflow or product state is involved.
