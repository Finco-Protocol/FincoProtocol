# F3.9 Cross-vertical financial integration and numerical validation V2

## Provenance and boundaries

Base: `origin/main` `cff1a7b19a72429636ec20325aadf5364365b12d`. Branch `feat/model-f39-numerical-validation-v2`.
One integrated Draft PR. No approval, merge, deployment, rebase, squash or force push.

ZERO modifications to `financial_engine/`, `finco_core/`, `domain/`, `app/` production code, governance release pins,
existing tolerances, goldens or CI workflows. Junior production activation remains `False`; Senior+Junior coverage uses
only the already-authorised test-only fixture (`ACTIVATION_ENABLED` patched inside tests). The deliverable is a
**validation workflow**, not a second project-finance engine: it recomputes identities from persisted evidence and
compares; it never produces a number the product then uses.

## 1. Capability inventory

| Capability | State | Treatment |
| --- | --- | --- |
| P0-B3 two-snapshot framework (`reconcile.compare`, dependency stages, PASS/FAIL/UNAVAILABLE/NOT_COMPARABLE, canonical bytes, private output) | EXISTING | reused (stages, states, `canonical_bytes`, `_private_output`, error type) |
| Decimal oracles (`revenue`, `allocation`, `debt_rollforward`, `interest`, `sources_uses`, `cash_conservation`, `balance_sheet`, `discounted_cashflows`, `check`) | EXISTING | reused unchanged; added `debt_service`, `ebitda`, `ebit`, `dscr`, `cash_after_service`, `sum_of_periods`, `cfd_settlement`, `energy_revenue`, independent Decimal `xirr` |
| Immutable owner-scoped Run History (statements 2dp, schedules, full-precision integrity evidence, identity fields) | EXISTING | read-only source |
| F0/F1/F2/F3.7/F3.8, Revenue V2, statements and Run Integrity tests and tolerances | EXISTING | tolerances reused verbatim; tests untouched |
| Read-only persisted-evidence extraction for four verticals | MISSING → added | `evidence.py`, `source.py` |
| Period-by-period, tolerance-explicit, earliest-divergence reconciliation | MISSING → added | `periodic.py`, `identities.py` |
| Four-vertical coverage matrix | MISSING → added | `coverage.py` |
| Project/Equity NPV, unlevered project cash-flow vector, facility-level tax, price path | UNSUPPORTED | reported UNAVAILABLE, never synthesised |
| Investor-specific returns | UNSUPPORTED here | F4 scope |
| External workbook parity | UNSUPPORTED | no authorised independent workbook exists in the repository; **no parity is claimed** |

## 2. Workflow

`bundle_from_history_entry(entry)` → evidence bundle (schema `FINCO_NUMERICAL_EVIDENCE_V1`) bound to project, scenario,
immutable Run key, snapshot id, composite content hash, configuration digest, engine version and a SHA-256 of the
persisted payloads → `reconcile_bundle(bundle)` → deterministic `report.json/.csv/.md`; `coverage.render(results)` →
`coverage.json/.csv/.md`. CLI: `python -m tools.numerical_validation.verify --db … --owner … --project … --output …`
(or `--bundle`). Exit 0 = nothing failed or unverifiable, 2 = a validation verdict (FAIL/UNAVAILABLE/NOT_COMPARABLE),
3 = malformed input. Reports go only to private locations.

Rules enforced by code and tests: Decimal throughout; exact-period alignment by ISO date and phase (duplicate, missing
or conflicting axes are withheld and reported, never repaired); declared units (a series carrying the wrong unit is
withheld and reported `UNIT_MISMATCH`); independent totals versus period sums; relative and absolute residuals,
signed; first divergence in dependency order with later FAILs labelled `DOWNSTREAM_OF_EARLIER_DIVERGENCE`; input
records (`INPUT_MISMATCH`) separated from calculation (`CALCULATION_MISMATCH`); absent evidence is `UNAVAILABLE`, never
zero; unprovable alignment (construction cross-payload) is `NOT_COMPARABLE`; facility attribution is never inferred.

