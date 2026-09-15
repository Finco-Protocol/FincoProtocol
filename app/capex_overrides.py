"""CapEx scaling helpers — proportional scaling of CapexItem line items."""
from dataclasses import replace, fields as dc_fields, is_dataclass

from domain.inputs import CapexStructure, CapexItem


def scale_capex_items(capex: CapexStructure, target_total_capex: float) -> CapexStructure:
    """Return a new CapexStructure where CapexItem amounts and contributing scalar
    fields are scaled proportionally.

    CapexStructure.total_capex = hard_capex_keur + commitment_fees_keur + bank_fees_keur
    + other_financial_keur + vat_costs_keur + reserve_accounts_keur + idc_keur

    This helper scales CapexItem.amount_keur fields and the scalar fields idc_keur,
    bank_fees_keur, other_financial_keur, and vat_costs_keur.  Commitment fees and
    reserve accounts are NOT scaled because they represent financing-structure
    items outside the hard-capex base.

    As a result, if commitment_fees_keur and reserve_accounts_keur are both zero
    (as in the default solar/wind projects), total_capex will equal target exactly.
    Otherwise it will be approximate — the docstring claims "approximately equal"
    rather than exact equality.
    """
    if target_total_capex < 0:
        raise ValueError(f"target_total_capex must be non-negative, got {target_total_capex}")
    current_total = capex.total_capex
    if current_total <= 0:
        return capex
    scale = target_total_capex / current_total

    if not is_dataclass(capex):
        return capex

    # Scalar non-CapexItem fields that contribute to total_capex_before_idc
    # (excluded: commitment_fees_keur, reserve_accounts_keur — not part of hard capex base)
    _SCALAR_CAPEX_FIELDS = (
        "idc_keur",
        "bank_fees_keur",
        "other_financial_keur",
        "vat_costs_keur",
    )

    updates = {}
    for f in dc_fields(capex):
        val = getattr(capex, f.name)
        if is_dataclass(val) and hasattr(val, 'amount_keur'):
            # It's a CapexItem — scale amount_keur
            updates[f.name] = replace(val, amount_keur=val.amount_keur * scale)
        elif f.name in _SCALAR_CAPEX_FIELDS and val:
            updates[f.name] = val * scale

    if not updates:
        return capex
    return replace(capex, **updates)
