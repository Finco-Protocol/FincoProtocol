"""
app.v2.opex_assembly — canonical per-line OPEX assembly for Workbook V2.

This module owns the authoritative mapping between:

  - Snapshot keys  (opex_technical_management_y1_keur, …)  — stored in the
    workspace draft_snapshot_json when a user edits a scalar OPEX override.
  - B.XX canonical group codes  (B.01 … B.13)  — defined in
    app.ui.opex_sheet_projection.CANONICAL_OPEX_GROUPS.
  - OpexItem.name strings  — the human-readable names used in each project
    factory (solar factory uses "Infrastructure Maintenance" for B.02,
    wind factory uses "O&M Preventive & Corrective" for the same slot, etc.).

Rules
-----
1.  B.13 (Contingencies) is ALWAYS derived (percentage_of_opex > 0).  It is
    never user-entered, so it is excluded from override application.
2.  Explicit zero (0.0) is a valid override — it must be applied.  A missing
    key or a None value means "no override".
3.  build_effective_draft_opex() replaces only y1_amount_keur via
    dataclasses.replace(); all other OpexItem attributes (annual_inflation,
    step_changes, percentage_of_opex, …) are preserved unchanged.
4.  If no per-line snapshot key is present the original tuple is returned
    unchanged (identity — no copy).
5.  B.09 (Fees) has no scalar field; it is engine-only (custom sub-lines only).
    The name-to-code mapping still covers it so the engine can route
    factory items with name "Fees" to B.09 for display purposes, but no
    snapshot key exists for it and it is never overridden here.

Snapshot key → B.XX table
--------------------------
opex_technical_management_y1_keur                → B.01
opex_o_and_m_preventive_and_corrective_y1_keur   → B.02
opex_maintain_site_y1_keur                       → B.03
opex_clean_material_y1_keur                      → B.04
opex_security_y1_keur                            → B.05
opex_insurance_y1_keur                           → B.06
opex_lease_and_property_tax_y1_keur              → B.07
opex_power_expenses_y1_keur                      → B.08
(B.09 has no snapshot key)
opex_audit_and_accounting_and_legal_y1_keur      → B.10
opex_bank_fees_opex_y1_keur                      → B.11
opex_environmental_and_social_management_y1_keur → B.12
opex_contingencies_y1_keur                       → B.13 (derived — never applied)
"""
from __future__ import annotations

import dataclasses
from typing import Optional

# ---------------------------------------------------------------------------
# Forward-declare OpexItem type for type-checking without a hard import cycle.
# The actual class is imported lazily inside functions that need it at runtime.
# ---------------------------------------------------------------------------
try:
    from finco_core.inputs._models import OpexItem  # noqa: F401 (used in annotations)
except ImportError:  # pragma: no cover
    pass  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Snapshot key → B.XX mapping (single source of truth)
# ---------------------------------------------------------------------------

SNAPSHOT_KEY_TO_OPEX_CODE: dict[str, str] = {
    "opex_technical_management_y1_keur":                    "B.01",
    "opex_o_and_m_preventive_and_corrective_y1_keur":       "B.02",
    "opex_maintain_site_y1_keur":                           "B.03",
    "opex_clean_material_y1_keur":                          "B.04",
    "opex_security_y1_keur":                                "B.05",
    "opex_insurance_y1_keur":                               "B.06",
    "opex_lease_and_property_tax_y1_keur":                  "B.07",
    "opex_power_expenses_y1_keur":                          "B.08",
    # B.09 (Fees) has no scalar snapshot key — custom sub-lines only
    "opex_audit_and_accounting_and_legal_y1_keur":          "B.10",
    "opex_bank_fees_opex_y1_keur":                          "B.11",
    "opex_environmental_and_social_management_y1_keur":     "B.12",
    "opex_contingencies_y1_keur":                           "B.13",
}

# Reverse mapping: B.XX code → snapshot key
OPEX_CODE_TO_SNAPSHOT_KEY: dict[str, str] = {
    code: key for key, code in SNAPSHOT_KEY_TO_OPEX_CODE.items()
}


# ---------------------------------------------------------------------------
# OpexItem.name → B.XX mapping (covers all factory name variants)
# ---------------------------------------------------------------------------
#
# Solar factory (Generic Solar Reference) and wind factory (Generic Wind Reference) use different names for some
# groups.  All variants are listed here so the assembly layer can route any
# known name to the correct B.XX bucket.
#
# Items with no corresponding snapshot field (B.09, B.13) are included purely
# for completeness; they are skipped during override application.

