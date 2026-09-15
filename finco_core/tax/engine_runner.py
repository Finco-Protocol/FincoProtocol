"""Phase 6B.4 — Pure SPV tax engine runner.

run_spv_tax_engine() produces an SPVTaxResult from SPVTaxEngineInputs.

Pure function: no mutation, no side effects, no waterfall wiring.
No deferred tax accounting, no HoldCo logic, no SHL tax treatment,
no withholding tax — those are handled by future engine layers.

CAVEAT: This is a standalone SPV-level tax calculator only.
The entity-level result must be wired into the model waterfall
by a separate integration step (Phase 6B.5+).
"""
from __future__ import annotations

from finco_core.tax.engine_inputs import SPVTaxEngineInputs
from finco_core.tax.engine_result import SPVTaxResult, SPVTaxPeriodResult
from finco_core.tax.templates.schedules import (
    build_tax_depreciation_schedule,
    build_tax_loss_carryforward_schedule,
)
from finco_core.tax.templates.calculations import calculate_progressive_cit

__all__ = ["run_spv_tax_engine"]


def run_spv_tax_engine(inputs: SPVTaxEngineInputs) -> SPVTaxResult:
    """Run the pure SPV tax engine for one entity.

    Pure function: no mutation of inputs, no side effects,
    no waterfall integration.

    Flow
    ----
    1. Resolve the depreciation rule for the asset category.
    2. Build the tax depreciation schedule
       (book dep vs tax dep with timing differences and accumulated pool).
    3. For each period compute:
         taxable_income_before_losses =
           EBITDA
         - deductible_interest
         - tax_depreciation_claimed
         + non_deductible_addbacks
    4. Build the tax loss carryforward schedule from taxable_income_before_losses.
    5. Compute CIT per period using calculate_progressive_cit().
    6. Compute effective tax rate = cit / taxable_income_after_losses (0 if <= 0).
    7. Aggregate into SPVTaxResult.

    Parameters
    ----------
    inputs : SPVTaxEngineInputs
        Validated inputs including resolved tax config, EBITDA, interest,
        book depreciation, asset cost, and non-deductible addbacks.

    Returns
    -------
    SPVTaxResult
        Per-period and aggregate tax results for this entity.

    Notes
    -----
    - No ATAD EBITDA limitation applied here — apply in future ATAD engine.
    - No thin-cap adjustment applied here — apply in future thin-cap engine.
    - loss_carryforward_years is accepted but vintage tracking is deferred.
    - No withholding tax on distributions — future WHT engine layer.
    - No deferred tax accounting — future DTA/DTL engine layer.
    """
    # Step 1: Resolve depreciation rule from config
    resolved_config = inputs.resolved_tax_config
    resolved_template = resolved_config.resolved_template
    rule_map = {r.asset_category: r for r in resolved_template.depreciation_rules}
    rule = rule_map[inputs.depreciation_rule_asset_category]

    # Step 2: Build tax depreciation schedule
    tax_dep_schedule = build_tax_depreciation_schedule(
        asset_cost_keur=inputs.asset_cost_keur,
        book_depreciation_by_period=inputs.book_depreciation_by_period_keur,
        rule=rule,
    )

    n_periods = len(inputs.ebitda_by_period_keur)
    addbacks = inputs.non_deductible_addbacks_by_period_keur
    if len(addbacks) == 0:
        addbacks = tuple(0.0 for _ in range(n_periods))

    # Step 3 + 4 + 5: Period-by-period calculation
    periods: list[SPVTaxPeriodResult] = []
    taxable_incomes_before_losses: list[float] = []

    for period_idx in range(n_periods):
        ebitda = inputs.ebitda_by_period_keur[period_idx]
        ded_interest = inputs.deductible_interest_by_period_keur[period_idx]
        book_dep = inputs.book_depreciation_by_period_keur[period_idx]
        tax_dep = tax_dep_schedule.periods[period_idx].tax_depreciation_keur
        non_ded_dep = tax_dep_schedule.periods[period_idx].non_deductible_depreciation_keur
        addback = addbacks[period_idx]

        # Taxable income before losses
        taxable_before = (
            ebitda
            - ded_interest
            - tax_dep
            + addback
        )
        taxable_incomes_before_losses.append(taxable_before)

    # Step 4: Build loss carryforward schedule
    loss_schedule = build_tax_loss_carryforward_schedule(
        taxable_income_by_period_keur=tuple(taxable_incomes_before_losses),
        loss_carryforward_years=inputs.loss_carryforward_years,
    )

    # Step 5: CIT per period using resolved CIT tiers
    cit_tiers = resolved_template.cit_tiers

    for period_idx in range(n_periods):
        ebitda = inputs.ebitda_by_period_keur[period_idx]
        ded_interest = inputs.deductible_interest_by_period_keur[period_idx]
        book_dep = inputs.book_depreciation_by_period_keur[period_idx]
        tax_dep = tax_dep_schedule.periods[period_idx].tax_depreciation_keur
        non_ded_dep = tax_dep_schedule.periods[period_idx].non_deductible_depreciation_keur
        addback = addbacks[period_idx]

        taxable_before = taxable_incomes_before_losses[period_idx]

        # Loss carryforward results for this period
        loss_period = loss_schedule.periods[period_idx]
        loss_used = loss_period.loss_used_keur
        taxable_after = loss_period.taxable_income_after_losses_keur
        closing_loss_pool = loss_period.closing_loss_carryforward_keur

        # CIT payable
        cit_payable = calculate_progressive_cit(taxable_after, cit_tiers)

        # Effective tax rate
        if taxable_after > 0:
            eff_rate = cit_payable / taxable_after
        else:
            eff_rate = 0.0

        period_result = SPVTaxPeriodResult(
            period=period_idx,
            ebitda_keur=ebitda,
            deductible_interest_keur=ded_interest,
            book_depreciation_keur=book_dep,
            tax_depreciation_keur=tax_dep,
            non_deductible_depreciation_keur=non_ded_dep,
            taxable_income_before_losses_keur=round(taxable_before, 10),
            loss_used_keur=loss_used,
            taxable_income_after_losses_keur=round(taxable_after, 10),
            cit_payable_keur=round(cit_payable, 10),
            closing_loss_carryforward_keur=round(closing_loss_pool, 10),
            effective_tax_rate=round(eff_rate, 10),
        )
        periods.append(period_result)

    # Aggregate totals
    total_before = sum(p.taxable_income_before_losses_keur for p in periods)
    total_loss_used = sum(p.loss_used_keur for p in periods)
    total_after = sum(p.taxable_income_after_losses_keur for p in periods)
    total_cit = sum(p.cit_payable_keur for p in periods)
    ending_loss = periods[-1].closing_loss_carryforward_keur if periods else 0.0

    return SPVTaxResult(
        entity_code=inputs.entity_code,
        country_code=resolved_template.country_code,
        tax_year=resolved_template.tax_year,
        periods=tuple(periods),
        total_taxable_income_before_losses_keur=round(total_before, 10),
        total_loss_used_keur=round(total_loss_used, 10),
        total_taxable_income_after_losses_keur=round(total_after, 10),
        total_cit_payable_keur=round(total_cit, 10),
        ending_loss_carryforward_keur=round(ending_loss, 10),
    )