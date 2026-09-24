"""Public generic detail taxonomy for the canonical Solar and Wind models.

``PUBLIC_GENERIC_DETAIL_V1`` is deliberately an application-layer *display and
editing decomposition*.  It has no amounts of its own: a child receives a
deterministic share of its already-authoritative canonical parent.  The module
contains no workbook, client, vendor, country, or project-specific data.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable


PUBLIC_GENERIC_DETAIL_V1 = "PUBLIC_GENERIC_DETAIL_V1"


@dataclass(frozen=True)
class DetailChild:
    code: str
    label: str
    weight: Decimal


def _children(parent: str, rows: tuple[tuple[str, str], ...]) -> tuple[DetailChild, ...]:
    """Build normalized children from integer public-generic weights."""
    total = sum(weight for _, weight in rows)
    return tuple(
        DetailChild(f"{parent}.{index:02d}", label, Decimal(weight) / Decimal(total))
        for index, (label, weight) in enumerate(rows, 1)
    )


_COMMON_CAPEX: dict[str, tuple[tuple[str, int], ...]] = {
    "C.02": (("Engineering, Procurement and Construction", 70), ("Site Civil Works", 30)),
    "C.03": (("Grid Connection Works", 65), ("Interconnection Studies and Testing", 35)),
    "C.04": (("Operations Readiness", 60), ("Training and Handover", 40)),
    "C.05": (("Balance of Plant", 60), ("Construction Logistics", 40)),
    "C.06": (("Construction All-Risk Insurance", 70), ("Liability and Commissioning Cover", 30)),
    "C.07": (("Land Access and Lease", 55), ("Construction Taxes and Permits", 45)),
    "C.08": (("Legal and Contract Advisory", 50), ("Audit and Reporting", 50)),
    "C.09": (("Owner's Engineering", 55), ("Construction Supervision", 45)),
    "C.10": (("Commissioning Tests", 60), ("Acceptance and Handover", 40)),
    # C.11 is the non-owning alias of C.08/audit_legal.  It deliberately has
    # visible zero-value taxonomy only, preventing a second economic authority.
    "C.11": (("Independent Advisory Services", 100),),
    "C.12": (("Project Controls", 50), ("Site Administration", 50)),
    "C.13": (("Construction Contingency", 100),),
    "C.14": (("Indirect Taxes", 55), ("Statutory Charges", 45)),
    "C.15": (("Development Rights", 60), ("Acquisition Advisory", 40)),
    "C.16": (("Project Rights", 65), ("Connection Rights", 35)),
}

_CAPEX_ROWS: dict[str, dict[str, tuple[tuple[str, int], ...]]] = {
    "solar": {
        "C.01": (("PV Modules", 52), ("Inverters", 20), ("Mounting Structure", 18), ("DC Cabling and Balance of System", 10)),
        **_COMMON_CAPEX,
    },
    "wind": {
        "C.01": (("Wind Turbines", 70), ("Turbine Supply Agreement Optionals", 0), ("Flow Parts", 10), ("Procurement Fees", 8), ("Logistics and Transport", 12)),
        **_COMMON_CAPEX,
    },
}

_COMMON_OPEX_ROWS: dict[str, tuple[tuple[str, int], ...]] = {
    "B.01": (("Asset Management Contract", 25), ("Operation Management Contract", 20), ("Performance Monitoring", 16), ("Technical Inspections", 14), ("Meteorological / Weather Forecast Service", 10), ("SCADA / Monitoring Platform", 15)),
    "B.03": (("Vegetation Management", 35), ("Access Road Maintenance / Repair", 30), ("Pest Control", 15), ("Site Inspections", 20)),
    "B.04": (("Site Materials and Consumables", 55), ("Waste Management", 45)),
    "B.05": (("Security Monitoring", 60), ("HSE Prevention Plan", 40)),
    "B.06": (("Operational Insurance", 70), ("Insurance Administration", 30)),
    "B.07": (("Land Lease", 65), ("Property Taxes and Local Charges", 35)),
    "B.08": (("Grid Services", 55), ("Market and Balancing Services", 45)),
    "B.09": (("Regulatory Inspections", 50), ("Site Safety Services", 50)),
    "B.10": (("Accounting and Reporting", 50), ("Legal and Compliance Support", 50)),
    "B.11": (("Bank Administration", 60), ("Payment Services", 40)),
    "B.12": (("Environmental Monitoring", 60), ("Community and Stakeholder Support", 40)),
    "B.13": (("OPEX Contingency", 100),),
}

_OPEX_ROWS: dict[str, dict[str, tuple[tuple[str, int], ...]]] = {
    "common": _COMMON_OPEX_ROWS,
    "solar": {
        "B.02": (("Preventive and Corrective Maintenance", 28), ("Minor Maintenance", 12), ("HV Substation / O&M Building Maintenance", 12), ("Regulatory Inspections", 10), ("HSE Prevention Plan", 8), ("Meteorological Station Maintenance", 7), ("Special Equipment / Vehicle Maintenance", 8), ("PV Module / Array Inspection", 8), ("Other Maintenance", 7)),
    },
    "wind": {
        "B.02": (("Preventive and Corrective Maintenance", 26), ("Minor Maintenance", 10), ("HV Substation / O&M Building Maintenance", 11), ("Regulatory Inspections", 9), ("HSE Prevention Plan", 8), ("Meteorological Station Maintenance", 7), ("Special Equipment / Vehicle Maintenance", 8), ("Blade Maintenance", 14), ("Other Maintenance", 7)),
    },
}

OPEX_PARENT_BY_CANONICAL_KEY = {
    "Technical Management": "B.01",
    "Maintenance": "B.02",
    "Insurance": "B.06",
    "Lease & Tax": "B.07",
}

OPEX_PARENT_NAMES = {
    "B.01": "Technical Management", "B.02": "Infrastructure Maintenance",
    "B.03": "Site Maintenance", "B.04": "Site Materials", "B.05": "Security & HSE",
    "B.06": "Insurance", "B.07": "Lease & Property Tax", "B.08": "Power Expenses",
    "B.09": "Regulatory & Site Services", "B.10": "Audit, Accounting & Legal",
    "B.11": "Bank Fees", "B.12": "Environmental & Social", "B.13": "Contingencies",
}


def capex_children(technology: str, parent_code: str) -> tuple[DetailChild, ...]:
    """Return the public generic CAPEX taxonomy for one parent code."""
    tech = technology.strip().lower()
    if tech not in _CAPEX_ROWS:
        raise ValueError(f"Unsupported public generic technology: {technology!r}")
    return _children(parent_code, _CAPEX_ROWS[tech][parent_code])


def opex_children(parent_code: str, technology: str | None = None) -> tuple[DetailChild, ...]:
    """Return the public generic OPEX taxonomy for one parent code."""
    if parent_code in _COMMON_OPEX_ROWS:
        rows = _COMMON_OPEX_ROWS[parent_code]
    elif parent_code == "B.02":
        tech = (technology or "solar").strip().lower()
        if tech not in {"solar", "wind"}:
            raise ValueError(f"Unsupported public generic technology: {technology!r}")
        rows = _OPEX_ROWS[tech][parent_code]
    else:
        raise KeyError(f"Unknown public generic OPEX parent: {parent_code}")
    return _children(parent_code, rows)


def allocate_parent_amount(amount_keur: float, children: Iterable[DetailChild], *, places: int = 8) -> tuple[tuple[DetailChild, float], ...]:
    """Allocate a canonical parent amount with a deterministic final residual.

    Rounding every non-final child then assigning the residual to the final
    child makes the persisted/display total exactly equal to the parent at the
    catalogue precision.  A zero-weight child remains visibly zero.
    """
    rows = tuple(children)
    if not rows:
        return ()
    quant = Decimal("1").scaleb(-places)
    total = Decimal(str(float(amount_keur)))
    allocated: list[tuple[DetailChild, Decimal]] = []
    consumed = Decimal("0")
    for child in rows[:-1]:
        value = (total * child.weight).quantize(quant, rounding=ROUND_HALF_UP)
        allocated.append((child, value))
        consumed += value
    allocated.append((rows[-1], total - consumed))
    return tuple((child, float(value)) for child, value in allocated)


__all__ = [
    "PUBLIC_GENERIC_DETAIL_V1", "DetailChild", "OPEX_PARENT_BY_CANONICAL_KEY",
    "OPEX_PARENT_NAMES", "allocate_parent_amount", "capex_children", "opex_children",
]
