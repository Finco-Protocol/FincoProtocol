# RC-5A — Scenario effective-input authority

**Rule.** A scenario override may be saved or Run only if the canonical Run provably consumes it.
The single admission authority is `app/workbook/scenario_override_authority.py`
(`unbound_override_keys`). Anything else fails closed with the typed error
`SCENARIO_OVERRIDE_UNBOUND`.

## Why

The canonical Run (`v2_workbook_run`) builds `ProjectInputs` from the **Working Copy draft**.
Scenario overrides reach the engine only through (a) `bind_scenario_tariff`, (b) approved CAPEX/OPEX
sub-line and contingency folds, (c) contract payload keys, and (d) the reviewed Q4 What-if single
candidate key. Before RC-5A the editor offered eight scalar fields; seven were saved, displayed and
"successfully" Run while having **no effect** on the result (empirically verified on Solar and Wind).

## Field-by-field authority matrix

| UI field | Workbook field | Registry scenario policy | Canonical Run binding | RC-5A behaviour |
|---|---|---|---|---|
| `tariff_eur_mwh` | `revenue.ppa.tariff_legacy` → `revenue.ppa.base_tariff` | not_allowed (legacy alias) | **RUN_CONSUMED** via `bind_scenario_tariff` (Solar/Wind) | Save OK, Run OK |
| `p50_hours` | `project_setup.technical.p50_hours` | override | none (draft only) | Save rejected 422; saved value → Run refused |
| `opex_y1_keur` | `opex.summary.total_y1` | not_allowed | none (aggregate scaling not introduced) | rejected / refused |
| `total_capex_keur` | `capex.summary.total` | not_allowed | none (aggregate scaling not introduced) | rejected / refused |
| `gearing_pct` | `debt.senior.gearing_pct` | override | none; Q4 What-if only | rejected / refused (Q4-reviewed What-if alone stays admissible) |
| `interest_rate_pct` | `debt.senior.interest_rate_pct` | override | none | rejected / refused |
| `tenor_years` | `debt.senior.tenor_years` | override | none | rejected / refused |
| `target_dscr` | `debt.senior.target_dscr` | override | none; Q4 What-if only | rejected / refused (Q4-reviewed What-if alone stays admissible) |

Payload keys (`rev_multistream_config_json`, `bess_native_config_json`, `developer_economics_json`)
keep their own CAS-protected editors/authorities and are not touched.

## Behaviour

* **Save** (`/workbook/scenarios/update-overrides`): all-or-nothing, rejected with HTTP 422 JSON
  (`code`, `unbound_fields`, `supported_fields`) before any write.
* **Run** (`/workbook/run`): a previously saved unbound override refuses the Run **before the engine and before any
  commitment**; prior Run, history and draft are untouched. The values stay visible ("Not applied to Run") and
  removable through the existing `remove-override` path.
* **Editor**: the seven non-binding inputs are disabled; the false “aggregate CAPEX/OPEX” hint is replaced by the real contract.
* **Create**: a repeated submission or case-insensitive name clash returns 409 `SCENARIO_NAME_DUPLICATE`
  (checked inside the insert transaction; archived names may be reused).
* **Status truthfulness**: the Trust pack reads the project's latest committed Run. When the Last Run is not proven to be the
  *active* scenario's, the Integrity verdict is withheld (`UNAVAILABLE`, with a note) in the status strip, Trust sheet and Smart
  Panel. Freshness (CURRENT/STALE/NOT RUN) semantics are unchanged; switching only moves the active pointer.

## Not changed

Protected financial formulas, debt sizing, goldens and tolerances, aggregate CAPEX scaling, F3 financing inheritance
(child scenarios do not inherit or invent a multi-Senior scope), release activation.

## Financial-policy decisions left open

1. Bind `gearing_pct` / `target_dscr` / `tenor_years` / `interest_rate_pct` / `p50_hours` through the canonical resolver (each is a debt-sizing or
   energy-yield decision; needs the financial owner) — or retire the dead editor fields.
2. Define semantics (or retire) aggregate `total_capex_keur` / `opex_y1_keur` overrides versus approved sub-line controls.
3. Whether child scenarios should inherit an activated F3 multi-Senior base scope.
4. Trust-pack identity/KPI sections still describe the project's latest committed Run under a scenario with no Run of its own
   (only the Integrity verdict is withheld here).
