# RC-4 / Workstream B — Institutional Credit Decision V3 (lender cases, debt capacity, covenant evidence, scenario risk)

Status: DRAFT for independent review. NO MERGE / NO DEPLOY. Read-only decision intelligence, not lender certification.

## 1. Provenance

- Base: `origin/main` `4483b30904a30cd3f5406506283202e2ebeaf427` (independently re-read from GitHub before branching; equals the last observed main).
- Branch: `feat/model-rc4-credit-decision-v3` (one workstream branch; no rebase, squash or force push).
- Scope guard: no change to `financial_engine/`, `finco_core/`, `domain/`, persistence repositories, migrations, tolerances, goldens, release pins, A's PPA-01 governance files or C's import modules.

## 2. Implemented-versus-missing inventory (taken before coding)

| Area | Already on main (reused, not duplicated) | Missing before this work |
|---|---|---|
| Debt sizing, F2 lender-case controls | `financial_engine` solver; `app/workbook/bankability_config.py` (`sizing_mode`, `lender_case`, targets, rates, fees, reserve) | no cross-Run credit view of what the committed Runs actually did |
| Committed sizing evidence | `runtime_summary.financing_evidence.bankability` (`dscr_debt_capacity_keur`, `gearing_debt_capacity_keur`, `final_senior_commitment_keur`, `binding_senior_constraint`, `gearing_basis_keur`, `gearing_ratio`, fixed-point diagnostics) validated by `app/v2/financing_sources_uses_projection.py`; legacy Runs without the block stay unavailable | one place comparing it across 2–3 Runs |
| Sources & Uses / facilities | F1 S&U projection, F3 instrument reconciliation (`financing_instrument_reconciliation.py`), two-Senior and Junior authorities | facility-level credit summary beside debt service |
| DSCR / debt schedule | `debt_schedule`, `integrity_evidence.senior_debt.periods` (per period base CFADS, bank CFADS, debt service, interest, principal, reported and target DSCR), `distribution_schedule.lockup_active`, `sponsor_schedule.summary.terminal_financial_state` | a compact period credit matrix |
| Covenant / threshold authority | Model Quality `QM-COV-001..004`, `QM-SD-003..007`, `QM-CASH-002`, `ProjectTerms` (project input vs contractual), Diagnostics V2 bankability monitor (Last Run) | the same evidence for any selected committed Run, with the four finding classes |
| Run identity, immutability | `RunHistoryEntry`, `get_run_history_entry` (owner scoped), `resolve_run_status_dimensions`, Run Compare, Diagnostics Run Comparison (QM/DX checks only) | credit-metric comparison across Runs and scenarios |
| Scenario comparison | `build_scenario_projection` / `build_compare_rows`, Insight scenarios | Uses / DSRA / IDC / fee attribution for the F-3 pattern |
| Sensitivity | M3 two-driver matrix (read-only, not committed Runs) | not duplicated and not used as Run evidence |
| Statements | canonical Statements, `/v2/workbook/run-history/statements`, `workspace_destinations` | click-through from a credit period |
| LLCR / PLCR / EoD / cash sweep | `min_llcr` only when persisted in the debt-schedule summary; no PLCR, no EoD mechanic, cash sweep amount not persisted | stays UNAVAILABLE with the exact evidence gap |
| Lender case (P50/P90) | typed `DebtSizingCaseConfig`; **not** persisted with a Run | bound only when the Last Run is CURRENT (Q3 rule), otherwise UNAVAILABLE |
| Failed Runs | never committed (Run History is a ledger of successful Runs) | represented as failure/absent, never as a bankable scenario |

No new solver, sizing formula, DSCR schedule, covenant evaluator, Run writer, scenario repository or migration is introduced.

## 3. What was built

One focused, read-only entry point: `GET /v2/credit-decision?project=<code>&run=<history_id>[&run=…]` (one to three committed Runs of one project; default: the Last Run). It is reached from the Run History sheet ("Credit decision →") or directly.

