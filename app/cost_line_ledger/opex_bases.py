"""Read-only list of the six OPEX group base amounts (PR-U1).

Six OPEX groups carry an editable canonical scalar (``opex.lines.<name>``) next to their added cost lines. The Run folds them additively
(``fold_opex_with_provenance``): a base item is dropped only when a reference-SEEDED line replaces its canonical key, and Data Center / EV
Charging power expenses come from the technology drivers. This module only DESCRIBES that existing precedence for the workbench: it reads the
saved scalar, says whether it can change the Run (``editable``) and why not. It writes nothing and the write path stays the canonical cell
writer for the same ``field_id``.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping

OPEX_BASE_FIELD_BY_GROUP: dict[str, str] = {
    "B.04": "opex.lines.cleaning_materials",
    "B.05": "opex.lines.security",
    "B.08": "opex.lines.power_expenses",
    "B.10": "opex.lines.audit_accounting_legal",
    "B.11": "opex.lines.bank_fees",
    "B.12": "opex.lines.environmental_social",
}


def _text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return ""
    return format(number.normalize(), "f") if number.is_finite() else ""


def opex_bases(get_value: Callable[[str], Any], authority_notes: Mapping[str, str], *, protected: bool) -> list[dict[str, Any]]:
    """``[{group, field_id, value, editable, note}]`` for the six groups, in group order."""
    out: list[dict[str, Any]] = []
    for group, field_id in OPEX_BASE_FIELD_BY_GROUP.items():
        note = authority_notes.get(group)
        out.append({"group": group, "field_id": field_id, "value": _text(get_value(field_id)),
                    "editable": (not protected) and not note, "note": note or ("Read-only project" if protected else None)})
    return out
