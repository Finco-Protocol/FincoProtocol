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
    "data_center": {
        **_COMMON_CAPEX,
        "C.01": (
            ("UPS and Electrical Distribution", 30),
            ("Cooling and Heat Rejection Systems", 25),
            ("Backup Generation", 18),
            ("White Space / Racks Infrastructure", 12),
            ("Controls / BMS / DCIM Infrastructure", 8),
            ("Technical Installation / Integration", 7),
        ),
        "C.02": (
            ("Building Shell and Structural Works", 45),
            ("MEP Installation Works", 35),
            ("Internal Fit-Out", 20),
        ),
        "C.03": (
            ("Grid Connection Works", 50),
            ("HV Substation / Transformers", 35),
            ("Interconnection Studies / Protection / Testing", 15),
        ),
        "C.04": (
            ("Operations Readiness", 45),
            ("Commissioning Preparation", 35),
            ("Training / Procedures / Handover", 20),
        ),
        "C.05": (
            ("External Civil Works", 35),
            ("Roads / Drainage / Site Infrastructure", 25),
            ("Security Perimeter / Physical Infrastructure", 20),
            ("Utility Infrastructure", 20),
        ),
        "C.08": (
            ("Legal and Contract Advisory", 40),
            ("Audit / Reporting", 25),
            ("Technical / Commercial Advisory", 35),
        ),
        "C.09": (
            ("Owner's Engineering", 50),
            ("Construction Supervision", 30),
            ("Project Controls", 20),
        ),
    },
    # EV Charging (V1): C.01 and the EV-specific parents below; every other
    # parent keeps the shared common taxonomy. Weights reconcile to 100 each.
    "ev_charging": {
        "C.01": (("DC Fast Chargers", 55), ("Power Cabinets / Conversion Equipment", 18), ("Charging Dispensers / Cables", 10), ("Site Energy Management / Charging Controls", 7), ("Payment / Authentication Hardware", 4), ("Spare Equipment / Initial Parts", 6)),
        "C.02": (("Electrical Installation", 45), ("Charger Installation", 25), ("LV / MV Distribution Installation", 20), ("Testing / Integration", 10)),
        "C.03": (("Grid Connection Works", 40), ("Transformer / MV Equipment", 35), ("Utility Interface / Metering", 15), ("Protection / Studies / Testing", 10)),
        "C.04": (("Commissioning Preparation", 40), ("Operational Procedures", 30), ("Training / Handover", 30)),
        "C.05": (("Civil Works / Foundations", 35), ("Parking / Traffic Layout", 25), ("Canopies / Weather Protection", 15), ("Lighting / Signage", 10), ("Site Security / Ancillary Infrastructure", 15)),
        "C.08": (("Legal / Contract Advisory", 45), ("Audit / Reporting", 20), ("Permitting / Commercial Advisory", 35)),
        "C.09": (("Owner's Engineering", 50), ("Construction Supervision", 30), ("Project Controls", 20)),
        "C.13": (("Construction Contingency", 100),),
        **{k: v for k, v in _COMMON_CAPEX.items() if k not in {"C.01", "C.02", "C.03", "C.04", "C.05", "C.08", "C.09", "C.13"}},
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
    "data_center": {
        # B.01: Technical Management — DC-specific; no meteorological service.
        "B.01": (
            ("Asset Management Contract", 25),
            ("Operation Management Contract", 20),
            ("Performance Monitoring", 18),
            ("Technical Inspections", 16),
            ("DCIM / Monitoring Platform", 21),
        ),
        "B.02": (
            ("Preventive MEP Maintenance", 30),
            ("UPS / Electrical Maintenance", 20),
            ("Cooling Plant Maintenance", 20),
            ("Generator Maintenance", 12),
            ("BMS / DCIM Systems Maintenance", 8),
            ("Critical Spares", 10),
        ),
        # B.03: Site Maintenance — DC-specific; no vegetation management.
        "B.03": (
            ("Access Road & Perimeter Maintenance", 40),
            ("Civil / Structural Inspections", 35),
            ("Site Inspections", 25),
        ),
        "B.05": (
            ("Physical Security", 55),
            ("HSE / Emergency Preparedness", 25),
            ("Fire / Life Safety Services", 20),
        ),
        # B.08 Power Expenses is a DERIVED authority for Data Center
        # (IT MW × occupancy × PUE × 8,760 × EUR/MWh); the single-child row
        # below is a transparent display decomposition only and is never
        # seeded as an editable persisted sub-line.
        "B.08": (("Grid Electricity", 100),),
    },
    # EV Charging (V1): technology-specific children for B.02/B.05/B.08/B.11;
    # every other group keeps the shared common taxonomy. B.08 Electricity
    # Procurement is 100% of the group: the DERIVED energy×price line is the
    # group's only economic content (spec L/K — never mixed into fixed OPEX).
    "ev_charging": {
        "B.02": (("Preventive Charger Maintenance", 35), ("Corrective Charger Maintenance", 25), ("Electrical Infrastructure Maintenance", 18), ("Site / Civil Maintenance", 10), ("Software / Firmware Technical Support", 7), ("Critical Spares", 5)),
        "B.05": (("Site Security", 45), ("HSE / Safety Inspections", 35), ("Emergency Equipment / Procedures", 20)),
        "B.08": (("Electricity Procurement", 100),),
        "B.11": (("Payment Processing", 60), ("Bank / Merchant Administration", 40)),
    },
}

OPEX_PARENT_BY_CANONICAL_KEY = {
    "Technical Management": "B.01",
    "Maintenance": "B.02",
    "Insurance": "B.06",
    "Lease & Tax": "B.07",
    # Data Center canonical OPEX parent names (no Solar/Wind factory uses
    # these names, so the extended mapping is backward-compatible).
    "Infrastructure Maintenance": "B.02",
    "Security": "B.05",
    "Audit, Accounting & Legal": "B.10",
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
    """Return the public generic OPEX taxonomy for one parent code.

    Technology-specific rows take precedence over the common rows (only
    technologies that explicitly override a parent deviate; Solar and Wind
    override B.02 only, so their outputs are unchanged).
    """
    tech_key = (technology or "solar").strip().lower()
    tech_rows = _OPEX_ROWS.get(tech_key) if tech_key else None
    if tech_rows and parent_code in tech_rows:
        return _children(parent_code, tech_rows[parent_code])
    if parent_code in _COMMON_OPEX_ROWS:
        return _children(parent_code, _COMMON_OPEX_ROWS[parent_code])
    if parent_code == "B.02":
        if tech_key not in {"solar", "wind"}:            raise ValueError(f"Unsupported public generic technology: {technology!r}")
        return _children(parent_code, _OPEX_ROWS[tech_key][parent_code])
    raise KeyError(f"Unknown public generic OPEX parent: {parent_code}")


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
