"""Versioned FINCO cost-line ledger for Solar and Wind (``PUBLIC_GENERIC_DETAIL_V1`` taxonomy).

Every row has a stable ``template_line_id`` (technology + template version + immutable FINCO business code; never a spreadsheet address),
a FINCO display code, a ``row_kind`` and, only when the repository's locked mapping proves it, the canonical economic field.
The ledger carries NO spreadsheet provenance of any kind.  It is derived from ``app.reference_detail_catalog`` and the locked
``CAPEX_CATEGORY_TO_FIELD`` mapping; it adds metadata and changes no amount, fold or Run path.

Row kinds
  heading             parent group row (C.NN / B.NN); carries no amount of its own
  editable_run_bound  child row whose parent maps to a canonical field the Run fold consumes
  derived_runtime     C.17 / C.18: computed at Run time, never user spend
  unresolved_mapping  taxonomy kept visible but NOT signed off as an economic mapping (C.04, C.05, C.08, C.11, C.13, B.13)
  blank_slot / unsupported  reserved vocabulary; no row of these kinds is emitted for the generic taxonomy
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, Mapping, Optional

from app.reference_detail_catalog import PUBLIC_GENERIC_DETAIL_V1, capex_children, opex_children, OPEX_PARENT_NAMES

LEDGER_VERSION = "WF06B_COST_LEDGER_V1"
TEMPLATE_VERSION = PUBLIC_GENERIC_DETAIL_V1
TECHNOLOGIES = ("solar", "wind")

CAPEX_PARENT_NAMES = {
    "C.01": "Production Units", "C.02": "EPC Contract", "C.03": "Grid Connection", "C.04": "Operations Preparation",
    "C.05": "Other EPC Costs", "C.06": "Construction Insurances", "C.07": "Lease / Construction Taxes", "C.08": "Audit & Legal",
    "C.09": "Construction Management A", "C.10": "Commissioning", "C.11": "Other Professional Services",
    "C.12": "Construction Management B", "C.13": "Contingency", "C.14": "Construction Taxes",
    "C.15": "Project Acquisition / Development", "C.16": "Project Rights",
    "C.17": "Financing Costs", "C.18": "Reserve Accounts",
}
DERIVED_CAPEX_PARENTS = frozenset({"C.17", "C.18"})
# Not guessed: the locked fold still consumes persisted lines under these parents, but the v2 catalogue does not claim a proven mapping.
UNRESOLVED_CAPEX_PARENTS = frozenset({"C.04", "C.05", "C.08", "C.11", "C.13"})
UNRESOLVED_OPEX_PARENTS = frozenset({"B.13"})


class RowKind(str, Enum):
    EDITABLE_RUN_BOUND = "editable_run_bound"
    DERIVED_RUNTIME = "derived_runtime"
    HEADING = "heading"
    BLANK_SLOT = "blank_slot"
    UNRESOLVED_MAPPING = "unresolved_mapping"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class LedgerRow:
    template_line_id: str
    finco_display_code: str
    display_order: int
    label: str
    sheet: str                      # capex | opex
    parent_group: str
    row_kind: str
    canonical_field: Optional[str]  # CapexStructure field when proven, else None
    unit: str                       # kEUR
    taxonomy_signed_off: bool       # taxonomy sign-off only. NOT 'does not affect the Run': see feeds_run_fold for that
    reason: str


def template_line_id(technology: str, business_code: str) -> str:
    return f"{technology.strip().lower()}:{TEMPLATE_VERSION}:{business_code}"


def _capex_field(parent: str) -> Optional[str]:
    from app.persistence.capex_sub_lines import CAPEX_CATEGORY_TO_FIELD
    return CAPEX_CATEGORY_TO_FIELD.get(parent)


def _build(technology: str) -> tuple[LedgerRow, ...]:
    from app.reference_detail_catalog import _CAPEX_ROWS, _OPEX_ROWS, _COMMON_OPEX_ROWS
    rows: list[LedgerRow] = []
    order = 0

    def add(sheet, code, label, parent, kind, field, taxonomy_signed_off, reason):
        nonlocal order
        order += 1
        rows.append(LedgerRow(template_line_id(technology, code), code, order, label, sheet, parent, kind.value, field, "kEUR", taxonomy_signed_off, reason))

    for parent in sorted(_CAPEX_ROWS[technology]):
        field = _capex_field(parent)
        unresolved = parent in UNRESOLVED_CAPEX_PARENTS
        add("capex", parent, CAPEX_PARENT_NAMES[parent], parent, RowKind.HEADING, field, False, "Parent group; carries no amount of its own.")
        for child in capex_children(technology, parent):
            if unresolved:
                add("capex", child.code, child.label, parent, RowKind.UNRESOLVED_MAPPING, field, False,
                    "Taxonomy mapping not signed off; active saved lines under this parent still feed the existing locked Run fold unchanged.")
            else:
                add("capex", child.code, child.label, parent, RowKind.EDITABLE_RUN_BOUND, field, True,
                    "Folded into the canonical CAPEX field by the locked category mapping.")
    for parent in sorted(DERIVED_CAPEX_PARENTS):
        add("capex", parent, CAPEX_PARENT_NAMES[parent], parent, RowKind.DERIVED_RUNTIME, None, False,
            "Computed at Run time (financing / reserves); never user spend and never summed into CAPEX lines.")

    opex_parents = sorted(set(_COMMON_OPEX_ROWS) | set(_OPEX_ROWS[technology]))
    for parent in opex_parents:
        add("opex", parent, OPEX_PARENT_NAMES[parent], parent, RowKind.HEADING, None, False, "Parent group; carries no amount of its own.")
        for child in opex_children(parent, technology):
            if parent in UNRESOLVED_OPEX_PARENTS:
                add("opex", child.code, child.label, parent, RowKind.UNRESOLVED_MAPPING, None, False,
                    "OPEX contingency is rejected as a sub-line parent by the existing route; taxonomy only, never folded.")
            else:
                add("opex", child.code, child.label, parent, RowKind.EDITABLE_RUN_BOUND, None, True,
                    "Folded into the OPEX item for its group by the canonical OPEX fold.")
    return tuple(rows)


@lru_cache(maxsize=None)
def ledger_rows(technology: str) -> tuple[LedgerRow, ...]:
    tech = technology.strip().lower()
    if tech not in TECHNOLOGIES:
        raise ValueError(f"No WF-06B cost-line ledger for technology {technology!r}")
    return _build(tech)


def ledger_sha256() -> str:
    payload = {t: [asdict(r) for r in ledger_rows(t)] for t in TECHNOLOGIES}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


#: Literal pin of the immutable catalogue. A change to the taxonomy is a new LEDGER_VERSION, never an edit in place.
LEDGER_SHA256 = "b5406e61502edb48bfc29efbe396331f7f2c3bd9d46c38abd0e013e2906c6c6b"


def verify_ledger() -> bool:
    return ledger_sha256() == LEDGER_SHA256


_USER_CODE = re.compile(r"^[CB]\.\d{2}\.U\d{3}$")


def feeds_run_fold(sheet: str, parent: str) -> bool:
    """Whether ACTIVE saved lines under ``parent`` are consumed by the existing Run fold (independent of taxonomy sign-off)."""
    if sheet == "capex":
        from app.persistence.capex_sub_lines import CAPEX_CATEGORY_TO_FIELD
        return parent in CAPEX_CATEGORY_TO_FIELD
    from app.persistence.opex_sub_lines import ALLOWED_PARENT_GROUPS
    return parent in ALLOWED_PARENT_GROUPS


def classify_persisted_line(technology: str, sheet: str, business_code: str, parent: str) -> dict[str, Any]:
    """Classify one persisted line. Unknown codes are user lines (identity = their own sub_line_id), never a guess."""
    rows = {r.finco_display_code: r for r in ledger_rows(technology) if r.sheet == sheet}
    row = rows.get(business_code)
    if row is not None:
        return {"template_line_id": row.template_line_id, "row_kind": row.row_kind, "taxonomy_signed_off": row.taxonomy_signed_off, "lineage": "template",
                "feeds_run_fold": feeds_run_fold(sheet, parent),
                "mapping_status": "UNRESOLVED" if row.row_kind == RowKind.UNRESOLVED_MAPPING.value else "PROVEN"}
    if _USER_CODE.match(business_code or ""):
        unresolved = parent in (UNRESOLVED_CAPEX_PARENTS if sheet == "capex" else UNRESOLVED_OPEX_PARENTS)
        return {"template_line_id": None, "row_kind": RowKind.UNRESOLVED_MAPPING.value if unresolved else RowKind.EDITABLE_RUN_BOUND.value,
                "taxonomy_signed_off": not unresolved, "lineage": "user", "feeds_run_fold": feeds_run_fold(sheet, parent), "mapping_status": "UNRESOLVED" if unresolved else "PROVEN"}
    return {"template_line_id": None, "row_kind": RowKind.UNSUPPORTED.value, "taxonomy_signed_off": False, "lineage": "unknown", "feeds_run_fold": False, "mapping_status": "UNRESOLVED"}
