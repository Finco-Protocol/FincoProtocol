# RC-7C — 6/6 vs 3/3 numerical reconciliation (canonical engine path)

**Not an approval.** Every figure below is produced by the canonical Run composition (generic financing policy → shareholder waterfall → statements) of
`tests/rc7c_frequency_reconciliation.py` on the actual reference Solar and Wind projects. Nothing is rounded to agree and no golden was edited. The
expected values behind the pass/fail tests are derived independently from dates and 60-digit Decimal arithmetic (`tests/rc7b_quarterly_oracle.py`,
`tests/test_rc7c_quarterly_date_authority.py`), never from the engine under test. Regenerate with
`PYTHONPATH=.:tests python tests/rc7c_frequency_reconciliation.py`.

Columns: operating rows and last operating date for the released 6/6 project, the historical RC-7B candidate **v1** (`rc7b-quarterly-candidate-v1`,
fixed `4N` rows) and the RC-7C candidate **v2** (`rc7c-quarterly-candidate-v2`, date-authoritative); the revenue difference of v1 and v2 against 6/6;
the largest difference of production / OPEX / book depreciation of v2 against 6/6; the Senior commitment difference; Sponsor XIRR.

| Case | Rows 6/6 | Rows v1 | Rows v2 | End 6/6 | End v1 | End v2 | Revenue v1 % | Revenue v2 % | Prod/OPEX/Dep v2 % | Senior size v2 % | Sponsor XIRR 6/6 | Sponsor XIRR v2 |
|---|---:|---:|---:|---|---|---|---:|---:|---:|---:|---:|---:|
| solar/2031-03-31/cm12 | 50 | 100 | 99 | 2055-12-31 | 2056-03-31 | 2055-12-31 | +1.073 | +0.1688 | 0.000000 | +0.000 | 0.1704 | 0.1736 |
| solar/2031-06-30/cm12 | 50 | 100 | 100 | 2056-06-30 | 2056-06-30 | 2056-06-30 | +0.000 | +0.0000 | 0.000000 | +0.000 | 0.1705 | 0.1733 |
| solar/2031-09-30/cm12 | 50 | 100 | 99 | 2056-06-30 | 2056-09-30 | 2056-06-30 | +1.082 | +0.1707 | 0.000000 | +0.000 | 0.1704 | 0.1735 |
| solar/2031-12-31/cm12 | 50 | 100 | 100 | 2056-12-31 | 2056-12-31 | 2056-12-31 | +0.000 | +0.0000 | 0.000000 | +0.000 | 0.1705 | 0.1734 |
| wind/2031-03-31/cm12 | 54 | 108 | 107 | 2057-12-31 | 2058-03-31 | 2057-12-31 | +0.798 | +0.0791 | 0.000000 | +0.000 | 0.2082 | 0.2121 |
| wind/2031-06-30/cm12 | 54 | 108 | 108 | 2058-06-30 | 2058-06-30 | 2058-06-30 | +0.000 | +0.0000 | 0.000000 | +0.000 | 0.2074 | 0.2113 |
| wind/2031-09-30/cm12 | 54 | 108 | 107 | 2058-06-30 | 2058-09-30 | 2058-06-30 | +0.816 | +0.0800 | 0.000000 | +0.000 | 0.2081 | 0.2121 |
| wind/2031-12-31/cm12 | 54 | 108 | 108 | 2058-12-31 | 2058-12-31 | 2058-12-31 | +0.000 | +0.0000 | 0.000000 | +0.000 | 0.2075 | 0.2114 |
| solar/2032-06-30/cm9 | 50 | 100 | 100 | 2057-06-30 | 2057-06-30 | 2057-06-30 | +0.000 | +0.0000 | 0.000000 | +0.000 | 0.1757 | 0.1787 |
| solar/2032-03-31/cm15 | 50 | 100 | 99 | 2056-12-31 | 2057-03-31 | 2056-12-31 | +1.062 | +0.1688 | 0.000000 | +0.000 | 0.1647 | 0.1677 |
| wind/2032-09-30/cm18 | 54 | 108 | 107 | 2059-06-30 | 2059-09-30 | 2059-06-30 | +0.816 | +0.0798 | 0.000000 | +0.000 | 0.1938 | 0.1972 |
| solar/2028-12-31/cm24 | 50 | 100 | 100 | 2053-12-31 | 2053-12-31 | 2053-12-31 | +0.000 | +0.0000 | 0.000000 | +0.000 | 0.1499 | 0.1521 |
| solar/2031-03-31/cm12/horizon=15 | 30 | 60 | 59 | 2045-12-31 | 2046-03-31 | 2045-12-31 | +2.045 | +0.3250 | 0.000000 | +0.000 | 0.1300 | 0.1336 |
| solar/2031-03-31/cm12/horizon=30 | 60 | 120 | 119 | 2060-12-31 | 2061-03-31 | 2060-12-31 | +0.836 | +0.1329 | 0.000000 | +0.000 | 0.1743 | 0.1774 |
| wind/2031-09-30/cm12/horizon=20 | 40 | 80 | 79 | 2051-06-30 | 2051-09-30 | 2051-06-30 | +1.221 | +0.1196 | 0.000000 | +0.000 | 0.1996 | 0.2038 |
| solar/2031-03-31/cm12/tenor=8 | 50 | 100 | 99 | 2055-12-31 | 2056-03-31 | 2055-12-31 | +1.073 | +0.1688 | 0.013169 | +0.523 | 0.1377 | 0.1405 |
| wind/2031-09-30/cm12/tenor=12 | 54 | 108 | 107 | 2058-06-30 | 2058-09-30 | 2058-06-30 | +0.816 | +0.0800 | 0.000000 | +0.000 | 0.2081 | 0.2121 |
| solar/2031-03-31/cm12/day_count=ACT_365 | 50 | 100 | 99 | 2055-12-31 | 2056-03-31 | 2055-12-31 | +1.073 | +0.1688 | 0.000000 | +0.000 | 0.1706 | 0.1738 |
| wind/2031-12-31/cm12/tenor=10/day_count=ACT_360 | 54 | 108 | 108 | 2058-12-31 | 2058-12-31 | 2058-12-31 | +0.000 | +0.0000 | 0.000000 | +0.000 | 0.2075 | 0.2114 |
| solar/2031-03-31/cm12/ppa=7.0 | 50 | 100 | 99 | 2055-12-31 | 2056-03-31 | 2055-12-31 | +1.037 | +0.1579 | 0.000000 | +0.000 | 0.1756 | 0.1790 |
| wind/2031-09-30/cm12/horizon=25/ppa=12.0 | 50 | 100 | 99 | 2056-06-30 | 2056-09-30 | 2056-06-30 | +0.903 | +0.0889 | 0.000000 | +0.000 | 0.2067 | 0.2108 |
| solar/2031-04-17/cm12/ppa=0.0 | 50 | 100 | 99 | 2055-12-31 | 2056-03-31 | 2055-12-31 | +0.830 | +0.0000 | 0.000000 | +0.000 | 0.1942 | 0.1978 |
| solar/2031-09-17/cm12/ppa=0.0 | 50 | 100 | 100 | 2056-06-30 | 2056-06-30 | 2056-06-30 | +0.000 | +0.0000 | 0.000000 | +0.000 | 0.1941 | 0.1977 |
| wind/2031-11-15/cm12/ppa=0.0 | 54 | 108 | 107 | 2058-06-30 | 2058-09-30 | 2058-06-30 | +0.698 | +0.0000 | 0.000000 | +0.000 | 0.2240 | 0.2285 |
| solar/2032-02-29/cm13/ppa=0.0 | 50 | 100 | 100 | 2056-12-31 | 2056-12-31 | 2056-12-31 | +0.000 | +0.0000 | 0.000000 | +0.000 | 0.1915 | 0.1951 |
| wind/2031-01-10/cm12/ppa=0.0 | 54 | 108 | 108 | 2057-12-31 | 2057-12-31 | 2057-12-31 | +0.000 | +0.0000 | 0.000000 | +0.000 | 0.2228 | 0.2273 |
| solar/2031-05-03/cm12/horizon=15/ppa=0.0 | 30 | 60 | 59 | 2045-12-31 | 2046-03-31 | 2045-12-31 | +1.502 | +0.0000 | 0.000000 | +0.000 | 0.1658 | 0.1697 |
| wind/2031-10-24/cm12/tenor=10/ppa=0.0 | 54 | 108 | 107 | 2058-06-30 | 2058-09-30 | 2058-06-30 | +0.697 | +0.0000 | 0.000000 | +0.000 | 0.2238 | 0.2283 |
| solar/2031-07-01/cm12/ppa=0.0 | 50 | 100 | 100 | 2056-06-30 | 2056-06-30 | 2056-06-30 | -0.009 | -0.0090 | 0.015276 | +0.000 | 0.1937 | 0.1973 |
| wind/2031-04-01/cm12/ppa=0.0 | 54 | 108 | 107 | 2057-12-31 | 2058-03-31 | 2057-12-31 | +0.671 | -0.0076 | 0.015428 | +0.000 | 0.2237 | 0.2281 |


