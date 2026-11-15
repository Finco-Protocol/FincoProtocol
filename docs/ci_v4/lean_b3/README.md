# CI V4 Lean B3 — WARN-ONLY test-admission report + data-only weights refresh (GLM, 2026-11-15)

**Scope:** ONE finite exact-source successor of the accepted B2 cohort carrying (a) the machine-readable
**test-admission report** (B3: added/removed/renamed/changed test modules and exact nodes over the trusted-base
diff, selected/NOT_SELECTED status from the trusted-base plan, hosted wall seconds where the run's JUnit has them,
admission metadata with UNKNOWN-for-missing, duplicate CANDIDATES as a heuristic only, new skip/xfail markers,
budget warnings and predicted-critical-path provenance — every number labelled, exit code always 0) and (b) a
DATA-ONLY refresh of `docs/ci_v4/module_weights.json` from the hosted JUnit of run 43744944268 (u1 measured
directly at 1537.3 s). No selector, policy, workflow, timeout, product, financial or UI change; no test selected,
deleted, skipped or moved.

**B4: ZERO demotions proposed (`B4_PROOF_BLOCKED_ZERO_DEMOTIONS`).** The post-#451 hosted evidence shows the
critical path already reduced to ~37 min by the merged U1 call-scope bounding; the remaining heavy module
(`tests/test_u1_scope.py`, 1537.3 s measured) stays on the PR path because no node-level same-SHA replacement
proof exists. The weights refresh is the only safe non-selection optimization included (better shard balancing;
the critical path stays pinned by u1). Node-split of u1 remains a SEPARATE change requiring its own split-safety
proof (`node_split_policy.json` stays disabled here).

**Rollback:** `git revert` of this single commit restores B2's weights, report and registry state; the successor
chain is acyclic and the B2 cohort stays exact at the revert.
