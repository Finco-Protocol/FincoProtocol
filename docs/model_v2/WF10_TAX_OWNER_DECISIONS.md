# WF-10 — Advanced Tax & Jurisdiction Contracts V1 — Financial Owner Decision Register

Branch: `feat/model-wf10-tax-jurisdictions-candidate-v1` (base `a0c0d3efd215a28a82b6d01294186ddc373e943b`).
Package: `app/model_v2/tax_wf10_candidate/` (release-closed; `TAX_WF10_RELEASE_CLOSED`).

**Every decision below is OPEN.** The candidate implements only the
deterministic core each decision would operate on; no rate, convention,
recovery percentage or legal interpretation is invented, defaulted or
implied. Harvest/reference observations are NOT FINCO policy authority.

| # | Decision | Released behaviour today | Candidate V1 convention (explicit, changeable) | Consequence of the choice |
|---|---|---|---|---|
| D-01 | Tax jurisdiction and entity determination | `TaxJurisdictionProfile` (XA/XB/XC synthetic, provenance-gated); `country_iso` on project info; no jurisdiction→rate mapping anywhere | Opaque 2-char code per `TaxEntityIdentity`; every economic parameter arrives separately | Which real jurisdictions/profiles get registered, and under what provenance (`SOURCE_PROVEN` evidence standard), before anything resolves |
| D-02 | Effective date of each legal assumption | Production rate is per-run (no dates); audit templates are per-`tax_year` | `TaxRateSchedule` dated windows; a rate change inside one caller-declared tax year fails closed (`TAX_WF10_TAX_YEAR_RATE_SPLIT`) | Whether tax years must be re-aligned to legal rate-change dates, or a day-proportional split within a tax year is permitted |
| D-03 | Corporate tax rate source | Workbook `tax_corporate_rate_pct` (single value); `corporate_rate_override` under a country policy id | Rates only via `TaxRateSchedule` evidence | The authoritative source of rates per jurisdiction (Financial Owner supply vs an approved template registry) and its update policy |
| D-04 | Interest deduction limits | Production: annual `max(30% EBITDA, 3k)` de-minimis with chronological allocation; EBITDA≤0 → de-minimis-only capacity; carryforward raises NOT IMPLEMENTED; thin-cap raises NOT IMPLEMENTED | Same capacity shape on caller-declared tax-year figures; explicit `disallowed` output; no carryforward, no thin-cap | Whether disallowed interest carries forward, whether EBITDA≤0 should limit everything (HoldCo-audit convention), and whether a thin-cap formula is ever added |
| D-05 | Depreciation convention | Runtime straight-line only (`Only straight_line depreciation is implemented`); per-class book/tax lives on main; deferred tax = declared non-capability | STRAIGHT_LINE only; explicit book/tax lives per asset; temporary-difference ledger; no DTA/DTL | Whether accelerated/declining methods are ever supported (with what evidence), and whether a deferred-tax engine is built |
| D-06 | Construction/COD depreciation boundary | Tax depreciation starts from placed-in-service per the canonical wiring (`cod_period=2` convention) | `in_service_date >= COD` required; construction-period tax depreciation fails closed | Whether assets commissioned before COD may depreciate (and how construction-period depreciation interacts with the construction P&L / reintegration) |
| D-07 | Tax loss utilisation | Production: vintage FIFO, finite `loss_carryforward_years` (workbook field 0–30), implicit 100% offset, `TAXABLE_INCOME_POSITIVE` gate | Window OR unlimited (explicit); explicit `utilisation_cap_pct`; expiry-before-use; FIFO | Jurisdiction-specific windows/caps if they differ from the project setting, the utilisation gate (`TAXABLE_INCOME_POSITIVE` vs `EBT_POSITIVE`), and ordering vs the cap |
| D-08 | VAT recovery eligibility and timing | No recovery engine on main (only per-CAPEX-item `vat_rate` + VAT facility financing); `TaxParams.vat_rate` fields are dead | Explicit rate + BOTH phase recovery percentages; net cash position per period (payable/refundable) | Recovery percentages per jurisdiction/asset class, refund lag/timing rules, and whether refund positions earn interest or carry forward |
| D-09 | Non-recoverable VAT treatment | Capitalised into the depreciable basis in the construction money flow; "capitalised-VAT treatment is OPEN — no authoritative per-project tax evidence" | Explicit CAPITALISE vs EXPENSE policy per config (no default) | Per-jurisdiction policy, and the interaction with the depreciation basis when CAPITALISE is chosen |
| D-10 | Construction-phase tax/VAT treatment | Construction periods are non-operating (generation/revenue zero); construction P&L loss seeds the loss ledger (`construction_pl.py`) | Out of candidate scope except the VAT phase split; CIT on construction activity not modelled | Whether construction-phase taxable income/loss follows the released construction-P&L seeding unchanged, and pre-COD VAT cash treatment in the funding plan |
| D-11 | SHL and dividend withholding | Dividend WHT typed in `DistributionAccountingPolicy` (unenabled by default → 0.0); SHL interest WHT parameters on SHL inputs (0.0 defaults); HoldCo audit WHT stored-not-remitted; no remittance timing | Rates + `legal_basis_ref` evidence per rule; senior/junior need a substantive basis; gross/net conservation; flow-id double-withholding prevention | Per-jurisdiction WHT rates and their evidence, remittance timing/authority, and whether senior/junior interest WHT is ever in scope |
| D-12 | HoldCo/SPV consolidation and distribution treatment | HoldCo roll-up is audit-only with a flat placeholder rate ("Do not add ATAD or detailed tax logic here"); no consolidated computation anywhere | Separate ledgers only; exact intercompany identities; PRINCIPAL never taxable; no consolidation routine exists (structural test) | Whether a consolidation or participation-exemption regime is ever modelled, and how HoldCo tax/WHT feeds sponsor distributions |
| D-13 | Rounding and currency conventions | Engine canonical unit kEUR; candidate uses exact Decimal, 6-decimal quantisation, ROUND_HALF_UP at output boundaries | Same as released candidates | Whether tax figures need a different quantum (e.g. whole EUR/cent), banker's rounding for statutory returns, or per-currency minor units |

## Required approvals for ANY release path

1. Financial Owner exact-content decision for the released slice (house style:
   `FINANCIAL_OWNER_*_DECISION_*.md` + exact JSON record + tests-side content
   pin — cf. the V11 Stage 3 precedent).
2. Independent review of every byte that would leave this package.
3. A governance successor slice (`tests/test_ci_acceptance.py` exact-path +
   exact-blob map) for any protected file the release wiring must touch —
   notably `financial_engine/policies/tax.py`, `financial_engine/tax/engine.py`
   (see design doc §5 seams).
4. Until then the package stays release-closed and production-invisible
   (proven by the isolation scans in `tests/test_tax_wf10_candidate.py`).
