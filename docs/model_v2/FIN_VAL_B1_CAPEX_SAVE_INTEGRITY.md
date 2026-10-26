# FIN-VAL V1 / Stage B — Correction B1: CAPEX Save integrity and precision-safe display

Base: main `80dbe67b42052ba7797f1466eb66e466aa1e3896` (tree `8891b56b2f15531bbcb14a383aaeccb5363e6d5f`). Scope is limited to two behaviours approved by the independent Stage A review (SC-2, SC-4). No economic maximum, solver, Run, router, CSRF, Run History or financial result is changed.

## SC-2 — CAPEX Save contract aligned with the canonical adapter
`app/input_adapter.py` already rejects a negative value for each of the 14 scalar CAPEX snapshot keys (`_SCALAR_CAPEX_MAP`, `non_negative=True`). The registry did not, so a negative amount could be saved but the saved draft could not be read back (workbook page 500, React inputs 503). `min_value=0` is added to exactly the 14 editable, `BOUND` `capex.C.*` / `capex.D.*` amount fields in `app/workbook/registry.py`; the set of those fields equals `_SCALAR_CAPEX_MAP` (asserted by a test). Derived, display-only and template-locked CAPEX rows, OPEX fields and every other registry bound are unchanged. Single-field Save and grid/batch Save both run `validate_field_update`, so the one registry change covers both routes; the grid route refuses the whole batch (422 `GRID_VALIDATION_FAILED`, nothing committed). Stored drafts are never rewritten.

## SC-4 — precision-safe `allocate_parent_amount`
The function quantised `total × weight` to `1e-8` under the default 28-digit Decimal context, which raises `decimal.InvalidOperation` for a parent amount of about `1e20` kEUR or more. The Decimal arithmetic now runs in a local context whose precision is `max(default, adjusted_exponent + places + 2)`. Weights, child order, `ROUND_HALF_UP`, the 8-place quantum and the last-child residual are unchanged; the process-wide context is not touched. A test reproduces the previous algorithm verbatim and shows float-for-float identical output for about 47,400 normal-range allocations (76 CAPEX/OPEX child sets across the supported technologies, 312 amounts, both signs, up to `9.9e18`).

The function is also used when reference projects are seeded, rescaled or cost templates are built (`reference_seed_service.py`, `cost_template/generic.py`), not only for display. For every input that previously succeeded, the output is identical; only inputs that previously raised now return values.

### Non-finite parent amounts (residual edge)
A non-finite parent amount now raises `NonFiniteParentAmountError` (a `ValueError`) before any arithmetic. It is never rounded, zeroed or replaced. The only documented effect for callers is a clearer exception instead of `InvalidOperation`.

## Residual R-1 — very large capacity (not closed here)
After SC-4 the workbook page renders for capacity up to `1e305` MW (verified: 1e18, 1e100, 1e200, 1e250, 1e290, 1e300, 1e305). From `1e306` MW the capacity rescale writes non-finite derived totals (`total_capex_keur` = `inf`, and from about `5e307` also `opex_y1_keur`) into the draft snapshot, after which the page still fails (now with `NonFiniteParentAmountError`). The persisted non-finite values are produced by `rescale_reference_seeded_project` (`app/services/reference_seed_service.py`) and applied by the capacity Save path in `app/workbook/update_service.py`; recovery also needs the unreadable-draft page handling in `app/v2/router.py` (SC-3). Both are outside this PR's authorised files and security-owned respectively. No claim is made that all overflow or poisoned-state paths are closed.

## Other baseline observation (pre-existing, unrelated, not changed)
On pristine main, saving positive values into six of the CAPEX scalar fields one after another (the sixth being `capex.C.insurances`) makes `/v2/workbook` return 500 (`BookDepreciableAssetBasis.components has duplicate codes ['Unused', …]`, `financial_engine/book_basis.py`). Reproduced on `80dbe67` without this change; each field alone is fine.

## Governed sources
| Path | Original blob | New blob |
|---|---|---|
| `app/workbook/registry.py` | `4e4d3b46371db567dad3b88e1123d3d924639fb4` | `0601ffe8216eb634036d347732c66a15e0729043` |
| `app/reference_detail_catalog.py` | `9b2e91321f5e84a70c77756bd9b954b35ecee532` | `d41c2211e811df0e2bef9ac144399c9016fab5bc` |

Neither blob is pinned by an exact-content test at its current value in this repository; the historical RC-2 pin for `registry.py` (`4f9c5192…`) is a release-time pin evaluated against its recorded reference, not a current-HEAD pin, and is not modified or relaxed. No governance inventory, CI manifest or protected golden file is edited. Financial engine, `finco_core/`, `app/v2/router.py`, `app/v2/grid_router.py`, CSRF/Run/Clone security and Run History are untouched.

## Evidence
`tests/test_fin_val_b1_capex_save_integrity.py` (disposable databases, real canonical routes and fixtures): per-field negative rejection through single and grid Save (14 + 14 cases), atomic non-commit of a valid sibling cell, zero/positive acceptance with identical effective `ProjectInputs`, unchanged bounds elsewhere, CAS/CSRF/version/scenario/ownership guards unchanged, legacy stored negative drafts left byte-identical, SC-4 bit-identity oracle, large-amount reconciliation, non-finite refusal, page rendering at 1e18–1e305 MW, and the documented `1e308` residual.

## Not part of this PR
SC-3 unreadable-draft recovery, derived-total finiteness guard in the capacity rescale, economic warning/limit policy (D-028), IRR verification and status propagation (N-1/N-2), Run idempotency (D-029), and any change to `app/v2/router.py`.