| File | Role |
|---|---|
| `app/v2/credit_decision_projection.py` | Pure projection over `RunHistoryEntry` objects: structure, capacity, period matrix, findings, comparison. No I/O, engine or formula. |
| `app/v2/credit_decision_router.py` | Authorisation (authenticated owner, project isolation, protected-reference denial 409, foreign/unknown Run id 404, more than 3 Runs 422), Run state from the canonical freshness authority, Working-Copy terms bound to the CURRENT Last Run only. Single GET route; no POST exists. |
| `app/templates/v2/credit_decision.html`, `static/js/model_credit_decision.js`, `static/css/model_credit_decision.css` | Server-rendered tables (FastAPI + Jinja2 + HTMX stack, no React), sticky row labels, matrix-contained horizontal scrolling, keyboard period navigation (arrow keys / Home / End), class filter for findings. JavaScript performs no arithmetic and no network calls. |
| `main_web.py` (+3 lines), `sheet_run_history.html` (+1 link) | Router registration and entry link. |

Reused unchanged: Run History repository (`get_run_history_entry`, owner scoped), the F1/F3.7 Sources & Uses and instrument validators (`build_sources_uses_projection`), Model Quality (`evaluate_model_quality`; `QM-SD-003…007`, `QM-CASH-002`, `QM-COV-001…004`) for statuses, severities and thresholds, Run Integrity, `resolve_runtime_freshness`, `resolve_last_run_scenario`, `terms_from_project_inputs`, the F2 `build_view` and the F3 `build_view`.

### Sections

* **A Financing structure** — committed Senior commitment versus the requested gearing cap and actual gearing; facilities (two-Senior and Junior ledgers: commitment, draws, IDC, fees); equity and SHL cash; observed tenor and maturity; observed interest policy; fees and IDC; DSRA balances; lender case and sizing mode (Working-Copy terms bound only for the CURRENT Last Run); the Working-Copy F3 proposal (active versus saved-only) in a separate panel that is never part of a Run column.
* **B Debt capacity and service** — committed DSCR/gearing capacity, binding constraint, solver termination (kept apart from feasibility), min/avg DSCR, sizing target, LLCR, sums of principal / interest / debt service / CFADS over the scheduled periods (basis stated), tightest periods.
* **C Credit-risk timeline** — per Run, 13 rows × the committed Senior-debt periods (DSCR, target, base and lender-case CFADS, debt service, interest, principal, balance, DSRA, distribution, lock-up, DSCR < 1.0x, DSCR below the sizing target). Row labels link to the existing Statements / Financing / Diagnostics evidence; selecting a period shows its committed values.
* **D Scenario comparison** — plain differences of persisted values against the first Run for revenue, CFADS, debt service and coverage, capacity, the Uses lines that move debt, equity requirement, distributions and returns, with notes when input identities or engine versions coincide or differ.
* **Credit findings** — deterministic, four classes (CONTRACTUAL_COVENANT, PROJECT_INPUT_ADVISORY, OBSERVED_FINANCIAL_RESULT, UNSUPPORTED_EVIDENCE_MISSING). Each carries metric, Run and scenario identity, period, actual, threshold with its authority, headroom (only when both numbers exist), evidence source, the severity of the existing rule, and links.

## 4. WF-A findings: how each is treated

| ID | Treatment |
|---|---|
| F-1 | The active sizing mode (bound for a CURRENT Last Run) is shown with its limitation: `flat_dscr_sculpted` still applies the gearing cap; `gearing_cap` has no feasibility check. No formula changed. |
| F-2 | Solver termination and minimum DSCR are shown separately; finding `CD-F2` ("DSCR below 1.0x although the solver CONVERGED") takes its severity from QM-SD-007. Tested on real Solar (90 %) and Wind (95 %) gearing-cap Runs. |
| F-3 | Section D lists the Uses lines (CAPEX, IDC, fees, DSRA, total) that changed when Senior rose while revenue fell. Attribution is `COMMITTED_USES_LINES` only if GEARING is persisted as binding in both Runs, else `UNAVAILABLE`; it is explicitly not a causal proof. |
| F-5 | Missing equity IRR is rendered UNAVAILABLE with the Run's status (never 0, never estimated); finding `CD-F5`. |
| F-6 | Persisted `min_llcr` shown when present; PLCR and event of default are UNSUPPORTED; cash sweep is inventoried (observed only if amounts are persisted). A supplied threshold that is not proven contractual can only produce `BELOW_PROJECT_INPUT_THRESHOLD`, never a covenant breach. No default is ever declared. |
| F-7 | "Operational generation case (P50)" and "Credit-sizing case" are labelled separately; the lender case is shown only for a CURRENT Last Run (bound Working Copy value). A paired P50 → P90-10y test shows identical revenue/EBITDA and different DSCR capacity. |
| F-8 | A failed or fail-closed Run is never committed (verified: a very low tariff, and a 95 % gearing cap on Solar, fail closed and leave Run History unchanged), so it cannot be selected. A committed Run with failed Run Integrity is labelled "failure state, not a bankable scenario". |

