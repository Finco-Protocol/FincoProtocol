"""Phase 6C.3 — HoldCo tax engine runner.

Pure function — no mutation, no side effects, no waterfall wiring.

Uses Phase 6C.1 schema (HoldCoTaxInputs, HoldCoTaxResult) and
Phase 6C.2 primitives (WHT calculation, SHL treatment, taxable income).

No active CIT calculation. No WHT remittance/payment timing.
No thin-cap enforcement. No waterfall integration.
"""
from __future__ import annotations

from finco_core.tax.holdco_inputs import HoldCoTaxInputs
from finco_core.tax.holdco_result import HoldCoTaxPeriodResult, HoldCoTaxResult
from finco_core.tax.holdco_calculations import (
    calculate_withholding_tax_keur,
    exclude_shl_principal_from_taxable_income,
)


__all__ = ["run_holdco_tax_engine"]


def run_holdco_tax_engine(
    inputs: HoldCoTaxInputs,
) -> HoldCoTaxResult:
    """Run the HoldCo tax engine over all periods.

    Pure function — no mutation, no side effects.

    Per-period flow:
    1. dividend_income → taxable (WHT applicable)
    2. SHL interest income → taxable (WHT applicable)
    3. SHL principal → non-taxable (excluded from taxable income)
    4. holdco_opex → deductible (reduces taxable income)
    5. WHT calculated and stored (not remitted)
    6. interest_limited_keur = 0 (no HoldCo interest expense in current schema)

    Parameters
    ----------
    inputs : HoldCoTaxInputs
        Complete HoldCo tax inputs per period.

    Returns
    -------
    HoldCoTaxResult
        Audit-ready result with per-period breakdown and totals.

    Notes
    -----
    - SHL principal repayments are **not** taxable income.
    - WHT amounts are **calculated and stored** — no payment/remittance timing.
    - interest_limited_keur is 0 — thin-cap/EBITDA limitations are stored
      in config but not applied in Phase 6C.3.
    - No CIT payable is calculated — Phase 6C.3 is audit-only.
    """
    n = len(inputs.dividend_income_by_period_keur)

    period_results: list[HoldCoTaxPeriodResult] = []

    for p in range(n):
        dividend = inputs.dividend_income_by_period_keur[p]
        shl_interest = inputs.shl_interest_income_by_period_keur[p]
        shl_principal = inputs.shl_principal_received_by_period_keur[p]
        opex = inputs.holdco_opex_by_period_keur[p]

        # SHL principal → validate (rejects negative), then track as non-taxable
        exclude_shl_principal_from_taxable_income(shl_principal)  # raises if negative
        non_taxable_principal_keur = shl_principal  # track the amount, not 0

        # WHT on dividends and interest (stored, not remitted)
        wht_div = calculate_withholding_tax_keur(
            dividend, inputs.withholding_tax_config.rate_dividends
        )
        wht_int = calculate_withholding_tax_keur(
            shl_interest, inputs.withholding_tax_config.rate_interest
        )

        # Taxable income before thin-cap / EBITDA limitations
        taxable_income = (
            dividend
            + shl_interest
            - opex
        )

        period_notes = [
            "SHL principal excluded from taxable income",
            "WHT stored, not remitted",
            "thin-cap/EBITDA limitations stored in config, not applied in Phase 6C.3",
        ]
        period_warnings: tuple[str, ...] = ()

        period_results.append(
            HoldCoTaxPeriodResult(
                period_index=p,
                taxable_dividend_income_keur=dividend,
                taxable_interest_income_keur=shl_interest,
                non_taxable_principal_keur=non_taxable_principal_keur,
                deductible_opex_keur=opex,
                taxable_income_before_limitations_keur=taxable_income,
                withholding_tax_dividends_keur=wht_div,
                withholding_tax_interest_keur=wht_int,
                interest_limited_keur=0.0,
                notes=tuple(period_notes),
                warnings=period_warnings,
            )
        )

    # Aggregate totals
    total_div = sum(r.taxable_dividend_income_keur for r in period_results)
    total_int = sum(r.taxable_interest_income_keur for r in period_results)
    total_principal = sum(r.non_taxable_principal_keur for r in period_results)
    total_wht_div = sum(r.withholding_tax_dividends_keur for r in period_results)
    total_wht_int = sum(r.withholding_tax_interest_keur for r in period_results)

    result_notes = (
        "Phase 6C.3 HoldCo tax engine — audit only",
        "WHT calculated but not remitted",
        "No CIT payable in Phase 6C.3",
        "No thin-cap/EBITDA limitation enforcement",
        "No waterfall integration",
    )

    return HoldCoTaxResult(
        entity_code=inputs.entity_code,
        country_code=inputs.country_code,
        tax_year=inputs.tax_year,
        period_results=tuple(period_results),
        total_taxable_dividend_keur=total_div,
        total_taxable_interest_keur=total_int,
        total_non_taxable_principal_keur=total_principal,
        total_withholding_tax_dividends_keur=total_wht_div,
        total_withholding_tax_interest_keur=total_wht_int,
        metadata=inputs.metadata,
        notes=result_notes,
    )