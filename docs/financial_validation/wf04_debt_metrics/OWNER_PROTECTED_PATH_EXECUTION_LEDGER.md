# WF-04 — Owner protected-path execution ledger

Basis `main` `b76ac65c99e7fc9b486a557ae3c5ba9a711f50b3`. Branch `claude/new-session-w64bc1`. Exact HEAD at generation: `see PR`.

**Authorisation basis:** the Financial Owner's direct instruction of 2026-10-29 ("Uključi sva odobrenja da odmah radi."), recorded as §0A of the unified WF-04 prompt: one bounded, minimally scoped implementation including the exact-path source, protected-test, exact-source-cohort and bundle changes needed for green exact-head CI. §8: no second signature; this ledger is an approved-scope execution record, not a request.

**Approval boundary kept** (verified by `tests/test_wf04_scope.py` and by the empty diff of these namespaces): `financial_engine/`, `finco_core/`, `domain/`, `.github/`, `app/run_integrity/`, `app/runtime/`, `app/export/` (signed certificate), `app/v2/router.py`, `grid_router.py`, `react_workspace_router.py`, `save_all_commands.py`, `mutation_csrf.py`, `update_service.py`, `bankability_config.py`, `frontend/src/app/editing/`. No Senior sizing / `GEARING_CAP`, SHL, reserve waterfall, DSRA/DSRF, cash sweep, maturity, Integrity predicate, native engine or security guard was changed.

## 1 — Every changed path (old blob → new blob)

Legend: **P** = protected / exactly pinned before this change (listed with reason below); **N** = new in this PR; **M** = modified, not previously pinned.