_OPEX_NAME_TO_CODE: dict[str, str] = {
    # --- B.01 Technical Management ---
    "Technical Management":                     "B.01",

    # --- B.02 O&M Preventive & Corrective ---
    # Solar factory uses "Infrastructure Maintenance" for the B.02 slot
    "O&M Preventive & Corrective":              "B.02",
    "Infrastructure Maintenance":               "B.02",

    # --- B.03 Site Maintenance ---
    "Maintain Site":                            "B.03",
    "Site Maintenance":                         "B.03",

    # --- B.04 Cleaning & Materials ---
    "Clean Material":                           "B.04",
    "Cleaning Materials":                       "B.04",
    "Cleaning & Materials":                     "B.04",

    # --- B.05 Security ---
    "Security":                                 "B.05",

    # --- B.06 Insurance ---
    "Insurance":                                "B.06",

    # --- B.07 Lease & Property Tax ---
    "Lease & Property Tax":                     "B.07",

    # --- B.08 Power Expenses ---
    "Power Expenses":                           "B.08",

    # --- B.09 Fees (no snapshot key — engine-only) ---
    "Fees":                                     "B.09",

    # --- B.10 Audit, Accounting & Legal ---
    # Solar factory omits spaces around "&"
    "Audit&Accounting&Legal":                   "B.10",
    "Audit & Accounting & Legal":               "B.10",
    "Audit, Accounting & Legal":                "B.10",

    # --- B.11 Bank Fees ---
    "Bank Fees":                                "B.11",
    "Bank Fees (opex)":                         "B.11",

    # --- B.12 Environmental & Social ---
    "Environmental&Social":                     "B.12",
    "Environmental & Social":                   "B.12",
    "Environmental & Social Management":        "B.12",

    # --- EV Charging (V1) canonical names ---
    "Security / HSE":                           "B.05",
    "Electricity Procurement":                  "B.08",  # DERIVED factory item — no snapshot key edits

    # --- B.13 Contingencies (derived — never overridden) ---
    "Contingencies":                            "B.13",

    # --- Generic solar factory names (project_factories.py create_default_solar_project) ---
    "Maintenance":                              "B.03",   # generic solar → Site Maintenance slot
    "Lease & Tax":                              "B.07",   # generic solar → Lease & Property Tax slot

    # --- Extra names found in some solar factory variants ---
    "Taxes":                                    None,      # Not mapped to any B-code
    "Salary&Payroll":                           None,      # Not mapped to any B-code
    "Salary & Payroll":                         None,      # Not mapped to any B-code
}

# B.13 is always derived — excluded from override application
_DERIVED_CODES: frozenset[str] = frozenset({"B.13"})

# B.09 has no snapshot key — excluded from override application
_NO_SNAPSHOT_KEY_CODES: frozenset[str] = frozenset({"B.09"})

# Combined set of codes that are never overridden
_SKIP_OVERRIDE_CODES: frozenset[str] = _DERIVED_CODES | _NO_SNAPSHOT_KEY_CODES

