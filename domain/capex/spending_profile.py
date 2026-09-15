"""CAPEX spending profile distribution.

Distributes CAPEX items across construction periods based on spending profiles.
Matches Excel Inputs rows 23-44 with spending columns D-H (Y0-Y4).

For Generic Solar Reference:
- Y0: Before construction (FC date)
- Y1-Y4: Construction spending years

Items with 100% Y0: Project Rights, Contingencies, Insurances, Bank Fees
Items with linear: EPC Contract (8.3%/month × 12 months)
"""
from typing import Sequence
from domain.inputs import CapexItem, CapexStructure, ProjectInputs
from domain.period_engine import PeriodEngine, PeriodMeta


def capex_in_period(
    item: CapexItem,
    period_index: int,
) -> float:
    """Calculate CAPEX amount for a specific period.
    
    Args:
        item: CapexItem
        period_index: Period index (0=Y0-H1, 1=Y0-H2, 2=Y1-H1, etc.)
    
    Returns:
        CAPEX amount in kEUR for this period
    """
    if period_index == 0:
        # Y0-H1: use y0_share
        return item.amount_keur * item.y0_share
    
    # Map period to construction year
    # period 0,1 = Y0 (construction)
    # period 2+ = Y1+ (operation, no CAPEX for construction items)
    if period_index <= 1:
        # Still in Y0
        return 0.0
    
    # Y1 = period_index - 1
    year = period_index - 1
    return item.amount_in_period(year)


def distribute_capex_items(
    items: list[CapexItem],
    periods: Sequence[PeriodMeta],
) -> dict[int, float]:
    """Distribute all CAPEX items across periods.
    
    Args:
        items: List of CapexItems
        periods: Period metadata
    
    Returns:
        Dict mapping period_index → total CAPEX in kEUR
    """
    schedule = {p.index: 0.0 for p in periods}
    
    for period in periods:
        for item in items:
            schedule[period.index] += capex_in_period(item, period.index)
    
    return schedule


def construction_capex_schedule(
    inputs: ProjectInputs,
    engine: PeriodEngine,
) -> dict[int, float]:
    """Generate construction CAPEX schedule.
    
    Only includes construction periods (Y0-Y3 based on Generic Solar Reference).
    
    Args:
        inputs: Project inputs
        engine: Period engine
    
    Returns:
        Dict mapping period_index → CAPEX in kEUR
    """
    # Get all CAPEX items
    items = [
        inputs.capex.epc_contract,
        inputs.capex.production_units,
        inputs.capex.epc_other,
        inputs.capex.grid_connection,
        inputs.capex.ops_prep,
        inputs.capex.insurances,
        inputs.capex.lease_tax,
        inputs.capex.construction_mgmt_a,
        inputs.capex.commissioning,
        inputs.capex.audit_legal,
        inputs.capex.construction_mgmt_b,
        inputs.capex.contingencies,
        inputs.capex.taxes,
        inputs.capex.project_acquisition,
        inputs.capex.project_rights,
    ]
    
    schedule = {}
    
    for period in engine.periods():
        if not period.is_construction and period.index > 1:
            # Only Y0 and Y1-H1 (first operation period) count as construction
            schedule[period.index] = 0.0
            continue
        
        capex_total = sum(capex_in_period(item, period.index) for item in items)
        schedule[period.index] = capex_total
    
    return schedule


def total_hard_capex(
    items: list[CapexItem],
) -> float:
    """Calculate total hard CAPEX (sum of all items).
    
    Args:
        items: List of CapexItems
    
    Returns:
        Total CAPEX in kEUR
    """
    return sum(item.amount_keur for item in items)


def total_capex_with_financing_fees(
    inputs: ProjectInputs,
) -> float:
    """Calculate total CAPEX including financing fees.
    
    Total CAPEX = Hard CAPEX + IDC + Commitment Fees + Bank Fees + VAT + Reserves
    
    Args:
        inputs: Project inputs
    
    Returns:
        Total CAPEX in kEUR
    """
    capex = inputs.capex
    
    return (
        capex.hard_capex_keur
        + capex.idc_keur
        + capex.commitment_fees_keur
        + capex.bank_fees_keur
        + capex.other_financial_keur
        + capex.vat_costs_keur
        + capex.reserve_accounts_keur
    )


def spending_profile_summary(
    items: list[CapexItem],
) -> dict[int, float]:
    """Generate summary of CAPEX by period.
    
    Args:
        items: List of CapexItems
    
    Returns:
        Dict mapping year → CAPEX in kEUR
    """
    # Max 5 years (Y0-Y4)
    schedule = {year: 0.0 for year in range(5)}
    
    for item in items:
        schedule[0] += item.amount_keur * item.y0_share
        for year_idx, share in enumerate(item.spending_profile, start=1):
            if year_idx < 5:
                schedule[year_idx] += item.amount_keur * share
    
    return schedule