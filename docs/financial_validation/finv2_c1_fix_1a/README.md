# FIN-V2-C1-FIX-1a — Senior Debt Transparency & Lender Evidence

Mode: additive, read-only financial **evidence**. No Senior Debt sizing, repayment, DSRA, IDC, gearing or any other engine arithmetic changed. No native kernel touched. Two-Senior restricted scope unchanged. Authorised by the Financial Owner's assigned prompt of 27 October 2026.

Baseline: main `128bf0c2b79af56985326543132cc806ff7f001c` (merge of PR #389). PR #388 verified open/draft, untouched.

## Why (the two "anomalies" are disclosures, not defects)

| Observation | Cause (already computed by the engine) | Where it is now disclosed |
|---|---|---|
| Solar/Wind/EV Senior is repaid several periods **before** its contractual maturity | The loan is **gearing-capped** (`binding_constraint = GEARING`; DSCR capacity is larger). The canonical DSCR-sculpted roll pays the whole DSCR debt-service budget, which retires the smaller gearing-sized balance early (`solver.py::_full_tenor_scale` docstring). | `financing_evidence.senior_debt_evidence.sizing.payoff_explanation = GEARING_CAP_BELOW_DSCR_CAPACITY_SCULPTED_BUDGET_RETIRES_DEBT_EARLY` |
| Data Center is DSCR-bound yet repaid at period 20 of 27 | Loan size is set by **interest cover in the first operating year (ramp-up)**: in period 5 the DSCR budget covers interest only (principal exactly 0.0) while bank CFADS is 29.8 % of the window peak; later CFADS growth retires the balance early. | `sizing.limiting_nature = RAMP_UP_INTEREST_COVERAGE`, `limiting_rows = [5]`, `limiting_context` |

## What is recorded (new Runs only) — `financing_evidence.senior_debt_evidence`

Schema `SENIOR_DEBT_EVIDENCE_V1`, produced by `app/run_integrity/senior_debt_evidence.py::build_from_clean_run` from the **same completed clean run** (no second calculation) and stored inside `financing_evidence`, so it inherits the Run's `run_binding` (snapshot id, composite hash, scenario). Every amount is copied at full precision.

- `repayment`: contractual repayment start (period/date), contractual maturity (period/date), first principal period, **actual extinguishment** (period/date), `periods_maturity_minus_payoff`, `days_maturity_minus_payoff`, `payoff_status`.
- `sizing`: engine `binding_constraint` (GEARING | DSCR | BOTH), `dscr_debt_capacity_keur` and `gearing_debt_capacity_keur` (kept distinct), the independent re-classification from the two capacities with a consistency flag, limiting rows and nature, `payoff_explanation`.
  - **Two DSCR capacities exist by engine design and are never merged**: the funded-pass diagnostic (what the loan is the minimum of) and the standalone DSCR-only capacity pass (what `bankability` reports). They are equal for Wind/DC/EV; Solar differs by 6.02 kEUR (0.017 %). Both are recorded and labelled.
- `dscr.sizing`: BANK sizing-case CFADS basis, target, requested yield scenario (`P90-10y`), minimum realised DSCR. `dscr.reported`: BASE-case CFADS basis (`technical.operating_hours_p50`), min/avg — bit-identical to `kpis.min_dscr/avg_dscr`. `bank_case_distinct_from_base_case` states honestly whether a distinct P90 series exists: **True for Solar/Wind; False for Data Center and EV Charging** (their requested P90-10y sizing case produces CFADS identical to the base case, max difference 0.0).
- `llcr_inputs`: contractual maturity **and** actual payoff recorded side by side for a future LLCR convention. No LLCR, no valuation policy is created (`llcr_status = NOT_COMPUTED_BY_THIS_EVIDENCE`).
- Typed statuses, never zero and never an exception that could fail a Run: `NOT_APPLICABLE_NO_SENIOR`, `UNSUPPORTED_FACILITY_STRUCTURE` (F3 Two-Senior and junior keep their own facility evidence; nothing is aggregated), `EVIDENCE_UNAVAILABLE`. Historical Runs: `project_senior_debt_evidence` returns `NOT_RECORDED` and never rebuilds.

Definitions and the ramp-up rule (no invented threshold): see the module docstring.

Read-only projections: `app/export/institutional_reporting_v3.py` Lender_Overview section **1b** (every row carries an evidence class; `NOT_AVAILABLE`/`n/a` for old Runs).

## Four-vertical period-level acceptance (reference configurations; MEASURED)

| Vertical | Tenor | Binding | Repayment start | Contractual maturity | Actual payoff | Maturity − payoff | Nature |
|---|---:|---|---:|---|---|---|---|
| Solar | 15 y | GEARING | 3 | **32** (2045-12-31) | **24** (2041-12-31) | 8 periods / 1461 d | GEARING_CAP |
| Wind | 15 y | GEARING | 4 | **33** (2046-06-30) | **23** (2041-06-30) | 10 / 1826 d | GEARING_CAP |
| Data Center | 12 y | DSCR | 4 | **27** (2043-12-31) | **20** (2040-06-30) | 7 / 1279 d | RAMP_UP_INTEREST_COVERAGE (row 5) |
| EV Charging | 10 y | GEARING | 2 | **21** (2040-12-31) | **16** (2038-06-30) | 5 / 915 d | GEARING_CAP |

Independent checks (tests): maturity = first operating index + 2·tenor − 1 from the configuration; payoff index/date = last persisted 2-dp debt-schedule row with principal > 0 and its closing balance 0; maturity index/date equals the persisted terminal state; the Data Center limiting rows equal the persisted rows with zero principal. Raw evidence: `reference_evidence_four_verticals.json`.

## Financial-integrity proof

1. **Bit-identical outputs**: `dump_payload_digest.py` hashes the complete `run_project` payload (every float as `float.hex()`), excluding only the new key, for the four reference verticals on **pristine main `128bf0c`** and on this branch: identical (`payload_digest_main_128bf0c.json` == `payload_digest_branch.json`).
2. **In-test exact differential** (`test_the_evidence_changes_no_other_byte_of_the_run_payload`): same run with the builder replaced by a sentinel → payloads equal everywhere else and all numeric KPIs have equal `.hex()`.
3. **No source calculation changed**: files changed are listed below; `financial_engine/`, `finco_core/`, native kernels, `app/services/sensitivity_service.py`, `lender_case_service.py`, `app/v2/*`, frontend and F01 writers are untouched.
4. **No historical rewrite**: nothing migrates or re-runs; old Runs show `NOT_RECORDED` (test builds the Lender sheet from a real committed Run with the key removed).

## Files

New: `app/run_integrity/senior_debt_evidence.py`, `tests/test_senior_debt_evidence_c1_fix_1a.py`, this directory.
Modified (additive): `app/api/project_runner.py` (+5 lines, one key), `app/export/institutional_reporting_v3.py` (read-only section 1b).

## Integration dependency on FIN-V2-B1

B1 (valuation policy + persisted C2 summary) must consume `llcr_inputs.loan_life_end_candidates` and `sizing.dscr_*` instead of re-deriving maturity/payoff, and must keep `min_llcr` meaning decisions (point-in-time vs rolling; contractual vs payoff loan life) separate from this evidence. Both files add keys inside `financing_evidence`/`runtime_authority`; they do not overlap but share `app/api/project_runner.py` and `app/services/clean_presentation_adapter.py` neighbourhoods — merge B1 after this PR or rebase mechanically (separate hunks).

## Out of scope / not changed

React frontend and `app/v2/react_*` (RC-M #388 can read the key; a read-only projection is available via `project_senior_debt_evidence`), F01 writers, SHL engine, valuation discount-rate policy, sensitivity (interest shock no-op remains FV2-D01), `lender_case_service`.
