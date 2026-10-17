# WF-09 — CAPEX Spending Profiles V1 (RC-6 / Workstream B)

Base: `origin/main` 97c5286a. **Candidate planning/preview capability only. No canonical Save, no persisted profile, no Run, no engine change.**

## 1. Existing-authority reuse matrix (from code on main)
| Element | Where | Reaches committed Run? |
| --- | --- | --- |
| `CapexItem.y0_share` + `spending_profile` (per CATEGORY, per existing construction PERIOD; semester axis) | `finco_core/inputs/_models.py`, set by cost-template plan fields in `model_v2_composition/compose.py` | **YES** - `derive_construction_financing` -> Stage B2 / canonical allocator -> hard uses, Senior draws, capitalised IDC, fees, total uses |
| `CapexPaymentItem.payment_weights`, `CapexScheduleSet`, `monthly_hard_capex` | `finco_core/construction/stage_b2.py` | YES (typed construction authority; per construction period) |
| User sub-line AMOUNTS | `capex_sub_lines.fold_sub_lines_into_capex` | YES - added to the category amount and **inherit the category's timing** (`dataclasses.replace` keeps `spending_profile`) |
| `CapexSubLine.schedule_json` | `capex_sub_lines.py`, passed through `cost_template/*` | **NO** - persisted and copied only; never read by compose/input_adapter/engine (source-guard test) |
| Monthly user profile | - | **NO** - no storage and no consumer; the Run's construction axis is SEMESTRIAL periods, not months |
| C.13 contingency, C.17/C.18, IDC, bank/commitment fees, VAT costs, reserves | derived / financing | derived or engine-computed; excluded from the planner |

## 2. Delivered (candidate)
`app/capex_profiles/` (contract, projection, plan), `app/v2/capex_profile_router.py` (mounted from `capex_router`), `capex_spending_profiles.html`, one link on the CAPEX sheet.
- Contract: exact `Fraction` weights; uniform / front / back (linear shapes the user selects) / explicit percent / single-month milestone; 1-60 whole months; negative, NaN, infinite, blank, wrong count, sum != 100 % (beyond 1e-9) -> typed rejection, **never normalised**; rounding to 1e-6 kEUR with the residual on the last weighted month so monthly uses reconcile EXACTLY; zero amount stable.
- Catalogue: leaf rows only (active sub-lines + category inputs) - parents are never items, so nothing is double counted; inactive rows excluded; derived/financing rows listed read-only.
- Timeline: existing `PeriodEngine` from the project's own inputs (same period convention as the construction derivation); degrades to "dates unavailable" instead of inventing dates.
- View: monthly uses, cumulative, remaining, unallocated/invalid amounts per row, and the **period-equivalent** the existing consumer would receive (end-of-period convention; intra-period monthly timing is not represented there).
- Safety: auth, CSRF, owner scoping; no write route exists (`save/apply/commit/run` -> 404/405); source guard forbids SQL/writers/engine calls in the package.

## 3. Why no canonical Save
A monthly profile has no persisted authority the Run reads: `schedule_json` is unbound and the construction axis is per semester. Persisting it as a model input would create an unconsumed "authoritative" field - explicitly refused.

## 4. Financial binding evidence (production path, nothing persisted - `test_model_wf09_capex_funding_binding.py`)
Timing changed only through `CapexItem.spending_profile` on the existing derivation (14-month, 3-period solar fixture): hard CAPEX 13,000 kEUR identical in every variant; period uses = amount x weights (independent oracle); Senior draws differ; capitalised IDC and total uses front-loaded > back-loaded; `total uses delta == financing-cost delta` exactly (timing moves only financing costs, reported separately); Sources = Uses every period and in total (residual < 1e-6).

## 5. Tests
114 contract + 14 planner/route + 6 binding + 2 Chromium (desktop 1440 / mobile 390, no page overflow, no console error, state unchanged). Regression: trust/RC-3/RC-5 governance and CAPEX/cost suites: 406 passed.

## 6. Missing authority / integration requirements (next authorised financial successor)
1. A persisted per-row profile owned by the existing CAPEX writer (e.g. bound `schedule_json` with a versioned schema, covered by composite identity and CAS).
2. Compose/materialize binding of that schedule into the construction timing, with a fold rule for sub-line vs category timing (today sub-lines inherit the category's).
3. A decision on the construction axis: monthly construction periods (needs the frequency architecture owned by Workstream A) or a documented monthly -> semester aggregation convention.
4. End-to-end Save -> STALE -> Run -> CURRENT acceptance and goldens for the bound profile.
5. Adding the WF-09 Chromium module to a mandatory CI role (not done here: shared CI selection).
