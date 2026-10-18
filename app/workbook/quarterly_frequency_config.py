"""RC-7B operating/debt frequency selection for the Working Copy (release-closed).

The released default is 6/6 for every existing project: an absent or empty
value is exactly the released semiannual contract and changes no identity.
A 3/3 selection is a versioned, strictly decoded JSON contract that binds the
matched quarterly calendar policy AND the explicit financing structure the
candidate admits (EQUITY_ONLY sponsor funding, NONE reserve support), in the
same way the two-Senior activation binds its structure. Nothing is inferred.

The existing ``excluded_structure`` wire key is retained for decoding saved
selections, not as permission to exclude anything. Both the actual inputs and
the recorded structure must already be equity-only, zero-SHL and zero-reserve.
Frequency selection changes the calendar only, never financing amounts.

``ACTIVATION_ENABLED`` stays ``False`` until the full 3/3 execution path is
independently financially reviewed and the owner has decided D-01..D-12: while
it is False, no Working Copy can save a 3/3 selection and no product Run can
execute one. This module never calculates finance.
"""
from __future__ import annotations

from dataclasses import fields, replace
import json

FIELD_ID = "project_setup.calendar.operating_frequency"
SNAPSHOT_KEY = "operating_frequency_config_json"
ACTIVATION_ENABLED = False
AUTHORITY = "RC7B_QUARTERLY_CANDIDATE_SCOPE_V1"
SUPPORTED_PROJECT_TYPES = frozenset({"solar", "wind"})
VERSION = 2
KEYS = {"version", "operating_months", "debt_service_months", "operating_calendar_policy",
        "sponsor_funding_mode", "reserve_support_mode", "authority", "excluded_structure"}
STRUCTURE_KEYS = {"sponsor_funding_mode", "shl_amount_keur", "clean_shl_principal_keur", "dsra_months"}
STRUCTURE_MODES = frozenset({"EQUITY_ONLY", "SHARE_CAPITAL_THEN_SHL"})
MAX_BYTES = 4000


class QuarterlyFrequencyError(ValueError):
    """Typed refusal; the message starts with a ``QUARTERLY_*`` reason code."""


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise QuarterlyFrequencyError(f"QUARTERLY_CONFIG_DUPLICATE_KEY: {key}")
        result[key] = value
    return result


def parse_config(raw):
    """Strict decode. Returns None for the released 6/6 default (absent/empty)."""
    if raw in (None, ""):
        return None
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_BYTES:
        raise QuarterlyFrequencyError("QUARTERLY_CONFIG_BOUNDED_JSON_REQUIRED")
    try:
        config = json.loads(raw, object_pairs_hook=_unique)
    except (TypeError, json.JSONDecodeError) as exc:
        raise QuarterlyFrequencyError("QUARTERLY_CONFIG_INVALID_JSON") from exc
    if not isinstance(config, dict) or set(config) != KEYS:
        raise QuarterlyFrequencyError("QUARTERLY_CONFIG_KEYS_INVALID")
    if type(config["version"]) is not int or config["version"] != VERSION:
        raise QuarterlyFrequencyError("QUARTERLY_CONFIG_VERSION_UNSUPPORTED")
    if (config["operating_months"], config["debt_service_months"]) != (3, 3) or any(
            type(config[k]) is not int for k in ("operating_months", "debt_service_months")):
        raise QuarterlyFrequencyError("QUARTERLY_MATCHED_3_3_REQUIRED")
    if config["authority"] != AUTHORITY:
        raise QuarterlyFrequencyError("QUARTERLY_CONFIG_AUTHORITY_INVALID")
    if config["sponsor_funding_mode"] != "EQUITY_ONLY" or config["reserve_support_mode"] != "NONE":
        raise QuarterlyFrequencyError("QUARTERLY_CONFIG_FINANCING_BINDING_INVALID")
    from finco_core.engine.calendar_policy import OperatingCalendarPolicy
    policy = OperatingCalendarPolicy.from_dict(config["operating_calendar_policy"])
    if (policy.operating_months, policy.debt_service_months) != (3, 3):
        raise QuarterlyFrequencyError("QUARTERLY_MATCHED_3_3_REQUIRED")
    excluded = _decode_structure(config["excluded_structure"])
    return config | {"operating_calendar_policy": policy, "excluded_structure": excluded}


