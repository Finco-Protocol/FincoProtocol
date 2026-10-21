# Quarterly Operating & Debt Sculpting — Institutional Acceptance V1

**Branch** `feat/model-quarterly-institutional-acceptance-v1` · **Draft PR** [#337](https://github.com/Finco-Protocol/FincoProtocol/pull/337) · **Base** `main` @ `b28a0572`

Scope: test, evidence and documentation only. No engine, solver, governance pin, activation flag or CI workflow file is modified. Quarterly (3/3) stays
**release-closed** (`ACTIVATION_ENABLED = False`). This is **synthetic institutional acceptance**: every expected value comes from dates or from
independently written Decimal/identity oracles. It is **not Excel parity** and must not be cited as such. It authorizes neither activation nor merge.

## 1. Verdict

**QUARTERLY ACCEPTANCE READY FOR INDEPENDENT REVIEW**

Basis: 1,441 acceptance tests pass and 1 strict reproduction (Q-F-02) fails as designed (`xfail(strict)`), over 28 deterministic scenarios and 6 suites. **No P0** (no
incorrect quarterly output, no fail-open) was found. The P1 items below are either deliberate typed refusals of unsupported institutional scenarios or
defects in shared code that are **identical under the released 6/6 path** (so not introduced or hidden by 3/3). They are activation dependencies,
not blockers of the candidate's financial correctness. Independent financial review and the Financial Owner decisions D-01…D-12 remain required before any activation.

## 2. Live preflight

| Item | Result |
|---|---|
| `origin/main` | `b28a05723967df590f6a684c64504d845e576508` ("Merge pull request #334 — Public Safety CI 200-minute budget"); unchanged during the work |
| Quarterly engine in `main` | RC-7B/RC-7C candidate (#310, #320, #325, #326) present; `quarterly_scope`, `calendar_policy` v1/v2, `quarterly_frequency_config` exist |
| Workstream A #332 | Not merged, not included, no shared engine/solver file touched |
| Diff vs `main` | 7 new test/support files + this document; zero modified existing files |

## 3. Baseline inventory (what exists, what is tested, what is closed)

| Capability | Implemented | Previously tested | Added here | Status |
|---|---|---|---|---|
| Operating/debt frequency 3/3 (matched) | Yes (`OperatingCalendarPolicy`, `QuarterlyProjectInfo`) | RC-7B/7C suites | A–E over 28 scenarios | **Release-closed** |
| Policy `rc7b-…-v1` (4 rows per year) | Yes (historical) | RC-7C reconciliation | Defect shape detected by oracle | Superseded by v2 |
| Policy `rc7c-…-v2` (date-authoritative) | Yes | RC-7C date authority | Calendar, operating, financing, statements | **Current candidate** |
| 6/6 (released default) | Yes | Entire suite | Used as comparison in E; default-unaffected control | Production |
| Mixed 3/6, 6/3 | No (D-06/D-07) | Refusal tests | Policy/config refusal matrix | Deferred, refused |
| Construction (monthly IDC / 6-month segments to COD) | Unchanged | RC-7B | Identical-to-6/6 in every scenario | Unchanged |
| SHL / DSRA / DSRF / reserves | Refused (D-09) | Refusal tests | 16 refusal reasons × 6 base scenarios + engine entry | Refused |
| Junior / multi-Senior / VAT / BESS / DC / EV | Refused (D-12) | Refusal tests | Included in the refusal matrix (BESS, junior) | Refused |
| ATAD / thin-cap / interest limitation | Refused (D-11) | Refusal tests | Re-asserted under S and Q | Refused |
| PPA expiry inside a quarter | Refused (D-05) | One COD | 6 CODs × 2 technologies | Refused (see G-01) |
| Six-month-authored Senior vectors / fixed-semiannual / explicit fractions | Refused | Rate/target vectors | + explicit service/principal schedules, day-count conventions | Refused |
| Product Run admission | Closed gate | Production acceptance (browser) | Gate and selection-contract matrix | Closed |
| Relation to OD-R | Independent | — | OD-R is not exercised; nothing here depends on it | n/a |

## 4. Oracle methodology (three layers; nothing is read back from the engine to form its own expectation)

1. **Calendar oracle** (`tests/quarterly_acceptance_support.py`) — pure `datetime.date` arithmetic: next quarter-end search, six-month boundary index, half-open day
   counts, end-year 365/366 denominators. Imports neither the engine nor `finco_core`. It is cross-checked against the independently written RC-7B oracle on every scenario.
2. **Decimal oracles** (`tests/rc7b_quarterly_oracle.py`, 60 digits) — revenue, OPEX, depreciation, calendar-year tax ledger with FIFO losses, Senior sizing with the tax-interest
   fixed point, sculpted roll-forward — all re-solved from the inputs.
3. **Identities** between engine outputs where the identity is an arithmetic definition (interest = opening × rate × actual days ÷ basis; closing = opening − principal; service = interest +
   principal; DSCR = CFADS ÷ service of the same period; assets = liabilities + equity; retained-earnings and tax-payable roll-forwards; ledger conservation).
   XIRR is recomputed with an independent bisection (ACT/365).

Tolerances are the existing approved constants and none was widened: `1e-9` (non-iterated operating arithmetic), `1e-4` (Senior policy convergence), `1e-6` (statements/funding identities),
`1e-7` (return tolerance). Each negative-control test proves the oracles can fail (dropped/duplicated/shifted row, wrong target DSCR, rate, tenor, v1 row-count shape).

## 5. Scenario matrix

| Suite | File | Scenarios | Tests | What it proves |
|---|---|---|---:|---|
| A Calendar | `test_quarterly_acceptance_calendar.py` | 28 | 349 | quarter dates, stub rows, year crossings, leap years/29 Feb, model-year layout, construction→operation boundary, same economic end date and maturity as 6/6, construction columns identical |
| B Operating | `test_quarterly_acceptance_operating.py` | 28 | 233 | production/revenue/OPEX/EBITDA vs Decimal oracle row by row, PPA flag and indexation timing, fixed/stepped/percentage OPEX, depreciation chain, annual aggregation vs 6/6 |
| C Financing | `test_quarterly_acceptance_financing.py` | 28 | 261 | Senior size and every service row vs Decimal oracle, actual-day interest, roll-forward, repayment calendar, DSCR from matched periods, sculpting capacity, gearing-bound early payoff, maturity, distributable cash |
| D Statements & tax | `test_quarterly_acceptance_statements.py` | 28 | 262 | income statement footing, calendar-year tax once per year, loss ledger, cash-flow reconciliation, RE/tax-payable roll-forward, balance sheet, equity and project XIRR |
| E Frequency switch | `test_quarterly_acceptance_frequency_switch.py` | 28 | 203 | only frequency/policy differ, alignment dates, cumulative EBITDA at every common boundary equals the oracle-explained difference, bounded financing deltas, same maturity, determinism after S→Q→S |
| Negative controls | `test_quarterly_acceptance_negative_controls.py` | — | 134 | typed refusals, gate closed, mixed frequencies unrepresentable, default run unaffected, oracle sensitivity |
| **Total** | | | **1,442** | **1,441 passed + 1 strict-xfail reproduction** (65 s) |

Scenario groups: quarter-boundary (7), year-crossing (4), mid-period COD (4), leap-year incl. 29 Feb COD (4), construction 12/13/18/24 months (3), financing tenor/horizon/day count (4),
DSCR-capacity-bound sculpting (5 + `solar-tenor10`), stepped/percentage OPEX and partial PPA share with indexation (3). Frequencies tested: 6/6 (released) and 3/3 (v2). Technologies: Solar, Wind.
Reproduce the evidence table with `python tests/quarterly_acceptance_support.py`.

## 6. Numerical evidence

| Scenario | Group | COD | Rows 6/6 | Rows 3/3 | End | Binding | Senior 6/6 | Senior 3/3 (Δ%) | Min DSCR 3/3 | Sponsor XIRR 6/6 | 3/3 | Δ pp |
|---|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| solar-q1end | quarter-boundary | 2031-03-31 | 50 | 99 | 2055-12-31 | GEARING | 25,343.9 | 25,343.9 (+0.00) | 1.201 | 17.04% | 17.36% | +0.32 |
| solar-q3end | quarter-boundary | 2031-09-30 | 50 | 99 | 2056-06-30 | GEARING | 25,346.1 | 25,346.1 (+0.00) | 1.202 | 17.04% | 17.35% | +0.32 |
| solar-h1end | quarter-boundary | 2031-06-30 | 50 | 100 | 2056-06-30 | GEARING | 25,343.9 | 25,343.9 (+0.00) | 1.202 | 17.05% | 17.33% | +0.28 |
| solar-yearend | year-crossing | 2031-12-31 | 50 | 100 | 2056-12-31 | GEARING | 25,346.1 | 25,346.1 (+0.00) | 1.201 | 17.05% | 17.34% | +0.29 |
| wind-q1end | quarter-boundary | 2031-03-31 | 54 | 107 | 2057-12-31 | GEARING | 33,281.9 | 33,281.9 (+0.00) | 1.201 | 20.82% | 21.21% | +0.40 |
| wind-q3end | quarter-boundary | 2031-09-30 | 54 | 107 | 2058-06-30 | GEARING | 33,287.6 | 33,287.6 (+0.00) | 1.204 | 20.81% | 21.21% | +0.40 |
| wind-yearend | year-crossing | 2031-12-31 | 54 | 108 | 2058-12-31 | GEARING | 33,287.6 | 33,287.6 (+0.00) | 1.201 | 20.75% | 21.14% | +0.39 |
| solar-mid-q2 | mid-period-cod | 2031-04-17 | 50 | 99 | 2055-12-31 | GEARING | 25,343.9 | 25,343.9 (+0.00) | 1.201 | 19.42% | 19.78% | +0.36 |
| solar-firstday | mid-period-cod | 2031-07-01 | 50 | 100 | 2056-06-30 | GEARING | 25,342.8 | 25,342.8 (+0.00) | 1.202 | 19.37% | 19.73% | +0.36 |
| solar-jan1 | year-crossing | 2032-01-01 | 50 | 100 | 2056-12-31 | GEARING | 25,346.1 | 25,346.1 (+0.00) | 1.201 | 19.37% | 19.74% | +0.36 |
| solar-aug | mid-period-cod | 2031-08-15 | 50 | 100 | 2056-06-30 | GEARING | 25,342.8 | 25,342.8 (+0.00) | 1.202 | 19.39% | 19.75% | +0.36 |
| solar-nov-leap | leap-year | 2027-11-10 | 50 | 99 | 2052-06-30 | GEARING | 25,346.1 | 25,346.1 (+0.00) | 1.202 | 19.43% | 19.79% | +0.37 |
| wind-mid-q2 | mid-period-cod | 2031-04-01 | 54 | 107 | 2057-12-31 | GEARING | 33,281.9 | 33,281.9 (+0.00) | 1.201 | 22.37% | 22.81% | +0.44 |
| wind-nov-leap | leap-year | 2027-11-10 | 54 | 107 | 2054-06-30 | GEARING | 33,287.6 | 33,287.6 (+0.00) | 1.204 | 22.39% | 22.85% | +0.45 |
| solar-feb29 | leap-year | 2032-02-29 | 50 | 100 | 2056-12-31 | GEARING | 25,437.0 | 25,437.0 (+0.00) | 1.201 | 19.15% | 19.51% | +0.35 |
| solar-cm18 | construction | 2031-09-30 | 50 | 99 | 2056-06-30 | GEARING | 25,881.8 | 25,881.8 (+0.00) | 1.202 | 15.93% | 16.21% | +0.28 |
| solar-cm24 | construction | 2032-03-31 | 50 | 99 | 2056-12-31 | GEARING | 26,427.9 | 26,427.9 (+0.00) | 1.201 | 14.97% | 15.22% | +0.25 |
| solar-tenor10 | financing | 2031-12-31 | 50 | 100 | 2056-12-31 | DSCR | 23,945.6 | 24,068.0 (+0.51) | 1.201 | 15.99% | 16.33% | +0.34 |
| solar-tenor18-h30 | financing | 2031-06-30 | 60 | 120 | 2061-06-30 | GEARING | 25,343.9 | 25,343.9 (+0.00) | 1.202 | 17.43% | 17.70% | +0.28 |
| solar-act365 | financing | 2031-12-31 | 50 | 100 | 2056-12-31 | GEARING | 25,340.5 | 25,340.5 (+0.00) | 1.201 | 17.08% | 17.36% | +0.28 |
| solar-h20 | financing | 2031-12-31 | 40 | 80 | 2051-12-31 | GEARING | 25,346.1 | 25,346.1 (+0.00) | 1.201 | 16.08% | 16.38% | +0.29 |
| solar-dscr-bound | sculpting | 2031-12-31 | 50 | 100 | 2056-12-31 | DSCR | 18,946.6 | 19,048.6 (+0.54) | 1.501 | 14.32% | 14.60% | +0.28 |
| solar-dscr-mid | sculpting | 2031-08-15 | 50 | 100 | 2056-06-30 | DSCR | 23,156.2 | 23,273.7 (+0.51) | 2.003 | 22.04% | 22.77% | +0.73 |
| wind-dscr-bound | sculpting | 2031-09-30 | 54 | 107 | 2058-06-30 | DSCR | 28,833.0 | 28,987.8 (+0.54) | 1.505 | 19.39% | 19.88% | +0.49 |
| solar-dscr-act365 | sculpting | 2031-06-30 | 50 | 100 | 2056-06-30 | DSCR | 19,177.7 | 19,279.4 (+0.53) | 1.502 | 14.43% | 14.72% | +0.29 |
| solar-dscr-high | sculpting | 2031-03-31 | 50 | 99 | 2055-12-31 | DSCR | 15,940.0 | 16,066.5 (+0.79) | 2.502 | 14.57% | 14.93% | +0.36 |
| solar-opex-step | operating | 2031-09-30 | 50 | 99 | 2056-06-30 | GEARING | 25,346.1 | 25,346.1 (+0.00) | 1.202 | 19.25% | 19.61% | +0.36 |
| solar-opex-pct | operating | 2031-06-30 | 50 | 100 | 2056-06-30 | GEARING | 25,343.9 | 25,343.9 (+0.00) | 1.202 | 16.98% | 17.27% | +0.28 |
| wind-ppa-share | operating | 2031-12-31 | 54 | 108 | 2058-12-31 | GEARING | 33,287.6 | 33,287.6 (+0.00) | 1.201 | 21.84% | 22.27% | +0.43 |

Reading the table:

* Operating/Senior equalities are exact (≤ 1e-9 operating, ≤ 1e-4 Senior solver) against the oracles on every row of every scenario.
* **Gearing-bound** scenarios (default fixtures) size the Senior at the gearing ratio, so the commitment, construction funding and IDC are identical under both frequencies.
* **DSCR-bound** scenarios show a Senior **+0.5 … +0.8 %** larger under 3/3 — finer sculpting dates, not value creation. Sponsor XIRR rises **+0.25 … +0.73 pp** because cash arrives earlier within the same half-year; cumulative EBITDA at every common boundary is identical except where a documented effect applies.
* Minimum base DSCR is never below the sculpting target (1.20/1.45/1.50/2.00/2.50) in any row.

## 7. Contractually expected differences between 6/6 and 3/3 (not defects)

| Item | Effect | Evidence |
|---|---|---|
| Interest/principal dates and sculpted profile | quarterly instead of six-monthly; DSCR path, Senior size (DSCR-bound), IDC follow | suites C, E |
| Tax | still one payment per calendar year in the last row (31 Dec); amounts follow interest | suite D |
| D-02 first-of-month COD | the half-open 3/3 rule does not count the COD day (e.g. 90 days Jan 1→Mar 31); the released axis adds it | calendar and operating suites |
| D-05 PPA expiry inside a six-month row | 3/3 switches to merchant at the quarter boundary on which the PPA expires; revenue differs only in that model year, exactly as the oracle predicts | operating and E suites |
| Sponsor/Project IRR | earlier cash ⇒ +0.25 … +0.73 pp; disclosed as `PENDING_D08` | suites D, E |

## 8. Findings and classification

P0 = incorrect output or fail-open; P1 = unsupported institutional scenario; P2 = usability/reporting. Reproductions for Workstream A are in the named tests.

| ID | Class | Finding | Frequency-specific? | Reproduction |
|---|---|---|---|---|
| — | **P0** | None found. Every unsupported input fails closed before calculation; every supported scenario reconciles to its oracle. | — | whole suite |
| Q-G-01 | **P1** | A PPA whose expiry (COD + N years) falls inside a quarter is refused (`QUARTERLY_INTRAPERIOD_PPA_EXPIRY_UNSUPPORTED`). Because expiry is COD-anchored, only quarter-end CODs can combine a PPA with 3/3 (all 6 tested non-quarter-end CODs refused, for both technologies); merchant-only works for any COD. This is the deliberate D-05 scope. | Yes (design) | `test_a_ppa_expiring_inside_a_quarter_is_refused_not_split` |
| Q-F-02 | **P1** | Financial close on 30/31 December: the **shared** statements code leaves a constant opening balance-sheet imbalance (0.79–2.0 keur ≈ 0.002–0.005 % of cost). The engine reports it (`BALANCE_SHEET_DOES_NOT_BALANCE`, fail-closed). Identical under 6/6 (verified on all 7 affected scenarios); FC on 30 Dec / 31 Dec fails, 1 Jan and Oct/Nov closes balance. The CIT/tax-payable carry of the construction stub is the suspected area; not root-caused here (shared code). | **No** (6/6 too) | strict-xfail `test_year_end_financial_close_should_balance` + `…imbalance_is_fail_closed…` |
| Q-F-01 | P2 | Where an asset life reaches the horizon end, book depreciation exceeds the depreciable base by ≈ 2 keur (0.006 %) because a model year straddling a leap day has fractions summing to 1.0014. Released actual-day convention; identical under 6/6. | No | `…book_depreciation_is_straight_line…[solar-tenor18-h30]` |
| Q-F-03 | P2 | An orphan DSRF commitment/fee with support mode `NONE` is accepted and silently inert (the Working Copy contract is stricter and refuses it). | No | `test_an_orphan_dsrf_commitment…` |
| Q-F-04 | P2 | `FIXED_SEMIANNUAL` / `EXPLICIT_FRACTIONS` day counts are refused with an untyped `ValueError` rather than a `QUARTERLY_*` code (fail-closed; wording only). | Partly | `test_a_six_month_authored_senior_vector…` |
| Q-F-05 | P2 | The statements' CIT accrual and the solver's cash tax differ by 0.01–0.2 % per year (≈ 0.1–0.7 keur); same relationship under 6/6, bounded so a quarter-only drift would fail. The first tax year's accrual includes the pre-COD construction stub. | No | `test_calendar_year_tax_is_paid_once…` |

Findings are reported as reproductions only; no shared financial-engine file was edited.

## 9. Gaps (not covered, by design or by scope)

* Mixed 3/6 and 6/3 (D-06/D-07), SHL, DSRA/DSRF and any reserve, Junior/multi-Senior, VAT facility, BESS/DC/EV, ATAD/thin-cap/interest limitation, multistream or dated PPA indexation, hierarchical OPEX, COD roll window (COD < 7 days before a quarter end), explicit off-grid maturity: refused, so only their **refusal** is accepted here, not their economics.
* No independent third-party model and no Excel parity run; the oracles are written in this repository.
* Browser/Run-lifecycle behaviour is covered by the existing RC-7B production-acceptance suite; this suite stays at engine/config level and does not enable the gate.
* Non-flat explicit all-in rate vectors on the 3/3 axis are refused rather than regridded (tested); no stepped-margin scenario can be accepted until a quarterly rate-vector contract exists.

## 10. Dependencies

**Activation (unchanged, none decided here):** independent financial review of the full 3/3 path; Financial Owner D-01…D-12 and D-03-b; Gate R governance successor; product admission decision; resolution or acceptance of Q-G-01 (intra-quarter PPA expiry) before any COD-agnostic use.

**Workstream A / shared-code owner:** Q-F-02 (year-end close statements imbalance), Q-F-01 and Q-F-05 (P2 precision); none is a prerequisite for this suite and none was addressed here.

## 11. Readiness decision

The matched 3/3 candidate (rc7c-v2) reproduces independent expectations for calendar, operating economics, Senior sculpting, tax and statements in all 28 scenarios, fails closed on everything outside its scope, and leaves the released 6/6 path bit-identical (including after interleaved quarterly runs). It is
**ready for independent review**; it is **not** activated, approved or merged by this document, and the P1 items above must be dispositioned by the Financial Owner and the shared-code owner.

**QUARTERLY ACCEPTANCE READY FOR INDEPENDENT REVIEW**
