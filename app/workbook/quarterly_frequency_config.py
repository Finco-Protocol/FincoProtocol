"""RC-7B operating/debt frequency selection for the Working Copy (release-closed).

The released default is 6/6 for every existing project: an absent or empty
value is exactly the released semiannual contract and changes no identity.
A 3/3 selection is a versioned, strictly decoded JSON contract that binds the
matched quarterly calendar policy AND the explicit financing structure the
candidate admits (EQUITY_ONLY sponsor funding, NONE reserve support), in the
same way the two-Senior activation binds its structure. Nothing is inferred.

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
KEYS = {"version", "operating_months", "debt_service_months", "operating_calendar_policy",
        "sponsor_funding_mode", "reserve_support_mode", "authority"}
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
    if type(config["version"]) is not int or config["version"] != 1:
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
    return config | {"operating_calendar_policy": policy}


def candidate_config_json() -> str:
    """The one defined 3/3 selection, canonically serialized (not approval)."""
    from finco_core.engine.calendar_policy import quarterly_candidate_policy
    return canonical_json(json.dumps({
        "version": 1, "operating_months": 3, "debt_service_months": 3,
        "operating_calendar_policy": quarterly_candidate_policy().to_dict(),
        "sponsor_funding_mode": "EQUITY_ONLY", "reserve_support_mode": "NONE", "authority": AUTHORITY,
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

    The selection replaces the timeline subtype and binds the structure recorded
    in the saved contract: EQUITY_ONLY sponsor funding (no shareholder loan) and
    NONE reserve support (no automatic DSRA). Explicit reserve authority already
    on the project (support mode, requirement or target) is refused, never erased.
    """
    config = parse_config(raw)
    if config is None:
        return pi
    require_admitted(project_type)
    from finco_core.inputs import (
        DebtServiceReserveSupportMode, PeriodFrequency, ProjectInputs, SponsorFundingMode,
    )
    from finco_core.inputs._models import QuarterlyProjectInfo
    if type(pi) is not ProjectInputs:
        raise QuarterlyFrequencyError(f"QUARTERLY_FACILITY_COMBINATION_UNSUPPORTED: {type(pi).__name__}")
    fin = pi.financing
    if (fin.dsra_support_mode is not DebtServiceReserveSupportMode.NONE
            or fin.debt_service_reserve_requirement_keur or fin.dsra_target_policy is not None):
        raise QuarterlyFrequencyError(
            "QUARTERLY_RESERVE_POLICY_PENDING_D09: explicit reserve authority cannot be discarded")
    values = {f.name: getattr(pi.info, f.name) for f in fields(pi.info)}
    values["period_frequency"] = PeriodFrequency.QUARTERLY
    info = QuarterlyProjectInfo(**values, operating_calendar_policy=config["operating_calendar_policy"])
    financing = replace(fin, sponsor_funding_mode=SponsorFundingMode.EQUITY_ONLY,
                        shl_amount_keur=0.0, clean_shl_principal_keur=0.0, dsra_months=0)
    return replace(pi, info=info, financing=financing)


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
        # Explicit, recorded consequence of the 3/3 selection (never silent):
        # the Working Copy's SHL and automatic DSRA are not part of this Run.
        "financing_structure_binding": {
            "sponsor_funding_mode": "EQUITY_ONLY", "reserve_support_mode": "NONE",
            "shareholder_loan": "EXCLUDED_BY_3_3_SELECTION", "automatic_dsra": "EXCLUDED_BY_3_3_SELECTION",
        },
    }
