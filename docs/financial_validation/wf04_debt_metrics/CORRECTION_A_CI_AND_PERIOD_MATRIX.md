# WF-04 — Correction A: CI governance (collection skip + mandatory browser role) and the Period Status Matrix

Owner decisions applied: **CI-A**, **UX-A**, **LABEL-A**, **SCOPE-A** (prompt of 2026-10-29, existing PR only). No financial method, engine, certificate, CSRF/CAS, Save All or #397 file was touched.

## 1 — P00 refresh (read live, not inherited)

| Item | Value |
|---|---|
| `main` | `b76ac65c99e7fc9b486a557ae3c5ba9a711f50b3`, tree `a948fd18ad74a4d8c87523900ab86c585fcc6b41` — unchanged since the first P00 |
| PR #399 | open **draft**, head `271fdec74ff30da83ba27ca9761c64535ddd52e5` (remote); 0 review threads; base `main` `b76ac65c…`; merge-base `b76ac65c…` |
| PR #397 | open **draft**, head `58e7d07a2071c7cfe70bed3200dad5f7b05ce1e9` (moved since `92b3150c`), base `main` `b76ac65c…`; not merged, not touched |
| Exact-head CI of `271fdec7` | GREEN: compile-and-safety, independent-oracle, authoritative-history, atomic-batch (C0), dependency-audit, rate-contract-native-and-browser (F01), source-safety, route. **RED:** Public Safety `plan` (→ aggregate, tests, mandatory-evidence follow), and the **Protocol UI Browser Acceptance** role run (`mandatory-browser-evidence`) |

## 2 — Two real failures at `271fdec7`, both reproduced from the original logs

### 2.1 Public Safety `plan`: `collection skip change; reviewed reconciliation authority required`

The accepted-source reference is the authenticated plan artifact of the last successful Public Safety run on `main` (run `40843562163`, head `b76ac65c`). Both plan artifacts were downloaded and compared record by record (`collection/child/adapter.json`):

| Ledger | Collection-skip records |
|---|---|
| accepted reference (`main` `b76ac65c`, run 40843562163) | **70** |
| PR head `271fdec7` (run 40889260943, artifact 12904022610) | **71** |
| **exact delta** | **+1:** `tests/test_wf04_debt_metrics_browser.py — "Skipped: playwright not installed in this workflow"` (module-level `pytest.importorskip`) |

`tests/test_react_main_coexistence_browser.py` and `tests/test_model_react_poc_browser_acceptance.py` are **in the accepted reference already** (they are only absent from the older 68-entry historical baseline); they were not touched. Nothing in `tools/ci_v3_source_reference.py`, the reference or the baseline was changed.

