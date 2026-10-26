# OPEX / financial impact regression (bit parity main vs branch)

## Method
The same harness (`parity.py`, real canonical routes, disposable databases, 16 MW reference-seeded Working Copies) was executed once against a pristine worktree of main `8944aca351ef89c81a8a9bf715ab352629c35624` and once against the branch working tree. For each of Solar and Wind: default Run, `revenue.ppa.base_tariff = 60` then Run, `project_setup.technical.capacity_mw = 30` then Run. The persisted `runtime_summary_json` of the committed Run (all headline financials, DSCR, IRRs, totals, statements digest inputs) was compared after removing only the per-run identity fields that are different by construction on every execution: `binding.snapshot_id` (a timestamp), `binding.composite_hash` and `digest` (derived from that timestamp).

## Result
| Case | Run rows | sha256 main (first 16) | sha256 branch (first 16) | Result |
|---|---:|---|---|---|
| solar/capacity30 | 1 | 49ee19a3c65fc8d0 | 49ee19a3c65fc8d0 | **identical** |
| solar/default | 1 | d1973ca21c17aabb | d1973ca21c17aabb | **identical** |
| solar/tariff60 | 1 | 383df1832fb3303f | 383df1832fb3303f | **identical** |
| wind/capacity30 | 1 | 2ed6714d5154c8ed | 2ed6714d5154c8ed | **identical** |
| wind/default | 1 | 30437ad30fd9d2fe | 30437ad30fd9d2fe | **identical** |
| wind/tariff60 | 1 | 30437ad30fd9d2fe | 30437ad30fd9d2fe | **identical** |

All six Runs are **bit-identical** in every financial field. (Wind with tariff 60 equals Wind default on both sides: the PPA base tariff is not the active revenue input for that Wind reference; unchanged by this PR.)

## What changes a number, and what does not
* **No financial number changes** for any previously valid input: engine, solver, tolerances, goldens and `finco_core/` are untouched; the OPEX fold, adapter mapping and Run endpoint are untouched.
* **Capacity rescale** produces the same line amounts as before for every finite result (oracle in the test module reproduces the previous algorithm verbatim; also covered by the 30 MW parity Run).
* **Placeholder CAPEX identifiers** change only an item *name*; two placeholder edits give the same Run metrics as one (Solar total CAPEX 8,250.0; Wind 14,333.333…; IRRs, DSCR, depreciation, statements hash all equal).
* **OPEX non-negative floor**: a negative scalar was ignored by the engine (`max(0.0,…)`), so a stored `-100` produced a Run identical to baseline (3,027.523 kEUR Solar total OPEX). It is now refused at Save instead of being silently ignored; **no Run value changes** for any input that was previously saved as non-negative.
* **OPEX read-only presentation** changes the UI affordance only; for a shadowed group the Run did not depend on the cell before either (Δ Run = 0 in the matrix).

## Per-field Run deltas
See `OPEX_FIELD_TO_ENGINE_AUTHORITY_MATRIX.md` for each OPEX field × technology (edit 25 and 60) and `FINANCIAL_OWNER_DECISION_REGISTER.md` for the methodology items not implemented.

## Test evidence
`tests/test_fin_val_b2_c1_recovery_finite_opex.py` — 68 tests, all pass; B1 module — 77 pass (four assertions updated to the new, stronger behaviour, listed in the executive review).
