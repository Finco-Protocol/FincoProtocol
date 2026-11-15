# CI V4 Lean B2 — data-only scheduling-weight refresh (GLM, 2026-11-15)

**Scope:** ONE finite exact-source successor of the accepted B1 cohort carrying a DATA-ONLY refresh of
`docs/ci_v4/module_weights.json` (fresh hosted per-module JUnit weights from run 43692118132; the indivisible
`tests/test_u1_scope.py` weight is DERIVED from the hosted shard-2 wall, labelled as such in the file's `source`).
No selector, policy, workflow, timeout, product, financial or UI change; no test selected, deleted, skipped or moved.

**Measured context (labels preserved):** with fresh weights the B1-selected corpus has an indivisible floor of
`tests/test_u1_scope.py` ≈ 3944 s (DERIVED_FROM_HOSTED_WALL) — the critical path stays ≈ 4064 s at ANY worker count.
More workers cannot fix an indivisible test; a node-level split of u1 would be a SEPARATE minimal change requiring its
own split-safety proof (the closed `node_split_policy.json` machinery stays disabled here). Fable's 15–25 min
projection remains unproven.

**B2 demotions: ZERO proposed.** The historical exact-source inventory of the accepted B1 cohort remains
authoritative and unchanged on this base; decision-ledger item #2 stays OPEN. No test is selected, deleted,
skipped, moved or re-tiered by this change.

**Rollback:** `git revert` of this single commit (or merge-revert on main) restores B1's weights and registry state;
the successor chain is acyclic and the B1 cohort stays exact at the revert.
