# RC-7 / Workstream B - Monthly CAPEX funding binding V2

Base: `origin/main` 05183b2a. Branch `feat/model-rc7-capex-funding-binding-v2`. Status: **stage 1 (monthly bridge and real-engine proof) and stage 2 (persistence, Save, Run binding, reconciliation) delivered.** Unsupported paths are listed in section 6.

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

## 5. Stage 2 - persistence, Save and Run consumption (delivered)
**Storage.** One canonical JSON document in the Working Copy snapshot under `capex_monthly_profiles_json` (`app/capex_profiles/config.py`, strict schema v1; only the authoring input is stored - shape plus parameters - and exact `Fraction` weights are derived at bind time). Being a snapshot key it is part of the composite workbook identity, is copied into every Run's runtime snapshot (historical Runs are immutable) and is inherited by scenarios.
**Ownership.** Leaves follow the Run's own sub-line fold (REPLACE semantics): a category with active sub-lines is owned by those sub-lines only (item key = sub-line business code); otherwise by its base amount (`base:<CapexStructure field>`). A parent and its children can never both own a profile. Derived/financing rows (contingency, IDC, fees, VAT costs, reserves) are not profile items. Note: the WF-09 V1 catalogue listed the base next to sub-lines, which the Run zeroes; V2 uses the Run's leaves.
**Save/Reset.** `app/capex_profiles/service.py::save_profiles` - one `BEGIN EXCLUSIVE` transaction with owner, protected-reference, scenario-selection and composite-identity CAS checks, `dirty=1` in the same transaction, and a pre-write proof that the candidate binds to the exact effective Run inputs. Rejects stale pages (`CAPEX_PROFILE_STALE`), unknown/orphaned leaves, duplicate keys, invalid sums/negatives/milestones, and any edit while a non-Base scenario is selected. Removing the document returns the identity to its exact pre-profile hash.
**Run.** `app/capex_profiles/runtime.py` runs after the folds in `v2_workbook_run` (and in one-driver sensitivity, Goal Seek, the two-driver matrix and the working-preview export). It installs the monthly typed `construction_financing`; the unchanged generic policy then treats construction as explicitly supplied and the canonical Stage B2 path computes everything. With no document it returns the same object (identity). A stored profile that cannot bind fails the Run closed with its typed code.
**UI.** The planner shows leaf items, the saved profile (pre-filled), the binding status, Save to Working Copy / Remove, and the Last Run reconciliation (freshness, whether the Run used the profile, per-period uses/sources/difference, hard CAPEX, IDC, fees, DSRA, total uses) read from the committed Run evidence.

### Proof on the real app (`tests/test_model_rc7_capex_profile_run.py`, real Solar project, real Run)
Save -> Working Copy dirty and Last Run STALE -> Run -> 14 monthly construction periods (3 by default), every period Sources = Uses, hard CAPEX unchanged, capitalised IDC moved, history of earlier Runs byte-identical -> Last Run CURRENT -> Remove -> identity back to the pre-profile hash -> Run reproduces the default financing evidence EXACTLY. Reference Solar 16 MW, 14 months, back-loaded on every leaf vs default (kEUR): IDC 136.35 -> 207.51, commitment fee 57.22 -> 45.20, structuring fee 67.31 -> 68.59, initial DSRA funding 464.41 -> 573.65, Senior debt 6,731.47 -> 6,858.71, total uses 8,975.29 -> 9,144.95. Total-uses movement = IDC + commitment + structuring + DSRA movements exactly (169.66 = 71.16 - 12.01 + 1.27 + 109.24); the DSRA term is the canonical fixed point re-sizing the reserve to the re-timed Senior debt service.

## 6. Unsupported / not bound (explicit, typed)
* **Commercial-stress comparison** (`v2_revenue_commercial_stress`) is an exact-source protected security function; it was NOT edited and still computes on default timing. Binding it needs an approved pinned-function successor.
* **Excel/PDF export of a Last Run executed with a monthly profile** is refused (`CAPEX_PROFILE_UNBOUND_SURFACE`): its sub-line basis is the persisted identity, the binder reads live rows. The working-preview export binds.
* **Legacy `/run`, compare, download, save-run and legacy sensitivity/scenario routes** (main_web) are refused through a guarded snapshot builder rather than silently running default timing.
* Scenario-specific profiles (a scenario inherits the Base profile but cannot own one), Junior / Multi-Senior projects, a project with an explicit typed construction input or manual financing costs (including a bankability fee override), per-period Senior pricing vectors, an enabled VAT facility, SHL accrual tails, and a financial close whose semester boundaries are not month boundaries.
* Surfaces audited as non-engine (display / validation) are listed in `tests/test_model_rc7_capex_binding_surfaces.py`; a new CAPEX-folding surface fails that test until it binds, refuses, or is reviewed.

## 7. Governance
No edit to `finco_core/`, `financial_engine/`, `period_engine.py`, `axis_contract.py`, `orchestrator.py`, `adapters/project_inputs.py`, Revenue/PPA, Credit Decision, or any pinned protected function (the pin test caught and reverted an attempted edit of the commercial-stress function). The planner router now has two CSRF-protected POSTs (preview, Save); `tests/wf09_csrf_successor.py` was extended and re-pinned (31 drift mutations, each rejected structurally except a byte-only edit, which fails the pin). **This successor, like the first, is a review proposal and needs independent approval.** The WF-09 Chromium module is still mandatory in the `import` role and now has a third node and screenshot (Save and Reset in a real browser).
