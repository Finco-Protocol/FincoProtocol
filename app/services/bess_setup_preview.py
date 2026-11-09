"""Ephemeral standalone Storage setup; native schema owns every input rule.

No factory, dispatch evaluator, financial calculator or persistence writer is
called here. An imported contract is explicit user input, never a seed model.
"""
from dataclasses import fields
from decimal import Decimal
import json

from domain.bess.contracts import Battery, BessInputError, number
from finco_core.inputs.bess_native import parse_native_contract

# Presentation metadata only. Bounds and relationships belong to the native parser.
EDIT_FIELDS = (
    ("discharge_power_mw", "Discharge power", "MW"),
    ("installed_energy_mwh", "Installed energy", "MWh"),
    ("usable_energy_mwh", "Usable DC energy", "MWh"),
    ("charge_efficiency", "Charge efficiency", "fraction"),
    ("discharge_efficiency", "Discharge efficiency", "fraction"),
    ("round_trip_efficiency", "Round-trip efficiency", "fraction"),
    ("calendar_loss_per_year", "Calendar loss per year", "fraction/year"),
    ("cycle_loss_per_efc", "Cycle loss per equivalent full cycle", "fraction/EFC"),
    ("minimum_soh", "Minimum state of health", "fraction"),
)


def capability():
    from app.product_capability import PRODUCT_CAPABILITIES
    from app.workbook import bess_config
    cap = next(c for c in PRODUCT_CAPABILITIES if c.product_area == "model" and c.key == "storage")
    # This preview has no draft writer or canonical creator. A future flag change
    # alone cannot advertise a supported lifecycle through this adapter.
    blockers = []
    if not bess_config.ACTIVATION_ENABLED:
        blockers.append({"code": "BESS_FINANCIAL_ACTIVATION_RELEASE_CLOSED",
                         "message": "Native financial activation is closed. Create, Save and Run are unavailable."})
    blockers.extend((
        {"code": "BESS_CANONICAL_CREATOR_UNAVAILABLE",
         "message": "Storage has no released project-setup creator or draft persistence path. The protected reference cannot be cloned."},
        {"code": "BESS_INVENTORY_FINANCIAL_BASIS_UNRESOLVED",
         "message": "Initial and terminal battery energy need an approved financial inventory basis."},
        {"code": "BESS_POST_COD_ACCOUNTING_RELEASE_CLOSED",
         "message": "Post-COD augmentation and replacement need approved accounting, tax and funding contracts."},
        {"code": "BESS_FINANCE_AXIS",
         "message": "A financial configuration must cover the complete canonical operating horizon; setup validation cannot prove that alignment."},
        {"code": "BESS_DUPLICATE_REVENUE_AUTHORITY",
         "message": "Legacy PPA, multistream and certificate revenue cannot be assumed compatible. Financing readiness is unproven."},
    ))
    return {
        "reference_exists": bool(cap.reference_available),
        "preview_supported": bool(cap.public_visible),
        "create_supported": False, "save_supported": False, "run_supported": False,
        "release_state": "ACTIVATION_BLOCKED", "persistence": "BROWSER_MEMORY_ONLY",
        "blockers": blockers,
        "fields": [{"name": name, "label": label, "unit": unit} for name, label, unit in EDIT_FIELDS],
    }


def _parse(raw):
    try:
        return parse_native_contract(raw)
    except BessInputError:
        raise
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        # Invalid JSON numbers can fail during the native parser's strict JSON
        # serialization. Treat that as a typed refusal, never an HTTP 500.
        raise BessInputError("BESS_NATIVE_SCHEMA") from exc


def preview(native_json: str, edits: dict[str, str]):
    # Parse the original first: partial documents never become a made-up model.
    contract = _parse(native_json)
    allowed = {name for name, _label, _unit in EDIT_FIELDS}
    if set(edits) - allowed:
        raise BessInputError("BESS_SETUP_FIELDS: unsupported battery edit")
    obj = json.loads(contract.canonical_json)
    battery = obj["configuration"]["battery"]
    for key, raw in edits.items():
        try:
            value = json.loads(raw)
        except (ValueError, TypeError, RecursionError) as exc:
            raise BessInputError(f"BESS_NUMBER: {key} requires an explicit numeric value") from exc
        if type(value) not in (int, float):
            raise BessInputError(f"BESS_NUMBER: {key} requires an explicit numeric value")
        number(value, key)
        battery[key] = value
    if {"usable_energy_mwh", "discharge_power_mw"} & set(edits):
        power = Decimal(str(battery["discharge_power_mw"]))
        energy = Decimal(str(battery["usable_energy_mwh"]))
        # Invalid numbers are still refused by the native parser, never repaired.
        if power.is_finite() and energy.is_finite() and power > 0:
            battery["duration_hours"] = float(energy / power)
    contract = _parse(json.dumps(obj, allow_nan=True))
    config = contract.configuration
    return {
        "battery": {f.name: str(getattr(config.battery, f.name)) for f in fields(Battery)},
        "start": config.start.isoformat(), "end": config.end.isoformat(),
        "dispatch_mode": config.mode.value, "dispatch_rows": len(config.points),
        "events": len(config.events),
        "validation_scope": "NATIVE_SCHEMA_ONLY",
        "physical_balance_verified": False, "financial_horizon_verified": False,
        "financial_calculation_count": 0, "persisted": False,
    }
