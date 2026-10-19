# RC-7B post-merge governance recovery (main green after PR #320)

Starting main: `bf0167a036a6e30d3225b901aeda1b353681171a` — merge commit of PR #320, parents `5be8c4b149712dd39b38b54c6fabcf3fcf47ef0d`
(immutable predecessor) and `e9c3326a9f8b7791cd8032102347a735c12178e4` (merged PR head). Merged through GitHub by `FincoProtocol`. The merge is
history; this change does not re-open its pre-merge authorization and creates no Financial Owner record, signature or review.

Scope: governance test infrastructure and one presentation script. **No change under `financial_engine/`, `finco_core/` or `domain/`; none of the twelve
RC-7B blobs is touched or repinned; `ACTIVATION_ENABLED` stays a literal `False`.**

## 1. Reproduced failures on `bf0167a` (current-authority guards)

Fifteen test nodes fail on a clean checkout of main, every one of them a current-authority check that still expected the pre-RC-7B blobs of the
twelve merged paths (`project_inputs.py`, `tax_inputs.py`, `generic_product_policy.py`, `project.py`, `quarterly_scope.py`, `inputs.py`,
`orchestrator.py`, `senior_debt/project_adapter.py`, `calendar_policy.py`, `period_engine.py`, `_models.py`, `serialization.py`):

| # | Node | Original assertion | Category |
|---|---|---|---|
| 1 | `test_finance_integrity_governance::test_approved_engine_paths_are_allowed` | engine paths = approved + candidates only | B |
| 2 | `test_finance_integrity_governance::test_stream_guard_exemption_covers_only_allow_listed_engine_files` | candidate paths never a released exemption | B |
| 3 | `test_financing_f3_junior_governance::test_only_fifteen_independently_accepted_blobs_are_released` | F3.5-A pins | B |
| 4 | `test_financing_f3_multisenior_governance::test_only_exact_seven_paths_at_their_pinned_content_are_authorized` | F3 multi-Senior pins | B |
| 5 | `test_m7_bess_boundaries::test_exact_candidate_manifest_is_not_a_release_and_mutations_fail` | M7 candidate blobs | B |
| 6 | `test_m7_rc3_candidate_successor::test_the_integrated_content_is_exactly_the_eleven_reviewed_blobs` | M7 eleven blobs | B |
| 7 | `test_ppa01_candidate_authority::test_exact_candidate_is_recognised_but_neither_approved_nor_released` | PPA-01 slice | B |
| 8 | `test_ppa01_candidate_authority::test_m7_eleven_blobs_are_unchanged_and_coexist_without_cross_approval` | M7/PPA-01 coexistence | B |
| 9 | `test_rc3_integration_inventory::test_the_integrated_head_is_exactly_the_documented_union_of_the_five_sources` | RC-3 union | B |
| 10 | `test_rc3_integration_inventory::test_the_merged_main_state_binds_head_to_the_pinned_candidate` | RC-3 merged state | B |
| 11 | `test_rc3_post_merge_authority_states::test_every_m7_blob_is_the_candidate_state_while_the_flags_are_closed` | M7 candidate state | B |
| 12 | `test_rc3_post_merge_authority_states::test_the_three_states_are_distinct_and_activation_is_unreachable_for_m7` | authority states | B |
| 13 | `test_rc7_quarterly_rc7a_compatibility::test_all_historical_m7_and_ppa_bytes_are_preserved_without_successors` | historical M7/PPA bytes | B |
| 14 | `test_wf04_numeric_precision_governance::test_exact_wf04_paths_and_content_only` | WF04 pin | B |
| 15 | `test_wf07_revenue_governance::test_exact_seven_content_pins_only` | WF07 pins | B |

Category A (historical authority correctly checked at its own checkpoint): none fails; every historical pin map and the original expected blobs are
kept and still asserted for every path and tree the successor does not recognise. Category C (genuine unauthorized change): none present in main.
`test_ci_acceptance::test_frozen_financial_namespaces_unmodified` and `test_finance_integrity_governance::test_this_branch_stays_within_the_governance_contract`
compare HEAD with `origin/main` and therefore pass on main itself; they are wired to the same successor so they also hold on branches that include the candidate.

