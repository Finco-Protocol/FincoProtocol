# RC-7 Quarterly: Owner Decision Pack (Correction B)

## Status and evidence boundary

All twelve decisions remain **OPEN**. Recommendations below are NOT financial
approval. No human acceptance record, release authorization or activation is
created by this document. D-06 and D-07 remain deferred.

Reviewed source: `03ee3aee54e9f6fea3eb6e849a440ba1ebb7307b`.
Compatibility baseline: `78e4c0edcc1bdb5013df79f11b3ba7b9c2151013` (#319).
Normal integration: `31cada62a9fe17474995acc7d03bab4296122b4c`, with those
two commits as parents, in that order. No protected file changed in this sync.

The five exact candidate blobs remain in
`RC7_QUARTERLY_CANDIDATE_BLOB_MANIFEST.json`. They implement an isolated research
operating/tax/single-Senior calculation, NOT a complete project finance Run.
The existing six-month PeriodEngine and financial equations are not replaced.
Read this alongside `PERIOD_FREQUENCY_AUTHORITY_V1.md` and the dependency matrix.

## D-01: Actual COD and initial stub

- **Released 6/6:** COD is FC plus construction months; an operating start less
  than seven days before a half-year boundary rolls to that boundary. Actual
  project COD itself does not move. Both released conventions must remain.
- **Candidate 3/3:** KEEP_ACTUAL_COD, half-open intervals, next calendar-quarter
  endpoint strictly after COD. No seven-day roll.
- **Example/consequence:** 29 June 2028 -> 30 June is one operating day. A
  1,000 kEUR opening loan at 6% ACT/360 accrues 1/6 kEUR, not zero and not a full
  quarter's interest. The candidate tests execute the one-day case.
- **Recommendation:** Retain actual COD and disclose the short stub. Do not
  inherit a six-month source convention for a newly authored quarterly model.
- **Approval needed:** Owner must choose stub/day-inclusion treatment; financial
  reviewer must accept exact generated/validated dates.
- **Modules:** `financial_engine/quarterly/calendar.py`, `runtime.py`,
  `financial_engine/orchestrator.py`; future production handoff to
  `finco_core/engine/period_engine.py` requires separate scope approval.

## D-02: Operating fraction versus debt accrual

- **Released 6/6:** Generic operation uses end-year denominator; the source
  convention can use next-year denominator for December endpoints and has a
  first-day rule. Senior ACT/360 or ACT/365 is separately authoritative.
- **Candidate:** Operation is actual half-open days / end-year 365 or 366.
  Debt uses actual half-open days / explicit 360 or 365. Construction remains
  inclusive ACT on its own monthly dates.
- **Example/consequence:** 31 December 2027 -> 31 March 2028 is 91 days.
  Candidate production fraction is 91/366. A split-calendar Actual/Actual
  alternative is 1/365 + 90/366: at 20,000 annual MWh the difference is
  0.149711804775806571 MWh. This is a policy difference, not rounding error.
  For 1,000 kEUR at 6%, debt interest is 15.1666666667 (ACT/360) or
  14.9589041096 kEUR (ACT/365).
- **Recommendation:** Ratify or replace the explicitly named operating fraction
  before release. Do not silently present it as split-calendar Actual/Actual.
  Keep operating, construction and debt fractions separate in evidence.
- **Approval needed:** Explicit operating convention plus debt contractual basis.
- **Modules:** quarterly calendar; `financial_engine/senior_debt/interest.py`,
  `financial_engine/construction/adapter.py`, `finco_core/revenue/generation.py`.
  These are affected authorities, not permission to edit them.

## D-03: Exact economic horizon

- **Released 6/6:** Exactly 2N operating rows including initial stub; not always
  actual COD plus N years.
- **Candidate:** Exactly 4N rows including initial stub.
- **Example/consequence:** COD 17 April 2028, horizon one year -> 31 March
  2029, not 17 April 2029. Seventeen elapsed operating days are absent relative
  to the anniversary alternative, affecting revenue, depreciation and terminal
  return assumptions. Same row-count years do not prove matched economic life.
- **Recommendation:** Prefer an exact dated economic horizon plus explicit
  terminal stub for future institutional production; retain today's research
  fixed-count classification until separately approved and implemented.
- **Approval needed:** Owner choice of economic life and terminal-period method.
- **Modules:** quarterly calendar/runtime; future statement, depreciation,
  `financial_engine/project_returns/model.py` and valuation integration.

## D-04: Annual escalation clock

- **Released 6/6:** Sequential pairs, including stub, advance model year.
  Calendar tax year and contractual anniversary are distinct.
- **Candidate:** Sequential groups of four, including stub, advance model year.
- **Example/consequence:** With COD 17 April 2028, rows through 31 March 2029
  are model year 1. A 2% annual OPEX escalation starts on that date, before
  the 17 April anniversary. Annual 100 kEUR becomes 102 before period allocation.
  Model-year tariff and degradation follow this clock too.
- **Recommendation:** Require an explicit clock per economic contract. Do not
  claim four rows necessarily represent twelve elapsed months. Retain legacy
  exact behavior for all existing contracts.
- **Approval needed:** Owner selects model-year versus elapsed-anniversary
  treatment for yield, legacy PPA, OPEX and depreciation independently.
- **Modules:** quarterly calendar; revenue generation, OPEX projections,
  `financial_engine/orchestrator.py::_compute_depreciation`.

## D-05: PPA dates, reviews and expiry

- **Released 6/6:** Legacy PPA flag is period-start based; contractual PPA-01
  separately binds actual COD, review dates and boundary-only price changes.
  Existing V2 physical streams and CfD notional overlays have separate evidence.
- **Candidate:** Only bounded legacy formula with whole-period expiry; all
  multistream and dated-indexation contracts are refused before calculation.
- **Example/consequence:** COD 17 April, one-year PPA ends 17 April inside
  31 March -> 30 June. Candidate refuses; it does not sell all quarter at PPA,
  invent day-weighted energy, relocate expiry or manufacture Merchant revenue.
- **Recommendation:** First approved slice may retain refusal. Contractual
  support needs a revenue-owned dated integration, not six-month interpolation.
- **Approval needed:** Explicit contract/settlement and any intraperiod policy;
  unchanged PPA-01 authority must be retained.
- **Modules:** quarterly/runtime, `domain/revenue/multistream_runtime.py`,
  `domain/revenue/revenue_config.py`, `finco_core/revenue/generation.py`.

## D-06: Quarterly operations / semiannual service (DEFERRED)

- **Released 6/6:** Cash and debt service share the approved operating axis.
- **Proposal:** No executable mixed-frequency mode. Define eligible dated cash
  carry, interest and payment windows before any bridge.
- **Example/consequence:** Quarterly eligible cash 30 + 60 could support 60
  service at a 1.50 half-year test ONLY with approved accumulation. It does not
  prove 60 cash exists on the first quarterly date.
- **Recommendation:** Defer; no zero-cost cash holding or automatic dividends.
- **Approval needed:** Separate owner mixed-grid policy and contract review.
- **Modules:** future axis contract, post-Senior cash, reserves, shareholder
  waterfall, financing statement bridge. No modifications authorized here.

## D-07: Semiannual operations / quarterly service (DEFERRED)

- **Released 6/6:** A half-year amount has no independently sourced quarter cash
  arrival profile.
- **Proposal:** Refuse mixed 6/3. Geometry cannot create cash settlement dates.
- **Example/consequence:** Half-year CFADS 90 may arrive entirely at half-year
  end. Splitting it 45/45 falsely funds a first-quarter payment of 30.
- **Recommendation:** Defer until actual receipts/payment terms support finer
  cash allocation; neither equal split nor day weighting is sufficient.
- **Approval needed:** Source-backed subperiod cash policy and owner approval.
- **Modules:** same future cross-axis consumers as D-06, plus revenue/cost
  settlement; no alternative solver or browser calculator.

## D-08: Covenants and distribution eligibility

- **Released 6/6:** Existing approved checks, reserve/lock-up/release and
  distribution account evidence govern; sizing target is not automatically a
  sourced contractual covenant.
- **Candidate:** No new covenant interpretation, distributions or sponsor IRR.
- **Example/consequence:** CFADS/service pairs 100/100 and 300/200 give aggregate
  400/300 = 1.333333x, not arithmetic-average DSCR 1.25x. Neither identifies the
  contractually required test window or allows held distribution cash release.
- **Recommendation:** Require dated observation window, threshold source and
  explicit release authority. Missing terms remain UNAVAILABLE.
- **Approval needed:** Owner financial-credit policy and sourced covenant terms.
- **Modules:** `app/run_integrity/checks.py`, post-Senior cash, shareholder
  waterfall, `app/v2/credit_v4_evidence.py`. Credit's end-date-only join needs
  interval/frequency eligibility before cross-frequency admission (not fixed here).

## D-09: DSRA and DSRF coverage

- **Released 6/6:** Existing forward target uses next service times reserve
  months times periods/year / 12; DSRF is not a cash reserve/draw engine.
- **Candidate:** NONE only; active reserves refused, not silently set to zero.
- **Example/consequence:** Next quarterly services 100 and 200, six-month cover:
  dated sum 300 versus next-payment multiplier 100 * 6 * 4 / 12 = 200.
- **Recommendation:** Explicitly choose dated window/partial instalment policy
  for the new mode. Preserve all historical reserve policy and sponsor cash.
- **Approval needed:** Owner reserve/fee/funding/release policy with stub handling.
- **Modules:** `financial_engine/dsra/`, `financial_engine/financing/dsrf.py`,
  financing and shareholder waterfall; no new DSRF draw facility in this slice.

## D-10: Contractual debt maturity

- **Released 6/6:** Existing dated Senior axis and unpaid-liability rejection.
- **Candidate:** Explicit maturity equals an actual service endpoint; off-grid
  maturity refused. No terminal balloon or positive opening COD debt admitted.
- **Example/consequence:** COD 17 April + 18 months = 17 October, inside a
  quarterly interval. Moving to 31 December extends debt; forcing September
  repayment accelerates it. Both change economics without approval.
- **Recommendation:** First slice may refuse off-grid; exact terminal debt stub
  needs its own jointly generated/validated accrual and service axis.
- **Approval needed:** Owner maturity/stub policy and independent debt review.
- **Modules:** quarterly calendar/runtime, Senior axis contracts/schedule,
  financial statements terminal liability and valuation horizon.

## D-11: Annual tax, losses and payment dates

- **Released 6/6:** Existing TaxPolicy owns calendar-year basis, FIFO losses,
  annual limits and cash-tax timing. Period count is not tax-law authority.
- **Candidate:** Same calendar-year tax ledger, four-period metadata,
  TAX_YEAR_LAST_PERIOD with zero lag; no ATAD/thin-cap/exogenous tax vectors.
- **Example/consequence:** Annual taxable 100, valid opening losses 30, tax18%
  => liability 12.6 kEUR. It is NOT 3.15 payable each quarter without a payment
  policy. A 3,000 kEUR annual threshold must not become 750 by row count.
- **Recommendation:** Keep bounded policy and existing annual ledger; review
  actual due dates and cross-year stub allocation before expanded support.
- **Approval needed:** Owner tax timing/limitations policy and reference proof.
- **Modules:** `financial_engine/policies/tax.py`, `financial_engine/tax/`,
  orchestrator and quarterly runtime. No tax formula changes in Correction B.

## D-12: Instruments, verticals and complete Run admission

- **Released 6/6:** Existing per-project Solar/Wind/DC/EV financing support,
  historical evidence, protected/gated capabilities and exact pins remain.
- **Candidate:** Solar/Wind clean operating inputs + one Senior only. No SHL,
  Junior, multi-Senior, reserves, BESS/DC/EV or complete production Run.
- **Example/consequence:** A verified monthly Solar/Wind construction Run has
  positive actual COD Senior funding. Passing it as candidate opening debt is
  explicitly refused; isolated zero-opening sizing is NOT funding integration.
- **Recommendation:** Do not expose any frequency control until monthly funding,
  S&U, statements/BS, tax, reserves/distributions, returns and immutable Run/export
  evidence are all coherently accepted. Matched 3/3 first, not mixed frequencies.
- **Approval needed:** Owner scope plus independently reviewed exact financial
  content, then separate product admission/security acceptance.
- **Modules:** candidate runtime, financing/project, statements assembly,
  project/sponsor returns, input adapter, workbook CAS/history/export consumers.

## Decisions requested from the financial owner

1. Select explicit D-01..05 and D-10..11 policy; accept/refuse the current
   research choices rather than treating successful tests as approval.
2. Keep D-06/07 deferred; decide whether reserves/distributions remain excluded
   only from research or must be completed before first production admission.
3. Authorize exact further paths only after agreed D-03/D-04 and monthly COD
   handoff. This document is not a blanket scope amendment.
4. Commission independent review of the five unchanged candidate blobs and
   the additive successor proposal. A technical implementation review cannot
   substitute for an independent owner financial-content decision.
