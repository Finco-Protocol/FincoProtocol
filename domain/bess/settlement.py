"""Dimensional handoff proposals, never netted revenue or a second finance engine."""
from dataclasses import dataclass
from datetime import datetime, time, timezone
from decimal import Decimal, localcontext

from domain.bess.contracts import BessInputError
from domain.bess.dispatch import BatteryResult


@dataclass(frozen=True)
class FinancialPeriodProposal:
    period_index: int
    cash_date: str
    hours: int
    canonical_accrual_days: int
    grid_import_mwh: Decimal
    grid_export_mwh: Decimal
    gross_sale_revenue_keur: Decimal
    charging_purchase_cost_keur: Decimal
    auxiliary_purchase_cost_keur: Decimal
    import_charges_keur: Decimal
    export_charges_keur: Decimal
    net_merchant_contribution_keur: Decimal
    lifecycle_capex_keur: Decimal
    maximum_energy_residual_mwh: Decimal


def aggregate_to_financial_periods(result: BatteryResult, periods) -> tuple[FinancialPeriodProposal, ...]:
    """Require the FULL authoritative operating axis, not integer year indices.

    Explicit settlement policy is canonical financial period end. These are
    proposed classified receipts/expenses/CAPEX, not posted statements/CFADS.
    """
    with localcontext() as context:
        context.prec = 40
        return _aggregate(result, periods)


def _aggregate(result, periods):
    from finco_core.engine.period_engine import validate_canonical_period_axis
    periods = tuple(periods)
    try:
        validate_canonical_period_axis(periods)
    except ValueError as exc:
        raise BessInputError("BESS_FINANCE_AXIS: " + str(exc)) from exc
    operating = tuple(p for p in periods if p.is_operation)
    if not operating or len({p.index for p in operating}) != len(operating):
        raise BessInputError("BESS_FINANCE_AXIS: unique canonical operating periods required")
    utc = lambda day: datetime.combine(day, time(), timezone.utc)
    if result.hours[0].start != utc(operating[0].start_date) or result.hours[-1].end != utc(operating[-1].end_date):
        raise BessInputError("BESS_FINANCE_AXIS: complete dispatch must exactly cover canonical operating horizon")
    position, previous_end, proposals = 0, None, []
    names = ("grid_import_mwh", "grid_export_mwh", "gross_sale_revenue_keur", "charging_purchase_cost_keur",
             "auxiliary_purchase_cost_keur", "grid_import_charge_keur", "grid_export_charge_keur",
             "net_merchant_contribution_keur", "lifecycle_capex_keur")
    for period in operating:
        a, b = utc(period.start_date), utc(period.end_date)
        if a >= b or (previous_end is not None and a != previous_end):
            raise BessInputError("BESS_FINANCE_AXIS: positive contiguous canonical intervals required")
        first = position
        while position < len(result.hours) and result.hours[position].start < b:
            point = result.hours[position]
            if point.start < a or point.end > b:
                raise BessInputError("BESS_FINANCE_AXIS: hourly interval straddles a finance boundary")
            position += 1
        selected = result.hours[first:position]
        if len(selected) != int((b - a).total_seconds() / 3600) or selected[0].start != a or selected[-1].end != b:
            raise BessInputError("BESS_FINANCE_AXIS: missing dispatch hours")
        values = [sum((getattr(row, field) for row in selected), Decimal(0)) for field in names]
        proposals.append(FinancialPeriodProposal(period.index, period.end_date.isoformat(), len(selected), period.days_in_period, *values,
            max(abs(row.energy_conservation_residual_mwh) for row in selected)))
        previous_end = b
    if position != len(result.hours):
        raise BessInputError("BESS_FINANCE_AXIS: unassigned merchant intervals")
    for field, total in (("grid_import_mwh", result.purchased_import_mwh), ("grid_export_mwh", result.delivered_export_mwh),
                         ("gross_sale_revenue_keur", result.gross_sale_revenue_keur), ("lifecycle_capex_keur", result.lifecycle_capex_keur)):
        if sum((getattr(row, field) for row in proposals), Decimal(0)) != total:
            raise BessInputError("BESS_SETTLEMENT: financial aggregation does not reconcile")
    return tuple(proposals)
