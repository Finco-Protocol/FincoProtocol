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

## Head 2 — this report's commit

Head 2 differs from Head 1 only by this documentation file. Its checks are the PR's check runs on the final head;
results are recorded in the PR conversation because a commit cannot contain its own CI result.

## Local evidence (merged head)

297 tests passed (new P2a tests, six related suites, `tests/test_trust_readiness_claims.py`). On `main` the three
call-count tests in the new file fail (old decoder performs 17 `json.loads` per entry); on the branch they pass (9 per entry).