def _decode_structure(value):
    """Strict decode of the structure a selection records as excluded."""
    if not isinstance(value, dict) or set(value) != STRUCTURE_KEYS:
        raise QuarterlyFrequencyError("QUARTERLY_CONFIG_EXCLUDED_STRUCTURE_INVALID")
    if value["sponsor_funding_mode"] not in STRUCTURE_MODES:
        raise QuarterlyFrequencyError("QUARTERLY_CONFIG_EXCLUDED_STRUCTURE_INVALID: sponsor_funding_mode")
    decoded = {"sponsor_funding_mode": value["sponsor_funding_mode"]}
    for name in ("shl_amount_keur", "clean_shl_principal_keur"):
        amount = value[name]
        if type(amount) not in (int, float) or amount != amount or amount in (float("inf"), float("-inf")) or amount < 0:
            raise QuarterlyFrequencyError(f"QUARTERLY_CONFIG_EXCLUDED_STRUCTURE_INVALID: {name}")
        decoded[name] = float(amount)
    months = value["dsra_months"]
    if type(months) is not int or months < 0:
        raise QuarterlyFrequencyError("QUARTERLY_CONFIG_EXCLUDED_STRUCTURE_INVALID: dsra_months")
    decoded["dsra_months"] = months
    return decoded


def structure_of(financing) -> dict:
    """The exact financing structure a 3/3 selection would exclude (read, never modified)."""
    return {
        "sponsor_funding_mode": financing.sponsor_funding_mode.name,
        "shl_amount_keur": float(financing.shl_amount_keur or 0.0),
        "clean_shl_principal_keur": float(financing.clean_shl_principal_keur or 0.0),
        "dsra_months": int(financing.dsra_months or 0),
    }


def candidate_config_json(excluded_structure) -> str:
    """The one defined 3/3 selection, canonically serialized (not approval).

    The historical wire key records structure, not consent to remove it.
    Eligibility is checked against actual inputs by ``apply_config``.
    """
    from finco_core.engine.calendar_policy import quarterly_candidate_policy
    return canonical_json(json.dumps({
        "version": VERSION, "operating_months": 3, "debt_service_months": 3,
        "operating_calendar_policy": quarterly_candidate_policy().to_dict(),
        "sponsor_funding_mode": "EQUITY_ONLY", "reserve_support_mode": "NONE", "authority": AUTHORITY,
        "excluded_structure": excluded_structure,
    }))


def canonical_json(raw) -> str:
    config = parse_config(raw)
    if config is None:
        return ""
    serial = config | {"operating_calendar_policy": config["operating_calendar_policy"].to_dict()}
    return json.dumps(serial, sort_keys=True, separators=(",", ":"))


def frequency_label(raw) -> str:
    """'3/3' for an explicit quarterly selection, '6/6' for the released default."""
    return "6/6" if parse_config(raw) is None else "3/3"


def require_admitted(project_type: str) -> None:
    if not ACTIVATION_ENABLED:
        raise QuarterlyFrequencyError(
            "QUARTERLY_ADMISSION_CLOSED: matched 3/3 awaits independent financial review "
            "and owner decisions D-01..D-12")
    if str(project_type or "").strip().lower() not in SUPPORTED_PROJECT_TYPES:
        raise QuarterlyFrequencyError(
            f"QUARTERLY_TECHNOLOGY_UNSUPPORTED: project_type={project_type!r}; Solar and Wind only (D-12)")


