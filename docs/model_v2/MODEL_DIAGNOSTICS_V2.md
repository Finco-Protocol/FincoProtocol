# Model Diagnostics V2 — institutional financial intelligence (authority and acceptance contract)

Base: `origin/main` `6fc77de98bc0562fb51efdbf96e1803a29b5b148` (merge of RC-2 #278). Branch `feat/model-diagnostics-v2-institutional-intelligence`.
Read-only. No engine call, no write, no Working Copy value mixed into a committed Run, no change to the Quality registry,
score, coverage, tolerances, Run Integrity validators, Run Compare, Q4 / Goal Seek or any financial formula.

## 1. Preflight (live)

`origin/main` = `6fc77de…` (RC-2 #278 merge commit is an ancestor). Diagnostics V1 (#268) is on main with its 30 stable `QM-*`
identities and seven period-evidence-compatible controls (`QM-ACC-001`, `QM-SU-001`, `QM-SD-001..004`, `QM-CASH-001`); Run Integrity,
Insight Q1/Q2/Q3, Q4 Finding-to-What-if, Goal Seek, F3/F4 financing authority, M4 Developer Economics evidence and Revenue V2 are present.
Revenue V3 is release-closed (`ACTIVATION_ENABLED = False`) and is never read by Diagnostics.

## 2. Design

| Layer | File | Role |
| --- | --- | --- |
| Advanced checks (`DX-*`) | `app/v2/diagnostics_dx_checks.py` | Pure period identities over committed evidence; additive, outside the Quality registry |
| V2 projection | `app/v2/diagnostics_v2_projection.py` | Root-cause relationship model, period heatmap, bankability monitor, evidence inventory |
| Hook | `app/v2/diagnostics_projection.py`, `app/v2/insight_quality_projection.py` | One optional argument / one additive `v2` key; a malformed V2 never hides V1 |
| UI | `sheet_diagnostics.html`, `static/js/model_diagnostics_v2.js`, `static/css/model_diagnostics_v2.css`, `workbook.html` (asset links) | Same Diagnostics tab; no second page, no new route |

The DX family is deliberately NOT added to the Quality registry: doing so would change the score and coverage percentages, which needs a reviewed
registry policy. `DX-*` results carry `not_in_quality_score = true`. Every payload row states its check identity, definition, prerequisites,
tolerance source, classification and exact evidence gap.

## 3. Check inventory (CHECK ID → SOURCE → PERIOD → VALIDATOR → TOLERANCE → STATUS → EVIDENCE GAP)

| Check | Source | Financial period | Tolerance | Classification | Evidence gap |
| --- | --- | --- | --- | --- | --- |
| DX-CAPEX-001 construction spending vs total uses | `integrity_evidence.sources_uses`, `runtime_summary.financing_evidence` | Construction period index (cumulative + terminal identity) | `TOL_KEUR` | PERIODIC_PROVEN | Calendar-dated spending is not committed |
| DX-OPEX-001 OPEX / EBITDA / EBIT statement reconciliation | `financial_statements.pnl`, `.pf_cash_waterfall` | Every committed period | `TOL_KEUR` + ½-quantum per non-zero 2dp term | PERIODIC_PROVEN | Detailed OPEX line schedules are not committed |
| DX-DEP-001 accumulated-depreciation roll-forward + NBV | `integrity_evidence.balance_sheet`, `pnl`, `balance_sheet` | Periods with an adjacent committed opening | same | PERIODIC_PROVEN | **Additions / disposals: EVIDENCE_MISSING (never inferred)** |
| DX-CASH-001 distributable cash after debt service and reserves | `pf_cash_waterfall`, `tax_schedule.is_operation` | Operating periods | same | PERIODIC_PROVEN | Closing-cash roll-forward: EVIDENCE_MISSING |
| DX-SHL-001 SHL roll-forward incl. capitalised interest | `integrity_evidence.balance_sheet.shl`, `sponsor`, `pnl.shl_interest_expense_keur` | Operating periods with adjacent balances | `TOL_KEUR` + ½-quantum (accrual) | PERIODIC_PROVEN | Financial-close boundary periods have no presented balance → UNAVAILABLE |
| DX-SHL-002 SHL maturity evidence consistency | `sponsor_schedule.summary.terminal_financial_state`, balance sheet | Contractual-maturity period only | `TOL_KEUR` | PERIODIC_PROVEN (single point) | Unpaid maturity is reported as the canonical status (risk), mismatch is an error |
| DX-DIST-001 distributions vs distributable cash and the model's lock-up gate | `pf_cash_waterfall`, `distribution_schedule.lockup_active`, `sponsor` | Operating periods | same | PERIODIC_PROVEN | No contractual distribution rule is committed → none invented |
| DX-RES-001 cash DSRA roll-forward | `integrity_evidence.balance_sheet.dsra_balance`, `pf_cash_waterfall`, S&U `initial_dsra_funding_keur` | Operating periods | same | PERIODIC_PROVEN | MRA / other reserve instruments: EVIDENCE_MISSING; DSRF: NOT_APPLICABLE (standby, not a balance) |
| DX-REV-001 revenue statements + Revenue V2 contracted components | `pnl`, `pf_cash_waterfall`, `runtime_summary.revenue_multistream_audit` | Every period; contracts where committed | `TOL_KEUR` + ½-quantum | PERIODIC_PROVEN | Revenue V3 NOT_APPLICABLE (release-closed) |
| Scenario / yield consistency | `QM-PRV-005` (existing, global) | Global | identity equality | EXISTING_FULL (scenario identity); yield case EVIDENCE_MISSING | No explicit committed P50/P90 authority; never inferred from a number |

Classifications used: EXISTING_FULL, EXISTING_PARTIAL, AGGREGATE_ONLY, PERIODIC_PROVEN, NEW_CHECK_FEASIBLE, EVIDENCE_MISSING, NOT_APPLICABLE.
Existing checks keep their stable ids and results; `QM-SU-001/002` remain EXISTING_PARTIAL, `QM-ACC-003` AGGREGATE_ONLY, `QM-TERM-002` EXISTING_PARTIAL.

### Evidence rules (pinned by tests)

* Evidence only: committed statements / schedules / Run Integrity evidence of ONE Run. Periods join by committed period index and equal dates;
  sponsor rows join by ISO date because their own index can collide with the statement axis. A repeated key in a used source → UNAVAILABLE.
* Missing is UNAVAILABLE with an exact reason; zero is a committed value; digest mismatch → UNAVAILABLE; malformed evidence never becomes a financial FAIL.
* NOT_APPLICABLE only when the committed evidence proves it (explicit phase flag, committed all-zero SHL funding/balances/flows, explicit reserve regime).
* No balancing plug: residual = observed − expected of a stated identity (signed). Aggregate PASS means every *evaluated* period passed; the check
  states its coverage (`evaluated / applicable`, `complete`) and unevaluated periods stay UNAVAILABLE — never counted as passed.
* Tolerance: `TOL_KEUR` (Run Integrity) for full-precision evidence; for values the product persists rounded to 2 decimals, a reported half-quantum
  representation allowance per non-zero rounded term (same policy as the F3.9 numerical validation). No tolerance was widened.

## 4. Root-cause relationship model (no narrative generation)

Per failing or warning check/period: a typed list of items with explicit confidence.

| Confidence | Meaning | Example |
| --- | --- | --- |
| PROVEN | The canonical identity states the residual and its committed components | "Distributable cash differs from CFADS − debt service by +10.00 (tolerance 0.015)" |
| RELATED_EVIDENCE | Another finding in the same period, or a registered related check, is demonstrably connected | DX-REV-001 and DX-OPEX-001 both fail in P3 |
| POSSIBLE_CAUSE | An unverified arithmetic coincidence (residual equals / doubles a component) | "residual equals the depreciation component: possibly an omitted line" |
| UNAVAILABLE | Names the missing evidence that blocks a fuller explanation | `CASH_WATERFALL_LINE_MISSING` |

`cause_established` is always `false`: the model proves where and by how much a reconciliation fails, never why. Existing `QM-*` failures with period
evidence (and aggregate failures) receive the same structure; `QM-SU-001` adds the committed Sources & Uses components.

## 5. Period risk heatmap

Reuses the V1 committed period axis. Per period and per group (Accounting, CAPEX/OPEX, Cash Flow, Senior Debt, Reserves, SHL, Revenue,
Returns/Scenario): proven failed, warning, unavailable, passed, applicable, severity distribution, highest severity, click-through to existing check
detail. AGGREGATE_ONLY, NOT_PERIODIC and NOT_APPLICABLE are not counted; annual checks are not spread over monthly cells; global findings are listed
separately and never repeated per period.

## 6. Bankability & covenant monitoring — threshold authority inventory

| Subject | Class | Source | Used as |
| --- | --- | --- | --- |
| Contractual minimum DSCR | CONTRACTUAL_COVENANT only if a contractual term is source-proven, else NOT_SOURCE_PROVEN | `ProjectTerms.min_dscr_covenant` | Breach / headroom only when proven |
| Distribution lock-up DSCR | PROJECT_INPUT_ADVISORY (CONTRACTUAL only if supplied as such) | `financing.lockup_dscr` | "below project input" headroom, never "breach" |
| Minimum LLCR | PROJECT_INPUT_ADVISORY / CONTRACTUAL as above | `financing.min_llcr` | headline only: LLCR by period is not persisted |
| Cash DSRA requirement | PROJECT_INPUT_ADVISORY | `financing.debt_service_reserve_requirement_keur` | reserve coverage disclosure |
| Debt-sizing target DSCR | FINANCING_SIZING_TARGET | `runtime_summary.target_dscr` | "below sizing target" — **never a covenant** |
| Default DSCR / event of default | NOT_SOURCE_PROVEN | none | no event of default is ever declared |

Measured per period: DSCR (full precision), absolute and percentage headroom against each tested threshold with its class, debt-service /
cash shortfalls (committed CFADS < Senior service), committed lock-up flags, reserve coverage (DSRA ÷ next-period Senior service; DSRF and an
explicit no-reserve regime are not cash balances; missing evidence is not a zero balance), debt maturity (canonical terminal state), sponsor
distributions. STALE Runs do not inherit unsaved Working Copy terms. This is decision intelligence, not lender certification.

## 7. Verification

`tests/test_model_diagnostics_v2.py` (deterministic synthetic committed Runs: every check positive and negative, signed residuals, zero vs missing,
duplicates, digest, date join, tolerance bounds, root-cause confidence classes, heatmap axis/exclusions, bankability authority classes, scope guard),
`tests/test_model_diagnostics_v2_real_runs.py` (4 verticals × legacy / two-Senior / controlled Senior+Junior, Revenue V2 CfD, STALE and new-Run
identity isolation, GET without engine or writes, owner isolation, no new write route) and
`tests/model_diagnostics_v2_browser_acceptance.py` (real Chromium, run inside the EXISTING mandatory consolidation browser role through wrappers in `tests/test_model_workspace_consolidation_browser.py`: heatmap, advanced checks, drill-down, keyboard, injected failure with root cause, guided actions, Run comparison, 390 px).
Existing Diagnostics V1, Quality Q1, Insight Q3, Run Integrity suites run unchanged.

## 8. Delivered vs deferred

P0 delivered: D1 advanced checks (9 families implemented, 1 documented as existing/missing), D2 root-cause drill-down, D3 period heatmap, D6 bankability monitor.
P1 delivered after P0: D4 Diagnostics Run Comparison and D5 Guided Resolution (below).

### D4 Diagnostics Run Comparison (`app/v2/diagnostics_run_compare.py`)

No new route, repository or KPI engine. The Last Run is compared with up to four earlier committed Runs read from the existing immutable Run History (one
read-only repository call, owner and project scoped). Each Run is evaluated with the SAME checks (the Quality evaluation is injected by the existing
adapter with no Working Copy terms bound; the `DX-*` checks are pure over the entry's committed payloads, digest re-verified per Run).
Per check: Run A status/residual, Run B status/residual, signed residual change (B − A), and one of RESOLVED / NEW / PERSISTENT / UNCHANGED_PASS — or
**NOT_COMPARABLE** with the reason of each side when either Run did not evaluate the check (older evidence, digest mismatch, unbound thresholds). A
missing or UNAVAILABLE check in an older Run is never read as resolved. Historical evidence is never mutated (tested).

### D5 Guided Resolution (navigation only)

Per check (all 30 `QM-*` and 9 `DX-*`): open the owning schedule, open the related assumptions (Input Grid; registered ids only), open the Statements & Debt
calculation trace (financing families), open scenario/Run comparison, open Finding-to-What-if (Insight) only for the Q4-mapped checks
(`QM-SD-004/-006/-007`) on Solar/Wind (policy asserted equal to `app.v2.whatif.CANDIDATES` / `SUPPORTED_VERTICALS`), and Goal Seek (always disabled for a
reconciliation finding, with its reason). Unsupported actions are visibly disabled with the reason. No action writes, runs the model or creates a
scenario: Q4 keeps authority over scenario writes and signed confirmation.

## 9. Known limits

No BESS, valuation, reporting or export. Independent asset-register, closing-cash, MRA/other-reserve, calendar-dated spending and P50/P90 yield-case
evidence are not committed and therefore stay UNAVAILABLE. Aggregate PASS with partial coverage is disclosed per check.
