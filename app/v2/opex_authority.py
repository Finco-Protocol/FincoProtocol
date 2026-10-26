"""OPEX group authority notes for the Hybrid Inputs grid (presentation only).

A scalar ``opex.lines.*`` value is NOT authoritative for the Run in two proven cases (FIN-VAL B2/C1
trace; ``opex_matrix`` evidence): (1) the group's base item is replaced at the Run boundary by the
reference-seeded line items (``fold_opex_with_provenance`` drops items named by a replaced canonical
key), and (2) Data Center / EV Charging B.08 power expenses are derived from the persisted technology
drivers.  The grid must not offer an editor that cannot change the Run.  This module only describes
that existing precedence; it changes no financial input, rule or fold.
"""
from __future__ import annotations

from typing import Mapping

REPLACED_BY_LINES = "Sum of line items — edit on the OPEX sheet"
DERIVED_FROM_DRIVERS = "Calculated from the technology drivers"
_DRIVER_DERIVED_TEMPLATES = frozenset({"generic_data_center_reference", "generic_ev_charging_reference"})


def opex_group_authority_notes(project_id: str, template_source: str) -> Mapping[str, str]:
    """B.XX group code -> reason when the group's scalar value cannot change the Run.

    Fails open (empty mapping) on any read problem: the grid then behaves exactly as before.
    """
    notes: dict[str, str] = {}
    try:
        from app.services.opex_sub_lines_integration import _load_all_sub_lines, opex_fold_provenance
        from app.v2.opex_assembly import _OPEX_NAME_TO_CODE

        provenance = opex_fold_provenance(_load_all_sub_lines(project_id))
        for name in provenance.get("replaced_canonical_keys") or ():
            code = _OPEX_NAME_TO_CODE.get(name)
            if code:
                notes[code] = REPLACED_BY_LINES
    except Exception:  # noqa: BLE001 - presentation helper must never break the page
        notes = {}
    if str(template_source or "").strip().lower() in _DRIVER_DERIVED_TEMPLATES:
        notes["B.08"] = DERIVED_FROM_DRIVERS
    return notes
