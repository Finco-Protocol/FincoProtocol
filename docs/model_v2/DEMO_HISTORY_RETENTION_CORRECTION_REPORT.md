# Demo cleanup / Run History Correction A

Status: LOCAL CORRECTION VALIDATED; SEPARATE DRAFT PR REQUIRED.
The owner approved the bounded retention policy and its exact-content Trust
correction. This is not part of the CI-only PR #247.

Base: `5dbfd2a2fb1c6c777b7eb26d93a7090820acce23`.
Branch: `codex/fix-demo-history-retention`.
Existing CI PR #247 remains unchanged at
`2b71e29262040c5eea33810cfa40bbc8f2b025b8`, OPEN/DRAFT/unmerged.

## Root cause and approved policy

The original cleanup omitted project-linked Run History, deleted scenarios
before dependent exports, and relied on `with conn` with SQLite autocommit.
Parent/FK errors were swallowed after earlier child deletions had committed.
`LIKE 'demo_%'` also treated the underscore as a wildcard, unlike canonical
case-sensitive demo ownership. Protected project markers were not checked.

The owner explicitly authorized terminal disposal of a complete temporary
demo session, including its history, only after expiry or explicit gated reset.
Permanent/admin/reference/protected history is never deleted. History remains
immutable for the lifetime of its session; no ledger mutation API is added.

## Implemented changes

- `app/demo_cleanup.py`: literal case-sensitive owner selection; history-aware
  latest activity using both `ran_at` and `created_at`; BEGIN IMMEDIATE before
  eligibility reads; parent/child and scenario ownership validation; canonical
  protected-reference checks; explicit child-first deletion; rollback on every
  error; postconditions inside the transaction; no swallowed success result.
- `tools/demo_reset.py`: explain bounded disposal and permanent/admin refusal;
  existing environment/path/reset-opt-in/confirmation gates are unchanged.
- `docs/model_v2/RUN_HISTORY_V1_CONTRACT.md`: document the exact terminal demo
  retention exception without changing permanent append-only semantics.
- `tests/test_demo_history_retention.py`: real disposable SQLite positive and
  negative cases for complete disposal, activity preservation, history-only
  parent blocking, cross-owner/cross-project isolation, protected markers,
  every DELETE failure, postcondition rollback, FK/caller transaction guards,
  bootstrap refusal, reference-history preservation, orphan-state refusal and
  concurrent canonical history append versus cleanup.
- `tests/test_p6_correction_c.py`: replace the explicitly superseded admin-wipe
  expectation with stronger before-first-write refusal and exact preservation
  assertions. No test is deleted or skipped.
- `tests/test_p6_correction_d.py`: positive bootstrap fixture contains only
  approved disposable demo rows and pre-initialized references; FK protection
  stays enabled; delete-failure interceptors still target the actual DELETEs.
- `app/trust_readiness/registry.py`: only project/history retention copy changes
  and removal of the now-closed demo history FK gap. All statuses and other
  claims remain identical to the approved base.
- `docs/readiness/03_known_limitations_and_support_matrix.md` and
  `06_retention_and_deletion.md`: regenerated from that registry; no generator
  changes or other generated document changes.
- `tests/test_trust_readiness_controls.py`: replace the closed-gap assertion
  with expired-session disposal, permanent history byte-for-byte preservation
  and fresh demo history TTL protection.
- `tests/test_trust_readiness_registry.py`: exact 12-file correction scope,
  ten Git blob pins, invalid-base and missing-content rejection, broader-change
  negative tests, and exact registry text bridge from the historical CSRF
  snapshot. Historical CSRF/WF-05 exceptions, financial pins and global scope
  restrictions are unchanged. The guard and delivery report are reviewed
  exact paths, not wildcard namespaces.

## Bootstrap integration boundary

Existing reference data is never reseeded during reset. The standard reference
initializer uses multiple connections, so it cannot safely participate in
terminal disposal's transaction without expanding the correction into a
reference-service rewrite. An existing demo database must therefore already
have its five references initialized; otherwise bootstrap refuses before any
deletion. Empty database initialization still uses the unchanged, non-destructive
standard initializer. A seeding error in that empty path cannot partially commit
a required deletion, because no destructive statements were executed.

