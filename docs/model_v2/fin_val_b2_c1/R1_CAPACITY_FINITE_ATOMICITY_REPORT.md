# WF-1B — R-1 finite derived amounts and atomic capacity rescale

Base main `8944aca351ef89c81a8a9bf715ab352629c35624`.

## Reproduced facts (Stage A, main)
Saving a very large capacity (`project_setup.technical.capacity_mw`) made `rescale_reference_seeded_project` (`app/services/reference_seed_service.py`) write non-finite derived values into the draft and the seeded sub-lines while still returning success (HTTP 200):

| Case | capacity | `total_capex_keur` | page |
|---|---|---|---|
| Solar | 1e305 | 5.15625e307 (finite) | 200 |
| Solar | 1e306 / 5e307 / 1e308 | `inf` (and `opex_y1` `inf` from 5e307); non-finite CAPEX sub-line amounts persisted | 500 |
| Wind | 1e306 / 5e307 / 1e308 | same pattern | 500 |
| Data Center, EV Charging | 1e305 and above | `inf` already at 1e305 | 500 |

The CAPEX/OPEX sub-line rows had already been rewritten when the failure showed — the rescale was **not atomic** (the SQLite connection is autocommit, `isolation_level=None`, so `get_cursor` rollback does nothing).

## Root cause
No finiteness check on `capacity × unit-cost`-style products, and no transaction boundary around the multi-table rewrite.

## Implemented (SAFE ENGINEERING CORRECTION — mathematical guard, not a business cap)
* `NonFiniteDerivedAmountError` and `_require_finite`; every derived amount is checked before persistence: each rescaled CAPEX/OPEX line, the totals, EV B.08, DC power, and the 12-significant-digit formatted values that are stored.
* `rescale_reference_seeded_project` runs in one explicit `BEGIN IMMEDIATE … COMMIT` transaction with `ROLLBACK` on any exception; `save_workspace_state` is called only after a successful commit. A `_dry_run=True` path and `preflight_capacity_rescale(...)` evaluate everything and always roll back.
* `app/workbook/update_service.py`: `apply_draft_update` runs the preflight for `project_setup.technical.capacity_mw` **before** the CAS and refuses with `FieldValidationError` (class INVALID, text “…would exceed the representable numeric range. Nothing was changed.”).
* No economic maximum is introduced. Every finite capacity that previously worked still works and produces **byte-identical** line amounts (test oracle reproduces the previous algorithm verbatim).

## Evidence
* Stage A fix check (disposable DBs, 4 technologies × 1e305/1e306/5e307/1e308): refused cases leave the database byte-identical (`db_identical_after=true`), the page stays 200, capacity stays 16; Solar/Wind 1e305 remain accepted with all lines finite; Data Center / EV Charging 1e305 are now refused (their derived totals are not finite).
* `tests/test_fin_val_b2_c1_recovery_finite_opex.py::TestCapacityRescaleFiniteness`: refusal for 3 non-finite capacities × technologies with nothing written; large finite capacity applied with all derived amounts finite; **normal rescale bit-identical to the previous algorithm**; preflight never writes; stale CAS still changes nothing.
* Main-vs-branch Run parity: see `OPEX_FINANCIAL_IMPACT_REGRESSION.md` (capacity 30 MW included).
* B1 test `test_residual_capacity_overflow_never_yields_a_plausible_value` is replaced by `test_residual_capacity_overflow_is_now_refused_atomically_by_the_finite_guard` (the documented residual is closed; the assertion is stronger: unchanged draft + explicit refusal text).

## Deferred / risks
* A *finite but economically absurd* capacity (e.g. 1e305 MW Solar) is still accepted: that is D-028 (economic warning/limit policy) and is a Financial Owner decision, not engineering.
* Data Center / EV Charging now refuse capacities from about 1e305 MW whereas the display layer rendered them — they were already non-finite, so no previously valid input is lost.
