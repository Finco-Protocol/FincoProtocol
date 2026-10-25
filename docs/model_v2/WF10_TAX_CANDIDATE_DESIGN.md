# WF-10 — Advanced Tax & Jurisdiction Contracts V1 — Candidate Design

Branch: `feat/model-wf10-tax-jurisdictions-candidate-v1` (base `a0c0d3efd215a28a82b6d01294186ddc373e943b` — the live main tip at preflight, matching the mission checkpoint exactly).
Package: `app/model_v2/tax_wf10_candidate/` — release-closed (`ACTIVATION_ENABLED` literal `False`; `TAX_WF10_RELEASE_CLOSED` on every public calculation entry; no environment variable can enable it; never imported by production).
Companion: `WF10_TAX_OWNER_DECISIONS.md` (D-01..D-11, all OPEN).

## 1. Reused existing authorities (NOT duplicated)

| Capability | Released authority | Status |
|---|---|---|
| Production CIT | `financial_engine/tax/engine.py::calculate_tax` — flat `TaxPolicy.corporate_rate`, calendar-year fragments, cash-tax timing | REUSED (live in every run) |
| Tax-loss carryforward | `financial_engine/tax/loss_ledger.py::run_annual_fifo_ledger` — vintage FIFO, expiry-before-use, opening vintages, `TAX_OPENING_LOSS_FUTURE_VINTAGE` fail-closed | REUSED |
| ATAD interest limitation | `financial_engine/tax/atad.py::calculate_annual_atad` — `max(30% EBITDA, de-minimis)`, chronological allocation | REUSED |
| Typed SHL interest limitation | `financial_engine/tax/interest_limitation.py` (capitalisation gate, identity guard) | REUSED |
| Book vs tax depreciation | `finco_core/depreciation/**` — per-class bases, `_TAX_LIFE_YEARS_MAP`, `book_tax_difference_keur` audit rows (straight-line only at runtime) | REUSED |
| Dividend WHT (waterfall) | `finco_core/inputs/distribution_accounting_policy.py` + `financial_engine/shareholder_waterfall/**` (typed, fail-closed, unenabled by default) | REUSED |
| SHL interest WHT params | `finco_core/shl/inputs.py`, `finco_core/shl/fcf_waterfall.py` | REUSED |
| Jurisdiction profiles | `financial_engine/tax/jurisdiction.py` — `TaxJurisdictionProfile` with provenance gating (XA/XB/XC synthetic; no registered rates) | REUSED as the opacity precedent |
| Phase 6A/6B/6C audit engines | `finco_core/tax/templates|engine_*|holdco_*` (progressive CIT, SPV engine, HoldCo WHT stored-not-remitted) | REUSED (audit-only on main; not modified here) |

**What the released stack does NOT have — and this candidate adds (contracts + pure helpers only):**
dated multi-year CIT rate schedules; explicit LCF utilisation-cap/expiration conventions as caller evidence; ATAD-style inputs/outputs with an explicit DISALLOWED-interest output; an explicit book-vs-tax temporary-difference ledger per asset with construction/COD boundary rules; a VAT recovery/position engine (construction + operating, recoverable vs non-recoverable, cash vs P&L ledgers); evidence-supplied withholding with gross/net conservation, flow-id double-withholding prevention and senior/junior legal-basis gating; separate SPV/HoldCo entity books with exact intercompany attribution identities.

## 2. Package inventory

- `contracts.py` — typed frozen contracts, `TAX_WF10_*` fail-closed codes:
  `TaxEntityIdentity` (opaque 2-char jurisdiction label; SPV/HOLDCO), `TaxRateWindow`/`TaxRateSchedule` (FLAT / DATED_SERIES; overlap = `TAX_WF10_OVERLAP`; uncovered date = UNAVAILABLE), `TaxLossCarryforwardConfig` (exactly one of `unlimited` / `carryforward_years`; explicit `utilisation_cap_pct` — nothing defaulted), `OpeningLossVintage`, `InterestLimitationInputs` (both thresholds explicit; disallowed carryforward deliberately NOT representable), `DepreciationAsset` (STRAIGHT_LINE only; in-service before COD fails closed), `VatConfig` (rate + BOTH phase recovery percentages + non-recoverable treatment — all required evidence, no defaults), `VatPeriodInput`, `WithholdingRule` (rate + `legal_basis_ref` always required; senior/junior need a substantive basis reference), `IntercompanyFlow`, `TaxEntityBook`, `TaxCandidateBook` (unique ids; rules/flows reference known entities; no payer==payee).
