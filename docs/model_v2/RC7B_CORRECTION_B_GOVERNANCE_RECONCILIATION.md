# RC-7B Correction B - governance reconciliation (source-proven classification)

Measured on `b19a1f01` (the head before the governance edit) by running the 40 test modules that reference frozen paths, authority
blobs or main-relative diffs in a clean detached worktree: **74 failures in 40 modules**. This is a local run of the
governance-relevant modules, not the complete Public Safety job; the exact-head CI result of the complete job is authoritative.

The protected diff against main is exactly twelve paths: `financial_engine/adapters/project_inputs.py`, `adapters/tax_inputs.py`,
`financing/generic_product_policy.py`, `financing/project.py`, `financing/quarterly_scope.py`, `inputs.py`, `orchestrator.py`,
`senior_debt/project_adapter.py`, `finco_core/engine/calendar_policy.py`, `engine/period_engine.py`, `inputs/_models.py`, `inputs/serialization.py`.

## A. Historical-checkpoint assertion: corrected (1)

`tests/test_rc7_quarterly_research_isolation.py::test_protected_production_tree_and_historical_guards_are_exact_main` stated PR #313's
isolation claim (the research candidate changed no production path) but compared the moving HEAD with the #313 base `78e4c0ed`. The claim is
judged at its own immutable checkpoint: `78e4c0ed` is an ancestor of the #313 merge `5be8c4b1`, which is an ancestor of HEAD, and
`git diff 78e4c0ed 5be8c4b1` over the protected paths is empty; the research-only `financial_engine/quarterly/*` files do not exist at
`5be8c4b1`. The corrected test asserts exactly that. It allow-lists no path and does not touch any other guard.

## B. Current production-authority assertions: remain blocking (73)

All other failures assert that HEAD's protected blobs, or the diff against current main, equal the pinned released or candidate authority.
The twelve RC-7B paths differ, so these guards are *correctly* rejecting a change no independent financial reviewer has authorized. They are
not mis-anchored: none compares against a fixed historical SHA (checked: only the corrected guard and the RC-3 inventory use fixed SHAs, and
the RC-3 inventory binds the post-merge HEAD blobs to the pinned M7 candidate, a current-state claim).

### M7 / WF07 / PPA-01 / RC-3 exact-content authority (HEAD blob must equal pinned candidate)

- `tests/test_m7_rc3_candidate_successor.py`: `test_the_integrated_content_is_exactly_the_eleven_reviewed_blobs`, `test_extra_unlisted_and_partial_changes_are_rejected`, `test_a_complete_independent_record_is_required_and_each_defect_is_rejected`
- `tests/test_m7_bess_boundaries.py`: `test_exact_candidate_manifest_is_not_a_release_and_mutations_fail`
- `tests/test_ppa01_candidate_authority.py`: `test_exact_candidate_is_recognised_but_neither_approved_nor_released`, `test_m7_eleven_blobs_are_unchanged_and_coexist_without_cross_approval`, `test_release_is_blocked_without_a_complete_independent_record_and_each_defect_is_rejected`, `test_the_real_anchor_returns_to_head_after_integration_and_keeps_historical_proof`
- `tests/test_wf07_revenue_governance.py`: `test_exact_seven_content_pins_only`, `test_m7_candidate_is_exact_content_release_closed_and_never_inherits_released_authority[financial_engine/adapters/project_inputs.py]`, `test_m7_candidate_is_exact_content_release_closed_and_never_inherits_released_authority[financial_engine/orchestrator.py]`
- `tests/test_rc3_integration_inventory.py`: `test_the_integrated_head_is_exactly_the_documented_union_of_the_five_sources`, `test_the_merged_main_state_binds_head_to_the_pinned_candidate`
- `tests/test_rc3_post_merge_authority_states.py`: `test_the_three_states_are_distinct_and_activation_is_unreachable_for_m7`, `test_every_m7_blob_is_the_candidate_state_while_the_flags_are_closed`

### F3 / F3.5 / WF04 pinned-blob contracts

- `tests/test_financing_f3_junior_governance.py`: `test_only_fifteen_independently_accepted_blobs_are_released`
- `tests/test_financing_f3_multisenior_governance.py`: `test_only_exact_seven_paths_at_their_pinned_content_are_authorized`, `test_any_edit_to_a_pinned_file_loses_approval[financial_engine/financing/generic_product_policy.py]`, `test_any_edit_to_a_pinned_file_loses_approval[financial_engine/financing/project.py]`, `test_any_edit_to_a_pinned_file_loses_approval[financial_engine/senior_debt/project_adapter.py]`, `test_any_edit_to_a_pinned_file_loses_approval[finco_core/inputs/_models.py]`, `test_any_edit_to_a_pinned_file_loses_approval[finco_core/inputs/serialization.py]`
- `tests/test_wf04_numeric_precision_governance.py`: `test_exact_wf04_paths_and_content_only`, `test_any_further_edit_loses_authorization[financial_engine/financing/project.py]`

### Live financial-integrity / frozen-path governance

