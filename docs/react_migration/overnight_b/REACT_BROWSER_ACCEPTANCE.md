# Real-Chromium acceptance (Overnight B)

Harness: the repository's existing mandatory browser role — `tests/test_model_workspace_consolidation_browser.py`, Playwright
1.63.0 + Chromium 153 (`/opt/pw-browsers`), live uvicorn server on a temporary SQLite database, `FINCO_MODEL_REACT_V1=1`,
`FINCO_MODEL_EXECUTION_MODE=thread` (the suite default). Every project is a disposable Working Copy made by
`create_reference_seeded_project`; no deployed or staging system was touched.

## Counts (local, exact)

| Run | Result |
|---|---|
| Baseline, unmodified main, selected React subset (before any change) | 42 passed, **1 failed** (`test_d029_react_run_intent_acceptance[check_react_run_sends_a_uuid_intent_and_consumes_it_on_commit]`: `Page.wait_for_function … reading 'disabled'`); the same node then passed 4/4 alone on the same tree → pre-existing ordering race, not caused by this work |
| **Final, whole consolidation file, this PR's tree** | **106 passed, 0 failed, 0 skipped** in 533 s (80 pre-existing nodes + 26 new `test_onb_*`; JUnit `final-browser.xml`) |
| The 7 D-029 Chromium nodes (4 React + 3 Legacy) | all passed, unchanged |
| Negative control: the 26 new nodes against the **original** `main` bundle | 24 failed, 2 passed (the two that pass assert behaviour that was already correct: scalar Save persistence and protected-reference read-only); i.e. the new tests are not vacuous |

Pre-existing node ids: none removed or renamed (`test_d029_browser_original_node_ids_are_preserved` + governance test). Existing tests whose
assertions had to follow an intended UI change (node ids unchanged, intent kept or strengthened): Run identity text
(`snapshot_id[:12]` → contract text + exact `data-run-identity` binding), scenario compare field cell (`tariff_eur_mwh` text →
`data-compare-field` attribute), `page.url.split("?")[0]` → `urlsplit(page.url).path` (the URL no longer gets a query), the
unavailable-metric card text kept (`Not produced by this Run: <source>`).

## The brief's 20 acceptance items

| # | Item | Test node(s) |
|---|---|---|
| 1 | Solar Working Copy | `test_mvp_internal_path_with_financial_intelligence[solar]`, all `test_onb_*[solar]` |
| 2 | Wind Working Copy | `test_mvp_internal_path_with_financial_intelligence[wind]`, `test_onb_statement_identity…[wind]`, `test_onb_returns_lender…[wind]` |
| 3 | Data Center preview | `test_onb_returns_lender_metrics_and_vertical_scope_are_truthful[data_center]`, labels `[data_center]`, diagnostics `generic_data_center_reference` |
| 4 | EV Charging preview | same, `[ev_charging]` |
| 5 | Statement identity without query | `test_onb_statement_identity_is_the_authorized_project_in_every_vertical[×4]` |
| 6 | Malicious / stale query identity | `test_onb_hostile_or_stale_query_cannot_change_the_statement_identity` |
| 7 | Two Runs within the same hour | `test_onb_two_runs_in_the_same_hour_are_distinguishable_everywhere`, `…scenario_comparison_and_results_refer_to_the_intended_run` |
| 8 | Save scope and reload | `test_onb_inputs_save_scope_language_is_accurate`, `test_onb_scalar_save_persists_after_reload_and_never_saves_another_editor`, `test_wf2_end_to_end_supported_workflow_save_never_runs…` |
| 9 | Protected reference behaviour | `test_wf2_protected_reference_workspace_is_read_only_in_every_editor`, `test_onb_protected_reference_inputs_stay_visible_and_read_only`, `…protected_reference_grid_cannot_stage_or_save` |
| 10 | React D-029 lost-response and replay | `test_d029_react_run_intent_acceptance[×4]` |
| 11 | Current / Stale / Not Run | `test_current_stale_not_run_are_consistent_across_every_surface` |
| 12 | Scenario creation and comparison | `test_wf2_scenario_selection_compare_and_overrides…`, `test_mvp_internal_path…`, `test_onb_scenario_override_boundary_matches_the_canonical_capability` |
| 13 | Desktop navigation | `test_onb_workspace_navigation…` (1440 and 768), `test_responsive_layout_has_no_page_level_horizontal_overflow[desktop]` |
| 14 | Mobile 320/390 navigation | `test_onb_workspace_navigation…` (320, 390), `…responsive…[mobile]`, `test_wf2_editable_sections_fit…[390]` |
| 15 | Keyboard accessibility | nav ←/→/Home/End/Enter + focused-link-in-view at 320/390/768/1440; Inputs jump links move focus to the target; section `<summary>` toggles with Enter; Run-ID `<summary>` toggles with Enter and the Copy button is reached by Tab (tests above) + existing lifecycle tests |
| 16 | Every visual theme | `test_onb_every_theme_keeps_the_corrected_surfaces_legible` (FINCO default, Slate & Teal, High-Contrast, Forest Green / White Workbook; contrast ≥ 4.5:1 on 16 selector groups incl. the top bar; no overflow) |
| 17 | Six statement destinations | identity test clicks all six tabs per vertical |
| 18 | Unsupported financial metrics | `test_onb_returns_lender_metrics…[×4]` (unavailable ⇒ "Not available", never `0`/`—`; PLCR always unavailable; values equal the canonical API) |
| 19 | No synthetic fallback for missing canonical data | `test_onb_missing_or_conflicting_identity_fails_visibly`, `test_product_truth_no_prototype_or_synthetic_content_in_any_section` |
| 20 | No loss of editable controls | `test_onb_inputs_are_compact_complete_and_navigable[×4]` (rendered `[data-grid-cell]` set == canonical editable set, exact) |

