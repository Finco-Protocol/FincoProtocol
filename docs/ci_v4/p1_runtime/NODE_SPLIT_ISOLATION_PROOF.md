# P1: isolation proof for splitting `tests/test_u1_scope.py` by node

Subject: `main` `d32f49873994ecfa1103b0ecb7e3a5ee2e04c9de` (merge of #457). These are local runs in independent `git clone --shared` checkouts, one per process, mirroring separate runners. CPython 3.12.3, dependencies from the repository's `python.lock`, `requirements*.txt` and `constraints.txt`.

## Why the module was `NOT_BENEFICIAL` and why that is no longer true

`node_split_policy.json` kept U1 out of the allowlist with *"one node is 337 s of 388 s; module below target"* (run 41912154663). The current hosted measurement (CI V4 PR run 44147228493, head `ac84868e`, shard-2 artifact sha256 `cb555d74…`) is **2,413.2 s over 100 nodes**:
- the heaviest node is 976.9 s;
- the next is 539.7 s;
- 10 parametrised nodes take about 40 s each.

The whole module ran on one runner and set the 56-minute shard.

## Fixture isolation (static)

- `_tree` (module scope) creates **its own** detached worktree under `tmp_path_factory` for each process and removes it at teardown.
- `wt` (function scope) runs `git reset --hard -q` and `git clean -fdxq` after **every** test.
- No test depends on state left by another test. This is the pattern already accepted for `tests/test_wf06b_scope.py` (`SPLIT_SAFE_FLOOR_LIMITED`).
- `test_evaluation_at_a_commit_ref_matches_the_working_tree_and_rejects_a_foreign_ref` makes one **empty** commit in `wt` and does not reset HEAD. The tree stays byte-identical, and `exact_blobs_ok(wt)` judges the working tree and BASE ancestry, so later tests see the same bytes. The shuffled run below exercises every order relative to that test.
- Non-`wt` tests only read the real tree, inside `fin_v2_cohorts.call_scope()` where marked.

## Dynamic proof

The parts are exactly what the trusted scheduler (`tools/ci_v4_schedule.split_module_nodes`, main d32f4987) derives from the run 44147228493 node times, target 900 s:

| Run | Nodes | Result | Local wall |
|---|---|---|---|
| part 1 (the 977 s node alone) | 1 | **1 passed** | 1,310 s |
| part 2 | 44 | **44 passed** | 994 s |
| part 3 | 55 | **55 passed** | 1,049 s |
| whole module, seeded random order (seed 20261117) | 100 | **100 passed** | 3,213 s |

In the seeded order the empty-commit test runs at position 36 of 100, followed by 64 other tests; the 977 s node is at 12 and the 540 s node at 78. The recorded order equals `random.Random(20261117).shuffle` of the collection order. Every node passes in its part, in a process that has never run the other parts. The union of the three parts is exactly the 100 collected node IDs: no node is missing, none is duplicated, and none is renamed. Hosted, all 100 passed in run 44147228493.

## Floor

`test_an_older_cohort_accepts_a_superseded_blob_only_through_the_exact_cohort` (976.9 s hosted) is an indivisible floor: splitting cannot shorten it. The verdict is therefore `SPLIT_SAFE_FLOOR_LIMITED`, as for WF-06B.
