# TEST_EVIDENCE.md — G10/D8 Draft PR: what was run, what passed, what is deferred to CI

Environment: local Windows clone, Python 3.12, repo-pinned deps (`pip install -r requirements.txt -c constraints.txt`), disposable per-module test databases via the repo's own app fixture. Working tree normalized to LF (`core.autocrlf=false` + raw re-checkout) so local byte-pins are meaningful. Linux CI remains the authoritative byte-equality environment.

## 1. New tests (this PR) — all PASS locally

Command: `python -m pytest tests/test_g10_d8_opex_completion.py tests/test_g10_d8_scope.py -p no:pytest_ethereum -q`
Result: **18 passed** (14 oracle + 4 governance).

| Test | Tier / label | Verifies |
|---|---|---|
| `test_k1_two_percent_escallation_matches_exact_decimal` | Kernel, SYNTHETIC_ONLY | 100→Y2 102 / Y3 104.04 / Y5 108.243216 / **Y10 119.509256862231** (NUMERIC_ERRATA E1 #1) |
| `test_k2_zero_escalation_is_flat…` | Kernel | 0% flat over 20y (new-line default) |
| `test_k3_step_is_a_new_sustained_base…` | Kernel | step Y5=120 sustained; **Y10 132.489696384** (E1 #2) |
| `test_k4_negative_rates_never_go_below_zero` | Kernel | −50% clamped ≥ 0 |
| `test_k6_construction_and_nonpositive_years_are_zero` | Kernel | t≤0 ⇒ 0 |
| `test_t2_solar_all_in_full_year_sums_match_the_corrected_oracle` | T2, SYNTHETIC_ONLY | solar fixed sum **380.0**; Y5 **411.324220800**; Y20 **553.588245560563** (E1 #3/#4) |
| `test_t2_data_center_fixed_six_items_total_9700_excluding_driver_row` | T2 | DC fixed six items **9700.0** (E1 #5), Power Expenses excluded |
| `test_d8_escalation_sources_have_no_project_wide_input` | D8 | factory rates 2%; DC driver row rate 0% |
| `test_g10_endpoint_requires_flag_session_and_project` | T3 | typed refusals (401/404), never data |
| `test_g10_no_run_is_not_run_never_zero` | T3 | `NOT_RUN`, `run: null`, empty periods — never zeros |
| `test_g10_run_projection_passes_through_the_committed_run_evidence` | T3, one canonical Run | status OK; pass-through equality cell-by-cell vs `model_run_history` P&L; construction periods exactly 0.0; freshness CURRENT right after Run; no full-year-vs-period equation (T1 qualification honored) |
| `test_g10_second_run_appends_and_first_evidence_is_untouched` | T3 | new history id per Run; prior row still readable (immutability) |
| `test_d8_false_project_wide_escalation_copy_is_gone_and_truthful_copy_present` | D8 source pin | old false string absent; truthful copy present; CostLineManager correct copy intact |
| `test_g10_endpoint_module_has_no_writer_surface` | Governance | GET-only endpoint; registration present |
| `test_cohort_is_registered_and_exact` / `test_every_owned_path…` / `test_one_altered_byte…` / `test_new_financial_or_stream_paths…` | Cohort | closed G10/D8 cohort exact; drift fail-closed; stream paths never admitted |

## 2. Touched-surface regression guards — PASS locally

- `tests/test_u2_opex_lines.py` (U2 OPEX Years, 4 verticals): **PASS** (8/8) — my changes did not alter U2 behavior.
- Cohort exactness after the governed successor re-pins — all exact, registry **valid: True**:
  `tests.g10_d8_scope` ✓ · `tests.u2_scope` ✓ · `tests.u1_scope` ✓ · `tests.post413_r17_scope` ✓ · `tests.post413_r18_scope` ✓ · `tests.post413_r1_scope` ✓ · `tests.ci_v4_scope` ✓ (verified programmatically; the scope test files re-run in the final background batch).
- React build: `npm ci` + `npm run build` — typecheck (all three tsconfigs) + vite build **PASS**; bundle shipped to `static/react/` and re-pinned.
- The manifest-repin coordination itself is proven by the registry: `tests.fin_v2_cohorts.valid() == True` with all 20 cohorts exact.

## 3. Known-slow nodes excluded from the local batch (bounded budget rule)

`tests/test_rcux_governance.py::test_the_rcux_changes_touch_no_protected_financial_security_or_ci_path`, `::test_layer_is_a_subset…`, `::test_the_wf03_ci_workflow_successor_is_exact_path_and_exact_blob_only` (≈30+ min locally; unchanged by this PR; covered by hosted CI on the Draft PR). A first full local batch was stopped at the ~45-min mark per the bounded-budget rule; no result from it is claimed. **No unexecuted test is marked PASS.**

## 4. Explicitly NOT claimed

- No live Excel numeric parity (UNUPPORTED/NOT_COMPARABLE — independent oracle not run on authenticated Runs).
- No engine-behavior change is asserted or implied; the one canonical Run used in tests is the existing route's own output.
- Chromium browser check: NOT_RUN locally (no browser harness in this environment); the existing `tests/u2_browser_role.py` harness covers the Years view on CI and my panel reuses its conventions — flagged for the owner as the one locally-unexecuted acceptance.
- The full 20k-node CI was NOT triggered locally; the Draft PR's own CI run is the hosted gate.