## Inputs page height (all editors loaded; same method before/after; px)

| Vertical | 320 | 390 | 768 | 1440 |
|---|---|---|---|---|
| Solar before → after | 16,886 → 9,179 | 15,292 → 8,601 | 13,302 → 5,789 | 11,907 → 4,920 |
| Wind | 17,145 → 9,179 | 15,554 → 8,601 | 13,428 → 5,789 | 12,007 → 4,920 |
| Data Center | 18,276 → 6,891 | 16,054 → 6,592 | 13,471 → 4,648 | 11,887 → 3,948 |
| EV Charging | 19,187 → 7,170 | 16,862 → 6,751 | 14,255 → 4,817 | 12,585 → 4,105 |

(Audit figures reproduced: 11,889 px at 1440, ~15.2k px at 390. Enforced by test limits: Solar 1440 ≤ 6,000, Solar 390 ≤ 10,000,
Data Center 390 ≤ 8,000, EV 320 ≤ 9,000.) No document-level horizontal overflow at 320/390/768/1440 on Inputs or any section.

## Other suites run locally (same tree)

* 642 passed, 2 skipped in the React/router/governance Python batch (`test_model_react_*` ×16 files, `test_react_mvp_rc_sec`,
  `test_model_mutation_security_successor`, the new `test_model_react_overnight_b_v1` and `…_governance`,
  `test_fin_val_b2_c1_recovery_finite_opex`, `test_react_main_coexistence_browser`) — see the exceptions below.
* `tests/test_trust_readiness_registry.py` + `…_claims.py`: 180 passed once the clone had full history (with the default
  shallow clone 14 failed + 16 errors **identically on unmodified main**; environment, not this change).
* `tests/test_model_react_poc_browser_acceptance.py`: 2 failures (`test_results_distinguish_current_from_stale`,
  `test_statements_results_stale_and_unknown_outcomes`: the canonical Run answers "Draft changed since page loaded") **identical on
  unmodified main**; that file is not part of any CI browser role. Not caused or hidden by this change.
* `tools/public_safety_scan.py`: `PUBLIC_REPOSITORY_SAFETY_SCAN_PASS`.
* `npm run typecheck` (3 tsconfigs) clean; `npm run build` reproducible (same output twice).

## Screenshots

`docs/react_migration/overnight_b/screenshots/` — `before-*` (reproduced defects on main) and `after-*` (this tree): statement identity,
missing-identity alert, Data Center preview Results, Inputs 1440/390, navigation at 320, Run History with two Runs, green/white and
high-contrast themes. The mandatory role's own `prb-*.png` captures were also produced (12 files) by the unchanged evidence verifier path.

## Not covered / honest gaps

* Real-device touch and screen-reader sessions were not run; "touch targets" are measured (≥44 px) and keyboard paths are driven, not a screen reader.
* The Financial-insights credit pages were not redesigned; their existing tests ran unchanged.
* Third-party/CDN behaviour, the nginx cache (see readiness §3) and the live server are out of reach here.
