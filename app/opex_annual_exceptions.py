"""FINCO38 — Canonical Annual OPEX Exceptions authority.

Policy contract (authorized FINCO38 scope):
- An annual exception is an explicit nominal annual total in kEUR overriding that
  same existing canonical OPEX line and 1-based effective operating year, NOT adding
  to base or re-applying inflation.
- Absent year inherits the otherwise applicable escalated base.
- Explicit ``0.0`` is distinct from missing and valid (non-negative cost contract).
- Deletion / omission of an entry restores inheritance.
- Never writes to derived contingency (B.13), driver-owned DC/EV electricity (B.08),
  or scalar groups shadowed by active sub-lines (#479/#480 guard preserved).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from typing import Any, Iterable, Sequence

SNAPSHOT_KEY = "opex_annual_exceptions_json"
SCHEMA_VERSION = "opex-annual-exceptions-v1"
MAX_OVERRIDES = 2000


class OpexAnnualExceptionError(ValueError):
    """Typed fail-closed validation error for annual OPEX exceptions."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def document_token(raw_json: str | None) -> str:
    """Stable SHA-256 CAS token for an annual OPEX exceptions document."""
    text = (raw_json or "").strip()
    if not text:
        return hashlib.sha256(b"opex-annual-exceptions-empty-v1").hexdigest()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def effective_raw(draft_snapshot: dict | None, scenario: Any = None) -> str:
    """Resolve effective raw JSON with scenario inheritance (absent in scenario inherits Base)."""
    if scenario is not None and not getattr(scenario, "is_base_case", True):
        overrides = getattr(scenario, "overrides", None) or {}
        if SNAPSHOT_KEY in overrides:
            return str(overrides.get(SNAPSHOT_KEY) or "").strip()
    return str((draft_snapshot or {}).get(SNAPSHOT_KEY) or "").strip()


