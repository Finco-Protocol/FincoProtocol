# V11 — Exact-head CI report

PR: Finco-Protocol/FincoProtocol#385 (Draft, base `main` = `36edeeb5d9a14749fdfafcd3b60a0d384cac73ba`, tree `33e585f64f51edb4fddd06a0d4d0fb992cfaf9dd`).

This file records GitHub evidence per exact head. A later head's results are never inferred from an earlier one.

## Head 1 — `b3dc2f84b79c6e6146a1e4bd43dc2a439c2a87b0` (tree `721656e7419d4c3276bfd0dc25644274f1405d33`)

Code head: P2a + forward merge of `main` (PR #383). Public Safety run 40378362227, PR merge SHA `b24afecc46a723361ec3626df15d6afe7baecd0c`.

| Check | Result |
|---|---|
| compile-and-safety | success |
| source-safety | success |
| mandatory-browser-evidence | success |
| authoritative-history (Governance Full History) | success |
| dependency-audit | success |
| safety-and-smoke / route, plan | success |
| safety-and-smoke / worker-0, worker-2, worker-3, worker-4 | success |
| safety-and-smoke / worker-1 | **failure** (1 failed, 3800 passed) |
| safety-and-smoke / aggregate, tests; mandatory-evidence | failure (consequence of worker-1) |

Failure analysis (worker-1): the only failing node was
`tests/test_cost_batch_save_v1.py::test_single_row_command_still_works_after_a_batch_with_the_returned_token`
(`'NoneType' object has no attribute 'select_one'`, line 436). It is unrelated to Run History.
The test takes `rows[0]` of `capex_sub_lines ORDER BY sub_line_id`; `sub_line_id` is a random `uuid4`, and in the seeded
fixture 1 of 31 CAPEX rows renders no `<form data-sub-line-id>`, so roughly 1 run in 31 selects a row with no form.
Reproduced locally (31 rows, 1 without a form); the test passes 25/25 in isolation and passes on `main`.
No test was skipped, modified or quarantined.

A same-run retry (`rerun_failed_jobs`) was attempted once; the CI contract rejects it (`plan source/run/attempt drift`),
so a fresh exact-head run requires a new head.

## Head 2 — `84da9997b7c6234e654d894670311753541388f5` (tree `0c971eb2da39ab1e1b500b23f02310937122996e`)

Differs from Head 1 only by this report. Public Safety run 40384088178 and all other required checks: **15/15 success**
(route, plan, workers 0-4, aggregate, tests, mandatory-evidence, mandatory-browser-evidence, compile-and-safety, source-safety,
authoritative-history, dependency-audit; sequential skipped by design). Worker-1 passed; the Head-1 flake did not recur.

## Head 3 — `4e7c375578f6d552c1e0cdc1e98109405ee7b413`

Created by the repository owner account: forward merge of `main` at `6c642adcd193691818f1413bf5273885470c8ef9` (PR #384, D-029).
Main's CI V3 reconciliation now runs this PR in **sequential** (single-node) mode. Public Safety run 40395823616:
route, source-safety, compile-and-safety, authoritative-history, mandatory-browser-evidence, dependency-audit success;
**sequential/tests failed**, so tests and mandatory-evidence failed.

Failure analysis: 89 errors, all in this PR's own new file `tests/test_v11_p2a_run_history_single_decode.py`, at fixture setup:
`PROJECT_STAGE_INVALID: <object object ...> is not a canonical ProjectStage value`. No other test failed in the 3800+ node run.
Root cause: the new test imported `save_project` at module level. `tests/test_public_reference_models.py` does
`importlib.reload(projects_repository)`, which creates a new `_UNSET` sentinel; the stale function kept the old sentinel as its
default, so `project_stage` was no longer recognised as "omitted" and the raw `object()` reached `normalize_stage`. Previously
the PR ran in parallel shards where the reloading test did not precede these tests in the same process. Reproduced locally
(`pytest tests/test_public_reference_models.py tests/test_v11_p2a_run_history_single_decode.py` -> 89 errors) and fixed by
resolving `projects_repository.save_project` at call time (test-only change, no production code, no other test touched).
After the fix both orders pass (92 passed together; 89 passed alone).

## Head 4 — the commit carrying this correction

Checks for this head are recorded in the PR conversation (a commit cannot contain its own CI result).

## Local evidence (merged head)

297 tests passed (new P2a tests, six related suites, `tests/test_trust_readiness_claims.py`). On `main` the three
call-count tests in the new file fail (old decoder performs 17 `json.loads` per entry); on the branch they pass (9 per entry).
