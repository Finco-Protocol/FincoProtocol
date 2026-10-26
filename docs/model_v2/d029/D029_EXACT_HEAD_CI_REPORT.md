# D-029 exact-head CI report

## History

* `0bc14d43a15a`: everything passed except Public Safety worker-0 (4 Trust-readiness tests). Fixed in Correction B.
* `083c73ad12b1`: plan, workers 0-4 and mandatory Browser Acceptance (including the seven D-029 Chromium cases) passed; the
  `safety-and-smoke / aggregate` job failed with `original phase/native outcome regression:
  tests/test_trust_readiness_registry.py::test_scope_guard_this_work_touches_no_engine_input_writer_or_radar_code`; mandatory evidence
  failed downstream. Run `40379472631`.

## Root cause (Correction C)

The authenticated historical baseline (and the accepted-source reference) record that node as setup PASSED / call SKIPPED
("trust pack not part of this diff") / teardown PASSED, native JUnit skipped, because the Trust pack was not part of those diffs.
D-029 legitimately changes the Trust registry (one reviewed `data.run_intents` entry), so the original test now truly executes and
PASSES through its reviewed exact-content successor. `tools/ci_v3_production.py::verify_data` demanded unconditional equality with the
historical outcome. Not a collection mismatch, missing test, assertion failure or cleanup defect.

## Correction C (Financial Owner exact-path authorization)

`verify_data` still requires hard phase/native equality for every historical node. For exactly one literal node, both the baseline and the
accepted-source comparisons additionally accept `d029_authorized(...)`, which is true only when ALL hold: the exact node; baseline =
setup passed / call skipped with the original reason / teardown passed and native JUnit skipped with that reason; current = three passed
phases and native JUnit passed; setup/teardown unchanged; the Trust registry and the two regenerated readiness documents are the exact
reviewed Git blobs of HEAD; the registry at the pinned main `36edeeb5d9a1` is the pinned baseline blob; HEAD descends from that main; the
Trust-scope diff against it is exactly the four reviewed paths; the 15 required successor/historical Trust tests passed (phases AND native)
in the same run; and `evidence/D029_CI_V3_OUTCOME_RECONCILIATION.json` equals the reviewed constants. Anything else, any Git error and any
malformed evidence fails closed. It is not suppression: the test is not renamed, skipped or edited, and its real execution is required.
Authority is never inferred from a branch name, PR number or environment variable (tested).

Tests: `tests/test_ci_v3_outcome_reconciliation.py` (33): the positive on real reviewed sources; SKIPPED to FAILED / XFAIL / still-skipped /
missing execution / setup or teardown error; changed baseline reason; changed setup/teardown; missing, failed, skipped or malformed native
proof; every other node and family; unreviewed registry/doc blob; unrelated Trust change; incomplete reviewed set; wrong baseline main,
ancestry, git failure or receipt; each required successor test missing/skipped/failed; verifier wiring (exactly the two comparison sites,
hard equality retained, no other tool knows the exception). Existing CI V3 suites: 779 passed; the 3 failures
(`hosted_isolation::container_never_inherits_actions_credentials`, two `probe_tools`) fail identically on main in this container (no Docker/passwd).
A local replay of the authenticated plan and worker artifacts needs the GitHub artifact service and was not possible here; the exact-head
aggregate job is the authoritative replay.

Operational note: the reconciliation compares against the pinned main. If main advances before merge, the Trust-scope diff must be re-proven
and the pins refreshed through a new review; the verifier fails closed meanwhile.

The exact-head receipt for the Correction C commit must be read from the live PR checks.

## Status boundary

Release state: **RELEASE CLOSED**. See the release-state matrix in `D029_EXECUTIVE_REVIEW.md`.
Implemented and tested on PR #384 head: the canonical `POST /v2/workbook/run` intent lifecycle, the single-transaction
commit, startup schema, the React and Legacy clients and the governance successor. Not owner-approved, not activated:
the owner policies in `D029_OWNER_DECISION_REGISTER.md` remain candidates, `RELEASE_POLICY.enabled` is false, nothing is
deployed or merged. A request without `run_intent_id` keeps the released, non-idempotent behaviour.
