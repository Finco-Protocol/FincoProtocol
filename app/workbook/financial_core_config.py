"""FIN-V2-3 input boundary. Save/CAS is owned by WorkbookUpdateService.

Wire rates are explicitly human percentages. Typed valuation rates are ratios.
No default discount rate and no magnitude-dependent conversion are permitted.
"""
from __future__ import annotations

from dataclasses import replace
import json
import math

from finco_core.inputs.serialization import _deser_valuation_policies
from finco_core.inputs.shl_timing import ShlTimingBasis

FIELD_ID = "debt.valuation.configuration"
SNAPSHOT_KEY = "financial_core_config_json"
VERSION = "FIN_V2_3_POLICY_V1"
KEYS = {"schema_version", "rate_unit", "project", "coverage", "sponsor", "shl_timing_basis"}


def _unique(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ValueError("FIN_V2_POLICY_DUPLICATE_KEY")
        result[k] = v
    return result


def parse_config(raw):
    if raw in (None, ""):
        return None
    if not isinstance(raw, str) or len(raw.encode()) > 12000:
        raise ValueError("FIN_V2_POLICY_BOUNDED_JSON_REQUIRED")
    try:
        config = json.loads(raw, object_pairs_hook=_unique)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("FIN_V2_POLICY_INVALID_JSON") from exc
    if not isinstance(config, dict) or set(config) != KEYS:
        raise ValueError("FIN_V2_POLICY_KEYS_INVALID")
    if config["schema_version"] != VERSION or config["rate_unit"] != "human_percent_v1":
        raise ValueError("FIN_V2_POLICY_VERSION_OR_UNIT_INVALID")
    ShlTimingBasis(config["shl_timing_basis"])
    typed = {"policy_version": VERSION}
    common = {"discount_rate_pct", "authority_label", "discount_convention"}
    dated = {"valuation_date_policy", "explicit_valuation_date"}
    periodic = {"periodic_rate_conversion", "periods_per_year", "first_cashflow_timing"}
    coverage = {"cfads_case", "calculation_date_policy", "llcr_cashflow_basis", "plcr_cashflow_basis",
                "denominator_basis", "rolling_loan_life"}
    for name in ("project", "coverage", "sponsor"):
        part = config[name]
        if part is None:
            typed[name] = None
            continue
        required = common | (coverage if name == "coverage" else dated)
        allowed = required | (periodic if name != "sponsor" else set())
        if not isinstance(part, dict) or not required <= set(part) or set(part) - allowed:
            raise ValueError(f"FIN_V2_POLICY_SECTION_KEYS_INVALID: {name}")
        authority = part["authority_label"]
        if not isinstance(authority, str) or not authority.startswith("FINANCIAL_OWNER:") or not authority[16:].strip() or len(authority) > 200:
            raise ValueError("FIN_V2_POLICY_FINANCIAL_OWNER_AUTHORITY_REQUIRED")
        if "RESEARCH" in authority.upper():
            raise ValueError("FIN_V2_POLICY_RESEARCH_AUTHORITY_UNSUPPORTED")
        rate = part["discount_rate_pct"]
        if rate is not None and (type(rate) not in (float, int) or not math.isfinite(rate) or not -100 < rate <= 1000):
            raise ValueError("FIN_V2_POLICY_INVALID_DISCOUNT_RATE")
        p = {k: v for k, v in part.items() if k != "discount_rate_pct"}
        p["annual_discount_rate"] = None if rate is None else rate / 100.0
        if name == "sponsor" and p["discount_convention"] != "ACT_365_FIXED":
            raise ValueError("FIN_V2_SPONSOR_DISCOUNT_CONVENTION_UNSUPPORTED")
        if name != "coverage":
            if p["valuation_date_policy"] == "EXPLICIT_DATE" and not p["explicit_valuation_date"]:
                raise ValueError("FIN_V2_POLICY_VALUATION_DATE_REQUIRED")
            if p["valuation_date_policy"] != "EXPLICIT_DATE" and p["explicit_valuation_date"] is not None:
                raise ValueError("FIN_V2_POLICY_CONFLICTING_VALUATION_DATE")
        if p["discount_convention"] == "PERIODIC_COMPOUNDING":
            if (p.get("periodic_rate_conversion") != "AS_QUOTED_PER_MODEL_PERIOD"
                    or type(p.get("periods_per_year")) is not int or p["periods_per_year"] <= 0
                    or p.get("first_cashflow_timing") != "END_OF_FIRST_PERIOD"):
                raise ValueError("FIN_V2_POLICY_EXPLICIT_PERIODIC_CONTRACT_REQUIRED")
        typed[name] = p
    try:
        policies = _deser_valuation_policies(typed)
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("FIN_V2_POLICY_TYPED_CONTRACT_INVALID") from exc
    return config, policies


def canonical_json(raw):
    parsed = parse_config(raw)
    return "" if parsed is None else json.dumps(parsed[0], sort_keys=True, separators=(",", ":"), allow_nan=False)


def apply_config(inputs, raw):
    parsed = parse_config(raw)
    if parsed is None:
        return inputs
    config, policies = parsed
    return replace(inputs, valuation=policies, financing=replace(inputs.financing,
        shl_timing_basis=ShlTimingBasis(config["shl_timing_basis"])))
