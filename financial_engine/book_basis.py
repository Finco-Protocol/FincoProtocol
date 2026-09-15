"""financial_engine.book_basis — Canonical builder for BookDepreciableAssetBasis.

One function, two paths:

  Generic (Solar / Wind, construction_financing_result is None):
      Converts CapexStructure.book_depreciable_capex_items() directly to
      BookDepreciableAssetComponent entries. Economically identical to the
      current implicit CapexStructure path.

  Typed construction (Generic Solar Reference / Generic Wind Reference, construction_financing_result is not None):
      Hard CAPEX from CapexStructure.capex_items() (filtered by is_depreciable).
      Financing components from ConstructionFinancingResult:
          IDC    — sum(senior_idc_capitalized_uses_keur)      (NOT senior_idc_accrual_keur)
          Fee    — senior_commitment_fee_capitalized_keur      (NOT senior_commitment_fee_accrual_keur)
          Struct — sum(structuring_fee_keur)
          VAT    — vat_idc_keur + vat_commitment_fee_keur

Two caller contexts — one builder:

  A. Iterative economic production path (PR-9 outer loop, each iteration):
      Called from from_project_inputs(inner_inputs) with NO book_basis kwarg.
      The adapter fallback calls build_book_depreciable_asset_basis(inputs.capex)
      with NO construction_financing_result argument.
      capex_structure = updated_capex (financing-cost fields populated by
      apply_capitalized_financing_costs for that iteration).
      construction_financing_result = None (always, on this path).
      The canonical builder derives the economic depreciation basis from
      updated_capex via the generic path.  That basis drives
      DepreciationInput → book_depreciation_keur → tax/CFADS/Senior/SHL
      → convergence.

  B. Final typed downstream handoff (once, after strict convergence):
      Called from project.py after the final strict run_stage_b2 verification.
      capex_structure = orig_capex (original project inputs, before any
      financing-cost application).
      construction_financing_result = final ConstructionFinancingResult.
      Result is exposed on ProjectFinancingResult.book_depreciable_asset_basis
      for downstream C3 / audit consumers.
      Does NOT feed back into the PR-9 iteration loop.

Synthetic reference policy: financing components use explicit model-configured useful-life overrides.

No project-code dispatch. No project-name dispatch. No identity whitelist.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from finco_core.inputs.book_depreciable_asset_basis import (
    BookDepreciableAssetBasis,
    BookDepreciableAssetComponent,
)

if TYPE_CHECKING:
    from finco_core.inputs._models import CapexStructure
    from financial_engine.financing.contracts import ConstructionFinancingResult

_GENERIC_AUTHORITY = "GENERIC_CAPEX_STRUCTURE_BOOK_BASIS"
_TYPED_AUTHORITY = "TYPED_CONSTRUCTION_FINANCING_RESULT_BOOK_BASIS"

_PROV_GENERIC = "CAPEX_STRUCTURE_GENERIC"
_PROV_HARD_CAPEX = "CAPEX_STRUCTURE_HARD_CAPEX"
_PROV_IDC = "CONSTRUCTION_FINANCING_RESULT_SENIOR_IDC_CAPITALIZED_USES"
_PROV_FEE = "CONSTRUCTION_FINANCING_RESULT_SENIOR_COMMITMENT_FEE_CAPITALIZED"
_PROV_STRUCT = "CONSTRUCTION_FINANCING_RESULT_STRUCTURING_FEE"
_PROV_VAT = "CONSTRUCTION_FINANCING_RESULT_VAT_CAPITALIZED"


def build_book_depreciable_asset_basis(
    capex_structure: "CapexStructure",
    construction_financing_result: "ConstructionFinancingResult | None" = None,
) -> BookDepreciableAssetBasis:
    """Build the canonical book depreciable asset basis for one project.

    Args:
        capex_structure: For the iterative production path (path A), this is
            updated_capex with financing-cost fields populated for that iteration.
            For the final typed downstream handoff (path B), this is orig_capex
            (original project inputs, before any financing-cost application).
        construction_financing_result: The ConstructionFinancingResult for this
            call. None for Solar / Wind (generic path). For the final typed
            downstream handoff, this is the final strict post-convergence CFR.

    Returns:
        BookDepreciableAssetBasis with one component per depreciable line item.
    """
    if construction_financing_result is not None:
        return _build_typed_construction_basis(capex_structure, construction_financing_result)
    return _build_generic_basis(capex_structure)


def _build_generic_basis(capex_structure: "CapexStructure") -> BookDepreciableAssetBasis:
    components = tuple(
        BookDepreciableAssetComponent(
            code=item.name,
            name=item.name,
            amount_keur=item.amount_keur,
            asset_class_code=item.asset_class.value,
            useful_life_override=item.useful_life_override,
            provenance=_PROV_GENERIC,
        )
        for item in capex_structure.book_depreciable_capex_items()
        if item.amount_keur != 0.0
    )
    return BookDepreciableAssetBasis(
        components=components,
        authority=_GENERIC_AUTHORITY,
    )


def _build_typed_construction_basis(
    capex_structure: "CapexStructure",
    cfr: "ConstructionFinancingResult",
) -> BookDepreciableAssetBasis:
    components: list[BookDepreciableAssetComponent] = []

    # Hard CAPEX: policy-defined depreciable items
    for item in capex_structure.capex_items():
        if not item.is_depreciable:
            continue
        if item.amount_keur == 0.0:
            continue
        components.append(BookDepreciableAssetComponent(
            code=item.name,
            name=item.name,
            amount_keur=item.amount_keur,
            asset_class_code=item.asset_class.value,
            useful_life_override=item.useful_life_override,
            provenance=_PROV_HARD_CAPEX,
        ))

    # Capitalized Senior IDC — use capitalized-USE vector, not raw accrual.
    # Terminal IDC (accures after last funded draw) is excluded from capitalized uses.
    idc = sum(cfr.senior_idc_capitalized_uses_keur)
    if idc > 0.0:
        components.append(BookDepreciableAssetComponent(
            code="senior_idc",
            name="IDC (Interest During Construction)",
            amount_keur=idc,
            asset_class_code="financial_costs",
            useful_life_override=12,
            provenance=_PROV_IDC,
        ))

    # Senior commitment fees — use canonical capitalized scalar, NOT raw accrual vector.
    commitment_fee = cfr.senior_commitment_fee_capitalized_keur
    if commitment_fee > 0.0:
        components.append(BookDepreciableAssetComponent(
            code="senior_commitment_fee",
            name="Commitment Fees",
            amount_keur=commitment_fee,
            asset_class_code="financial_costs",
            useful_life_override=12,
            provenance=_PROV_FEE,
        ))

    # Structuring / arrangement fee
    structuring = sum(cfr.structuring_fee_keur)
    if structuring > 0.0:
        components.append(BookDepreciableAssetComponent(
            code="structuring_fee",
            name="Bank Fees",
            amount_keur=structuring,
            asset_class_code="financial_costs",
            useful_life_override=12,
            provenance=_PROV_STRUCT,
        ))

    # VAT-facility financing costs (combined; evidence: dep_vat_keur, 20-year useful life)
    vat = cfr.vat_idc_keur + cfr.vat_commitment_fee_keur
    if vat > 0.0:
        components.append(BookDepreciableAssetComponent(
            code="vat_costs",
            name="VAT Costs",
            amount_keur=vat,
            asset_class_code="financial_costs",
            useful_life_override=20,
            provenance=_PROV_VAT,
        ))

    return BookDepreciableAssetBasis(
        components=tuple(components),
        authority=_TYPED_AUTHORITY,
    )
