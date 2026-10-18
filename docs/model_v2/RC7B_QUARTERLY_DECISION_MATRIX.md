# RC-7B Matched 3/3: Financial Policy Decision Matrix (D-01..D-12)

Status: **ALL DECISIONS OPEN.** Recommendations below are not approvals. No owner
acceptance, release authorization or production activation is created here.
D-06 (3/6) and D-07 (6/3) remain deferred and are refused by the engine.

Sources reviewed at main `5be8c4b149712dd39b38b54c6fabcf3fcf47ef0d`:
`RC7_QUARTERLY_DECISION_REGISTER.md`, `RC7_QUARTERLY_OWNER_DECISION_PACK.md`,
`RC7_QUARTERLY_RESEARCH_ISOLATION_REPORT.md`, `RC7_QUARTERLY_RC7A_COMPATIBILITY_REVIEW.md`,
`PERIOD_FREQUENCY_AUTHORITY_V1.md`, `PERIOD_FREQUENCY_DEPENDENCY_MATRIX.md`.

**How implementation proceeds while decisions are open.** Every 3/3 convention is a
named, versioned candidate value (`rc7b-quarterly-candidate-v1`) carried in the
typed policy, the clean input fingerprint and the Run evidence. Product admission
is closed (`QUARTERLY_ADMISSION_ENABLED = False`), so no user Run can execute a
candidate convention. Where a decision changes economics that cannot be isolated
behind that gate, the combination is refused instead of being given a default.

