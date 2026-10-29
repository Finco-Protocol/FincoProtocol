# WF-04 — Acceptance matrix (PASS / FAIL / NOT RUN, with provenance)

Provenance of every "local" row: this branch, Python 3.13 venv (`requirements.txt` + pytest, pytest-xdist, playwright), Node 22.22, Chromium `chromium-1243` from `/opt/pw-browsers`,
canonical Python engine in thread mode, full git history. "Baseline" = clean `main` `b76ac65c…` in a separate worktree on the same machine. The exact-head CI result is **not** repeated in this
file (a file cannot contain its own commit): it is recorded on the PR.

## A — Owner matrix (§7)

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | Owner example: floor 1.05x, achieved < floor → one persisted completed Run, EoD `TRIGGERED`, period + persisted terms | **PASS** | `test_wf04_dscr_contract_terms::test_owner_example_floor_105_achieved_103_triggers_with_period_and_terms`; `test_wf04_credit_debt_metrics::test_owner_example_floor_above_actual_triggers_eod_on_a_completed_run…` (real committed Run, `len(history)==1`); browser `test_weak_coverage_eod_triggered_covenant_breached_and_run_completed` |
| 2 | Equality is no trigger (strict `<`, raw) | **PASS** | `…::test_equality_is_not_a_trigger`; `…::test_equality_is_not_a_trigger_and_one_ulp_below_is`; oracle boundary rows |
| 3 | Below Contractual DSCR but not below the floor → covenant breach, EoD not triggered (input-relative values) | **PASS** | `…::test_covenant_breach_without_eod_uses_input_relative_values`; `test_covenant_breach_without_eod_and_the_two_terms_stay_independent` |
| 4 | EoD condition although the model shows service fully paid → no payment-default statement | **PASS** | `…::test_eod_triggers_even_when_the_model_shows_debt_service_fully_paid_and_says_nothing_about_payment`; banned-wording scans (unit + browser) |
| 5 | Actual DSCR < 1.00x with/without a floor: high-severity shortfall + periods; no refusal; no "unprofitable" label | **PASS** (engine commit at 0.7559 proven by parity case `GEARING_CAP 0.75`; UI/Credit verdicts proven on the 0.9925 weak-coverage Run) | `…::test_coverage_below_one_is_independent_of_the_configured_terms_…`; `…::test_a_floor_below_actual_dscr_below_one_is_not_an_eod_…`; parity P1 |
| 6 | No floor / no covenant / non-finite ratio / missing period / no service / unsupported old Run → `NOT_CONFIGURED`/`UNAVAILABLE`/`NOT_APPLICABLE`, never a false PASS | **PASS** | `…::test_not_configured_unrecorded_invalid_and_unusable_inputs_are_never_a_pass`; `…partial_evidence…`; `…non_finite…`; `…period_without_service…`; `test_tampered_or_missing_evidence_withholds_every_verdict`; `test_a_run_committed_before_the_contract_is_not_recorded…`; browser `…no_terms_configured…`, `…without_a_recorded_contract…` |
| 7 | Raw 0.9951 / 0.99999 never read as 1.00x; 1.0499… below 1.05 triggers; above-threshold close case; 0→2→0 formatting does not affect hash/verdict | **PASS** | `format_ratio` tests (server + `debtMetrics.test.mjs`), `…raw_value_fractionally_below_the_floor_triggers_although_two_decimals_would_match`, ulp display test, `test_the_projection_is_a_pure_function_of_the_sealed_run_…` |
| 8 | Exact terms per history entry / project / tenant / snapshot; Working Copy edit after a Run → STALE, historical verdict unchanged; replaced Run while fetching fenced; wrong-owner denied | **PASS** (scenario: the terms are project-level by design — `ScenarioPolicy.NOT_ALLOWED` — so a per-scenario term does not exist; each Run records the terms of its own committed draft) | `test_wf04_run_bound_terms::test_a_later_edit_never_rewrites_a_historical_run_and_the_last_run_becomes_stale`; `…other_users_cannot_read_or_change_the_terms`; `test_historical_runs_keep_their_own_terms_across_edits_stale_state_and_compare`; `test_a_stranger_and_another_projects_run_never_see_or_are_judged_by_foreign_terms`; browser `test_picker_shows_each_runs_own_terms_stale_banner_and_historical_note` (stale request fencing) |
| 9 | Save All after #397 (≥50 inputs, single atomic commit/rollback, failure injection, request-id replay, reuse conflict, stale CAS, foreign CSRF, cross-tenant, Save never calls Run) | **PARTIAL / NOT RUN for the combined path.** PASS on `main` for the existing batch writer that #397's scalar cells use: atomic save, whole-batch rollback on one invalid cell, forged CSRF → 403, stale CAS → 409, Save never runs the model. **NOT RUN:** ≥50-change body, idempotency ledger / request-id replay / reuse conflict, combined UI — these exist only in #397 (open draft). | `test_wf04_run_bound_terms::test_batch_writer_*`; mapping doc §2 |
| 10 | Weak DSCR + a genuine independent arithmetic error → Integrity `FAIL` stays; missing evidence → `INCOMPLETE`; negative distribution account with `NO_UNFUNDED_CASH_DEFICIT` still FAIL | **PASS** | adversarial replay on this tree = recorded `main` verdicts for all 9 cases (parity P5); zero diff under `app/run_integrity/`; `test_h4b_run_integrity_checks.py` (passes) |
| 11 | SHL low-gearing refusal band unchanged; no POC-IV suppression, resize, shadow run, OD-R activation | **PASS** | parity P1: refusals at 0.50/0.55/0.575 identical (same code + residuals); 0.58 commits identically |
| 12 | Reserve-covered shortfall / unpaid service / maturity residual without trusted persisted inputs → `UNAVAILABLE` listing the exact missing fields | **PASS** | `test_reserve_draw_and_unpaid_service_stay_unavailable_and_name_the_exact_missing_evidence`; browser assertion on `data-dm-gaps`. The maturity residual is already judged by the untouched Integrity roll-forward check |
| 13 | Certificate behaviour unchanged | **PASS** | no certificate/export/signing module in the diff; `test_p3_run_certificate_v1.py`, `test_signed_run_certificate.py` pass; old identities lack only the additive key |
| 14 | Four technologies; live Chromium at 1440/1366/768/390; Run/Results/Overview/Credit/History/Compare, keyboard + screen-reader semantics, no Legacy navigation, no unrelated React regression | **PASS** for the Debt Metrics workspace and its four entry points (11 browser tests; 4 viewports × 4 themes: WCAG contrast ≥ 4.5, no horizontal page scroll, card layout ≤ 640 px; chart is keyboard-operable with a data table; status always text + glyph). Four technologies: `test_the_contract_is_recorded_and_projected_for_every_technology[4]`, oracle `…for_every_technology[4]`. **NOT RUN:** a manual assistive-technology (screen-reader) session. | `tests/test_wf04_debt_metrics_browser.py` |
| 15 | Regression: `QM-COV-001`, lock-up `QM-COV-002`, `QM-SD-007`, lender case, goal seek, project/multi-scenario, old Runs, Run intent, D-029, CSRF, Save All, institutional reporting | **PASS with the three reviewed expectation updates** (ledger §3) — 148 related test files run one by one (see §C); remaining failures are pre-existing on clean `main` | §C |