## 5. Unavailable metrics and exact evidence gaps

| Metric | State | Gap |
|---|---|---|
| Lender case (P50/P90-10y), sizing mode, reserve instrument (cash DSRA / DSRF / none), project thresholds (lock-up DSCR, minimum LLCR, DSRA requirement) | UNAVAILABLE for every Run except the CURRENT Last Run | Not persisted with a Run. |
| Binding constraint, DSCR/gearing capacity | UNAVAILABLE for legacy Runs | `financing_evidence.bankability` is absent; never reconstructed. |
| Minimum LLCR | UNAVAILABLE unless persisted | No discount basis is persisted. |
| LLCR by period, PLCR, event of default, contractual minimum-DSCR covenant | UNSUPPORTED | No computation and no contractual term in ProjectInputs. |
| Cash sweep | UNSUPPORTED unless amounts are persisted | `cash_sweep_keur` is null. |
| Per-facility operating rate, tenor, fees (two-Senior) | not shown as terms | Only observed aggregate rates and the committed construction ledgers are persisted; tenor/maturity are shown as observed. |
| Equity IRR under fixed-debt stress | UNAVAILABLE | The Run published none. |

## 6. Verification

* `tests/test_model_credit_decision_v3.py` — 32 synthetic evidence-contract tests (authority classes, missing versus breach, convergence versus feasibility, unavailable-never-zero, F-3 attribution, purity and no-write scans, JavaScript has no calculation).
* `tests/test_model_credit_decision_v3_real_runs.py` — real canonical Runs: Solar, Wind, Data Centre and EV charging (classified); single, two-Senior and Junior financing; sizing evidence read-not-reconstructed against the persisted payloads; GET never runs the engine or writes; POST → 405; owner scoping; unknown, foreign and oversized Run ids; duplicate and more-than-three selection; protected-reference denial.
* `tests/test_model_credit_decision_v3_scenarios.py` — real Runs: P50 vs P90-10y (paired, STALE binding), DSCR < 1 with CONVERGED (Solar, Wind), DSRA vs DSRF across three Runs, saved-but-inactive F3 proposal, revenue downside, failed attempt, multiple scenarios with Run History immutability.
* Result: 54 passed, 0 skipped. Existing rings re-run unchanged (Run Intelligence, public-surface hygiene, workspace consolidation, navigation safety, diagnostics display): 89 passed.
* Pre-existing environmental failures, identical on a pristine checkout of main `4483b30` and unrelated to this branch: the RC-2/RC-3 integration-manifest and inventory tests (2 failed, 94 errors) need git objects of unmerged review heads; the public safety scan reports only the known Swagger vendor CRLF hash mismatch.
* Real browser (Chromium via the Claude browser pane against a local seeded server with the production CSP `script-src 'self' 'unsafe-inline'`): zero console errors; desktop 1280 px with no page-level horizontal scroll (only the matrices scroll, each focusable); arrow-key period navigation with a committed-values detail panel; mobile 390 px layout; sticky row labels.

## 7. Remaining policy decisions (not made here)

1. QM-SD-004 (sizing-target ceiling) applies to explicit committed facilities: whether it should be advisory is unresolved and unchanged.
2. Whether the lender case, sizing mode and reserve instrument should be persisted with the Run so that historical Runs can show them (a persistence-contract change outside this read-only workstream).
3. Typed contractual terms (minimum DSCR covenant, default DSCR, LLCR): without them no CONTRACTUAL_COVENANT finding can be produced from real projects.
4. LLCR/PLCR discount basis and an event-of-default / cash-sweep mechanic (authorised capability work, WF-A U-1).
5. Financial-authority confirmation of the F-1 naming and the F-3 gearing mechanic.
6. The statement CFADS line ("FCF to banks") is after tax and reserve movements, so it can differ between lender cases with identical EBITDA; it is labelled as such.