## 2. The successor

`tests/rc7b_postmerge_successor.py` defines `RC7B_POSTMERGE_RELEASE_CLOSED_SUCCESSOR`. It is true only while all of the following hold; any missing fact is a rejection:

1. literal merge commit `bf0167a0…` exists, has exactly the parents (predecessor `5be8c4b1…`, PR head `e9c3326a…`) and is an ancestor of the evaluated ref;
2. the reviewed source head `4b086b83…` is an ancestor of the merged PR head;
3. the twelve protected blobs equal the pinned candidate blobs at the merge commit, at the PR head and at the evaluated ref;
4. the existing exact-content validator `content_violations` is empty: no other `financial_engine/`, `finco_core/` or `domain/` path differs from the predecessor,
   the historical authority files (`model_v2_governance.py`, `m7_rc3_candidate_successor.py`, `radar_authority_governance.py`) and the quarterly research
   reference are byte-identical to the predecessor, and `ACTIVATION_ENABLED` is a literal `False`.

| State | Result |
|---|---|
| Historical PR #320 integration | VERIFIED |
| Exact RC-7B content | VERIFIED |
| Release-closed candidate recognition | TRUE |
| Independent Financial Owner approval | FALSE |
| D-01..D-12 financial-policy approval | FALSE |
| Gate P / product admission / quarterly activation / financial release | FALSE |
| Gate R active | FALSE (pre-merge machinery unchanged and not made global) |

The module reuses `rc7b_quarterly_candidate_authority` (collect/content_violations/Gate R) without editing it. `approved_frozen_path`,
`released_engine_authority_matches` and every historical pin dictionary are untouched. The current-authority guards now ask
`rc7b_postmerge_successor.candidate_recognized / superseded / scope_exempt / current_expected_blob / without_superseded`, which accept either this
successor or (unchanged) a complete authentic Gate R. A tree that changes any of the twelve blobs — including a later RC-7C blob — is not recognised
and the original strict assertions fail exactly as before.

Negative controls (`tests/test_rc7b_postmerge_successor.py`, disposable clones): modification and removal of each of the twelve blobs; extra protected files in
all three namespaces; missing provenance; missing merge ancestry; modified historical authority maps / M7 evidence / quarterly research; `ACTIVATION_ENABLED = True`;
unrelated engine/core changes; forged acceptance and Gate R records (do not alter any state); each RC-7C-touched path substituted.

## 3. Browser failures (local, serial, exact main baseline)

The Public Safety workflow skips Playwright tests and the six mandatory GitHub browser roles do not include them, so GitHub CI never exercised them. They are reproducible on
`5be8c4b` (before PR #320) and on `bf0167a`, i.e. independent of RC-7B.

| Test | Root cause | Disposition |
|---|---|---|
| `test_rcux2_construction_timing_browser::test_the_manual_end_override…`, `test_model_project_timeline_browser::test_one_timeline_one_handler…` | **Application defect** introduced by `eccde42` (2026-10-18): a trusted edit inside Construction timing leaves the Project Setup view marked as an unsaved draft after that component saved it; the view never refreshes and its controls stay disabled with a wrong "unsaved edits" notice. | Fixed in `static/js/model_view_refresh.js` (drafts only in the timing component are cleared on `ct:saved`; edits elsewhere stay drafts). Regression test `test_rc7b_postmerge_view_refresh_browser.py` fails without the fix. |
| `test_rcux2_debt_equity_journeys_browser::test_two_investors…` | **Application defect**, same mechanism: after a successful agreement Save the Investor view stays "dirty", the next Run leaves it pending and the Reload button is blocked. | Fixed (a successful whole-form agreement save clears the Investor draft flag; cost-grid row writers keep their drafts). Existing test now passes. |
| `test_m7_bess_workflow_browser` (two nodes) | **Environment**: `chromium.launch()` without an executable; the installed Playwright 1.63 build is missing in this sandbox (`playwright install` required). Not an application defect. | No change; not reproducible as an application failure. |

No financial-engine file, browser assertion or acceptance criterion was changed or weakened.