**Resolution (the repository's own precedent, PR #375/#377):** the 11 browser bodies moved to the non-collected `tests/model_react_wf04_debt_metrics_acceptance.py` (no skip, no autouse) and are imported by the existing mandatory Chromium role `tests/test_model_workspace_consolidation_browser.py` through one additive, exactly-pinned import block. The role's own `live_server`/`browser` fixtures (one server, one port) are used; the WF-04 `world` fixture only creates synthetic projects in that server's database under the shared test user, in a module-scoped fixture with the role's existing cleanup — no second server and no second port.

Verification (this environment, `playwright` made unimportable the way the plan environment is):

| Check | main | this branch |
|---|---|---|
| collection-skip ledger (66 records locally) | 66 | 66 — **identical sorted ledger** (accepted: 70 = 70 once the one WF-04 record is gone) |
| original nodes removed | – | **0** (21,647 `main` nodes are all present) |
| nodes added to the plan collection | – | only new `tests/test_wf04_*` modules (executed by the hermetic workers like every other collected module) |
| role module collected nodes (`tests/test_model_workspace_consolidation_browser.py`) | **274** | **287 = 274 + 13** (the 11 original WF-04 tests + the 2 added here), verified by collection, not assumed |

### 2.2 `mandatory-browser-evidence`: one real regression of the WF-04 change (not a CI artefact)

The role ran all 274 original nodes at `271fdec7`: **273 passed, 1 failed** — `test_financing_workspace_has_the_six_sections_with_authority_and_closed_structures_stated` (`tests/model_react_rcm_financing_acceptance.py:145`). The Debt Metrics tab added to the Financing workspace changed the exact tab list asserted there. This had passed on `main`; I had not run that role locally. Fix: the expectation gains exactly one entry, `Debt metrics`, after `Overview`; the node id and every other assertion are unchanged (ledger §3, before/after). The full role is re-run locally before publication (§6).

## 3 — UX-A: the Period Status Matrix (replaces the OPEN/LOCKED tiles)

Server-evaluated, presentation-only: `app/v2/debt_metrics_projection.py::_period_matrix` turns each already-persisted per-period number into a status enum; the React component (`PeriodStatusMatrix.tsx`) only draws it and calculates nothing. Statuses: `OK` ✓ (green), `ALERT` × (red), `WARN` ! (amber), `NA` — (gray, outlined).

| Row | Truth class | Per-period source (Run id = the credit-payload Run; period index = the global model period) | Cell rule |
|---|---|---|---|
| Distribution lock-up | RUN RESULT | `distribution_schedule.periods[period].lockup_active` | `true` → WARN, `false` → OK, absent → NA (a blank flag is never OPEN) |
| Minimum DSCR | INPUT RECORDED WITH THIS RUN | sealed `integrity_evidence.senior_debt.periods[].reported_dscr` (raw) vs `last_runtime_identity.dscr_contract_terms` | raw `<` recorded term → ALERT; else OK; NA when the term is not recorded / not configured / invalid, when the period has no scheduled service, or when the ratio is not persisted |
| Contractual DSCR | INPUT RECORDED WITH THIS RUN | same | same rule, separate term |
| Debt-service coverage 1.00x | RUN RESULT | same evidence, base-case CFADS ÷ scheduled Senior service | raw `<` 1.0 → ALERT; NA without service/ratio |
| Cash shortfall (before reserves) | RUN RESULT | `integrity_evidence.cash[period_index].cash_after_senior_before_reserves` | `< −1e-6` kEUR (= the Run Integrity tolerance, test-pinned) → ALERT with the amount; `≥` → OK; absent → NA |
| DSRA requirement / reserve draw | – | **not recorded by a Run** | **no row is drawn**; disclosed beside the matrix as `UNAVAILABLE — the required DSRA amount and any reserve draw per period are not recorded with this Run` (no synthetic green) |

Every cell has a text alternative built from that Run's numbers, e.g. `2031 H2 — Minimum DSCR breached: actual 0.99x, Minimum DSCR 1.05x; model-evaluated condition on the entered terms, not a legally adjudicated Event of Default, nonpayment or default`. Ratios use the adaptive formatter (0.9951 prints `0.995x`, never `1.00x`). The evidence digest is verified before any cell is produced; forged or missing evidence withholds the whole matrix.

**Summary counts** (above the matrix): periods; Lock-up; Below Minimum DSCR; Covenant breaches; Coverage below 1.00x; Cash shortfall. A count is shown only when at least one period could be evaluated; otherwise `Not recorded` (never an inferred zero); a partially evaluated row says `n of N periods evaluated`.

**Interaction / accessibility:** `role="grid"`, `th scope="row" / "col" / "colgroup"`, two header rows (year group, then the period; full label + date in the tooltip, aria-label and the selected-period panel), a sticky row-heading column, fixed-width compact cells inside the matrix's own scroll box (the page never scrolls horizontally), one roving tab stop, arrow keys / Home / End, Enter or click selects the period and focuses the same column in the debt schedule (no write, no Run). Rendering: five memoised rows of dots; 54 semiannual and 120 quarterly periods are covered by a node test; no per-cell state.

## 4 — LABEL-A: user-visible terminology

Primary labels everywhere on the Debt Metrics screen: **Minimum DSCR** (editable, recorded with the Run), **Contractual DSCR** (separate editable covenant), **Achieved Minimum DSCR** (read-only result). The Credit chip reads `Minimum DSCR: Triggered / Met / Not recorded / Unavailable / Not applicable`. The meaning is kept in a tooltip, a standing note and the field description: *a model-evaluated Event-of-Default condition on the entered terms — not a legally adjudicated Event of Default, nonpayment or default*. Unchanged: the canonical backend identifiers (`eod`, `EOD_FLOOR`, `debt.contract.min_dscr_eod`, `dscr_min_eod_x`), the verdict enums and the covenant-row status text `EVENT_OF_DEFAULT: TRIGGERED`, and the strings recorded inside historical Runs. The workbook input label in the registry now reads `Minimum DSCR` (a string of the field this PR added). There are still exactly **two** editable DSCR fields. A browser test audits that `EoD threshold` / `EoD floor` appear nowhere on the screen.

## 5 — Unchanged by this correction (re-proved)

Financial statements, debt, tax, distribution, sponsor schedules and the Integrity evidence digest (`INDEPENDENT_ORACLE_AND_PARITY.md` P1–P6; the new `cash_after_senior_keur` is a read of the existing evidence); Run-bound terms; the independent oracle; `app/run_integrity/**`; `financial_engine/`, `finco_core/`, `domain/`; CSRF/CAS; #397.

## 6 — Local evidence before publication

See `WF04_ACCEPTANCE_MATRIX.md` §E for the final local results of this correction (typecheck, 15 node tests, the full mandatory role run, governance, Python suites). Exact-head CI is recorded on the PR.
