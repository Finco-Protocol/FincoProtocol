"""Opt-in native storage inputs; legacy TechnicalParams remain byte-identical."""
from dataclasses import dataclass
from decimal import Decimal
import json

from finco_core.inputs._models import TechnicalParams
from domain.bess.contracts import BessConfiguration, BessInputError, parse_configuration, exact, number, _unique


@dataclass(frozen=True)
class NativeBessContract:
    configuration: BessConfiguration
    variable_om_eur_per_dc_mwh: Decimal
    canonical_json: str


def parse_native_contract(raw: str) -> NativeBessContract:
    if not isinstance(raw, str) or len(raw.encode()) > 2_001_000:
        raise BessInputError("BESS_NATIVE_SIZE")
    try:
        obj = json.loads(raw, object_pairs_hook=_unique)
    except (ValueError, TypeError, RecursionError) as exc:
        raise BessInputError("BESS_NATIVE_SCHEMA") from exc
    exact(obj, {"version", "configuration", "variable_om_eur_per_dc_mwh"}, "native financial input")
    if type(obj["version"]) is not int or obj["version"] != 1:
        raise BessInputError("BESS_NATIVE_VERSION")
    variable = number(obj["variable_om_eur_per_dc_mwh"], "variable O&M EUR/DC MWh")
    config = parse_configuration(json.dumps(obj["configuration"], allow_nan=False))
    obj["configuration"] = json.loads(config.canonical_json)
    return NativeBessContract(config, variable, json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False))


@dataclass(frozen=True)
class NativeBessTechnicalParams(TechnicalParams):
    bess_native_config_json: str = ""
