# Exact-path gate proposal — WS1

Status: Section A APPROVED by Financial Owner on 2026-10-28 for authorization HEAD c848a979b3322c53d02631a5f5897180fae9c1e3; narrowly applied in this successor. Sections B and C remain NOT AUTHORIZED / NOT APPLIED. No guard is relaxed to obtain a green check.

## A. Exact presentation successor and mandatory browser registration

Concrete current source bytes are inventoried in CANDIDATE_SOURCE_BLOBS.json. Current local failures are recorded in the handover; baseline b1a58681 independently ran 98 pass / 1 fail on the same 99-test governance selection. Candidate had 93 pass / 6 fail before the precision addendum. The unchanged run-intent service and other financial files are rejected transitively when an existing exact cohort becomes invalid; WS1 has zero diff in those authorities. Do not add finance-source exceptions for these cascading failures.

Approved exact-path changes (Owner approval applies only to section A):

- tests/model_mutation_security_successor.py: a separate WS1 exact-blob presentation successor for WorkspaceView, FinancialResults and the rebuilt static JS/CSS only; retain original BLOBS, all historical successor dictionaries and drift/CSRF/ancestry checks.
- tests/test_rcux_governance.py, tests/test_rcm_governance.py, tests/test_model_react_overnight_b_governance.py: recognize only that exact later presentation state in current-source checks; preserve historical-source acceptance and every negative control. No wildcard, prefix or bypass for financial/security sources.
- tests/fin_v2_cohorts.py: register one closed exact-path WS1 cohort (new tests/wsv2_core_scope.py plus new tests/test_wsv2_core_scope.py), based on b1a58681. No alteration of financial methodology or existing cohort scope.
- tests/fin_v2_rcux_scope.py and docs/react_migration/rc_ux_completion/SOURCE_SUCCESSOR.json: exact successor attribution of the new read-only Overview adapter/aggregator and changed UI source; preserve historical manifests as ancestry evidence.
- docs/financial_validation/fin_v2_3/SOURCE_SUCCESSOR.json, docs/financial_validation/finv2_d01_d02/SOURCE_SUCCESSOR.json, docs/financial_validation/fin_v2_r1/SOURCE_SUCCESSOR.json: only exact pins for the just-authorized governance helper/test bytes owned by those cohorts; no financial source/golden change. Prefer additive successor recognition if updating a live pointer would erase history.
- tests/test_model_workspace_consolidation_browser.py and the exact source manifests above: add the new WS1 acceptance module to the existing mandatory browser role, with a narrowly reviewed new import. Existing mandatory execution inventory/evidence requirements remain intact. New test names and scenario/browser counts must be admitted with strict negative controls, not test skipping.

Applied as WSV2_PRESENTATION_SUCCESSORS (four exact React blobs), separate WSV2_BROWSER_SUCCESSORS (one additive mandatory-role import) and tests/wsv2_core_scope.py (closed exact path/byte cohort). Existing RC-UX OWNED_PATHS need no expansion: the new WS1 cohort owns Overview and its acceptance module. Live manifests retain complete predecessor pin dictionaries under historical_source_blobs[c848a979b3322c53d02631a5f5897180fae9c1e3], verified against Git, with original metadata unchanged. Only approved governance live pointers and the read-only aggregator pointer change. The new SOURCE_SUCCESSOR.json pins every WS1 source, test and document; no wildcard is added.

A concrete successor patch and its adversarial negative controls require independent exact-HEAD review and CI. Approval does not authorize arbitrary governance tests. Further required paths must be enumerated before editing. Legacy mandatory acceptance bodies still contain four-step wizard/local-precision expectations; they are not modified by this section A authorization. That UI-contract reconciliation requires a separate exact-path proposal, with existing test identities, authorization/security checks and numeric oracles preserved.

## B. Archive / unarchive