def apply_config(pi, raw, project_type: str):
    """Return ``pi`` unchanged for 6/6; otherwise the explicit quarterly ProjectInputs.

    Only the timeline subtype changes. Unsupported actual financing and legacy
    exclusion records are refused; user consent never authorizes their removal.
    """
    config = parse_config(raw)
    if config is None:
        return pi
    # Display and evidence surfaces read the typed Working Copy faithfully. The
    # admission gate is enforced where finance is produced (production
    # classification refuses every quarterly Run while closed) and where the
    # selection is written; technology scope is enforced here as well.
    if str(project_type or "").strip().lower() not in SUPPORTED_PROJECT_TYPES:
        raise QuarterlyFrequencyError(
            f"QUARTERLY_TECHNOLOGY_UNSUPPORTED: project_type={project_type!r}; Solar and Wind only (D-12)")
    from finco_core.inputs import (
        DebtServiceReserveSupportMode, PeriodFrequency, ProjectInputs, SponsorFundingMode,
    )
    from finco_core.inputs._models import QuarterlyProjectInfo
    if type(pi) is not ProjectInputs:
        raise QuarterlyFrequencyError(f"QUARTERLY_FACILITY_COMBINATION_UNSUPPORTED: {type(pi).__name__}")
    fin = pi.financing
    if (fin.sponsor_funding_mode is not SponsorFundingMode.EQUITY_ONLY
            or fin.shl_amount_keur or fin.clean_shl_principal_keur
            or fin.shl_idc_keur or fin.shl_construction_day_count_fraction
            or fin.shl_fcf_waterfall_cash_schedule_keur
            or fin.shl_fcf_waterfall_minimum_cash_retained_keur):
        raise QuarterlyFrequencyError(
            "QUARTERLY_SHL_UNSUPPORTED: 3/3 requires existing EQUITY_ONLY funding "
            "with zero SHL; frequency selection cannot change financing")
    if (fin.dsra_support_mode is not DebtServiceReserveSupportMode.NONE
            or fin.debt_service_reserve_requirement_keur or fin.dsra_target_policy is not None
            or fin.dsra_months or fin.dsrf_commitment_keur or fin.dsrf_commitment_fee_rate_pa
            or pi.capex.reserve_accounts_keur):
        raise QuarterlyFrequencyError(
            "QUARTERLY_RESERVE_POLICY_PENDING_D09: explicit reserve authority cannot be discarded")
    if fin.junior_or_other_project_funding_keur:
        raise QuarterlyFrequencyError(
            "QUARTERLY_FACILITY_COMBINATION_UNSUPPORTED: junior/other funding is outside 3/3 scope")
    recorded, actual = config["excluded_structure"], structure_of(fin)
    if recorded != actual:
        raise QuarterlyFrequencyError(
            "QUARTERLY_FINANCING_STRUCTURE_MISMATCH: the saved 3/3 selection records "
            f"{json.dumps(recorded, sort_keys=True)} but the Working Copy carries "
            f"{json.dumps(actual, sort_keys=True)}; a shareholder loan or DSRA is never removed "
            "by frequency selection. Use the financing workflow or reset to 6/6.")
    values = {f.name: getattr(pi.info, f.name) for f in fields(pi.info)}
    values["period_frequency"] = PeriodFrequency.QUARTERLY
    info = QuarterlyProjectInfo(**values, operating_calendar_policy=config["operating_calendar_policy"])
    quarterly = replace(pi, info=info)
    # Reuse the canonical scope boundary before any calculation, including
    # instrument, VAT, revenue, valuation and tax combinations.
    from financial_engine.financing.quarterly_scope import require_supported_quarterly_project
    require_supported_quarterly_project(quarterly)
    return quarterly


def run_evidence(project_inputs) -> dict:
    """Committed-Run evidence for the operating calendar (quarterly only)."""
    policy = getattr(getattr(project_inputs, "info", None), "operating_calendar_policy", None)
    if policy is None:
        return {}
    return {
        "operating_frequency": "3/3",
        "period_months": 3,
        "operating_calendar_policy": policy.to_dict(),
        "quarterly_scope_authority": AUTHORITY,
        "classification": "RC7B_QUARTERLY_CANDIDATE_RELEASE_CLOSED",
        "owner_decisions": "D-01..D-12 OPEN; D-06/D-07 deferred",
        "sponsor_returns_status": "PENDING_D08_DISTRIBUTION_ELIGIBILITY",
        "financing_structure_binding": {
            "sponsor_funding_mode": "EQUITY_ONLY", "reserve_support_mode": "NONE",
            "binding": "ACTUAL_ELIGIBLE_STRUCTURE_UNCHANGED",
            "shareholder_loan": "ABSENT_IN_WORKING_INPUTS",
            "automatic_dsra": "ABSENT_IN_WORKING_INPUTS",
        },
    }
