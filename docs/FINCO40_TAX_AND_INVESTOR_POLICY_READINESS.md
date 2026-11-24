# FINCO40 — Tax (`OD-TAX-01` / `P1-TAX-01`) & Investor (`OD-INVEST-01` / `C1F-B-1/2/3`) Policy Readiness Memo

> **Status**: Policy-independent engineering readiness implemented on PR #482 (`integration/finco38-40-opex-calendar-policy`).
> **No unauthorized tax, legal, or waterfall policy changes were made.**

---

## 1. Tax Policy Readiness (`OD-TAX-01` / `P1-TAX-01`)

### 1.1 Current Production Behavior (Unchanged)
- **Book depreciable base** (`CapexStructure.book_depreciable_capex_items()` in `finco_core/inputs/_models.py`): capitalizes hard CAPEX plus construction financing items (`idc_keur`, `commitment_fees_keur`, `bank_fees_keur` over 12 years, `vat_costs_keur` over 20 years).
- **Tax depreciable base** (`TaxParams.tax_dep_basis_source_owned` defaults to `False`): `tax_depreciable_capex_items()` returns **hard CAPEX only**, excluding capitalized construction financing costs (`idc_keur`, `commitment_fees_keur`, `bank_fees_keur`).
- **Operating interest**: `period_interest` reflects operating debt interest only (excludes construction-period IDC).
- **Net tax effect today**: Capitalized construction financing costs are **permanently non-deductible** for Corporate Income Tax (CIT), with **no deferred tax asset/liability** recognized.
- **Dormant tax registry**: `tax_reference_registry/` remains dormant (`ActivationBlockedError`), and WF10 jurisdiction policy decisions `D-01..D-13` remain OPEN.

### 1.2 Reproducible Hypothetical A/B Verification (Non-Production)
`tests/test_finco40_tax_investor_readiness.py::test_od_tax_01_hypothetical_ab_comparison_without_changing_default` runs an exact side-by-side comparison on dated Solar and Wind projects:
- **Arm A (Current production default)**: `tax_dep_basis_source_owned=False` (hard CAPEX tax basis only; construction financing permanently non-deductible).
- **Arm B (Hypothetical)**: `tax_dep_basis_source_owned=True` (tax basis follows book-depreciable basis including capitalized construction IDC/fees).
- **Verified**: Production default remains strictly `False`; Arm B increases cumulative tax depreciation by the exact capitalized financing cost basis, lowers cumulative CIT, and lifts CFADS / Equity IRR while maintaining a balanced Balance Sheet (`|BS diff| < 1e-6`).

### 1.3 Owner / Tax-Adviser Decision Options (`OD-TAX-01`)
1. **Option A (Status quo — conservative)**: Keep `tax_dep_basis_source_owned=False` (capitalized construction financing permanently non-deductible; simplest auditability, conservatively higher CIT).
2. **Option B (Book-aligned tax amortization)**: Allow capitalized IDC/fees in tax depreciable basis (amortized over asset/debt life; requires jurisdiction tax-adviser sign-off).
3. **Option C (Current-period deduction + NOL carryforward)**: Deduct construction financing costs as incurred during construction, creating tax losses carried forward into operations (requires NOL expiry/cap rules under WF10 `D-01..D-13`).
4. **Option D (Jurisdiction-configurable deferred tax)**: Activate jurisdiction profiles in `tax_reference_registry/` once WF10 `D-01..D-13` are signed off by tax counsel.

---

## 2. Investor Agreement Readiness (`OD-INVEST-01` / `C1F-B-1/2/3`)

### 2.1 Implemented Policy-Independent Controls
1. **`C1F-B-1` — Incomplete-Contribution Draft Warning (Save/GET/UI; Run remains fail-closed)**:
   - `assess_contribution_completeness()` in `app/model_v2/investor_f4.py` evaluates saved working agreements against Last Run canonical legal-equity funding.
   - Saving empty (`INCOMPLETE_CONTRIBUTIONS_EMPTY`) or date/amount-mismatched (`INCOMPLETE_CONTRIBUTIONS_MISMATCH`) contributions remains permitted for drafting, and now surfaces an explicit `draft_warning` in:
     - Legacy F4 HTML (`data-testid="f4-incomplete-draft-warning"`)
     - React Investors JSON API (`GET /v2/model-react/investors/agreement` -> `draft_warning`)
     - React `InvestorsPanel` UI (`data-investor-draft-warning`)
   - `POST /v2/workbook/run` remains strictly fail-closed (`allocate_run()` raises before commit if paid-in capital does not reconcile by exact date).
2. **`C1F-B-2` — Durable Monotonic / Tombstone `(agreement_id, version)` Ledger**:
   - New SQLite table `investor_agreement_version_ledger` (`app/persistence/investor_agreement_ledger_repository.py`, registered in `app/trust_readiness/registry.py`) keyed by `(owner_id, project_id, scenario_id, agreement_id)`.
   - Enforced atomically inside `BEGIN EXCLUSIVE` in `app/workbook/investor_agreement_service.py`:
     - Removing a working agreement (`remove=True`) or renaming `AGR-1 -> AGR-2` tombstones `AGR-1` at its highest committed version.
     - Re-creating or renaming back to `AGR-1` at any version `<= max_version` is refused with `InvestorAgreementConflict` (HTTP 409).
     - Strict monotonic continuation (`v = max_version + 1`) is permitted; tenant, project, and scenario scopes are strictly isolated.
3. **`C1F-B-3` — Zero-Paid-In & Negative Retained Earnings Edge-Case Reproduction**:
   - Verified in `tests/test_finco40_tax_investor_readiness.py`:
     - **60:40 one-founder-paid** (Founder A pays 100% of legal equity, Founder B pays `0.0`): Founder B receives `dpi=None`, `realized_moic=None`, `xirr=None`, `xirr_status="NO_NEGATIVE_CASHFLOW"` (zero NaN/Inf/fabrication); Founder A receives finite DPI/XIRR; total investor distributions equal 100% of canonical net dividends.
     - **Negative retained earnings / dividend-trap reproduction**: On a low-tariff (`18 EUR/MWh`, `EQUITY_ONLY`) dated Solar case, the current cash-sweep waterfall distributes `~26,494 kEUR` of net dividends across `51` periods in which `retained_earnings_keur < 0` (min `-29,070 kEUR`), while the Balance Sheet remains balanced (`|BS diff| < 1e-5`). No unauthorized statutory dividend-trap change was made; documented below for owner decision (`OD-INVEST-01`).
     - **Immutable history replay & export**: Committed Run History investor evidence and exports remain immutable after subsequent working agreement edits or removals.

### 2.2 Deferred Owner / Legal Policy Decisions (`OD-INVEST-01` — Out of Scope for PR #482)
- **Statutory retained-earnings dividend trap** (reproduced above):
  - **Option A (Status quo — economic cash-sweep)**: Keep covenant-gated cash-sweep distributions (assumes share-premium / capital-reduction mechanics in practice).
  - **Option B (Statutory RE blocker)**: Cap `gross_dividend_paid_keur <= max(0, distributable_retained_earnings)` and retain trapped cash on the Balance Sheet (or route via explicit ROC / share-premium reduction in FINCO41).
- Return-of-capital (ROC) ordering, preferred returns / hurdle rates, carry / promote tiers, NAV / terminal valuation multiples, and shareholder-loan (SHL) lender-level allocation remain **explicitly deferred** to FINCO41 (`Investor F4` / Acquisition).
