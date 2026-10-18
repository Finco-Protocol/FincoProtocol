# RC-7 / Workstream B - Monthly CAPEX funding binding V2

Base: `origin/main` 05183b2a. Branch `feat/model-rc7-capex-funding-binding-v2`. Status: **stage 1 (monthly construction bridge and real-engine proof) delivered; persistence, Save and Run binding are NOT yet delivered** - see section 5.

## 1. Source-to-Run path (verified in code)
| Layer | Authority | Granularity |
| --- | --- | --- |
| Per-category timing | `CapexItem.y0_share` + `spending_profile` | existing SEMESTER construction periods |
| Construction input | `derive_construction_financing` -> `ConstructionFinancingInput` (`financial_engine/financing/generic_product_policy.py`) | semester periods; `payment_weights` per CAPEX category code |
| Engine adapter | `financial_engine/construction/adapter.py` | **any consecutive dated periods**; Senior interest fraction comes from the period DATES |
| Funding / IDC | `finco_core/construction/stage_b2.py` + `allocator.py` | per period of the supplied timeline; cash date = period end |
| User sub-line amounts | `fold_sub_lines_into_capex` | amounts only; they inherit the category timing |
| `CapexSubLine.schedule_json` | persisted, hashed by no consumer | **not consumed by any Run** |

Consequence: the typed construction input is NOT semester specific. Feeding the unchanged engine a MONTHLY timeline is therefore a binding of the existing monthly-capable authority, not a second engine.

## 2. B2 - date-preserving monthly bridge (`app/capex_profiles/binding.py`)
`bind(construction, construction_months, category_amounts_keur, leaves)` turns the semester input the Run already derives into the monthly input:
* month grid = `financial_close + k` months (PeriodEngine rule); each month lies inside exactly one semester period;
* an un-profiled category keeps its cash dates: each semester weight moves to the LAST month of its period (the existing "paid at period end" convention); the structuring fee likewise;
* a category with profiled leaves gets the exact amount-weighted blend of its leaves (Fraction arithmetic; the remainder keeps default timing). Only leaf rows own profiles, so parents and children are never both counted;
* nothing is inferred from half-year amounts; IDC, commitment fees, draws and Total Uses are computed by the unchanged canonical engine.

Refused with a typed `BindingUnsupported` (the profile stays preview-only on that path): duration that does not match the financial-close axis, a month crossing a semester boundary, leaf amounts that do not sum to the category, a category absent from the construction input, per-period/floating Senior pricing vectors, an enabled VAT facility, SHL accrual tails, a disabled construction authority.

## 3. B3 - real-engine proof (`tests/test_model_rc7_capex_monthly_binding.py`, 26 tests)
Real canonical Solar (12, 14, 18 months) and Wind (20 months) projects, no persistence:
* monthly hard-CAPEX uses equal an independent exact oracle (`contract.allocate`) month by month, for base, front, back, milestone and mixed profiles; hard CAPEX is timing independent;
* Sources = Uses in total and every month; cumulative Senior draws never exceed the commitment and equal it at COD;
* every Total-Uses movement between any two runs equals the movement of (IDC + commitment fee + structuring fee) to 1e-5 kEUR;
* IDC follows draw dates (14-month Solar, kEUR): front 258.0 > semester-equivalent monthly base 225.7 > back 84.3; milestone month 3 447.6; commitment fees move the opposite way;
* zero-cost months carry no hard CAPEX or Senior draw; partly profiled categories keep default timing for the rest;
* monthly baseline (no profile) is the attribution reference: the finer interest grid alone moves 14-month Solar IDC from 223.5 (semester) to 225.7, so profile effects must be reported against the monthly baseline, not against the semester run.
* default parity: no engine/core module imports the bridge; with no bound profile `derive_construction_financing` and every default output are untouched.

## 4. Frozen / pinned areas respected
No edit to `finco_core/`, `financial_engine/`, `period_engine.py`, `axis_contract.py`, `orchestrator.py`, `adapters/project_inputs.py`, Revenue/PPA, Credit Decision, Export, or any governance pin. Existing generic limits are untouched (e.g. construction <= 12 months on the reference fixtures needs one extra horizon year for the existing SHL maturity rule; the 16 MW Wind reference fails its own semester run, so Wind is proven at 25 MW).

## 5. Not yet delivered (next stages, same branch)
1. B1 persistence: versioned profile document, CAS/transaction writer, scenario handling, composite-identity inclusion.
2. B4 Run consumption: apply the bridge on every Run-equivalent seam after the sub-line fold; Save -> STALE -> Run -> CURRENT acceptance; historical Run immutability.
3. Planner Save UI and the corresponding extension of the CSRF inventory successor (`tests/wf09_csrf_successor.py` must be re-pinned and independently reviewed).
Until then the Save/activation stays unavailable and the V1 planner remains preview-only.
