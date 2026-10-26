# WF-1C — CAPEX duplicate `Unused` component

Base main `8944aca351ef89c81a8a9bf715ab352629c35624`.

## Reproduced facts (Stage A, re-run on main in this session)
Saving a positive value into a second CAPEX scalar field whose category holds a *placeholder-named* item makes the next page render and the next Run fail with `ValueError: BookDepreciableAssetBasis.components has duplicate codes: ['Unused', 'Unused']` (`financial_engine/book_basis.py`, called from `financial_engine/adapters/project_inputs.py:256`):

| Technology | First field that fails (14 fields saved in registry order) |
|---|---|
| Solar | `capex.C.insurances` |
| Wind | `capex.C.ops_preparation` |
| Data Center | `capex.C.lease_tax` |
| EV Charging | `capex.C.lease_tax` |

The Run POST answered HTTP **500**, yet a Run history row **was committed** before the failing page render (probe on main: one row after one 500 answer; a second submission adds another). The user therefore sees an error while a result exists, and a retry creates a further row. That commit-before-response behaviour is the D-029 neighbourhood (Run commit/history) and is deliberately **not** changed here; removing the 500 removes the trigger, not the underlying ordering.

## Root cause
`app/input_adapter.py::_apply_scalar_capex` writes the scalar amount into a category's single `CapexItem`. For categories without a named seeded item the template carries a placeholder `CapexItem(name="Unused")`; the adapter kept that name. The generic builder in `book_basis._build_generic_basis` keys depreciable components by `item.name`, and `BookDepreciableAssetBasis` rejects duplicate codes, so two active placeholder-named items collide.

## Implemented (SAFE ENGINEERING CORRECTION)
* `_apply_scalar_capex` gives a placeholder-named item the *field's canonical label* as its name (deterministic, unique per field); a collision falls back to `"{label} [{field_name}]"`. Only placeholder names are touched: a named item (e.g. “Grid connection”) keeps its name.
* **Amounts, categories, asset classes and depreciation lives are unchanged.** The engine, `book_basis.py` and the builder are untouched.

## Evidence
* `TestPlaceholderCapexIdentifiers`: 14 sequential positive edits keep the page readable on all four technologies; a Run after two placeholder edits **commits** and equals, metric by metric (total CAPEX 8,250.0 Solar / 14,333.333 Wind, Project IRR, Equity IRR, DSCR, senior debt, revenue, EBITDA, tax, distributions, depreciation total, financial-statement hash), the single-edit result; unique deterministic names; named items keep their names.
* The two scalar edits are *decorative* for the Run in seeded copies (CAPEX sub-lines replace the category bases): the 14 scalar edits changed no Run total in any technology (Stage A matrix). That is a Financial Owner topic, not changed here.

## Deferred / risks
* The same-named-component collision could in principle also occur if a user names two cost lines identically; that is outside this root cause and not changed.