## B — New and changed tests

| File | Tests | Result (local) |
|---|---|---|
| `tests/test_wf04_dscr_contract_terms.py` (pure) | capture / read / evaluate / formatters, negative-control mutations | PASS |
| `tests/test_wf04_run_bound_terms.py` | registration, real writer, Run-bound capture, immutability, STALE, upgrade safety, batch writer | PASS |
| `tests/test_wf04_credit_debt_metrics.py` | real committed Runs through the real credit route | PASS |
| `tests/test_wf04_independent_oracle.py` | stdlib-only oracle vs product (threshold grid, boundary, 4 technologies) | PASS |
| `tests/test_wf04_debt_metrics_browser.py` | 11 live-server Chromium tests | PASS (11/11) |
| `frontend/src/app/debtmetrics/__tests__/debtMetrics.test.mjs` | 9 node tests | PASS (9/9); `npm run typecheck` clean |
| `tests/test_wf04_scope.py` | cohort admission, drift/delete of every owned byte (×2), forged/malformed manifests, unapproved paths, ancestry, unregistered cohort, predecessor re-pin tamper (7 variants), protected-path hunks | PASS |
| governance subset (53 files) | exact-source cohorts and successors | PASS except the 8 failures that also fail on clean `main` |

## C — Pre-existing failures (identical on clean `main` in the same environment; not caused by WF-04)

| Test | Where it fails on `main` |
|---|---|
| `test_rc7b_quarterly_csrf_successor::{test_exact_router_and_security_structure, test_inventory_requires_the_exact_successor}`, `test_rc_sec_csrf_successor::{test_exact_reviewed_run_clone_and_helper_contract, test_inventory_rejects_unproven_rc_sec_while_preserving_other_successors}`, `test_wf09_csrf_successor::test_inventory_admits_the_router_only_while_the_successor_holds` | route/CSRF-inventory tests (the trust-readiness ones report `app/v2/quarterly_calendar_router.py` as an extra item) |
| `test_trust_readiness_controls::{test_known_gap_no_product_route_deletes_user_data, test_known_gap_state_changing_posts_have_no_csrf_token}`, `test_trust_readiness_routes::test_trust_routes_are_get_only_and_exactly_the_expected_set` | same route inventory |
| `test_model_react_rcux_{credit_decision,compare,compare_projects,capex,import,credit_headroom,projects}_v1::test_router_is_mounted_before_the_project_catch_all`, `test_model_react_insights_v1::test_served_react_router_composition…`, `test_rc_institutional_workspaces_integration::test_all_three_routes_registered_once…`, `test_sc34_historical_production_wiring` (2) | route-mount inspection of the served application |
| `test_model_workspace_productivity_v1::…test_macro_output_matches_the_base_commit_except_three_additive_attributes`, `test_finval_f01_fixture_integrity::test_authority_mock_has_only_its_missing_unit_added` | unrelated to this change |
| `frontend … insights.test.mjs` (3 sub-tests: money display / metric cards / sponsor columns) | identical failure on clean `main` (insights presentation fixtures) |
| `test_model_react_rcux_goal_seek_targets_v1.py` | the file stalls at the same test (24th of the file; 23 passes first) on clean `main` **and** on this branch; neither run finished in 20+ minutes in this sandbox, so this file is **NOT RUN to completion** on either tree |
| `test_model_credit_decision_v4_render` | needs `FINCO_TEST_CHROMIUM_PATH` in this sandbox (browser binary path), environment only |

## D — NOT RUN (stated, not implied)

* Native V10/V11 arms, 183-case catalogue (`runtime_compilation_authorized: false`).
* Combined Save All + Debt Metrics in one browser (needs #397 merged): `save_all` request-id/idempotency tests, ≥50-input body, combined-UI keyboard flow.
* Manual screen-reader pass.
* Signed-certificate regeneration; any production/staging action.
* Original workbook bytes: "V3 forensic report supplied; original workbook not independently rechecked."
