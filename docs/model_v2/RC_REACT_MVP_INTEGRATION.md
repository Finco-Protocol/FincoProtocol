# RC-REACT-MVP — final product integration

Base: `origin/main` `d745b69bbb491525bbc90d10aafff3b8d5f26f82` (tree `d6fcadb322c87411803139277ba655c9ddf5cd65`), which contains
#375, #376, #377, #378 and #379. Branch `feat/model-rc-react-mvp-integration`.

Scope: React source, generated assets, docs and tests only. **No** change to the financial engine, any backend router or service,
`app/v2/router.py`, the CAPEX/OPEX routers, CSRF/security authority, protected tests, RC-SEC inventories, tolerances or goldens. The
parallel RC-SEC correction is untouched.

## What is connected

| Surface | Integration |
|---|---|
| **Analysis** | `FinancialInsights({ project })` (WF-React-3, unchanged) below the Last Run charts. Explicit one-to-three committed-Run selection; Credit Dashboard (min/avg DSCR, min LLCR when persisted, debt capacity/structure, CFADS and debt-service timeline with data tables), canonical findings, historical Run intelligence, sponsor/equity returns, evidence disclosures. A scope note separates "Last Run charts" from "explicitly selected committed Runs". |
| **Scenarios** | The obsolete "KPI comparison unavailable" notice is replaced by `ScenarioKpiComparison`: a thin container over the existing insights client and components (no new data layer). Nothing is selected or read automatically; the active scenario is never used as a substitute; assumption compare (saved assumptions) stays separate from committed-Run results. Per-scenario committed-Run availability now comes from the same canonical history, so the Base Case row, each scenario and the comparison agree. |
| **Results** | Stale statement about DSCR corrected; links to deeper analysis and committed scenario comparison. |
| **Lifecycle** | PR #378's registries, navigation guard, single-flight Run, protected-reference behaviour and export are unchanged; the insights surfaces are read-only (GET, same-origin, no-store) and never save, run, reset a draft or change the selected scenario. |
| **UX closeout (D-031)** | `rc-react-mvp.css`: 44px touch targets for tabs, breadcrumb/library/legacy links, bar and dialog buttons, inputs and the Run selector at ≤820px or coarse pointers; long identifiers and scenario names wrap; scenario names are limited to the server's 80 characters in the client. Same three themes, no new theme. |

## Verified findings forwarded (not fixed here)

* With an explicit contract book, the canonical Run refuses a scenario whose override is a tariff alias
  (`REVENUE_V2_SCENARIO: replace the explicit contracts, not legacy PPA aliases`). The override can be saved but the Run is refused. The
  supported scenario override for such projects is the scoped contract edit, which is what the acceptance uses. Forward to the model workstream.
* The first Run on a never-opened Working Copy commits but leaves the draft STALE (second Run → CURRENT); reproduced on pristine main.
* CAPEX/OPEX line routes, scenario routes, ordinary registry-field writes and export carry no CSRF token on main → RC-SEC workstream.

## Unsupported, intentionally not activated

PLCR and any metric without approved persisted evidence (shown as Unavailable), blank-project creation, spending-profile save, Sensitivity,
Goal Seek, V3 revenue products, multi-tranche/mezzanine/BESS facilities.