def parse_exceptions(raw_json: str | None) -> dict[str, dict[int, float]]:
    """Parse canonical JSON into ``{line_key: {year: amount_keur}}``."""
    text = (raw_json or "").strip()
    if not text:
        return {}
    try:
        doc = json.loads(text)
    except Exception as exc:
        raise OpexAnnualExceptionError("OPEX_ANNUAL_JSON_INVALID", f"Malformed JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise OpexAnnualExceptionError("OPEX_ANNUAL_SCHEMA_INVALID", "Document must be a JSON object")
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise OpexAnnualExceptionError(
            "OPEX_ANNUAL_SCHEMA_UNSUPPORTED",
            f"Unsupported schema_version: {doc.get('schema_version')!r}",
        )
    rows = doc.get("overrides")
    if not isinstance(rows, list):
        raise OpexAnnualExceptionError("OPEX_ANNUAL_SCHEMA_INVALID", "'overrides' must be a list")
    if len(rows) > MAX_OVERRIDES:
        raise OpexAnnualExceptionError(
            "OPEX_ANNUAL_TOO_MANY_OVERRIDES",
            f"Exceeds maximum of {MAX_OVERRIDES} annual overrides",
        )
    out: dict[str, dict[int, float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise OpexAnnualExceptionError("OPEX_ANNUAL_ROW_INVALID", "Each override must be an object")
        line_key = str(row.get("line_key") or "").strip()
        if not line_key:
            raise OpexAnnualExceptionError("OPEX_ANNUAL_LINE_INVALID", "line_key is required")
        yr = row.get("year")
        if isinstance(yr, bool) or not isinstance(yr, int) or yr <= 0:
            raise OpexAnnualExceptionError("OPEX_ANNUAL_YEAR_INVALID", f"Invalid operating year: {yr!r}")
        amt = row.get("amount_keur")
        if isinstance(amt, bool) or not isinstance(amt, (int, float)):
            raise OpexAnnualExceptionError("OPEX_ANNUAL_AMOUNT_INVALID", f"Non-numeric amount: {amt!r}")
        amt_f = float(amt)
        if not math.isfinite(amt_f) or amt_f < 0.0:
            raise OpexAnnualExceptionError(
                "OPEX_ANNUAL_AMOUNT_INVALID",
                f"Amount must be finite and >= 0 kEUR, got {amt!r}",
            )
        line_map = out.setdefault(line_key, {})
        if yr in line_map:
            raise OpexAnnualExceptionError(
                "OPEX_ANNUAL_DUPLICATE_ENTRY",
                f"Duplicate override for line_key={line_key!r} year={yr}",
            )
        line_map[yr] = amt_f
    return out


def validate_and_canonicalize(
    payload: dict | str | None,
    *,
    horizon_years: int,
    allowed_line_keys: Iterable[str],
    replaced_canonical_keys: Iterable[str] = (),
    project_type: str = "",
) -> str:
    """Validate proposed annual OPEX exceptions against canonical line authority and horizon.

    Returns canonical sorted JSON string, or ``""`` when there are zero overrides (restoring inheritance).
    """
    if payload is None:
        return ""
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return ""
        try:
            doc = json.loads(text)
        except Exception as exc:
            raise OpexAnnualExceptionError("OPEX_ANNUAL_JSON_INVALID", f"Malformed JSON: {exc}") from exc
    elif isinstance(payload, dict):
        doc = payload
    else:
        raise OpexAnnualExceptionError("OPEX_ANNUAL_SCHEMA_INVALID", "Payload must be JSON object or string")

    if not isinstance(doc, dict):
        raise OpexAnnualExceptionError("OPEX_ANNUAL_SCHEMA_INVALID", "Payload must be a JSON object")
    schema_ver = doc.get("schema_version", SCHEMA_VERSION)
    if schema_ver != SCHEMA_VERSION:
        raise OpexAnnualExceptionError(
            "OPEX_ANNUAL_SCHEMA_UNSUPPORTED",
            f"Unsupported schema_version: {schema_ver!r}",
        )
    raw_rows = doc.get("overrides", [])
    if not isinstance(raw_rows, list):
        raise OpexAnnualExceptionError("OPEX_ANNUAL_SCHEMA_INVALID", "'overrides' must be a list")
    if len(raw_rows) > MAX_OVERRIDES:
        raise OpexAnnualExceptionError(
            "OPEX_ANNUAL_TOO_MANY_OVERRIDES",
            f"Exceeds maximum of {MAX_OVERRIDES} annual overrides",
        )

    allowed = {str(k).strip() for k in allowed_line_keys if str(k).strip()}
    replaced = {str(k).strip() for k in replaced_canonical_keys if str(k).strip()}
    tech_norm = (project_type or "").strip().lower()
    is_driver_b08_tech = tech_norm in ("data center", "data_center", "ev charging", "ev_charging")

    seen: set[tuple[str, int]] = set()
    canonical_rows: list[dict[str, Any]] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            raise OpexAnnualExceptionError("OPEX_ANNUAL_ROW_INVALID", "Each override must be an object")
        line_key = str(row.get("line_key") or "").strip()
        if not line_key:
            raise OpexAnnualExceptionError("OPEX_ANNUAL_LINE_INVALID", "line_key is required")
        if line_key == "B.13" or line_key.startswith("B.13.") or "contingenc" in line_key.lower():
            raise OpexAnnualExceptionError(
                "OPEX_ANNUAL_DERIVED_LINE_UNSUPPORTED",
                f"Cannot override derived contingency line {line_key!r}",
            )
        if is_driver_b08_tech and (line_key == "B.08" or line_key.startswith("B.08.")):
            raise OpexAnnualExceptionError(
                "OPEX_ANNUAL_DRIVER_LINE_UNSUPPORTED",
                f"Cannot override driver-owned electricity line {line_key!r} for {project_type}",
            )
        if line_key in replaced:
            raise OpexAnnualExceptionError(
                "OPEX_ANNUAL_SHADOWED_SCALAR_UNSUPPORTED",
                f"Line {line_key!r} is replaced by active OPEX sub-lines; edit the sub-line directly",
            )
        if allowed and line_key not in allowed:
            raise OpexAnnualExceptionError(
                "OPEX_ANNUAL_LINE_UNKNOWN",
                f"Unknown or inactive canonical OPEX line {line_key!r}",
            )

        yr = row.get("year")
        if isinstance(yr, bool) or not isinstance(yr, int) or yr < 1 or yr > int(horizon_years):
            raise OpexAnnualExceptionError(
                "OPEX_ANNUAL_YEAR_INVALID",
                f"Operating year must be an integer in 1..{int(horizon_years)}, got {yr!r}",
            )

        amt = row.get("amount_keur")
        if isinstance(amt, bool) or not isinstance(amt, (int, float)):
            raise OpexAnnualExceptionError(
                "OPEX_ANNUAL_AMOUNT_INVALID",
                f"amount_keur must be a finite number >= 0, got {amt!r}",
            )
        amt_f = float(amt)
        if not math.isfinite(amt_f) or amt_f < 0.0:
            raise OpexAnnualExceptionError(
                "OPEX_ANNUAL_AMOUNT_INVALID",
                f"amount_keur must be finite and >= 0 kEUR, got {amt!r}",
            )

        pair = (line_key, yr)
        if pair in seen:
            raise OpexAnnualExceptionError(
                "OPEX_ANNUAL_DUPLICATE_ENTRY",
                f"Duplicate override for line_key={line_key!r} year={yr}",
            )
        seen.add(pair)
        canonical_rows.append({"amount_keur": amt_f, "line_key": line_key, "year": yr})

    if not canonical_rows:
        return ""
    canonical_rows.sort(key=lambda r: (r["line_key"], r["year"]))
    return json.dumps(
        {"overrides": canonical_rows, "schema_version": SCHEMA_VERSION},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def apply_annual_exceptions_to_opex(
    opex_items: Sequence[Any],
    raw_json: str | None,
    *,
    horizon_years: int | None = None,
) -> tuple[Any, ...]:
    """Attach canonical ``annual_overrides`` onto matching ``OpexItem``s.

    Returns the exact input tuple when ``raw_json`` is empty (bit-for-bit identity).
    Fails closed if an override targets a non-existent or derived percentage item,
    or a year beyond ``horizon_years``.
    """
    parsed = parse_exceptions(raw_json)
    if not parsed:
        return tuple(opex_items)

    item_names = {item.name for item in opex_items}
    pct_names = {item.name for item in opex_items if getattr(item, "percentage_of_opex", 0.0) > 0.0}
    for line_key, yr_map in parsed.items():
        if line_key in pct_names:
            raise OpexAnnualExceptionError(
                "OPEX_ANNUAL_DERIVED_LINE_UNSUPPORTED",
                f"Cannot override percentage-based OPEX item {line_key!r}",
            )
        if line_key not in item_names:
            raise OpexAnnualExceptionError(
                "OPEX_ANNUAL_LINE_UNKNOWN",
                f"Annual OPEX override references missing item {line_key!r}",
            )
        if horizon_years is not None:
            for yr in yr_map:
                if yr > int(horizon_years):
                    raise OpexAnnualExceptionError(
                        "OPEX_ANNUAL_YEAR_INVALID",
                        f"Override year {yr} exceeds horizon_years={int(horizon_years)}",
                    )

    result = []
    for item in opex_items:
        yr_map = parsed.get(item.name)
        if yr_map:
            overrides_tuple = tuple(sorted(yr_map.items()))
            result.append(dataclasses.replace(item, annual_overrides=overrides_tuple))
        else:
            result.append(item)
    return tuple(result)