| ID | Existing 6/6 authority | Proposed 3/3 behavior (candidate) | Financial consequence | Recommended treatment | Owner approval required | Implementation while pending |
|---|---|---|---|---|---|---|
| D-01 COD stub | COD = FC + construction months; operating start rolls to Jun 30 / Dec 31 when COD is < 7 days before it; COD on the 1st adds one inclusive day | `KEEP_ACTUAL_COD`: half-open quarters, first quarter ends at the next Mar 31 / Jun 30 / Sep 30 / Dec 31 strictly after COD; no roll, no +1 day | A one-day first quarter is retained (29 Jun -> 30 Jun accrues 1 day of debt interest and 1/365 of annual production). Where the 6/6 roll would apply, 3/3 construction columns would end on a different date | Keep actual COD and disclose the stub. **Refuse 3/3 where the 6/6 roll window applies** (`QUARTERLY_COD_ROLL_WINDOW_PENDING_D01`) so construction dates are provably identical under both frequencies | Yes | Yes — candidate value, admission closed; roll-window combination refused |
| D-02 Day counts | Operating fraction = days / end-year 365/366 (generic) or next-year denominator for December (source-aligned); Senior interest separately ACT/360 or ACT/365; construction inclusive ACT | Operating fraction = half-open days / end-year 365/366. Senior interest keeps its own ACT/360 or ACT/365 on the same quarter dates. Construction unchanged | 31 Dec 2027 -> 31 Mar 2028 = 91 days -> 91/366 operating fraction; split-calendar Actual/Actual would differ by 0.1497 MWh per 20 GWh/yr. Interest on 1,000 kEUR at 6% = 15.1667 (ACT/360) or 14.9589 (ACT/365) | Ratify the named operating fraction or replace it before release; keep operating, construction and debt fractions separate in evidence. Source-aligned convention refused for 3/3 | Yes | Yes — candidate value; source-aligned 3/3 refused |
| D-03 Economic horizon | Exactly 2N operating rows including the initial stub (not COD + N years) | Exactly 4N operating rows including the stub | COD 17 Apr 2028, N = 1 ends 31 Mar 2029: 17 days of operation absent versus an anniversary horizon; affects revenue, depreciation tail and terminal returns | Long-term: dated economic horizon with explicit terminal stub. First slice: fixed-count candidate, disclosed | Yes | Yes — candidate value; anniversary horizon not implemented |
| D-04 Annual clock | Pairs of rows (stub included) advance model year for degradation, legacy PPA/merchant indexation, flat OPEX inflation and depreciation year | Groups of four rows (stub included) advance model year | With COD 17 Apr 2028 a 2% escalation starts 31 Mar 2029, before the anniversary. Same number of annual escalation events as 6/6 (not doubled) | Explicit clock per economic input; never let four rows behave as two years | Yes | Yes — candidate value; hierarchical OPEX and external annual series refused |
| D-05 PPA dates | Legacy flag on period start; PPA-01 contractual dated reviews; Revenue V2/V3 multistream separate | Legacy formula only; expiry must fall on a quarter boundary; multistream, dated indexation, per-period CO2 vectors and merchant-index overrides refused | No mid-quarter energy split is invented; COD 1 Apr gives boundary-aligned expiry; COD 17 Apr refused | Retain refusal in the first slice; contractual support via a revenue-owned dated integration | Yes | Yes — refusal only |
| D-06 3/6 mixed | Not available | Refused (`QUARTERLY_MATCHED_3_3_REQUIRED`) | None — not executable | Keep deferred | Yes (separate) | Deferred — no work |
| D-07 6/3 mixed | Not available | Refused | None — not executable | Keep deferred until sourced sub-period cash timing exists | Yes (separate) | Deferred — no work |
| D-08 Covenants / distributions | Existing DSCR lock-up, Senior-first cash, distribution account; sizing target is not a sourced covenant | The released distribution mechanics are executed unchanged on quarterly dates inside the candidate Run; quarterly lock-up observation uses each quarter's own DSCR | Distributions and Sponsor IRR become quarterly-dated; a ratio tested per quarter can lock up cash a half-year aggregate would release (100/100 + 300/200 aggregates to 1.33x, not 1.25x) | Require a dated observation window, threshold source and release authority before Sponsor returns are relied on | Yes | Computed in the release-closed candidate; **Sponsor distributions/returns labelled PENDING D-08** in Run evidence |
| D-09 Reserves (DSRA/DSRF) | Forward target = next DS x months x periods/yr / 12; generic peak-forward cash DSRA; DSRF is not cash | `NONE` only. Generic DSRA derivation disabled for 3/3; any typed CASH_DSRA / DSRF / reserve requirement refused | Next quarterly services 100 and 200 with 6-month cover: dated sum 300 vs multiplier rule 200 — not silently chosen | Explicit dated window and partial-instalment policy for quarterly before any reserve | Yes | Yes — refusal only |
| D-10 Debt maturity | Tenor years x 2 rows on the dated Senior axis; unpaid terminal liability rejected | Tenor years x 4 rows; maturity is the end date of that row; balloon not permitted; unpaid terminal Senior rejected | Maturity is always a quarterly service endpoint by construction; no extension or acceleration | First slice keeps row-count maturity; an off-grid contractual date needs its own terminal stub axis | Yes | Yes — candidate value; terminal liability check unchanged |
| D-11 Tax | Calendar-year TaxPolicy, FIFO losses, annual limits, approved cash-tax timing; `periods_per_tax_year = 2` | Same calendar-year ledger with `periods_per_tax_year = 4`; cash tax paid in the last period of the tax year with zero lag; ATAD/thin-cap/interest limitation refused | 100 taxable, 30 losses, 18% -> 12.6 paid once per calendar year, never 3.15 per quarter; annual thresholds are not divided by four | Keep annual ledger; review actual due dates and cross-year stub allocation before expanded support | Yes | Yes — candidate value; other timing/limitations refused |
| D-12 Scope | Solar/Wind/DC/EV with existing financing support, SHL, DSRA, gated Junior/multi-Senior/BESS | Solar and Wind only; single Senior; `EQUITY_ONLY` sponsor funding; no SHL, Junior, multi-Senior, VAT facility, BESS, DC or EV | Legacy four-vertical 6/6 results are untouched (verified bit-exact) | Matched 3/3 Solar/Wind first; expand only with separately reviewed evidence | Yes | Yes — everything outside scope refused before calculation |

## Decisions requested from the financial owner

1. Accept or replace the candidate values for D-01..D-05, D-10, D-11.
2. Decide whether D-08 (distribution eligibility on quarterly dates) and D-09
   (reserves) must be completed before first product admission, or whether a
   reserve-free, Sponsor-returns-disclosed slice is admissible.
3. Confirm D-12 scope (Solar/Wind, single Senior, equity-only).
4. Commission independent review of the exact successor blobs listed in
   `RC7B_QUARTERLY_PRODUCTION_SUCCESSOR_CONTRACT.md`.

Until 1-4 are recorded by the owner, the integration PR stays Draft and
`QUARTERLY_ADMISSION_ENABLED` stays `False`.