## 3. Tolerances

| Policy | Value | Origin |
| --- | --- | --- |
| `KEUR_FULL_PRECISION` | 1e-6 kEUR | `app/run_integrity/contracts.py` `TOL_KEUR`; `FINANCE_TOLERANCE_KEUR` (asserted equal by test) |
| `KEUR_PERSISTED_2DP` | 1e-6 kEUR **plus** a separate half-quantum (0.005) representation allowance per non-zero value persisted rounded | same financial tolerance; the allowance only bounds F3.8 2-decimal serialisation and is reported separately |
| `RATIO` | 1e-7 | `check_dscr_identity`: `TOL_RATIO` × 100 |
| `XIRR` | 1e-9 | `TOL_XIRR` |
| `MWH_DISPLAY_ROUNDING` | 0.5 MWh | representation bound; generation is persisted only as whole-MWh display text; used solely by the allocation check |

Nothing is relaxed per identity, vertical or Run.

## 4. Financial identities verified (per Run, period by period)

Axes and units; day-fraction vs day-count; revenue total vs period sum and vs statements; EBITDA = revenue − opex
(summary, statements, cash waterfall); EBIT and depreciation; Sources & Uses conservation (including the Financial
Close use outside construction when recorded); financing draws, Senior IDC, commitment and upfront fees vs S&U;
CAPEX link; Senior and per-facility debt roll-forward (opening + draws − principal = closing; consecutive openings),
interest = opening × rate × day fraction, debt service = interest + principal, aggregate Senior = Σ facilities;
Junior facility roll-forward, Junior cash IDC vs its own record; Senior interest/closing/service vs P&L, balance sheet
and cash waterfall; balance-sheet identity; tax total, cash-tax link and loss movements where the audit fields are
persisted; CFADS − Senior service = cash after Senior; statement CFADS/service links; distribution totals; pure- and
total-sponsor flows, independent Decimal XIRR, and link of reported IRR to the recomputation. Revenue V2 contract runs:
energy revenue = Σ quantity × price / 1000; signed two-way CfD settlement = quantity × (strike − reference) / 1000
(negative when strike < reference, exercised at strike 40 vs 90); net revenue = Σ streams − balancing + certificate;
net vs `revenue_period`; physical allocation vs generation.

## 5. Four-vertical coverage

Results below are the executed tests (`tests/test_f39_four_vertical_acceptance.py`); the full per-identity matrix is
generated by `coverage.render` and asserted free of FAIL.

| Configuration | PASS | FAIL | UNAVAILABLE | NOT_COMPARABLE | Largest residual (identity, kEUR, basis) |
|---|---:|---:|---:|---:|---|
| solar/legacy | 938 | 0 | 26 | 0 | REV-STATEMENT-TOTAL, 0.013829, PERSISTED_2DP |
| solar/two | 1043 | 0 | 16 | 0 | TAX-TOTAL, 0.019592, PERSISTED_2DP |
| solar/junior | 1102 | 0 | 12 | 2 | REV-STATEMENT-TOTAL, 0.013829, PERSISTED_2DP |
| wind/legacy | 979 | 0 | 27 | 0 | EBITDA-TOTAL, 0.040528, PERSISTED_2DP |
| wind/two | 1087 | 0 | 17 | 0 | EBITDA-TOTAL, 0.040528, PERSISTED_2DP |
| wind/junior | 1146 | 0 | 13 | 2 | EBITDA-TOTAL, 0.040528, PERSISTED_2DP |
| data_center/legacy | 766 | 0 | 27 | 0 | EBITDA-TOTAL, 0.014303, PERSISTED_2DP |
| data_center/two | 961 | 0 | 17 | 0 | EBITDA-TOTAL, 0.014303, PERSISTED_2DP |
| data_center/junior | 1020 | 0 | 13 | 2 | EBITDA-TOTAL, 0.014303, PERSISTED_2DP |
| ev_charging/legacy | 691 | 0 | 25 | 0 | EBITDA-TOTAL, 0.032795, PERSISTED_2DP |
| ev_charging/two | 945 | 0 | 15 | 0 | EBITDA-TOTAL, 0.032795, PERSISTED_2DP |
| ev_charging/junior | 1004 | 0 | 11 | 2 | EBITDA-TOTAL, 0.032795, PERSISTED_2DP |

