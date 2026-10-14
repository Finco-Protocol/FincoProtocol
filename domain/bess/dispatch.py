"""One hourly DC inventory equation; no optimizer, clipping or financial engine."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext

from dateutil.relativedelta import relativedelta

from domain.bess.contracts import BessConfiguration, BessInputError, DispatchMode, EventKind

ZERO = Decimal(0)


@dataclass(frozen=True)
class HourEvidence:
    start: datetime
    end: datetime
    requested_charge_mw: Decimal
    requested_discharge_mw: Decimal
    available: bool
    outage_suspension: bool
    opening_energy_mwh: Decimal
    closing_energy_mwh: Decimal
    available_energy_opening_mwh: Decimal
    available_energy_closing_mwh: Decimal
    installed_energy_mwh: Decimal
    soh_opening: Decimal
    soh_closing: Decimal
    ac_charge_mwh: Decimal
    ac_discharge_mwh: Decimal
    auxiliary_grid_mwh: Decimal
    grid_import_mwh: Decimal
    grid_export_mwh: Decimal
    charging_loss_mwh: Decimal
    discharging_loss_mwh: Decimal
    dc_throughput_mwh: Decimal
    equivalent_full_cycles: Decimal
    cumulative_equivalent_full_cycles: Decimal
    purchase_price_eur_mwh: Decimal
    sale_price_eur_mwh: Decimal
    gross_sale_revenue_keur: Decimal
    charging_purchase_cost_keur: Decimal
    auxiliary_purchase_cost_keur: Decimal
    grid_import_charge_keur: Decimal
    grid_export_charge_keur: Decimal
    net_merchant_contribution_keur: Decimal
    lifecycle_capex_keur: Decimal
    energy_conservation_residual_mwh: Decimal
    source_ref: str


@dataclass(frozen=True)
class BatteryResult:
    input_fingerprint: str
    hours: tuple[HourEvidence, ...]
    maximum_energy_residual_mwh: Decimal
    purchased_import_mwh: Decimal
    delivered_export_mwh: Decimal
    gross_sale_revenue_keur: Decimal
    charging_purchase_cost_keur: Decimal
    auxiliary_purchase_cost_keur: Decimal
    grid_import_charge_keur: Decimal
    grid_export_charge_keur: Decimal
    net_merchant_contribution_keur: Decimal
    lifecycle_capex_keur: Decimal
    total_dc_throughput_mwh: Decimal
    total_equivalent_full_cycles: Decimal


@dataclass
class _Cohort:
    born: datetime
    installed: Decimal
    nominal: Decimal
    useful_life_years: int
    cycles: Decimal = ZERO


def evaluate(configuration: BessConfiguration) -> BatteryResult:
    # A local Decimal context makes results independent of caller precision.
    with localcontext() as context:
        context.prec = 40
        return _evaluate(configuration)


def _evaluate(config):
    battery = config.battery
    cohorts = [_Cohort(config.start, battery.installed_energy_mwh, battery.usable_energy_mwh, battery.useful_life_years)]
    energy = battery.initial_energy_mwh
    elapsed = 0
    cumulative_cycles = ZERO
    events = {event.at: event for event in config.events}
    outages = iter(config.outages)
    outage = next(outages, None)
    evidence = []

    def capacity(at):
        total = ZERO
        for cohort in cohorts:
            age_hours = Decimal(int((at - cohort.born).total_seconds())) / 3600
            health = 1 - battery.calendar_loss_per_year * age_hours / 8760 - battery.cycle_loss_per_efc * cohort.cycles
            if not battery.minimum_soh <= health <= 1:
                raise BessInputError("BESS_SOH: minimum State of Health breached; no silent capacity clamp")
            total += cohort.nominal * health
        return total

    while config.start + timedelta(hours=elapsed) < config.end:
        at = config.start + timedelta(hours=elapsed)
        until = at + timedelta(hours=1)
        point = config.points[elapsed] if config.mode is DispatchMode.EXPLICIT_HOURLY else config.points[at.hour]
        event = events.get(at)
        cost = ZERO
        if event is not None:
            if event.kind is EventKind.REPLACE:
                if energy != 0:
                    raise BessInputError("BESS_REPLACEMENT_INVENTORY: replacement requires empty inventory; no energy write-off")
                cohorts = []
            elif battery.soc_min != 0:
                raise BessInputError("BESS_AUGMENTATION_SOC: positive minimum SoC needs separately funded commissioning authority")
            cohorts.append(_Cohort(at, event.installed_energy_mwh, event.usable_energy_mwh, event.useful_life_years))
            cost = event.cost_keur
        for cohort in cohorts:
            expiry = cohort.born + relativedelta(years=cohort.useful_life_years)
            if at >= expiry or until > expiry:
                raise BessInputError("BESS_USEFUL_LIFE: paid replacement required before operation beyond physical life")
        while outage is not None and outage.end <= at:
            outage = next(outages, None)
        declared_outage = outage is not None and outage.start <= at < outage.end
        available = point.available and not declared_outage
        charge, discharge = point.charge_mw, point.discharge_mw
        suspended = declared_outage and config.mode is DispatchMode.FIXED_DAILY_PLAN
        if suspended:
            charge = discharge = ZERO  # Explicit contract policy, not SoC/power clipping.
        if charge > 0 and discharge > 0:
            raise BessInputError("BESS_SIMULTANEOUS: charging and discharging cannot coincide")
        if not available and (charge > 0 or discharge > 0):
            raise BessInputError("BESS_UNAVAILABLE: dispatch in unavailable interval")
        if charge > battery.charge_power_mw or discharge > battery.discharge_power_mw:
            raise BessInputError("BESS_POWER: rated AC power exceeded")
        auxiliary = point.auxiliary_grid_mw  # Grid-fed auxiliaries; no invented DC drain.
        imported, exported = charge + auxiliary, discharge
        if imported > battery.grid_import_limit_mw or exported > battery.grid_export_limit_mw:
            raise BessInputError("BESS_GRID_POWER: grid connection limit exceeded")
        opening_capacity = capacity(at)
        nominal = sum((c.nominal for c in cohorts), ZERO)
        installed = sum((c.installed for c in cohorts), ZERO)
        if not battery.soc_min * opening_capacity <= energy <= battery.soc_max * opening_capacity:
            raise BessInputError("BESS_OPENING_SOC: inventory outside available capacity")
        cell_charge, cell_discharge = charge * battery.charge_efficiency, discharge / battery.discharge_efficiency
        closing = energy + cell_charge - cell_discharge
        throughput = cell_charge + cell_discharge
        cycles = throughput / (2 * nominal)
        for cohort in cohorts:
            cohort.cycles += cycles
        closing_capacity = capacity(until)
        if not battery.soc_min * closing_capacity <= closing <= battery.soc_max * closing_capacity:
            raise BessInputError("BESS_CLOSING_SOC: impossible dispatch or degradation inventory; no energy discarded")
        charge_loss, discharge_loss = charge - cell_charge, cell_discharge - discharge
        residual = imported - exported - auxiliary - charge_loss - discharge_loss - (closing - energy)
        if abs(residual) > Decimal("1e-28"):
            raise BessInputError("BESS_CONSERVATION: hourly energy balance failed")
        sale = exported * point.sell_price_eur_mwh / 1000
        purchase = charge * point.buy_price_eur_mwh / 1000
        auxiliary_cost = auxiliary * point.buy_price_eur_mwh / 1000
        import_fee = imported * point.import_charge_eur_mwh / 1000
        export_fee = exported * point.export_charge_eur_mwh / 1000
        contribution = sale - purchase - auxiliary_cost - import_fee - export_fee
        cumulative_cycles += cycles
        evidence.append(HourEvidence(at, until, point.charge_mw, point.discharge_mw, available, suspended,
            energy, closing, opening_capacity, closing_capacity, installed, opening_capacity / nominal, closing_capacity / nominal,
            charge, discharge, auxiliary, imported, exported, charge_loss, discharge_loss, throughput, cycles, cumulative_cycles,
            point.buy_price_eur_mwh, point.sell_price_eur_mwh, sale, purchase, auxiliary_cost, import_fee, export_fee,
            contribution, cost, residual, point.source_ref))
        energy = closing
        elapsed += 1
    if energy != battery.terminal_energy_mwh:
        raise BessInputError("BESS_TERMINAL_SOC: explicit terminal inventory not met; no final charge/discharge adjustment")
    def total(field):
        return sum((getattr(row, field) for row in evidence), ZERO)
    return BatteryResult(hashlib.sha256(config.canonical_json.encode()).hexdigest(), tuple(evidence),
        max(abs(row.energy_conservation_residual_mwh) for row in evidence), total("grid_import_mwh"), total("grid_export_mwh"),
        total("gross_sale_revenue_keur"), total("charging_purchase_cost_keur"), total("auxiliary_purchase_cost_keur"),
        total("grid_import_charge_keur"), total("grid_export_charge_keur"), total("net_merchant_contribution_keur"),
        total("lifecycle_capex_keur"), total("dc_throughput_mwh"), total("equivalent_full_cycles"))
