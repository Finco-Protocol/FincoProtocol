# ON-07 gap register — UPDATED COPY (post-#399 main db504f6; #400 still Draft 21d3ad8)
**Derived from `ON07_REACT_LEGACY_GAP_CHECKLIST.md` (package sha256 in FIXTURE_PROVENANCE.md). Only the Expected column was annotated. OBSERVED_REACT / OBSERVED_LEGACY / OBSERVED_COMPETITOR / State / Evidence are EMPTY by design — no browser evidence exists. Do not read any tag as an observation.**
Tags: `[TESTABLE_WITHOUT_#400]` can run on current main once deployed; `[DEPENDS_ON_#400]` needs #400 merged+deployed; `[REVERIFY_AFTER_#400]` area modified by #400 (wizard/Library) so re-check expectations. Count note: the README says 36 UX checks; this register has 39 A-F checks + 5 G negatives = 44 rows — reconcile with the owner before reporting "36 of 36".

# ON-07 — React vs Legacy Browser UX Gap Checklist

**Status:** PREPARED — NO OBSERVATIONS RECORDED. Every observation column is intentionally empty.
**Repo baseline:** `main` @ `8a74fcb5cd57e470cf83a458bd165ea14ad394fb`. Legacy acceptance baseline is
separately frozen in the repo at `docs/react_migration/ux00_legacy_baseline_manifest.md` (legacy `main`
HEAD `b28a0572`, 2026-10-21) — re-verify that manifest is still the operative baseline at execution time.

## How to use this register

- Execute after PR #399 + #400 merge and staging deployment (see `ON07_RUNBOOK.md` §1).
- One row per check. Fill `OBSERVED_*` columns only from what you actually see/screenshot; write
  `NOT_OBSERVED` (never 0, never inferred) where a check did not run — the repo's own convention is
  "unavailable stays null — never zero" (`tools/numerical_validation/evidence.py`).
- State vocabulary follows the repo convention (`docs/react_migration/feature_parity_matrix.md:3-11`):
  **D** defined, **R** rendered, **B** behaviour verified, **P** functional parity tested against the
  legacy acceptance reference, **F** done/fully verified; a visually complete screen never counts as P.
- Evidence columns must reference the actual artifact (screenshot filename, URL, history_id,
  composite_hash). Do not fabricate observations, timings or numbers.
- Input-parity mechanism to assert in the editing section: the rendered React grid cell set must equal
  the canonical API's editable cell list exactly (`docs/react_migration/overnight_b/REACT_INPUTS_UX_REDESIGN.md`,
  `[data-grid-cell]` set == editable cells), and project-setup bound fields must equal inputs.
- Known open input-parity gap to re-check: WSV2 ledger **M-003 — "Matched external-input parity is not
  established"** (`docs/react_migration/wsv2_core/WSV2_MASTER_GAP_LEDGER.md:9`).

## A. Navigation & shell