Full per-identity matrix: `docs/model_v2/F3_9_COVERAGE_MATRIX.md` (generated by `coverage.render`). `NOT_APPLICABLE` marks identities with no subject in a configuration (for example per-facility checks in a legacy single-Senior Run, Junior checks without a Junior facility). The two NOT_COMPARABLE outcomes in each Senior+Junior Run are the reported Senior total and service that span Senior and Junior in the persisted statements, which cannot be compared to the Senior-only recomputation.


## 6. Residuals and limitations

* Every FAIL count is 0 across the 12 real configurations and the four Revenue V2 contract runs (Solar/Wind, strike 100 and 40). Largest residuals are on persisted 2-decimal statement totals (≤ 0.041 kEUR on a sum of many rounded terms), inside the separate representation allowance; full-precision identities close to ≤ 1e-9 kEUR (Revenue V2 ≤ 6.3e-10).
* Two definition corrections were made during validation, both to the validator, not the product: the Financial Close use outside the construction periods is now an explicit term of the Sources & Uses identity (otherwise a 464.4 kEUR residual appeared), and capitalised IDC in Sources & Uses is Senior IDC only, with Junior cash IDC checked against its own record.
* Reference financial drift: none; no engine output changed.

* Persisted statements are 2-decimal; their residual against full-precision evidence is bounded by the separate
  representation allowance and reported as such, never as a financial tolerance.
* Revenue V2 identities are available only for Solar and Wind contract runs; Data Center and EV Charging are
  disclosed as unsupported by Revenue V2 and reconcile on the legacy revenue path.
* Tax-loss identities need the persisted tax audit fields; where absent they are `UNAVAILABLE`.
* Project IRR cannot be recomputed independently (no unlevered cash-flow vector is persisted); NPV is not published.
  Both remain UNAVAILABLE.
* Construction-period payloads from different statements cannot be proven to share an axis; those cross-checks are
  `NOT_COMPARABLE`.
* Senior+Junior is validated through the controlled test-only path only. **No production Junior activation is claimed.**
* **No external Excel parity is claimed.** No authorised independent workbook reference is part of this repository;
  a comparison would need explicitly authorised data kept outside the public repository.
* Facility-level tax attribution and investor-specific returns (F4) are not evidenced and are not inferred.
* Staging acceptance is PENDING while staging tooling is unavailable.

## 7. Negative regression coverage

Negative residual on a real statement row (signed residual, earliest stage, classification); duplicate period (axis
`NOT_COMPARABLE`, `DUPLICATE_PERIOD`); missing period (coverage drops, never passes as zero); unit mismatch (series
withheld, `UNIT_MISMATCH_EUR_EXPECTED_kEUR`); tampered source (`SOURCE_HASH_MISMATCH`, `IDENTITY_MISMATCH_*`); missing
identity (refused); duplicate evaluation and unknown identity/stage/policy (refused); tolerance constants equal to the
product's; tools never import `financial_engine`/`finco_core`/`domain` and only `source.py` touches `app`.
CURRENT/STALE/Last-Run immutability: an input edit leaves the committed Run's evidence digest and reconciliation
byte-identical; a new Run is a new immutable record with a different configuration digest.

## 8. Remaining blockers

None in the code. Exact-head CI and independent numerical review are tracked on the Draft PR.