# R7/N01 — canonical OpexItem.name for B.XX codes that a family's factory
# hierarchy may not carry as named items.  When a user edits such a line the
# override is appended as an explicit item so the edit is causally effective
# against the engine-consumed OPEX vector (never silently dropped).
_CODE_TO_CANONICAL_NAME: dict[str, str] = {
    "B.01": "Technical Management",
    "B.02": "O&M Preventive & Corrective",
    "B.03": "Maintain Site",
    "B.04": "Cleaning Materials",
    "B.05": "Security",
    "B.06": "Insurance",
    "B.07": "Lease & Property Tax",
    "B.08": "Power Expenses",
    "B.10": "Audit & Accounting & Legal",
    "B.11": "Bank Fees",
    "B.12": "Environmental & Social Management",
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def has_per_line_overrides(snapshot: dict) -> bool:
    """Return True if any per-line OPEX snapshot key exists with a non-None value.

    Parameters
    ----------
    snapshot:
        The workspace draft_snapshot_json dict (may be empty).

    Returns
    -------
    bool
        True when at least one OPEX scalar key in *snapshot* has a value that
        is not None.  False otherwise (key absent or value is None).
    """
    for key in SNAPSHOT_KEY_TO_OPEX_CODE:
        value = snapshot.get(key)
        if value is not None:
            return True
    return False


def get_per_line_override_for_group(snapshot: dict, b_code: str) -> Optional[float]:
    """Return the snapshot override value for a specific B.XX group, or None.

    Parameters
    ----------
    snapshot:
        The workspace draft_snapshot_json dict.
    b_code:
        Canonical group code, e.g. ``"B.06"``.

    Returns
    -------
    float | None
        The override value in kEUR if the snapshot key exists and is not None;
        ``None`` if absent, None-valued, or the group has no snapshot key
        (B.09, B.13).
    """
    snap_key = OPEX_CODE_TO_SNAPSHOT_KEY.get(b_code)
    if snap_key is None:
        return None
    value = snapshot.get(snap_key)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_effective_draft_opex(
    base_opex: tuple,
    snapshot: dict,
) -> tuple:
    """Apply per-line OPEX overrides from *snapshot* onto *base_opex*.

    For each OpexItem in *base_opex*:

    1.  Its ``name`` is looked up in ``_OPEX_NAME_TO_CODE`` to find the B.XX
        code.
    2.  If the B.XX code maps to a snapshot key *and* the snapshot has a
        non-None value for that key, the item's ``y1_amount_keur`` is replaced
        via ``dataclasses.replace()``.
    3.  All other fields (``annual_inflation``, ``step_changes``,
        ``percentage_of_opex``, …) are preserved unchanged.
    4.  B.13 (Contingencies, ``percentage_of_opex > 0``) and B.09 (Fees, no
        scalar field) are always skipped.
    5.  If the snapshot contains no applicable overrides the original *base_opex*
        tuple is returned unchanged (same object identity — no allocation).

    Parameters
    ----------
    base_opex:
        Tuple of ``OpexItem`` instances from the project factory (or active
        scenario).
    snapshot:
        The workspace draft_snapshot_json dict.

    Returns
    -------
    tuple
        Either the original *base_opex* (no overrides) or a new tuple of
        ``OpexItem`` instances with per-line Y1 amounts substituted.

    Notes
    -----
    Explicit zero (``0.0``) is a valid override and will be applied.  Only
    ``None`` or a missing key counts as "no override".
    """
    if not snapshot:
        return base_opex

    # Pre-resolve which B.XX codes have overrides so we only call float() once
    # per key rather than per item.
    active_overrides: dict[str, float] = {}
    for snap_key, b_code in SNAPSHOT_KEY_TO_OPEX_CODE.items():
        if b_code in _SKIP_OVERRIDE_CODES:
            continue
        value = snapshot.get(snap_key)
        if value is None or value == "":
            continue
        try:
            active_overrides[b_code] = float(value)
        except (TypeError, ValueError):
            continue

    if not active_overrides:
        return base_opex

    # Walk the base items and apply overrides where applicable.
    changed = False
    new_items: list = []
    applied_codes: set[str] = set()

    for item in base_opex:
        b_code = _OPEX_NAME_TO_CODE.get(item.name)

        if b_code is None or b_code in _SKIP_OVERRIDE_CODES:
            # Unknown name, unmapped item (Taxes, Salary&Payroll), or skipped code
            new_items.append(item)
            continue

        override_value = active_overrides.get(b_code)
        if override_value is None:
            new_items.append(item)
            continue

        # Apply the override — replace only y1_amount_keur
        new_items.append(dataclasses.replace(item, y1_amount_keur=override_value))
        applied_codes.add(b_code)
        changed = True

    # R7/N01: a family's factory hierarchy may not carry a named item for
    # every registry-editable OPEX line (generic Wind/Solar factories only
    # name B.01/B.03/B.06/B.07).  An edit to an uncovered line must still be
    # causally effective: append an explicit item for it.  Without this the
    # edit persists and displays while the engine-consumed OPEX stays
    # unchanged — exactly the Astra N01 defect.  Appended lines escalate at
    # the same flat 2% the accepted scalar-collapse convention uses; no
    # source-calibrated schedule is invented for them.
    from finco_core.inputs._models import OpexItem as _OpexItem

    for b_code, override_value in active_overrides.items():
        if b_code in applied_codes or b_code in _SKIP_OVERRIDE_CODES:
            continue
        new_items.append(_OpexItem(
            name=_CODE_TO_CANONICAL_NAME.get(b_code, b_code),
            y1_amount_keur=float(override_value),
            annual_inflation=0.02,
        ))
        changed = True

    if not changed:
        return base_opex

    return tuple(new_items)