No endpoint exists at the base. Exact proposed authority paths: app/library/router.py (new operation-bound CSRF archive/unarchive handlers under authenticated same-origin existing library authority), app/persistence/projects_repository.py (one owner-scoped transaction toggling archived with expected-state/CAS), and app/v2/react_projects.py (issue/display only authorized lifecycle capabilities). New handler must refuse templates/read-only/foreign projects, preserve all immutable history and inputs, be idempotent/explicit under retry, and never hard-delete or Run. Existing security/source inventories and new negative authorization tests require a separately reviewed exact successor. No such changes are applied in WS1.

## C. True Blank / backend Run optimization

The seeded creator app/v2/react_new_project.py cannot persist an actually blank project. The current branch uses the assignment's allowed explicit blocked constraint. A non-runnable setup draft would require an exact approved create/persistence design; do not mark seeded assumptions as blank. No request to alter protected financial inputs is implied.

app/v2/post_run_context.py deep-copy and history-read optimization remain deferred: require_binding, validate_current, immutability and tenant isolation stay unchanged. No performance/source exception is requested by this branch.

No merge, deployment, release flag, finance policy, native gate, golden update or Legacy retirement is requested.


## D. Additional acceptance-contract reconciliation — NOT AUTHORIZED / NOT APPLIED

Section A exposed a necessary path omission: prior mandatory browser bodies still require the removed read-only wizard step or local precision controls. A real reproduction through the mandatory role returned seven WS1 passes and one original Solar wizard failure at model_react_rcm_new_project_acceptance.py:191, waiting for the intentionally removed timeline panel. Restoring that redundant panel or skipping old cases would violate the requested product/test requirements.

The concrete UNAPPLIED diff is ACCEPTANCE_SUCCESSOR_PROPOSAL.patch. It is a review proposal; its presence does not execute or admit the changed test bytes. Original test function identities and parametrization are preserved; no skip is added. Exact additional requested paths (all under tests/):

1. model_react_mvp_acceptance.py — advance directly from validated details to review.
2. model_react_rcm_new_project_acceptance.py — three-step flow; verify the same canonical timeline in review; require created project #inputs; preserve error, ownership, preview, single-create, retry and responsive tests.
3. model_react_rcm_themes_acceptance.py — review is step three; retain all-theme checks.
4. model_react_rcux_navigation_acceptance.py — audit the three actual wizard phases; preserve routing checks.
5. model_react_rcux_product_acceptance.py — explicit Blank limitation disclosure and three-step flow; preserve isolation and create count.
6. test_model_react_poc_browser_acceptance.py — existing creation helper reaches the three-step review; ambiguous-outcome cases unchanged.
7. model_react_wf1_browser_acceptance.py — shared Report precision selector, preserving the independent Decimal oracle, raw parity and ratio/unit assertions.
8. model_react_rcm_investors_acceptance.py — default-zero monetary expectation plus explicit 2/3/0 display checks; ownership percentage, DPI and Save/Run evidence checks unchanged.
9. model_react_rcux_analysis_acceptance.py — select the dedicated existing workspace navigation without a union that now also finds a mobile-hidden sidebar link.

Support changes would stay confined to the already listed section A paths: a separate exact acceptance-body successor in tests/model_mutation_security_successor.py (no editing of earlier dictionaries or the four presentation pins); corresponding current-source recognition in tests/test_rcux_governance.py; the literal added paths and negative controls in tests/wsv2_core_scope.py and tests/test_wsv2_core_scope.py; and exact test-byte attribution in the four approved manifests plus the WS1 manifest. The archived source_blobs maps remain immutable. Only acceptance test pointers may additionally change; financial/app/security pins remain unchanged. New adversarial checks must bind unchanged test identities/parametrization, old financial/security assertions and no-skip rules.

This is not permission to edit arbitrary acceptance, financial fixtures, golden results, CI workflows, native gates, Run integrity, Archive/Blank or WS2. The proposed patch needs Owner exact-path approval, implementation validation, independent exact-head review and fresh CI before any acceptance claim.