| Path | Kind | Status | Old blob (`main`) | New blob |
|---|---|---|---|---|
| `app/persistence/workspace_repository.py` | P | M | `3dbcd861d363d1c3f3ef1ff148f0ecae173612f7` | `7841d30e091bafd3a179862e8d9a8e94d3cc961f` |
| `app/v2/credit_decision_projection.py` | M | M | `a487670ba14b49092902c4ffbc8c42872490b85f` | `d194e824006c2df5e016c5abb0176ee2219533e8` |
| `app/v2/debt_metrics_projection.py` | N | A | — | `72ff9125f14686035cf35f36df7a75efd6242270` |
| `app/workbook/dscr_contract_terms.py` | N | A | — | `05024753c0a52a68c085a63d736289f4fa8f2f75` |
| `app/workbook/registry.py` | P | M | `31570edc0e6ca1c0191e13e987a0598ade5c8f8b` | `7880dca5b53d87d9e01b50d2fc0d43b20e504bd6` |
| `docs/financial_validation/fin_v2_3/SOURCE_SUCCESSOR.json` | P | M | `3289f350bb8a1fc564317239100f8a41508cb7ef` | `caca040779bd620e78cd687909246e27f5b6e568` |
| `docs/financial_validation/fin_v2_r1/SOURCE_SUCCESSOR.json` | P | M | `45c818843183a033d76deb490f9a05f4229748dd` | `62d5711043a2ce35f2fb14cb56750c7919a1b86e` |
| `docs/financial_validation/finv2_d01_d02/SOURCE_SUCCESSOR.json` | P | M | `16bc1fc11bdfcc966476b20ca5998aeccb652b7f` | `33ac6e10115528b0914b3e7a7fe66a6bbdb2d8b8` |
| `docs/financial_validation/wf04_debt_metrics/CORRECTION_A_CI_AND_PERIOD_MATRIX.md` | N | A | — | `d996c3b6437dafbe9931564923f7bff21d62f74f` |
| `docs/financial_validation/wf04_debt_metrics/INDEPENDENT_ORACLE_AND_PARITY.md` | N | A | — | `1d65e0250386f2111f437082cb4f83e66bdcea29` |
| `docs/financial_validation/wf04_debt_metrics/OWNER_DECISION_AND_CONFLICT_REGISTER.md` | N | A | — | `7c2921bf6d010da2b85015dcf778aa3f709602d8` |
| `docs/financial_validation/wf04_debt_metrics/P00_VERIFIED_STATE.md` | N | A | — | `55fc9e4d7120313ba8906fed287f2a3efde2bd90` |
| `docs/financial_validation/wf04_debt_metrics/REVIEW_VERDICT.md` | N | A | — | `7ea2d594f7d588612811a3737aabf622507b2507` |
| `docs/financial_validation/wf04_debt_metrics/TWO_DSCR_CONTRACT_MAPPING.md` | N | A | — | `74c25a02616d3fe1b03fa78568242a1f8d0eadcd` |
| `docs/financial_validation/wf04_debt_metrics/WF04_ACCEPTANCE_MATRIX.md` | N | A | — | `87dd275943448198392389b23aedd7fa65ee2d60` |
| `docs/react_migration/wsv2_core/SOURCE_SUCCESSOR.json` | P | M | `415752eefc64d6baff4c48602b9978d5b6ad4548` | `d4ce6e7b7e83d1be1badddb76cd2d8089d40ac45` |
| `frontend/src/app/FinancialOverview.tsx` | P | M | `9e073447afb224ba60fc8b97d72f776b2a67ea14` | `6ec33e4695a1fbb2289b9dea26aeaa5d7f29d432` |
| `frontend/src/app/FinancialResults.tsx` | P | M | `c53b677f29671380db916ceb4f4cfb2e2e53beeb` | `eb5ddb89b663f8145b702df26d591b884fbb4339` |
| `frontend/src/app/credit/CreditDecisionPanel.tsx` | M | M | `a3a39ee566be572fae9a96df7690c7bd7009b0e0` | `2a48162683d4641454876b41c2bddf0e51b0f59c` |
| `frontend/src/app/debtmetrics/CovenantTable.tsx` | N | A | — | `730af51b994e1d95fa54ea277d44e24039195c6a` |
| `frontend/src/app/debtmetrics/DebtMetricsWorkspace.tsx` | N | A | — | `2f726058e8079194c6dae85893da31dd44f9aef7` |
| `frontend/src/app/debtmetrics/DscrProfileChart.tsx` | N | A | — | `bab34a6173111d74bcececf0cd2de68eaa64c51e` |
| `frontend/src/app/debtmetrics/KpiRow.tsx` | N | A | — | `7a07365413f11ca18eaa92950d21806aecc66f4f` |
| `frontend/src/app/debtmetrics/PeriodSchedule.tsx` | N | A | — | `b1bf9e571646dbc295a05f3f9b2176f549ff4dac` |
| `frontend/src/app/debtmetrics/PeriodStatusMatrix.tsx` | N | A | — | `f38d4a0e926555d4b3af3dc502ec2645b51c8b78` |
| `frontend/src/app/debtmetrics/ReservesPanel.tsx` | N | A | — | `f2cd6a9890c7af68c28b3aba24f3ec017b85c662` |
| `frontend/src/app/debtmetrics/__tests__/debtMetrics.test.mjs` | N | A | — | `8fc9960b4c32d0de5e61469aa19a4953b9539e5d` |
| `frontend/src/app/debtmetrics/__tests__/periodMatrix.test.mjs` | N | A | — | `a4063d13c3795c918f49bda89d5a59dbb8dc65f9` |
| `frontend/src/app/debtmetrics/api.ts` | N | A | — | `0192ba2a78214af8d6d2dc5ad777cbcb5a75dd9e` |
| `frontend/src/app/debtmetrics/debtMetricsLink.ts` | N | A | — | `a704d29f9f1120c4c0e80208248eb8e56858db56` |
| `frontend/src/app/debtmetrics/format.ts` | N | A | — | `10ac26b23dfb88082decc62191b42b2811d74a0e` |
| `frontend/src/app/debtmetrics/types.ts` | N | A | — | `829efdf3080323cb75129c22c525be759898d2af` |
| `frontend/src/app/financing/FinancingStudio.tsx` | M | M | `fdc8ff8b4b8bc270765c5f99ac89772ce6b00bf0` | `72917e28ebd8278ac02cf13d88390d9e05766728` |
| `frontend/src/app/workflow/WorkflowBar.tsx` | P | M | `f478c911513c4dd1bc8e0b5fc8250bdca863aa0d` | `5f7d657e7fe50886426c2255cc1c44ecabf1a7b4` |
| `frontend/src/styles/rcm-debtmetrics.css` | N | A | — | `7e4cdd3e5e0f36e50b47fc06a3f08a4c24a9c321` |
| `per1_fail.txt` | N | A | — | `e69de29bb2d1d6434b8b29ae775ad8c2e48c5391` |
| `per2_fail.txt` | N | A | — | `e69de29bb2d1d6434b8b29ae775ad8c2e48c5391` |
| `static/react/finco-react.css` | P | M | `3a1eab32a691696787aa5b54893fe24812186608` | `9a1346c08aa6cbed4bdbb077c090e84f6e4ccf69` |
| `static/react/finco-react.js` | P | M | `74531cc4c53fa4fdedde0a4ec5967b75db6e3697` | `e08f91399e460a63d09d14332467d25b1e023d00` |
| `tests/fin_v2_cohorts.py` | P | M | `f3c320bcd022539eb5ee8c53d09ac7050cfb553b` | `244c3949a8c6adc193eafc0fa118094e6719058a` |
| `tests/model_react_rcm_financing_acceptance.py` | P | M | `e44930875947bf0043ce4e2e49c8fceeb87d851e` | `df42c9e19f43a597a8267c5f6c973dea6f6ff884` |
| `tests/model_react_wf04_debt_metrics_acceptance.py` | N | A | — | `a6fb48304c4330d345437dc50be38f67f112a4e5` |
| `tests/test_fin_v2_3_scope.py` | P | M | `b9671b2c1d9e55e7169261f84ccd44fb5db2c61e` | `701f2514efe7edf0f9c390cdae23f610f19dda35` |
| `tests/test_fin_v2_r1_scope.py` | P | M | `7dd9f42f00eb8a6f849ad29d5e565c2f924ce7c7` | `6153c2edb7f0cb2ad3dad59ec860f1dd6d1b745c` |
| `tests/test_finval_f01_fixture_integrity.py` | M | M | `71c48ba68cb53e2dcd81b470a88777b3d3801d06` | `568d8ee528790981bf74b7f71eb2e688c914a41b` |
| `tests/test_model_credit_decision_v3_real_runs.py` | P | M | `61ec7bead5f71b29e38677ef9a6b1f8c562387a7` | `e2009d63694a64d9c1ea161bc4ffc34606114feb` |
| `tests/test_model_mutation_security_successor.py` | P | M | `4672261c9aa91f0b727e116886ccc98b3e888f5a` | `c922d847fa598a1b60815dc24db0192ebf6b41a5` |
| `tests/test_model_react_insights_v1.py` | P | M | `29b07e518eef65a9ade11f141d433594cc6ee82a` | `d62036ab8eb8dbc72e0436d821864078e76ce556` |
| `tests/test_model_workspace_consolidation_browser.py` | P | M | `7c6478289c029f8b53e16103fa22b22123cbd19a` | `e5f3ace7a7406fc2b487ef90eab369e4ed51955b` |
| `tests/test_model_workspace_productivity_v1.py` | P | M | `024c1c9dfea3dd18186a59e0ef6cc55c54671231` | `5470a0f40339aca9a60c22c864dfd8803de76e6e` |
| `tests/test_rcm_governance.py` | P | M | `414373f3aaa0da42d4521df88d2788e40f60c02d` | `7b173cb4de41d910e5fe3c0796b62ad5ab9eb98e` |
| `tests/test_rcux_governance.py` | P | M | `4a3b8a7d3a8f99a2061bbe38c784bd0669a9c122` | `88cd1291f9935f4d07320d328fea0137adde98ae` |
| `tests/test_wf04_credit_debt_metrics.py` | N | A | — | `5223cc75c81bb680aa717032bd986a997c668bd8` |
| `tests/test_wf04_dscr_contract_terms.py` | N | A | — | `c0572ce139f19b9b223a9f4502a8ed6f8aa8032f` |
| `tests/test_wf04_independent_oracle.py` | N | A | — | `2131ea106c1758b6020b42ca49bbc0f567c76994` |
| `tests/test_wf04_period_matrix.py` | N | A | — | `1f9e83c385f1055c1c1e1b3bb481b16fa52202ac` |
| `tests/test_wf04_run_bound_terms.py` | N | A | — | `aeab52711ae1cfa0a121c07639c374a78111d861` |
| `tests/test_wf04_scope.py` | N | A | — | `f2c659fa244fc5c04f7a1598329bd0aed0e640df` |
| `tests/test_wsv2_core_scope.py` | P | M | `6fafea72bfca4c6be200709d55bd8466049a8bbc` | `e7a88c88cac5abb8d7bb8691f307072ea1ded615` |
| `tests/wf04_scope.py` | N | A | — | `154901ac1b18f680d9ae909c12c3abc09153e05f` |
| `tests/wsv2_core_scope.py` | P | M | `c7b6f2aedb618f068bf091ead5258f299af4f052` | `13cc263f66ed37e8d36f1499fd6857e9c1869902` |
| `tools/wf04_independent_dscr_oracle.py` | N | A | — | `f286d019a6b6cbb964c48ff7ed68281e7715b65d` |