- `tests/test_finance_integrity_governance.py`: `test_approved_engine_paths_are_allowed`, `test_this_branch_stays_within_the_governance_contract`, `test_stream_guard_exemption_covers_only_allow_listed_engine_files`
- `tests/test_ci_acceptance.py`: `test_frozen_financial_namespaces_unmodified`
- `tests/test_m3_two_driver_sensitivity.py`: `test_no_engine_or_financial_authority_files_are_touched`
- `tests/test_parallel_stream_frozen_diff.py`: `test_ce_real_repo_guards_green_against_current_main`
- `tests/test_model_v2_cost_templates.py`: `test_revenue_and_engine_files_untouched`
- `tests/test_model_v2_cost_templates_cd.py`: `test_cd_revenue_and_engine_files_untouched`
- `tests/test_model_v2_revenue_runtime_parity.py`: `TestNoFrozenDiff::test_zero_frozen_and_unauthorized_changes`
- `tests/test_model_v2_assumption_trace_references.py`: `test_no_frozen_namespace_touched`
- `tests/test_p0a_model_execution.py`: `test_frozen_engine_and_core_are_untouched_by_this_stream`
- `tests/test_p1_2_xlsx_export_reconciliation.py`: `test_xlsx_frozen_namespace_no_financial_engine_changes`, `test_finco_pr98_correction_a_true_xlsx_reconciliation_complete`, `test_finco_pr98_correction_b_persisted_xlsx_authority_complete`, `test_finco_pr98_correction_c_final_xlsx_lineage_complete`
- `tests/test_p1_3_institutional_validation.py`: `test_p1_3_frozen_namespace`, `test_finco_p1_3_institutional_validation_pack_complete`
- `tests/test_p3_run_certificate_v1.py`: `TestFrozenNamespaces::test_financial_engine_not_modified`

### Per-stream zero-diff guards on `financial_engine/` and `finco_core/` (crypto, RWA, tokenized, yield, radar, market bridge, data center, staging/public product truth)

- `tests/test_crypto_p0_product_reality_reset.py`: `test_frozen_namespaces_zero_diff[financial_engine]`, `test_frozen_namespaces_zero_diff[finco_core]`
- `tests/test_crypto_roadmap_q4_q1.py`: `test_frozen_authority_namespaces_unchanged_from_canonical_base`
- `tests/test_data_center_a3_1.py`: `test_DC_A3_ZERO_DIFF_FINANCIAL_ENGINE`, `test_DC_A3_ZERO_DIFF_FINCO_CORE`
- `tests/test_model_market_bridge.py`: `TestFrozenAuthorities::test_zero_diff_vs_main[financial_engine]`, `TestFrozenAuthorities::test_zero_diff_vs_main[finco_core]`
- `tests/test_multi_source_evidence_v2.py`: `test_frozen_namespaces_have_zero_diff[financial_engine]`, `test_frozen_namespaces_have_zero_diff[finco_core]`
- `tests/test_public_product_truth_sync.py`: `TestFrozenAuthoritiesZeroDiff::test_financial_engine_zero_diff`, `TestFrozenAuthoritiesZeroDiff::test_finco_core_zero_diff`
- `tests/test_radar_crypto_surface_coherence.py`: `test_authorities_have_zero_diff[financial_engine]`, `test_authorities_have_zero_diff[finco_core]`
- `tests/test_radar_r3_deepstate_composition.py`: `test_no_frozen_namespace_delta_on_branch`
- `tests/test_radar_r4_tokenized_monitor_v2.py`: `test_no_frozen_financial_venue_or_collector_authority_changed`
- `tests/test_radar_tokenized_signal_lifecycle.py`: `test_frozen_namespaces_and_parallel_r4_isolation`
- `tests/test_rwa_integrity.py`: `TestFrozen::test_zero_diff[financial_engine]`, `TestFrozen::test_zero_diff[finco_core]`
- `tests/test_staging_product_truth.py`: `TestFrozenAuthorities::test_zero_diff_vs_main[financial_engine]`, `TestFrozenAuthorities::test_zero_diff_vs_main[finco_core]`
- `tests/test_stock_token_oracle_rejection.py`: `TestFrozen::test_zero_diff[financial_engine]`, `TestFrozen::test_zero_diff[finco_core]`
- `tests/test_tokenized_access_wiring.py`: `test_frozen_namespaces_zero_diff[financial_engine]`, `test_frozen_namespaces_zero_diff[finco_core]`
- `tests/test_tokenized_live_intelligence_v1.py`: `TestDeploymentContract::test_frozen_namespaces_zero_diff[financial_engine]`, `TestDeploymentContract::test_frozen_namespaces_zero_diff[finco_core]`
- `tests/test_tokenized_markets_composition.py`: `TestFrozen::test_zero_diff[financial_engine]`, `TestFrozen::test_zero_diff[finco_core]`
- `tests/test_yield_alerts_core.py`: `TestFrozenAuthorities::test_zero_diff_vs_main[financial_engine]`, `TestFrozenAuthorities::test_zero_diff_vs_main[finco_core]`

None of these was edited, relaxed, re-pinned or allow-listed. The Correction A removal of unreviewed exemptions stands.

### Not a governance assertion
`tests/test_golden_flow_correction_b.py::test_active_scenario_override_stays_stale_on_reopen_and_first_run_succeeds` failed in the
multi-module local run (`calls == 1` observed 5) and passes alone (3 of 3). It is order-dependent in this selection; the exact-head complete
CI job is the authority for it. No change was made.

## Which are technically correctable and which need an external decision

- Technically corrected here: 1 (section A).
- Needs an external approval decision: all 73 of section B. Two routes exist and both belong to the financial owner: an independent
  successor review that authorizes the exact twelve blobs (updating the pins through the reviewed successor mechanism), or removing the
  twelve protected changes from this branch. Neither can be self-approved.
- The twelve-blob successor candidate inventory (`tests/rc7b_quarterly_candidate_authority.py`) is unchanged: no reviewed source change to
  those twelve paths was made in Correction B (the corrections are in `app/`, the Credit V4 projection and tests only).
