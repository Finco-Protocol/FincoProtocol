# Exact-path gate proposal — WS1

Status: NOT AUTHORIZED / NOT APPLIED. The UI implementation diff is reviewable; protected tests and historical pin values remain unchanged. A green check cannot be obtained by relaxing an old guard.

## A. Exact presentation successor and mandatory browser registration

Concrete current source bytes are inventoried in CANDIDATE_SOURCE_BLOBS.json. Current local failures are recorded in the handover; baseline b1a58681 independently ran 98 pass / 1 fail on the same 99-test governance selection. Candidate had 93 pass / 6 fail before the precision addendum. The unchanged run-intent service and other financial files are rejected transitively when an existing exact cohort becomes invalid; WS1 has zero diff in those authorities. Do not add finance-source exceptions for these cascading failures.

Proposed minimal changes requiring Owner approval:

- tests/model_mutation_security_successor.py: a separate WS1 exact-blob presentation successor for WorkspaceView, FinancialResults and the rebuilt static JS/CSS only; retain original BLOBS, all historical successor dictionaries and drift/CSRF/ancestry checks.
- tests/test_rcux_governance.py, tests/test_rcm_governance.py, tests/test_model_react_overnight_b_governance.py: recognize only that exact later presentation state in current-source checks; preserve historical-source acceptance and every negative control. No wildcard, prefix or bypass for financial/security sources.
- tests/fin_v2_cohorts.py: register one closed exact-path WS1 cohort (new tests/wsv2_core_scope.py plus new tests/test_wsv2_core_scope.py), based on b1a58681. No alteration of financial methodology or existing cohort scope.
- tests/fin_v2_rcux_scope.py and docs/react_migration/rc_ux_completion/SOURCE_SUCCESSOR.json: exact successor attribution of the new read-only Overview adapter/aggregator and changed UI source; preserve historical manifests as ancestry evidence.
- docs/financial_validation/fin_v2_3/SOURCE_SUCCESSOR.json, docs/financial_validation/finv2_d01_d02/SOURCE_SUCCESSOR.json, docs/financial_validation/fin_v2_r1/SOURCE_SUCCESSOR.json: only exact pins for the just-authorized governance helper/test bytes owned by those cohorts; no financial source/golden change. Prefer additive successor recognition if updating a live pointer would erase history.
- tests/test_model_workspace_consolidation_browser.py and the exact source manifests above: add the new WS1 acceptance module to the existing mandatory browser role, with a narrowly reviewed new import. Existing mandatory execution inventory/evidence requirements remain intact. New test names and scenario/browser counts must be admitted with strict negative controls, not test skipping.

A concrete successor patch and its adversarial negative controls must then receive independent exact-HEAD review. This document requests bounded reconciliation, not permission to rewrite arbitrary governance tests. If further paths are found necessary, enumerate them before editing.

## B. Archive / unarchive

No endpoint exists at the base. Exact proposed authority paths: app/library/router.py (new operation-bound CSRF archive/unarchive handlers under authenticated same-origin existing library authority), app/persistence/projects_repository.py (one owner-scoped transaction toggling archived with expected-state/CAS), and app/v2/react_projects.py (issue/display only authorized lifecycle capabilities). New handler must refuse templates/read-only/foreign projects, preserve all immutable history and inputs, be idempotent/explicit under retry, and never hard-delete or Run. Existing security/source inventories and new negative authorization tests require a separately reviewed exact successor. No such changes are applied in WS1.

## C. True Blank / backend Run optimization

The seeded creator app/v2/react_new_project.py cannot persist an actually blank project. The current branch uses the assignment's allowed explicit blocked constraint. A non-runnable setup draft would require an exact approved create/persistence design; do not mark seeded assumptions as blank. No request to alter protected financial inputs is implied.

app/v2/post_run_context.py deep-copy and history-read optimization remain deferred: require_binding, validate_current, immutability and tenant isolation stay unchanged. No performance/source exception is requested by this branch.

No merge, deployment, release flag, finance policy, native gate, golden update or Legacy retirement is requested.
