"""Candidate evidence boundary. NO canonical BESS finance/persistence promotion."""
import hashlib
from dataclasses import dataclass
from decimal import Decimal

from domain.bess.contracts import BessConfiguration, BessInputError
from domain.bess.dispatch import BatteryResult
from domain.bess.settlement import FinancialPeriodProposal, aggregate_to_financial_periods

ACTIVATION_ENABLED = False


class BessFinancialIntegrationUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class FinancialHandoff:
    released: bool
    blockers: tuple[str, ...]
    periods: tuple[FinancialPeriodProposal, ...]
    initial_capex_categories: tuple[tuple[str, str, float], ...]
    opex_categories: tuple[str, ...]


def propose_financial_handoff(project_inputs, config: BessConfiguration, result: BatteryResult) -> FinancialHandoff:
    """Inspect the actual canonical calendar and cost structures; never a Run.

    The current clean OperatingModelInput drops TechnicalParams.bess. Gross
    receipts and charging/aux/grid expenses therefore cannot safely be injected
    without a reviewed typed native operating-input successor. Post-COD asset
    commissioning/disposal/tax is a separate missing authority, not an expense.
    """
    if not project_inputs.technical.bess_enabled:
        raise BessInputError("BESS_VERTICAL: an explicitly battery-enabled source is required")
    if project_inputs.technical.operating_hours_p50 or project_inputs.technical.operating_hours_p90_10y:
        raise BessInputError("BESS_VERTICAL: hybrid generation is not supported")
    if result.input_fingerprint != hashlib.sha256(config.canonical_json.encode()).hexdigest():
        raise BessInputError("BESS_BINDING: physical result does not belong to submitted configuration")
    blockers = ["BESS_FINANCIAL_RELEASE_CLOSED", "BESS_NATIVE_OPERATING_INPUT_AUTHORITY_MISSING",
                "BESS_GROSS_RECEIPTS_AND_PURCHASE_EXPENSE_CLASSIFICATION_NOT_RELEASED",
                "BESS_TYPED_WORKBOOK_SCENARIO_RUN_SERIALIZATION_NOT_RELEASED"]
    legacy = project_inputs.technical.bess
    if legacy is None or (Decimal(str(legacy.power_mw)) != config.battery.discharge_power_mw
                         or Decimal(str(legacy.energy_mwh)) != config.battery.installed_energy_mwh):
        blockers.append("BESS_SAVED_PHYSICAL_INPUT_MISMATCH")
    if config.events:
        blockers.append("BESS_POST_COD_ASSET_COMMISSIONING_BOOK_TAX_AND_FUNDING_UNRESOLVED")
    if config.battery.initial_energy_mwh or config.battery.terminal_energy_mwh:
        blockers.append("BESS_INITIAL_TERMINAL_INVENTORY_FINANCIAL_BASIS_UNRESOLVED")
    from finco_core.engine.period_engine import PeriodEngine
    info = project_inputs.info
    proposed = ()
    try:
        engine = PeriodEngine(info.financial_close, info.construction_months, info.horizon_years, 0,
            frequency=info.period_frequency, cod_date=info.cod_date, period_axis_convention=info.period_axis_convention.value)
        proposed = aggregate_to_financial_periods(result, engine.periods())
    except ValueError as exc:
        blockers.append("BESS_CANONICAL_AXIS_UNAVAILABLE: " + str(exc))
    from app.services.production_financial_authority import classify_production_authority
    decision = classify_production_authority(project_inputs)
    if not decision.promoted:
        blockers.append(decision.reason_code)
    capex = tuple((row.name, row.asset_class.value, row.amount_keur) for row in project_inputs.capex.capex_items())
    opex = tuple(item.name for item in project_inputs.opex)
    return FinancialHandoff(False, tuple(blockers), proposed, capex, opex)


def require_canonical_financial_run(_handoff: FinancialHandoff):
    # Neither an app setting nor caller-supplied ready flag can bypass a missing
    # reviewed financial integration. This function is never an alternative Run.
    raise BessFinancialIntegrationUnavailable("BESS_FINANCIAL_RELEASE_CLOSED: typed native input and accounting handoff not released")
