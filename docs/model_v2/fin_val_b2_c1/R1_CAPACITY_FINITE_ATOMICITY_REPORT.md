# WF-1B — R-1 finite derived amounts and atomic sub-line rescale (full capacity Save is NOT atomic — see the final section)

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


## ATOMICITY SCOPE — corrected statement (Correction A audit, failure-injection evidence)

**Earlier wording ("the capacity rescale is atomic") is only true of the sub-line phase.** The user-visible capacity Save is three separately committed phases (`app/workbook/update_service.py::apply_draft_update` → `app/services/reference_seed_service.py::rescale_reference_seeded_project`):

1. `v2_atomic_draft_update` — CAS write of the new `capacity_mw` into the draft (commits);
2. `rescale_reference_seeded_project` — one `BEGIN IMMEDIATE … COMMIT` over the CAPEX/OPEX sub-line UPDATEs and the reconciling sums (commits; atomic *within itself*, introduced by this PR);
3. `save_workspace_state` — unconditional (non-CAS) write of a reconciled snapshot built from a snapshot read **before** phase 2 (commits).

The non-finite preflight (dry run, rolled back) runs before phase 1, so the *expected* overflow case is refused with nothing written. It does not protect against an unexpected exception or a concurrent writer after phase 1.

### Deterministic evidence (disposable databases, Solar 16 MW → 30 MW Save; harness `r1_atomic.py`, outputs `r1_atomic_branch.json` / `r1_atomic_main.json`)
| Scenario | HTTP | Draft/lines/profile consistent afterwards | Persisted differences vs before |
|---|---:|---|---|
| S0 normal Save (control) | 200 | yes | {'capacity_mw': ('16', '30'), 'snap_total_capex': ('8250', '15468.75'), 'snap_opex_y1': ('95', '178.125'), 'profile_seed_capacity': (16, 30.0), 'lines_capex_sum': (8250.0, 15468.75), 'lines_opex_sum': (95.0, 178.125)} |
| S1 unexpected exception inside the sub-line transaction (after phase 1) | 500 | **NO** | {'capacity_mw': ('16', '30.0')} |
| S2 exception in phase 3 `save_workspace_state` (after phase 2 committed) | 500 | **NO** | {'capacity_mw': ('16', '30.0'), 'lines_capex_sum': (8250.0, 15468.75), 'lines_opex_sum': (95.0, 178.125)} |
| S3 a competing valid, committed Save (tariff 50 → 77) lands between phase 2 and phase 3 | 200 | yes | {'capacity_mw': ('16', '30'), 'snap_total_capex': ('8250', '15468.75'), 'snap_opex_y1': ('95', '178.125'), 'profile_seed_capacity': (16, 30.0), 'lines_capex_sum': (8250.0, 15468.75), 'lines_opex_sum': (95.0, 178.125)} |

* **S1 (branch):** the sub-line transaction rolled back (line sums unchanged — this PR's guarantee holds), but phase 1 already committed `capacity_mw = 30.0`; the draft totals and `seed_capacity_mw` stay at the 16 MW values → **half-updated persisted state** (capacity new, lines/totals old). (S1 cannot be injected the same way on main, which has no finiteness hook; main's sub-line updates were never transactional.)
* **S2 (main and branch, identical):** capacity and line amounts at 30 MW, but draft `total_capex_keur`, `opex_y1_keur` and `_reference_seed_profile.seed_capacity_mw` still describe 16 MW → **half-updated state**.
* **S3 (main and branch, identical):** the competing committed tariff write returned success and was then **silently overwritten** (tariff back to 50.0) by phase 3's unconditional save of the stale pre-phase-2 snapshot → **lost update**.
* **S4:** the expected non-finite capacity (1e308) is refused with every persisted byte unchanged (this PR's fix works for the case it targets).

### Classification
* S2 and S3 are **pre-existing** (same on main); S1 is the same defect class seen through this PR's new transaction boundary. None is a regression, but **this PR must not claim a fully atomic capacity Save**.
* Reported as a **separate material acceptance finding: BLOCKED — MATERIAL ATOMICITY FINDING** for a claim of full R-1 closure. What *is* closed: non-finite derived amounts can no longer be persisted by the expected input path; the sub-line rewrite is all-or-nothing.

### Smallest safe all-or-nothing design (proposed, NOT implemented — needs exact-path owner authorisation)
Perform the capacity edit, the sub-line rescale and the reconciled snapshot write in **one** `BEGIN IMMEDIATE` transaction on one connection:
1. new `workspace_repository.v2_atomic_capacity_update(...)` (sibling of `v2_atomic_draft_update`): inside the transaction re-read the draft, verify the composite content hash (same CAS as today), apply the capacity field;
2. run the existing sub-line `_apply` logic with that **same cursor** and build the reconciled snapshot from the **in-transaction** snapshot (never from a snapshot read earlier);
3. write the snapshot in the same transaction; `COMMIT`; any exception → `ROLLBACK` (database byte-identical);
4. keep the dry-run preflight as the early user-facing refusal, keep operation CSRF, CAS, ownership and "no implicit Run" unchanged; no economics, rounding or override semantics change (user-override rows are still skipped).
Permanent regression tests: S1–S3 above become assertions (fault → database byte-identical; competing write is serialised, never lost). Files: `app/persistence/workspace_repository.py`, `app/services/reference_seed_service.py`, `app/workbook/update_service.py` (none pinned by the SEC-02/RC-SEC inventories at current main).
