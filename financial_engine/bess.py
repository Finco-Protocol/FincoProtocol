"""Native merchant receipts/expenses into the ONE existing financial engine."""
from dataclasses import dataclass
import json
from decimal import Decimal

from financial_engine.inputs import TechnicalInput
from financial_engine.run_scope import scoped_memo
from finco_core.inputs.bess_native import parse_native_contract
from domain.bess.dispatch import evaluate
from domain.bess.settlement import aggregate_to_financial_periods


@dataclass(frozen=True)
class NativeBessTechnicalInput(TechnicalInput):
    bess_native_config_json: str = ""


@dataclass(frozen=True)
class LegacyBessTechnicalInput(TechnicalInput):
    """Legacy ``bess_enabled`` flag WITHOUT a native contract.

    Adaptation (metadata, depreciation classes, reference listings) keeps working exactly as before, but this
    marker can never be executed: ``run_operating_model`` rejects it with BESS_NATIVE_CONTRACT_REQUIRED, so no
    legacy spread economics are ever calculated and no financial authority is added.
    """
    bess_legacy_unsupported: bool = True


@scoped_memo(maxsize=2)
def operating_evidence(raw: str, periods: tuple):
    """Full hourly proof transient; bounded period evidence is the finance handoff."""
    contract = parse_native_contract(raw)
    config = contract.configuration
    if config.events:
        raise ValueError("BESS_POST_COD_ACCOUNTING_RELEASE_CLOSED: no augmentation financial posting")
    if config.battery.initial_energy_mwh or config.battery.terminal_energy_mwh:
        raise ValueError("BESS_INVENTORY_FINANCIAL_BASIS_UNRESOLVED")
    result = evaluate(config)
    rows = aggregate_to_financial_periods(result, periods)
    evidence = []
    offset = 0
    for row in rows:
        hours = result.hours[offset:offset + row.hours]
        offset += row.hours
        throughput = sum((h.dc_throughput_mwh for h in hours), Decimal(0))
        variable = throughput * contract.variable_om_eur_per_dc_mwh / 1000
        evidence.append(json.dumps({
            "authority": "bess_native_hourly_v1", "input_fingerprint": result.input_fingerprint,
            "period_index": row.period_index, "cash_date": row.cash_date, "hours": row.hours,
            "canonical_accrual_days": row.canonical_accrual_days,
            "gross_sale_revenue_keur": str(row.gross_sale_revenue_keur),
            "charging_purchase_cost_keur": str(row.charging_purchase_cost_keur),
            "auxiliary_purchase_cost_keur": str(row.auxiliary_purchase_cost_keur),
            "grid_import_charge_keur": str(row.import_charges_keur),
            "grid_export_charge_keur": str(row.export_charges_keur),
            "net_merchant_contribution_keur": str(row.net_merchant_contribution_keur),
            "variable_om_keur": str(variable), "lifecycle_capex_keur": str(row.lifecycle_capex_keur),
            "net_after_variable_om_keur": str(row.net_merchant_contribution_keur - variable),
            "dc_throughput_mwh": str(throughput), "grid_import_mwh": str(row.grid_import_mwh),
            "grid_export_mwh": str(row.grid_export_mwh),
            "opening_energy_mwh": str(hours[0].opening_energy_mwh),
            "closing_energy_mwh": str(hours[-1].closing_energy_mwh),
            "closing_soh": str(hours[-1].soh_closing),
            "cumulative_efc": str(hours[-1].cumulative_equivalent_full_cycles),
            "max_energy_residual_mwh": str(row.maximum_energy_residual_mwh),
        }, sort_keys=True))
    return tuple(evidence)


def require_native_separation(inputs):
    tech, rev = inputs.technical, inputs.revenue
    if tech.operating_hours_p50 or tech.operating_hours_p90_10y:
        raise ValueError("BESS_HYBRID_NOT_SUPPORTED")
    if (rev.ppa_base_tariff_eur_mwh or rev.ppa_term_years or rev.ppa_production_share or rev.co2_enabled
            or getattr(rev, "multistream_config_json", "")):
        raise ValueError("BESS_DUPLICATE_REVENUE_AUTHORITY")