## 2 — Protected / pinned paths: reason, minimal diff, approved scope, negative controls

### `app/workbook/registry.py`
* **Why protected:** Registry of every workbook field; pinned by the FIN-V2-3 cohort; `app/workbook/` is a protected namespace in the RC-UX scope guard
* **Minimal diff:** Adds exactly the two contractual DSCR INPUT fields (`debt.contract.min_dscr_eod`, `debt.contract.contractual_dscr`) in a new "Contractual DSCR terms" section and the section reference on the Senior Debt sheet; no existing field, bound, version or default changes
* **Approved scope:** §0A "existing versioned financing/covenant/project-term model and authorized Save writer"; V3 §1 (exactly two inputs)
* **Tests / negative controls / pins:** test_wf04_scope::test_registry_change_is_the_two_contract_fields_and_the_sheet_line_only; test_wf04_run_bound_terms (registration, writer, bounds); drift/delete of the owned bytes; fin_v2_3 pin re-pinned with history

### `app/persistence/workspace_repository.py`
* **Why protected:** Run-commit transaction (`v2_atomic_run_commit`); historical authority asserted unchanged by the FIN-V2-3 and FIN-V2-R1 cohort tests
* **Minimal diff:** One additive 12-line hunk inside `v2_atomic_run_commit` that records the draft's two DSCR terms in that Run's immutable `last_runtime_identity["dscr_contract_terms"]`; fail-closed (ROLLBACK + `V2RunCommitConflictError`); no existing line changed
* **Approved scope:** §0A "Run materialisation / persisted immutable Run-bound evidence"
* **Tests / negative controls / pins:** test_wf04_scope::test_workspace_repository_change_is_one_additive_hunk_inside_the_atomic_run_commit_only (removing the hunk gives the accepted file line-for-line); test_wf04_run_bound_terms; parity P2 (financial blobs raw-identical)