| # | Check | Expected (verified source) | OBSERVED_REACT | OBSERVED_LEGACY | State | Evidence |
|---|---|---|---|---|---|---|
| A-01 | Login/session gate present on both UIs | Session resolution + CSRF bound tokens (`app/auth.py`; `react_new_project.py:193-199` AUTH_REQUIRED) [TESTABLE_WITHOUT_#400] | | | | |
| A-02 | Project Library list | `GET /model-react/library` (React) vs `/projects` (Legacy, `main_web.py:4411`) — same user-owned projects [REVERIFY_AFTER_#400: wizard/Library changed by #400] | | | | |
| A-03 | Workspace shell loads per project | `GET /model-react/workspace?project=CODE`; workspace URL `/v2/model-react/{code}` (`react_new_project.py:248-252`) [TESTABLE_WITHOUT_#400] | | | | |
| A-04 | Feature flag gate behaviour | `FINCO_MODEL_REACT_V1` flag; disabled → `REACT_POC_DISABLED` 404 (`react_workspace_router.py` `_gate`) [TESTABLE_WITHOUT_#400] | | | | |
| A-05 | Protected reference read-onlyness | Reference projects render non-editable (`is_protected_reference`; grid save refused) [TESTABLE_WITHOUT_#400] | | | | |

## B. New Project / Library / Archive

| # | Check | Expected (verified source) | OBSERVED_REACT | OBSERVED_LEGACY | State | Evidence |
|---|---|---|---|---|---|---|
| B-01 | Technology cards (Solar/Wind creatable; Data Center/EV preview-ack; Storage refused) | `GET /model-react/new-project/options` (`react_new_project.py:202-231`) [REVERIFY_AFTER_#400: wizard/Library changed by #400] | | | | |
| B-02 | Preview shows effective scaled CAPEX/OPEX before create | `GET /model-react/new-project/preview` (`react_new_project.py:234-245`, `_effective` scaling) [REVERIFY_AFTER_#400: wizard/Library changed by #400] | | | | |
| B-03 | Create is idempotent by request_id; replay returns same project | `create_reference_seeded_project_once` (`react_new_project.py:343-362`) [REVERIFY_AFTER_#400: wizard/Library changed by #400] | | | | |
| B-04 | Preview acknowledgement required for PREVIEW-tier technologies | 409 `PREVIEW_ACKNOWLEDGEMENT_REQUIRED` (`react_new_project.py:326-328`) [REVERIFY_AFTER_#400: wizard/Library changed by #400] | | | | |
| B-05 | Legacy `/projects/create` creates the same seeded working copy | `main_web.py:4487`; same `create_reference_seeded_project` authority [REVERIFY_AFTER_#400: wizard/Library changed by #400] | | | | |
| B-06 | **Archive** | NOT on `main` for React (PR #400 "guarded Archive/Restore", unmerged). Record presence/absence exactly as observed; Legacy archive behaviour also record-only [DEPENDS_ON_#400] Archive/Restore not on main (checked 2026-10-30, main db504f6); expect absent until #400 merges+deploys | | | | |
| B-07 | Capacity bounds enforced in wizard | 0.1–10,000 MW (`react_new_project.py:52-53,161-164`) [REVERIFY_AFTER_#400: wizard/Library changed by #400] | | | | |

## C. Editing & Save All

| # | Check | Expected (verified source) | OBSERVED_REACT | OBSERVED_LEGACY | State | Evidence |
|---|---|---|---|---|---|---|
| C-01 | Grid cell set == canonical editable cell list (exact equality) | overnight_b input-parity mechanism (see header) [TESTABLE_WITHOUT_#400] [LOCAL_ENGINE_EVIDENCE: `total_capex_keur`/`opex_y1_keur` are not effective inputs via a snapshot cell on the Run route; check they are non-editable summary cells] | | | | |
| C-02 | Grid save bound: CAS on `composite_hash`, ≤50 cells | `POST /v2/workbook/grid/save` (`react_workspace_router.py:630` save block) [TESTABLE_WITHOUT_#400] | | | | |
| C-03 | Save All atomic: one transaction, nothing on failure | `app/v2/save_all_commands.py` (BEGIN EXCLUSIVE; rollback) [TESTABLE_WITHOUT_#400] | | | | |
| C-04 | Save All idempotency: same request_id + same body replays; different body refused | `save_all_commands.py:145-153` [TESTABLE_WITHOUT_#400] | | | | |
| C-05 | Save All limits: ≤200 items, ≤50 cells; excluded fields refused (`debt.financing.instruments`, `revenue.multistream.contracts`) | `save_all_commands.py:46-52,101-123` [TESTABLE_WITHOUT_#400] | | | | |
| C-06 | Pending-change store / Changes drawer present (WS-2, merged #397) | Merged PR #397 title; verify drawer renders and gates Save All [TESTABLE_WITHOUT_#400] | | | | |
| C-07 | OPEX/CAPEX line editing with inflation via cost-lines editor | `CostLineEdit.inflation_pct` (`save_all_commands.py:89-91`) [TESTABLE_WITHOUT_#400] [LOCAL_ENGINE_EVIDENCE: on the workbook Run route seeded CAPEX/OPEX sub-lines override snapshot totals (fixture 45,600 -> 30,937.5 effective); fixture totals must be entered via cost-lines editor and verified] | | | | |
| C-08 | Locked controls on calibrated schedules (rate/DSCR lock) | `assert_debt_scalar_edit_allowed` R8/N02 (`input_adapter.py:188-221`) [TESTABLE_WITHOUT_#400] | | | | |
| C-09 | Editing does NOT run the model; Last Run marked STALE after save | "The model is never run… leaves the Last Run STALE" (`save_all_commands.py:19-20`) [TESTABLE_WITHOUT_#400] | | | | |
| C-10 | Draft recovery state on corrupt draft | `diagnose_draft` → 409 typed recovery (`react_workspace_router.py:570-620`) [TESTABLE_WITHOUT_#400] | | | | |

## D. Run

| # | Check | Expected (verified source) | OBSERVED_REACT | OBSERVED_LEGACY | State | Evidence |
|---|---|---|---|---|---|---|
| D-01 | Run only on explicit user action (`POST /v2/workbook/run`) | run_contract note (`react_workspace_router.py:1012`) [TESTABLE_WITHOUT_#400] | | | | |
| D-02 | Run commits immutable history entry with `history_id`, `runtime_snapshot_id`, `ran_at`, `engine_version`, `composite_hash` | `GET /model-react/runs` (`react_workspace_router.py:949-993`) [TESTABLE_WITHOUT_#400] | | | | |
| D-03 | Historical Run export bound to one immutable row; no engine execution | exports block (`react_workspace_router.py:995-1012`) [TESTABLE_WITHOUT_#400] | | | | |
| D-04 | Busy/failed/timeout surfaces typed states (429 Retry-After; 503) | `main_api.py` + `app/runtime/model_execution` codes via router [TESTABLE_WITHOUT_#400] [LOCAL_ENGINE_EVIDENCE: WND-02 as specified is refused fail-closed (SHL_MATURITY_NOT_ON_PERIOD_GRID_FAILS_CLOSED, index 57); expect a typed refusal in both UIs, not a number] | | | | |
| D-05 | WND-02 shows gearing warning (>85%) path; SOL-02 at 85% shows none | `app/api/router.py:44-53` (verify which surface actually renders it) [TESTABLE_WITHOUT_#400] [NOTE: rule is in v1 `/api/v1/validate` (`app/api/router.py`); whether either browser surface renders it is UNVERIFIED. Local engine: WND-02 88% never reaches a result (refused)] | | | | |
| D-06 | Statements view of an earlier Run renders without recalculation | `GET /model-react/analysis/run-statements` ("never runs the engine, never recalculates", `react_run_statements.py:1-21`) [TESTABLE_WITHOUT_#400] | | | | |

## E. Scenario / analysis

| # | Check | Expected (verified source) | OBSERVED_REACT | OBSERVED_LEGACY | State | Evidence |
|---|---|---|---|---|---|---|
| E-01 | Scenario list & compare endpoints | `GET /model-react/scenarios`, `/scenario-compare`, `/scenario-overrides` (`react_workspace_router.py:1142-1300`); Legacy `/scenarios*` (`main_web.py:4624-6057`) [TESTABLE_WITHOUT_#400] | | | | |
| E-02 | Built-in Base/Downside/Upside deltas applied as documented | `app/scenario_manager.py:62-121` (Downside: tariff −5%, P50 −10%, capex +5%, opex +10%, degradation ×1.15) [TESTABLE_WITHOUT_#400] | | | | |
| E-03 | ScenarioPolicy.OVERRIDE fields scenario-scoped; NOT_ALLOWED fields refuse | `ScenarioPolicy` in registry fields [TESTABLE_WITHOUT_#400] | | | | |
| E-04 | Sensitivity / goal-seek parity surfaces (0.01 pp tolerance) | `docs/react_migration/rc_m_integrated/04_ANALYSIS_SENSITIVITY_GOALSEEK_PARITY.md` [TESTABLE_WITHOUT_#400] | | | | |
| E-05 | Lender-case route | Legacy `/scenarios/lender-case` (`main_web.py:5484`); React equivalent observe-only [TESTABLE_WITHOUT_#400] | | | | |

## F. Financing output & reports

| # | Check | Expected (verified source) | OBSERVED_REACT | OBSERVED_LEGACY | State | Evidence |
|---|---|---|---|---|---|---|
| F-01 | Debt metrics / period status rendering | `senior_debt` schedules + `binding_constraint` in Run payload (`project_runner.py`) [TESTABLE_WITHOUT_#400] [EXPECTATION_UPDATED_POST_#399: merged WF-04 adds React Debt Metrics workspace (`frontend/src/app/debtmetrics/*`), Covenant table, Period Status Matrix, and two contractual inputs `debt.contract.min_dscr_eod` / `debt.contract.contractual_dscr` (blank=NOT_CONFIGURED). Low DSCR is a model result, not an Integrity FAIL; lock-up (engine default 1.10, not editable) and covenant are separate verdicts] | | | | |
| F-02 | Bankability configuration editor (typed JSON, bounded) | `app/workbook/bankability_config.py` (sizing_mode/lender_case/targets/rates/day_count/fees/reserve) [TESTABLE_WITHOUT_#400] | | | | |
| F-03 | Financing Studio serializer parity (byte-identical documents) | `tests/test_model_react_rcm_financing_v1.py`; `docs/react_migration/rc_m_integrated/00_EXECUTIVE_README.md` [TESTABLE_WITHOUT_#400] | | | | |
| F-04 | Investor agreement (F4) editor | `investor.agreement.common_equity` JSON field (`registry.py:1104-1113`) [TESTABLE_WITHOUT_#400] | | | | |
| F-05 | Reports/exports (Excel, CSV) reflect the SAME committed Run | `/v2/workbook/export` CANONICAL_LAST_RUN authority (`react_workspace_router.py:996-1005`) [TESTABLE_WITHOUT_#400] | | | | |
| F-06 | kEUR/EUR/mEUR unit labelling correctness (defect B1 class) | `docs/react_migration/wf_react_1/README.md` (B1 ×1000 error resolved by Decimal oracle) [TESTABLE_WITHOUT_#400] | | | | |

## G. Negative tests (paired with RUNBOOK §4)

| # | Check | Expected | OBSERVED_REACT | OBSERVED_LEGACY | State | Evidence |
|---|---|---|---|---|---|---|
| G-01 | No data leakage between users | `resolve_accessible_project(user, code)` scoping (`react_run_statements.py:35`) [TESTABLE_WITHOUT_#400] | | | | |
| G-02 | No hidden writes when browsing | All `/model-react` reads are read-only; only explicit POST endpoints mutate [TESTABLE_WITHOUT_#400] | | | | |
| G-03 | No automatic Run on save/browse | Save All never runs the model (C-09); run only via `POST /v2/workbook/run` [TESTABLE_WITHOUT_#400] | | | | |
| G-04 | Past Run not mutated after Save All | Run history immutable; freshness becomes STALE instead [TESTABLE_WITHOUT_#400] | | | | |
| G-05 | No cross-project mix-ups | Every request carries explicit `project` code; identity CAS per (user, project) [TESTABLE_WITHOUT_#400] (plus #400 archived-deep-link cases are DEPENDS_ON_#400) | | | | |

## Screenshot protocol

For every OBSERVED cell: capture PNG named `ON07_<section>_<check>_<ui>.png`, record URL, timestamp,
browser/version, and the project's `history_id` + `composite_hash` when a Run is involved. Screenshots
are evidence, not acceptance: parity state P requires the behavioural assertion, not the picture.