- `pure.py` — deterministic helpers (Decimal kEUR, 6-dp ROUND_HALF_UP):
  `taxable_income_reconciliation` (explicit line-item identity), `corporate_tax_for_tax_year` (dated rate; a rate change inside one tax year fails `TAX_WF10_TAX_YEAR_RATE_SPLIT`; negative income → zero), `tax_loss_schedule` (vintage FIFO, expiry-before-use, cap, exact per-year identity audit, future opening vintages rejected), `interest_limitation` (capacity `max(pct×EBITDA, de-minimis)`; explicit `deductible`/`disallowed` outputs), `build_depreciation_schedules` (book/tax straight-line over released-axis `day_fraction`s; temporary differences; basis cap), `compute_vat_position` (recoverable/non-recoverable split; CASH ledger vs P&L ledger separation; CAPITALISE/EXPENSE explicit policy), `apply_withholding`/`withholding_ledger` (exact `gross = withheld + net`; duplicate flow id = `TAX_WF10_DOUBLE_WITHHOLDING`), `attribute_intercompany_interest` (exact payer/payee identity — zero leakage; PRINCIPAL never taxable).
- `tests/test_tax_wf10_candidate.py` — 65 focused tests covering the 17 mission acceptance cases + release closure + both isolation scans.

## 3. Explicitly unsupported (fail-closed, per mission §3)

Declining-balance / any non-straight-line depreciation (no invented acceleration); construction-period tax depreciation (D-06); deferred tax / DTA-DTL (the released stack declares it a non-capability — `BLOCKED_BY_DEFERRED_TAX_CAPABILITY`); interest-limitation loss carryforward (the released engine raises the same); thin-cap formula (`SHL_THIN_CAP_RUNTIME_NOT_IMPLEMENTED` upstream); treaty relief, beneficial-ownership and exemption logic (rates are evidence-supplied; no relief computation); consolidated tax computation (structural absence test); quarterly-frequency tax year alignment (released adapter refuses; D-11).

## 4. Jurisdiction policy

A jurisdiction code is an OPAQUE attribution label. The candidate never maps a jurisdiction to anything: rates arrive via `TaxRateSchedule`, VAT recovery via `VatConfig`, withholding via `WithholdingRule` — each with its own evidence and basis reference. An entity whose schedule does not cover a date yields UNAVAILABLE (`corporate_tax_for_tax_year → None`); a rate change inside a caller-declared tax year fails closed. This mirrors the released `TaxJurisdictionProfile` provenance gating (`TAX_JURISDICTION_SOURCE_UNRESOLVED`) and the trust-pack gap `COUNTRY_SPECIFIC_INTEREST_LIMITATION_NOT_MODELLED`.

## 5. Release integration seams (future, NOT in this PR)

1. Dated rate schedules would enter production through `financial_engine/policies/tax.py::TaxPolicy` (replace `corporate_rate` with a resolved schedule; `financial_engine/tax/engine.py` consumes it per calendar-year fragment) — requires a governance successor for the pinned engine files.
2. Temporary-difference outputs would extend `finco_core/depreciation/tax_bridge.py` (audit bridge already exists) into a deferred-tax engine — blocked by the released deferred-tax non-capability until a Financial Owner decision (D-05).
3. VAT positions would join the construction money flow (`finco_core/construction/stage_b2.py` VAT facility) and the workbook via new registry fields — the workbook currently exposes only `tax_corporate_rate_pct` / `tax_loss_carryforward_years`.
4. Withholding ledgers would feed `financial_engine/shareholder_waterfall/model.py` dividend WHT and `finco_core/shl/fcf_waterfall.py` interest WHT, both currently parameter-driven with no remittance timing.
5. Any graduation of candidate files into `financial_engine/**` requires the exact-path + exact-blob successor-slice pattern in `tests/test_ci_acceptance.py` (V10/V11 precedent).

## 6. Test evidence summary (65 tests)