### `frontend/src/app/FinancialOverview.tsx`
* **Why protected:** Pinned by the WS1 (wsv2_core) cohort
* **Minimal diff:** Adds the "Open Debt Metrics" link and the INCOMPLETE-integrity notice; no figure or status logic changes
* **Approved scope:** §0A "existing frontend/src/app components for Financial Overview, Results, Financing, Credit"
* **Tests / negative controls / pins:** wsv2_core pin re-pinned with history; browser test `test_overview_results_and_credit_link_to_the_same_view_without_a_document_reload`

### `frontend/src/app/FinancialResults.tsx`
* **Why protected:** Pinned by the WS1 cohort and by the WS1 presentation dictionary
* **Minimal diff:** Widens the integrity status type to `string`, adds the FAIL sentence and the Debt Metrics link; no calculation
* **Approved scope:** §0A (as above)
* **Tests / negative controls / pins:** presentation_successor lineage in three governance tests; browser tests

### `frontend/src/app/workflow/WorkflowBar.tsx`
* **Why protected:** Pinned by the WS1 cohort
* **Minimal diff:** Copy change only: "Run committed. Results come from the saved Run only. Check Run Integrity and Credit findings before relying on them."
* **Approved scope:** §0A (low-DSCR addendum: a Run that completes with DSCR < 1.00x must not read as a failure)
* **Tests / negative controls / pins:** wsv2_core pin re-pinned with history; browser test