Full bootstrap preflights all user-owned state and FK integrity. Permanent,
admin or protected non-demo data refuses the reset before its first modification.
Canonical reference rows/history are preserved byte-for-byte. An existing caller
transaction is refused rather than being committed or rolled back by cleanup.

## Local evidence

Windows/Python 3.12.10, disposable databases and separate pytest processes.
Plugin autoload disabled; pytest-asyncio explicitly loaded. Real Git GNU grep
was added to process PATH for the existing Unix-command legacy test. This LF
worktree preserves the approved vendor Git bytes. No scanner, pin, platform
test or assertion was weakened to accommodate the earlier Windows failures.

| Suite | Result |
| --- | --- |
| New retention suite | 57 passed |
| P6 demo isolation | 12 passed |
| P6 Correction A | 24 passed initially; TTL=0 reference test then passed after preserving existing zero-TTL compatibility |
| P6 Correction B | 37 passed |
| P6 Correction C | 24 passed |
| P6 Correction D | 9 passed |
| Immutable Model V2 Run History | 23 passed |
| Unique focused cases after targeted rerun | 187 passed; no unresolved failure in these suites |
| Independent Trust registry/controls/claims/routes | 140 passed |
| Final combined P6/demo/history/Trust ring | 327 passed, 0 failed, normal exit 0 (507.32 seconds) |
| Standalone unchanged public safety scan | PUBLIC_REPOSITORY_SAFETY_SCAN_PASS, exit 0 |

Final targeted rerun: new retention suite plus original zero-TTL reference
test = 58 passed. Every tested process returned normally. The unmodified
safety-scanner test passed in Correction A. py_compile and git diff --check
passed; diff check emits only informational Windows line-ending warnings.
The final combined run supersedes the earlier integration diagnostic failure.
Generated documents check and all changed Python compilation checks pass.

New tests compare full immutable history and all project state before/after
for permanent/admin/reference owners and prefix near-matches. Fresh activity
in every authority preserves the complete session. Trigger-induced failures
at each deletion step roll back history and parents together. A concurrent
canonical append holds the write lock; cleanup waits, observes its fresh history
and preserves the complete session. No financial engine is executed by these
tests.

## Independently reproduced integration blocker and authorized resolution

`tests/test_trust_readiness_controls.py::test_known_gap_run_history_survives_demo_ttl_cleanup`
asserts that history is excluded from cleanup and the old expired parent/history
remain. That explicitly pinned gap is now intentionally closed by the approved
retention behavior. `app/trust_readiness/registry.py` also publishes the old
retention claim in its project/history entries and known-gap record.

Unmodified Trust registry/control diagnostic: 47 passed, 1 skipped, 1 failed
(the old retention-gap assertion). The existing Trust scope guard forbids
combining Trust edits with demo-cleanup edits. Updating only a test would leave
published retention claims false; silently weakening the guard is not acceptable.

The owner explicitly authorized the directly related retention copy, stronger
tests and exact-content exception only in this separate correction PR. The
closed gap is removed; the absence of a user erasure API remains an open gap.
No unrelated Trust claim/status is changed. Ten exact blobs pin all correction
code, policy contract, linked tests and generated retention documents; any
additional changed path, altered pinned file or invalid base rejects the
exception. No financial defect or new financial authority is involved.

## Frozen boundaries and next gate

ZERO DIFF: financial_engine, finco_core, domain, app/persistence, app/auth.py,
main_web.py and all workflows. No schema, canonical Run writer, scenario,
financial contents, pins or goldens changed. No broad cascade or production
FK-disable exists. The only FK-OFF statement in the new tests constructs a
deliberately invalid negative fixture, then immediately restores FK ON.

Exact-head correction CI and the final SHA are recorded in the Draft PR body
after publication, avoiding a self-referential commit SHA in this document.
Obtain all exact-head gates and stop for independent review. Only after a separately
authorized normal upstream merge may #247 normally merge main and rerun the
original unsharded control/shadow selection and full equivalence acceptance.