## Reading the table

| Finding | Evidence |
|---|---|
| **Root cause of D-03.** v1 ends the horizon `4N` rows after COD, so when COD lies in the *second quarter of a half-year* the stub counts as a whole row and the project operates exactly one extra quarter (e.g. `2055-12-31` → `2056-03-31`). | rows `100` vs `50` ⇒ v1 `+1.073 %` revenue (Solar, COD 31 Mar 2031); the effect is `+0.000` where COD is in the first quarter of a half-year (the 30 Jun and 31 Dec CODs). |
| **v2 removes the horizon effect.** v2 operating start, operating end, operating days, model-year boundaries and Senior maturity date equal the 6/6 project in every case. | End 6/6 = End v2 in all 30 cases; `Prod/OPEX/Dep v2 %` is `0.000000` except the two first-of-month cases and the DSCR-bound tenor case explained below. |
| **Remaining revenue differences are explained, not forced.** Solar/Wind with a PPA whose expiry date is not a six-month boundary: the released 6/6 row keeps the PPA tariff to the end of the row containing the expiry; the 3/3 axis switches at the quarter boundary where the PPA actually expires (**D-05**; no mid-quarter split is invented). Per-model-year identities in the tests prove every other year is identical. | `+0.0791 … +0.3250 %` for PPA cases; exactly `+0.0000 %` where `ppa=0.0` (merchant only) — **no invented revenue**. |
| **First-of-month COD (D-02).** The released 6/6 axis counts the COD day (`+1 day` on the first row for a COD on the 1st); the 3/3 half-open rule does not. One day, `0.015 %`. | the two `…-07-01` / `…-04-01` cases: production/OPEX/depreciation `0.0153 %` (one day of the first row, as D-02 states). |
| **Senior size.** Equal in 29 of 30 cases. Where the DSCR sizing is bound by the tenor (`tenor=8`) the quarterly DS profile legitimately sizes a different Senior amount (`+0.523 %`), which changes financing-cost uses and the depreciation basis; the test makes the construction/depreciation identities conditional on equal Senior size and always requires equal hard CAPEX. | `solar/…/tenor=8` row (also the `0.013 %` depreciation difference: depreciable basis includes financing costs). |
| **IRRs differ by timing only.** Sponsor XIRR is `~+0.3 pp` higher under 3/3 because the same cash flows are distributed up to a quarter earlier; it is not an economic improvement and the Run keeps `sponsor_returns_status = PENDING_D08_DISTRIBUTION_ELIGIBILITY`. | all rows. |
| **Tax.** Calendar-year ledger paid in the last row of the year under both frequencies (D-11); amounts differ only through revenue/interest above. Cash tax is paid once per calendar year, never in four instalments. | `tests/test_rc7c_frequency_reconciliation.py`. |

## 6/6 bit-identical proof

`python tools/rc7b_semiannual_regression.py --baseline origin/main` (baseline `162a3d70ea0cf5b15024ecbe5f7dec33f447a48d`, live main after PRs #320 and #326):
Solar, Wind, Data Center and EV Charging — run tree, input dictionary, cache key and clean input fingerprint all identical, **maximum financial
difference 0 (bit-identical)**. Full output: `RC7C_SEMIANNUAL_REGRESSION.json` (the candidate run executed on the working tree of this branch).