Release closure (literal-False flag, 10 gated entries, no-env proof) · Case 1 reconciliation identity + CIT feed · Case 2 dated rates + split fail-closed + uncovered UNAVAILABLE · Case 3 FIFO use/expiration/cap/unlimited/future-vintage · Case 4 limitation outputs + de-minimis + disabled + negative EBITDA + no carryforward field · Case 5 book/tax temporary differences + non-SL + pre-COD in-service fail · Case 6 construction VAT refund position · Case 7 CAPITALISE/EXPENSE explicit-only · Case 8 cash vs P&L ledger separation + negative (refund) cash · Case 9 dividend gross/net conservation + explicit zero rate · Case 10 SHL + senior/junior basis gating · Case 11 separate entities + no-consolidation structural scan + duplicate ids · Case 12 jurisdiction opacity + missing evidence + unknown arrangements + malformed numbers · Case 13 COD stub 184/365 + leap 366 denominator via the real PeriodEngine + tax-year-keyed ledger · Case 14 negative income → loss + zero tax · Case 15 double-withholding + duplicate flow ids · Case 16 exact intercompany identity + principal non-taxable + unknown-entity/leakage fails · Case 17 AST import-forbidden scan + reverse reference scan + released-file diff proof.


## Correction A — monetary integrity and date authority

No country/treaty defaults or owner decisions are introduced. D-01..D-13 remain
OPEN and the literal release flag stays False. Calculations accept finite Decimal,
integer or compatible float evidence. Decimal amounts are never converted through
float; integers are exact, while a float's shortest decimal spelling represents
already rounded binary evidence, not recovery of its original decimal source.
Money validators preserve those types; no candidate monetary path calls float().

All public numerical operations use an isolated, evidence-scaled Decimal context
(minimum 128 digits, with guard digits for supplied significance/exponents),
ROUND_HALF_UP, and six-decimal output postings. Caller precision, rounding mode and
Inexact traps cannot change the result. Proportional calculations use exact input
Decimals until the declared output quantum. Where rounded ledgers must conserve
money, complementary fields derive from already rounded postings: withheld + net
= posted gross, recoverable + nonrecoverable = posted input VAT, deductible +
disallowed = posted interest, and depreciation totals equal posted row sums.
Loss vintages/incoming taxable ledger amounts are six-decimal postings before
FIFO movements; openings, consumption, generation, expiry and closing reconcile.
These are candidate numerical bookkeeping conventions, not statutory tax rules.

Tax reconciliation checks loss use against the positive exact-input pre-loss base
before rounding and again against the posted base. Negative/above-available offsets
fail TAX_WF10_LOSS_UTILISATION; a negative base without offset generates its actual
posted loss. The exact-input pre-loss sum is rounded once. Rounded displayed lines
may not sum to that value; rounding_adjustment_keur exposes the difference instead
of silently changing taxable income or creating a loss from rounding. The reported
identity includes that explicit adjustment. No positive-income year can generate
a loss through excess utilisation or component-rounding cancellation.

DATED_SERIES requires an immutable, strictly chronological tuple (duplicates retain
TAX_WF10_OVERLAP; unsorted input fails TAX_WF10_RATE_ORDER). Lookup cannot select an
older window because of input order. CIT validates every effective transition in
(start, end], where the supplied tax-year boundaries are inclusive. Change/reversion
fails TAX_WF10_TAX_YEAR_RATE_SPLIT even when beginning/end rates match. Repeated
same-rate windows are stable; uncovered beginning/end remains UNAVAILABLE. A new
rate on the year start is that year's initial rate, not an intrayear split; a new
rate on the inclusive end is a split. Invalid date intervals fail closed.

A depreciation asset entering inside a supplied period cannot consume the full
period fraction implicitly. active_day_fraction plus active_fraction_source is
required, nonnegative and <= full period fraction; without it the helper fails
TAX_WF10_DEPRECIATION_PRORATION_REQUIRED. No active fraction is derived from a
jurisdiction, day-count guess or COD label. Entry exactly at period start can use
the existing full fraction; entry on its inclusive final date still needs supplied
partial-active evidence. The old full-life numerical fixture now uses genuine full
annual periods starting with the in-service date; its monetary assertions are
unchanged. New tests retain and separately exercise the previously invalid geometry.

Correction evidence covers significant Decimal values above float's exact integer
range and long-significance amounts; finite guards; half-up boundaries and micro
CIT/withholding/loss postings; low/high ambient context equivalence across CIT,
losses, VAT, withholding and depreciation; all dated transitions including reversion;
loss rejection and exact reported identities; explicit depreciation proration.
Adjacent canonical CIT and FIFO regression tests remain unchanged.
