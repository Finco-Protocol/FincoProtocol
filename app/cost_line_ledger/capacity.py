"""Read-only "per MW" projection of persisted cost lines (WF-06B).

One stored amount per line (``amount_keur``); a per-MW figure is only a read-only division of that amount by the project's saved
installed capacity (``project_setup.technical.capacity_mw``). It is never stored, never written back and never reaches the Run:
the Run fold keeps using the stored amounts exactly as before.

Fail closed: when the capacity is missing, zero, negative, non-finite, not a plain number, or when the registry would offer more
than one capacity quantity for the technology (an AC/DC ambiguity), the basis is ``available = False`` with a reason, and no line
gets a per-MW figure. Nothing is estimated or defaulted.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

CAPACITY_FIELD_ID = "project_setup.technical.capacity_mw"
_BASIS_LABEL = "installed capacity (MW)"
_SCALE = Decimal("0.000001")

REASONS = {
    "MISSING": "The installed capacity is not set for this project, so per-MW figures are not shown.",
    "INVALID": "The installed capacity is not a positive number, so per-MW figures are not shown.",
    "AMBIGUOUS": "More than one capacity quantity (for example AC and DC) is defined for this technology, so per-MW figures are not shown.",
    "UNSUPPORTED": "Per-MW figures are not defined for this project type.",
}


def _capacity_fields_in_registry() -> list[str]:
    """Every registry field that names a capacity expressed in MW (more than one means the basis would be ambiguous)."""
    from app.workbook.registry import WORKBOOK

    found: list[str] = []
    for spec in WORKBOOK.all_fields():
        key = str(getattr(spec, "field_id", "") or "").lower()
        unit = str(getattr(spec, "unit", "") or "").strip().lower()
        if "capacity" in key and unit in ("mw", "mwp", "mwac", "mwdc") and "factor" not in key:
            found.append(spec.field_id)
    return found


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def _plain(value: Decimal) -> str:
    text = format(value.quantize(_SCALE).normalize(), "f")
    return "0" if text in ("-0", "") else text


def capacity_basis(technology: str, raw_capacity: Any) -> dict[str, Any]:
    """The explicit per-MW basis for one project: ``{available, mw, basis, source_field, technology, reason, note}``."""
    base = {"available": False, "mw": None, "basis": _BASIS_LABEL, "source_field": CAPACITY_FIELD_ID, "technology": technology,
            "reason": None, "note": None}
    if technology not in ("solar", "wind"):
        return {**base, "reason": "UNSUPPORTED", "note": REASONS["UNSUPPORTED"]}
    try:
        fields = _capacity_fields_in_registry()
    except Exception:  # noqa: BLE001 - no registry answer means no proof of an unambiguous basis
        fields = []
    if fields != [CAPACITY_FIELD_ID]:
        return {**base, "reason": "AMBIGUOUS", "note": REASONS["AMBIGUOUS"]}
    mw = _decimal(raw_capacity)
    if raw_capacity is None or (isinstance(raw_capacity, str) and not raw_capacity.strip()):
        return {**base, "reason": "MISSING", "note": REASONS["MISSING"]}
    if mw is None or mw <= 0:
        return {**base, "reason": "INVALID", "note": REASONS["INVALID"]}
    return {**base, "available": True, "mw": format(mw.normalize(), "f"), "note": None}


def per_mw_keur(amount_keur: Any, basis: Mapping[str, Any]) -> str | None:
    """``amount_keur / MW`` as a plain decimal text (kEUR per MW), or ``None`` when the basis or the amount is unavailable."""
    if not basis.get("available"):
        return None
    mw, amount = _decimal(basis.get("mw")), _decimal(amount_keur)
    if mw is None or amount is None or mw <= 0:
        return None
    return _plain(amount / mw)


def attach_per_mw(projection: dict[str, Any], sheet: str, basis: Mapping[str, Any]) -> dict[str, Any]:
    """Adds ``per_mw_keur`` to every projected line and the ``capacity`` basis to the projection (additive; no amount is altered).

    CAPEX: kEUR per MW of installed capacity. OPEX: the stored OPEX amount is the annual (year-1) amount, so the figure is kEUR per MW per year.
    """
    lines: Iterable[dict[str, Any]] = projection.get("lines", [])
    for row in lines:
        row["per_mw_keur"] = per_mw_keur(row.get("amount_keur"), basis)
    projection["capacity"] = {**basis, "time_basis": "per year" if sheet == "opex" else None}
    return projection