### `static/react/finco-react.js`
* **Why protected:** Jointly owned compiled bundle; pinned by the WS1 cohort and the WS1 presentation dictionary
* **Minimal diff:** Rebuilt once from the committed sources (`npm ci` + `npm run build`, byte-reproducible)
* **Approved scope:** §0A "one jointly owned bundle rebuild and pin reconciliation"
* **Tests / negative controls / pins:** presentation_successor lineage; clean rebuild equality check

### `static/react/finco-react.css`
* **Why protected:** as above
* **Minimal diff:** as above
* **Approved scope:** §0A
* **Tests / negative controls / pins:** as above

### `tests/fin_v2_cohorts.py`
* **Why protected:** Registry of exact-source cohorts; pinned by FIN-V2-R1 and WS1
* **Minimal diff:** Adds `tests.wf04_scope` to `COHORT_MODULES`
* **Approved scope:** §0A "exact-source cohort registries"
* **Tests / negative controls / pins:** test_wf04_scope::test_absent_or_unregistered_cohort_cannot_be_silently_omitted

### `tests/wsv2_core_scope.py`
* **Why protected:** WS1 cohort module; pinned in its own manifest
* **Minimal diff:** Adds `WF04_SUCCESSOR_REPIN` (named predecessor re-pins only) and `_successor_allows` (a path owned by the closed WF-04 cohort is that cohort's exact-blob responsibility; a missing/altered cohort widens nothing)
* **Approved scope:** §0A "legitimate source successor lineage, explicit path ownership and negative controls, not blanket allowlists"
* **Tests / negative controls / pins:** test_wf04_scope::test_historical_record_or_unnamed_repin_cannot_be_resealed[*]; test_wsv2_core_scope (all)

### `tests/test_wsv2_core_scope.py`
* **Why protected:** WS1 cohort tests
* **Minimal diff:** (1) the WS1-diff test is bounded to the accepted WS1 merge; (2) predecessor-pin test exempts only the named WF-04 re-pins; (3) the presentation-dictionary test accepts the WF-04 pinned later state for three paths
* **Approved scope:** §0A "protected acceptance nodes… before/after assertion review"
* **Tests / negative controls / pins:** see section 3

### `tests/test_fin_v2_3_scope.py`
* **Why protected:** FIN-V2-3 cohort tests
* **Minimal diff:** `test_native_and_historical_financial_authorities_are_not_rewritten`: `workspace_repository.py` is accepted only at the exact WF-04-pinned blob
* **Approved scope:** §0A
* **Tests / negative controls / pins:** see section 3

### `tests/test_fin_v2_r1_scope.py`
* **Why protected:** FIN-V2-R1 cohort tests
* **Minimal diff:** same exception as above
* **Approved scope:** §0A
* **Tests / negative controls / pins:** see section 3

### `tests/test_rcm_governance.py`
* **Why protected:** RC-M governance test; pinned by four manifests
* **Minimal diff:** Layer test accepts the WF-04 pinned later state for three presentation paths
* **Approved scope:** §0A
* **Tests / negative controls / pins:** see section 3

### `tests/test_rcux_governance.py`
* **Why protected:** RC-UX governance test; pinned by the WS1 manifest
* **Minimal diff:** (1) "touches no protected path" test exempts exactly `app/workbook/registry.py` and `app/workbook/dscr_contract_terms.py` at their pinned blobs; (2) layer test accepts the WF-04 later state for three presentation paths
* **Approved scope:** §0A
* **Tests / negative controls / pins:** see section 3

### `tests/test_model_workspace_consolidation_browser.py`
* **Why protected:** Existing mandatory Chromium role (the only place the repository lets browser acceptance live without a new collection-time skip); pinned by the WS1 cohort and constrained by `test_wsv2_core_scope::browser_contract_ok`
* **Minimal diff:** Appends one additive block: a comment and `from tests.model_react_wf04_debt_metrics_acceptance import *` (the 11 Debt Metrics browser tests; the helper has no skip, no autouse and is never collected on its own)
* **Approved scope:** §0A "CI-selected mandatory-browser evidence"; CI V3 collection governance (a standalone browser module added a collection skip and failed `safety-and-smoke / plan`)
* **Tests / negative controls / pins:** test_wf04_scope::test_browser_acceptance_is_an_additive_import_in_the_existing_role_with_no_skip_of_its_own and `…role_import_block_cannot_be_widened`; `test_wsv2_core_scope::test_browser_registration_preserves_original_role_and_exact_new_exports`

### `tests/test_model_mutation_security_successor.py`
* **Why protected:** D-029 security-successor tests; pinned by the FIN-V2-3, D-01/D-02 and WS1 manifests
* **Minimal diff:** `test_d029_browser_wrappers_are_exactly_the_seven_reviewed_cases_and_extras_are_refused`: the role file may equal the WS1 pinned state OR exactly the WF-04 pinned state (`presentation_successor`); the seven wrapper-name, extra-wrapper and skip negative controls are unchanged
* **Approved scope:** §0A (protected acceptance nodes)
* **Tests / negative controls / pins:** see section 3

### `tests/model_react_rcm_financing_acceptance.py`
* **Why protected:** RC-M Financing real-Chromium acceptance body (run by the mandatory consolidation role); pinned by the WS1 cohort
* **Minimal diff:** `test_financing_workspace_has_the_six_sections_with_authority_and_closed_structures_stated`: the expected tab list gains exactly one entry, `Debt metrics`, after `Overview` (the node id is unchanged)
* **Approved scope:** §0A / CI-A (the previous exact head was RED in the mandatory role for exactly this reason)
* **Tests / negative controls / pins:** see section 3

### `tests/test_model_workspace_productivity_v1.py`
* **Why protected:** Workspace field-editor DOM golden; pinned by the FIN-V2-3 manifest; it enumerates every registry field of the sheets under test
* **Minimal diff:** `test_macro_output_matches_the_base_commit_except_three_additive_attributes`: the four presentations (editable/protected × two fields) of the two new `debt.contract.*` inputs are added as a separately hash-locked `contract_additions` set, exactly like the existing FIN-V2-3 valuation field; the set equality now includes them
* **Approved scope:** §0A (protected acceptance nodes) - the hermetic CI worker 4 of the previous head failed on exactly this node
* **Tests / negative controls / pins:** see section 3

### `tests/test_model_credit_decision_v3_real_runs.py`
* **Why protected:** Real-Run credit acceptance; exact-pinned in the D-029 security-successor `BLOBS`; admitted through the WF-04 cohort pin
* **Minimal diff:** One assertion: the `CD-EOD` row of a Run with no configured floor is `NOT_CONFIGURED` (was a fixed `UNAVAILABLE` placeholder because no EoD mechanic existed)
* **Approved scope:** §0A "protected acceptance nodes whose immutable expectation must reflect this approved contract"
* **Tests / negative controls / pins:** see section 3; `test_wf04_credit_debt_metrics::test_no_terms_configured_is_not_configured_never_a_pass…`

### `tests/test_model_react_insights_v1.py`
* **Why protected:** Real-Run insights acceptance; exact-pinned in the D-029 security-successor `BLOBS`; admitted through the WF-04 cohort pin
* **Minimal diff:** `test_legacy_absent_root_identity_fields_preserve_committed_evidence[True]`: when the WHOLE identity is absent, only the Run-bound term verdicts (`debt_metrics` block, findings `CD-EOD`/`CD-COV-DSCR`) may differ, and must read `UNAVAILABLE`/`NOT_RECORDED`
* **Approved scope:** §0A (same)
* **Tests / negative controls / pins:** see section 3

### `docs/financial_validation/fin_v2_3/SOURCE_SUCCESSOR.json`
* **Why protected:** Predecessor manifest
* **Minimal diff:** Re-pins `app/workbook/registry.py`, `tests/test_fin_v2_3_scope.py`, `tests/test_rcm_governance.py`; previous map preserved under `historical_source_blobs[<BASE>]`
* **Approved scope:** §0A
* **Tests / negative controls / pins:** test_wf04_scope::test_predecessor_manifests_keep_their_base_state_except_the_named_repins

### `docs/financial_validation/fin_v2_r1/SOURCE_SUCCESSOR.json`
* **Why protected:** Predecessor manifest
* **Minimal diff:** Re-pins `tests/fin_v2_cohorts.py`, `tests/test_fin_v2_r1_scope.py`, `tests/test_rcm_governance.py` with history
* **Approved scope:** §0A
* **Tests / negative controls / pins:** same

### `docs/financial_validation/finv2_d01_d02/SOURCE_SUCCESSOR.json`
* **Why protected:** Predecessor manifest
* **Minimal diff:** Re-pins `tests/test_rcm_governance.py` with history
* **Approved scope:** §0A
* **Tests / negative controls / pins:** same

### `docs/react_migration/wsv2_core/SOURCE_SUCCESSOR.json`
* **Why protected:** WS1 manifest
* **Minimal diff:** Re-pins the three frontend files, the bundle, the two predecessor manifests it owns, the cohort registry and the WS1 cohort module/test, and the RC-UX/RC-M governance tests, with history
* **Approved scope:** §0A
* **Tests / negative controls / pins:** same

## 3 — Before/after assertion review of every edited existing test

Each edit keeps the original assertion's security/financial intent; nothing is skipped, xfailed, deleted or relaxed beyond the single named, exactly pinned exception. The exception only holds while the whole WF-04 cohort is valid (`WF04.matches` / `presentation_successor` call `valid()` = every registered cohort exact + every changed path owned).

| Test | Before | After | Why the original intent is preserved |
|---|---|---|---|
| `test_fin_v2_3_scope::test_native_and_historical_financial_authorities_are_not_rewritten` | for six paths, current bytes == bytes at the cohort base | identical, except `app/persistence/workspace_repository.py` may equal the exact WF-04-pinned blob | the other five paths still must equal the base; the one exception is one pinned additive hunk proven by `test_wf04_scope` |
| `test_fin_v2_r1_scope::test_native_and_historical_financial_authorities_are_not_rewritten` | same, eight paths | same single exception | same |
| `test_rcux_governance::test_the_rcux_changes_touch_no_protected_financial_security_or_ci_path` | no changed path under `app/workbook/` etc., one prior pinned exception (`run_intent_service.py`) | adds a second pinned exception: exactly `registry.py` and `dscr_contract_terms.py` at WF-04 blobs | every other `app/workbook/` path still fails the test |
| `test_rcux_governance::test_layer_is_a_subset…`, `test_rcm_governance::test_layer_is_exactly_six…`, `test_wsv2_core_scope::test_original_presentation…` | current bytes of a presentation path == the WS1 state | `== WS1 state` **or** `presentation_successor(path)` (three paths only, exact WF-04 pin) | any other byte still fails; the historical dictionaries remain immutable and individually admitted |
| `test_financing_workspace_has_the_six_sections_with_authority_and_closed_structures_stated` (in `model_react_rcm_financing_acceptance.py`) | the `[role=tab]` list `==` the six original tab names | the same list with one inserted entry `Debt metrics` after `Overview`; every other assertion of the node (authority text, closed structures, senior terms, tab navigation, reload) is unchanged | the original intent - the Financing workspace shows exactly its governed sections in a fixed order, no silent extras - is kept: the one new section is the Owner-approved Debt Metrics view |
| `test_model_workspace_productivity_v1::…test_macro_output_matches_the_base_commit_except_three_additive_attributes` | the set of rendered field presentations `==` golden hashes ∪ financing additions ∪ valuation additions | `==` the same ∪ **four** new, individually sha256-locked presentations of the two `debt.contract.*` inputs (the assertion that each equals its pinned hash is added) | no historical DOM hash changes (`drifted` check unchanged); the new fields are additions locked by value, not allowed by wildcard |
| `test_model_credit_decision_v3_real_runs::test_real_run_renders_credit_evidence_with_explicit_classification` (4 params) | `CD-EOD` status `== "UNAVAILABLE"` | `== "NOT_CONFIGURED"` | the intent — a Run with no configured floor never shows PASS/TRIGGERED and assumes no default — is kept and made stricter; the classification assertion on the same row is unchanged |
| `test_model_react_insights_v1::test_legacy_absent_root_identity_fields_preserve_committed_evidence[True]` | payload with the identity removed `==` payload with identity | `==` after removing only the Run-bound term verdicts, which must read `UNAVAILABLE`/`NOT_RECORDED` | the Run-bound terms live in the identity by design (never read from the Working Copy); every other byte — metrics, identity, evidence — is still compared. The `[False]` parameter (root fields removed, terms kept) is unchanged and still requires full equality |
| `test_model_mutation_security_successor::test_d029_browser_wrappers_…` and `test_wsv2_core_scope::test_correction_e_d029_role_pin_is_additive_…` | the role module blob `==` the WS1 pinned state | `==` the WS1 state **or** `presentation_successor(role)` (exact WF-04 pin, whole cohort valid) | the wrapper-name list, extra-wrapper and `@pytest.mark.skip` negative controls are untouched and still fail on any extra/skipped wrapper |
| `test_wsv2_core_scope::browser_contract_ok` (used by `test_browser_registration_preserves_original_role_and_exact_new_exports`) | after the WS1 marker the role module contains exactly the WS1 import line | exactly the WS1 import line, optionally followed by exactly the WF-04 block `ROLE_IMPORT_BLOCK` | every original negative control still holds (removed line, duplicated line, missing/skipped export all fail); any other trailing content fails |
| `test_wsv2_core_scope::test_ws1_diff_has_no_financial_run_integrity_or_ws2_source_change` | `git diff BASE` (to the working tree) has no financial/persistence/workbook/service/editing path | the diff is bounded to the accepted WS1 merge `b76ac65c…` | the test judges WS1's own diff, exactly what it was written for; WF-04's own diff is judged by `test_wf04_scope` (no engine/core/domain/CI/Save-All/writer/security path) |
| `test_wsv2_core_scope::test_predecessor_manifest_pins_and_metadata_remain_verbatim` | every non-React pin in the predecessor manifests equals its authorization-head value | same, except the named `WF04_SUCCESSOR_REPIN` pins | `test_wf04_scope::…named_repins` pins each moved value to the WF-04 pin and the real bytes; `historical_source_blobs` keeps the previous map |

## 4 — Snapshot / identity effects

* Run identity gains one additive key (`dscr_contract_terms`, schema `FINCO_DSCR_CONTRACT_TERMS_V1`). Old Runs, snapshots and signatures remain valid; they simply lack the key (`NOT_RECORDED`).
* `WORKBOOK.version` is unchanged (`2.3.0`); the two fields enter a project's input identity only once saved (parity P4: no existing Last Run turns STALE by deployment).
* No financial blob, period vector or Integrity-evidence digest changed (parity P1/P2).

## 5 — Oracle and CI gates

Oracle/parity: `INDEPENDENT_ORACLE_AND_PARITY.md`. Test outcomes with provenance: `WF04_ACCEPTANCE_MATRIX.md`. Exact-head CI is recorded in the PR once it has run.

