"""Workspace bridge to the typed Developer Economics V1 input, never a calculator.

The stored value is ONE versioned canonical JSON document holding exactly the existing
``DevelopmentEconomicsInput`` fields. Parsing is strict and fail-closed: unknown keys, wrong
types, non-finite numbers, non-ISO dates, unknown enum values and any ``DevelopmentEconomicsInput``
validation error reject the whole payload. Economics (XIRR, MOIC, project uses) stay in
``financial_engine.developer_economics``; nothing here computes a financial figure.

Units: ``developer_fee_value`` is a kEUR amount for FIXED_KEUR and a 0..1 FRACTION for
PCT_OF_HARD_CAPEX (0.05 is 5 %). Display conversion belongs to the UI boundary only.
"""
from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import date, datetime

FIELD_ID = "developer.economics.configuration"
SNAPSHOT_KEY = "developer_economics_json"
VERSION = 1
MAX_BYTES = 64 * 1024
MAX_SPEND_ROWS = 200

_TOP_KEYS = frozenset({
    "version", "enabled", "outcome", "spend_schedule", "reimbursed_development_cost_keur",
    "developer_fee_mode", "developer_fee_value", "settlement", "book_basis_mode",
})
_ROW_KEYS = frozenset({"spend_date", "amount_keur"})


class DeveloperConfigError(ValueError):
    """Malformed or economically invalid persisted/submitted Developer Economics payload."""


def _reject_constant(token):
    raise DeveloperConfigError(f"DEV_ECON_NONFINITE: {token} is not allowed")


def _number(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise DeveloperConfigError(f"DEV_ECON_NUMBER: {name} must be a finite number")
    return float(value)


def _parse_date(value):
    if not isinstance(value, str):
        raise DeveloperConfigError("DEV_ECON_SPEND_DATE: spend_date must be an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise DeveloperConfigError("DEV_ECON_SPEND_DATE: spend_date must be a real YYYY-MM-DD date") from exc
    if parsed.isoformat() != value:
        raise DeveloperConfigError("DEV_ECON_SPEND_DATE: spend_date must be canonical YYYY-MM-DD")
    return parsed


def parse_config(raw):
    """Return the typed input, or ``None`` when ``raw`` is absent/empty. Raises on anything malformed."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if isinstance(raw, dict):
        document = raw
    else:
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_BYTES:
            raise DeveloperConfigError("DEV_ECON_PAYLOAD: payload must be a bounded JSON object")
        try:
            document = json.loads(raw, parse_constant=_reject_constant)
        except json.JSONDecodeError as exc:
            raise DeveloperConfigError("DEV_ECON_JSON: payload is not valid JSON") from exc
    if not isinstance(document, dict) or set(document) != _TOP_KEYS:
        raise DeveloperConfigError("DEV_ECON_SCHEMA: payload keys are not exactly the Developer Economics schema")
    if document["version"] != VERSION or isinstance(document["version"], bool):
        raise DeveloperConfigError("DEV_ECON_VERSION: unsupported Developer Economics payload version")
    if not isinstance(document["enabled"], bool):
        raise DeveloperConfigError("DEV_ECON_ENABLED: enabled must be a boolean")
    rows = document["spend_schedule"]
    if not isinstance(rows, list) or len(rows) > MAX_SPEND_ROWS:
        raise DeveloperConfigError("DEV_ECON_SCHEDULE: spend_schedule must be a bounded list")
    from finco_core.inputs.development import (
        DeveloperBookBasisMode, DeveloperFeeMode, DeveloperSettlementAuthority,
        DevelopmentEconomicsInput, DevelopmentOutcome, DevelopmentSpendEntry,
    )
    entries = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != _ROW_KEYS:
            raise DeveloperConfigError("DEV_ECON_SCHEDULE: each spend row needs exactly spend_date and amount_keur")
        entries.append(DevelopmentSpendEntry(
            spend_date=_parse_date(row["spend_date"]), amount_keur=_number("amount_keur", row["amount_keur"])))
    try:
        return DevelopmentEconomicsInput(
            enabled=document["enabled"],
            outcome=DevelopmentOutcome(document["outcome"]),
            spend_schedule=tuple(entries),
            reimbursed_development_cost_keur=_number(
                "reimbursed_development_cost_keur", document["reimbursed_development_cost_keur"]),
            developer_fee_mode=DeveloperFeeMode(document["developer_fee_mode"]),
            developer_fee_value=_number("developer_fee_value", document["developer_fee_value"]),
            settlement=DeveloperSettlementAuthority(document["settlement"]),
            book_basis_mode=DeveloperBookBasisMode(document["book_basis_mode"]),
        )
    except DeveloperConfigError:
        raise
    except (ValueError, TypeError) as exc:      # enum values and every DevelopmentEconomicsInput rule
        raise DeveloperConfigError(str(exc)) from exc


def to_document(config) -> dict:
    from finco_core.inputs.serialization import _ser_development_economics
    return {"version": VERSION, **_ser_development_economics(config)}


def canonical_json(raw) -> str:
    """Canonical stored text for ``raw`` ('' when absent). Idempotent for stored values."""
    config = parse_config(raw)
    if config is None:
        return ""
    return json.dumps(to_document(config), sort_keys=True, separators=(",", ":"), allow_nan=False)


def apply_config(inputs, raw):
    """Materialise the typed input on ``ProjectInputs.development_economics``.

    Absent or disabled is the neutral ``None`` (bit-exact legacy behaviour). An enabled input is
    validated by the canonical calculator's own date rule against the effective Financial Close.
    """
    config = parse_config(raw)
    if config is None or not config.enabled:
        return inputs if getattr(inputs, "development_economics", None) is None else replace(
            inputs, development_economics=None)
    candidate = replace(inputs, development_economics=config)
    from financial_engine.developer_economics import resolve_developer_project_uses
    try:
        resolve_developer_project_uses(candidate)
    except ValueError as exc:
        raise DeveloperConfigError(str(exc)) from exc
    return candidate


def effective_raw(snapshot, scenario=None):
    """Canonical inheritance: a non-Base scenario's own override (even an explicit disabled
    document) wins; a missing override key inherits the Working Copy (Base) value."""
    if scenario is not None and not scenario.is_base_case and SNAPSHOT_KEY in (scenario.overrides or {}):
        return scenario.overrides[SNAPSHOT_KEY]
    return (snapshot or {}).get(SNAPSHOT_KEY, "")
