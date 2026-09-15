"""finco_core.inputs.book_depreciable_asset_basis — Canonical typed contract for the book
depreciable asset basis consumed by the clean book depreciation engine.

Authority: BOOK_DEPRECIABLE_ASSET_BASIS_UPSTREAM_REQUIRED (see Phase C3 authority doc).

Each project run produces one BookDepreciableAssetBasis instance carrying all components
that enter the straight-line book depreciation schedule. The two construction paths are:

  Generic (Solar / Wind): basis derived from CapexStructure.book_depreciable_capex_items()
      using the financing-cost fields already held on CapexStructure.

  Typed construction (Generic Solar Reference / Generic Wind Reference): basis derived directly from ConstructionFinancingResult
      — hard CAPEX from CapexStructure.capex_items(), financing components from the
      canonically resolved ConstructionFinancingResult vectors. This is the authoritative
      source for the capitalized IDC distinction (sum of capitalized USES, not raw accrual).

SHL PIK and DSRA are excluded by policy (not CAPEX, not depreciable assets).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BookDepreciableAssetComponent:
    """One depreciable asset component within the book basis.

    Each component maps directly to one CapexItemForDep entry when the basis
    is wired into DepreciationInput.book_capex_items_for_depreciation.
    """
    code: str
    name: str
    amount_keur: float
    asset_class_code: str
    useful_life_override: Optional[int]
    provenance: str

    def __post_init__(self) -> None:
        if not self.code or not isinstance(self.code, str):
            raise ValueError(f"BookDepreciableAssetComponent.code must be a non-empty string, got {self.code!r}")
        if not self.name or not isinstance(self.name, str):
            raise ValueError(f"BookDepreciableAssetComponent.name must be a non-empty string, got {self.name!r}")
        if not self.asset_class_code or not isinstance(self.asset_class_code, str):
            raise ValueError(f"BookDepreciableAssetComponent.asset_class_code must be a non-empty string, got {self.asset_class_code!r}")
        if not self.provenance or not isinstance(self.provenance, str):
            raise ValueError(f"BookDepreciableAssetComponent.provenance must be a non-empty string, got {self.provenance!r}")
        if isinstance(self.amount_keur, bool):
            raise ValueError(f"BookDepreciableAssetComponent.amount_keur must not be bool, got {self.amount_keur!r}")
        if not isinstance(self.amount_keur, (int, float)):
            raise ValueError(f"BookDepreciableAssetComponent.amount_keur must be numeric, got {self.amount_keur!r}")
        if math.isnan(self.amount_keur) or math.isinf(self.amount_keur):
            raise ValueError(f"BookDepreciableAssetComponent.amount_keur must be finite, got {self.amount_keur!r}")
        if self.amount_keur < 0.0:
            raise ValueError(f"BookDepreciableAssetComponent.amount_keur must be >= 0, got {self.amount_keur!r}")
        if self.useful_life_override is not None:
            if not isinstance(self.useful_life_override, int) or isinstance(self.useful_life_override, bool):
                raise ValueError(f"BookDepreciableAssetComponent.useful_life_override must be int or None, got {self.useful_life_override!r}")
            if self.useful_life_override <= 0:
                raise ValueError(f"BookDepreciableAssetComponent.useful_life_override must be > 0, got {self.useful_life_override!r}")


@dataclass(frozen=True)
class BookDepreciableAssetBasis:
    """Complete canonical book depreciable asset basis for one project at COD.

    Produced after PR-9 outer fixed-point convergence. Carries all components
    whose amounts will enter the straight-line book depreciation schedule over
    the operating life of the asset.

    authority values:
      "GENERIC_CAPEX_STRUCTURE_BOOK_BASIS"
          — generic path (Solar / Wind); CapexStructure fields are the source.
      "TYPED_CONSTRUCTION_FINANCING_RESULT_BOOK_BASIS"
          — typed construction path (Generic Solar Reference / Generic Wind Reference); ConstructionFinancingResult
            is the authoritative source for financing-cost components.
    """
    components: tuple[BookDepreciableAssetComponent, ...]
    authority: str

    def __post_init__(self) -> None:
        if not self.authority or not isinstance(self.authority, str):
            raise ValueError(f"BookDepreciableAssetBasis.authority must be a non-empty string, got {self.authority!r}")
        if not isinstance(self.components, tuple):
            raise ValueError(f"BookDepreciableAssetBasis.components must be a tuple, got {type(self.components)!r}")
        codes = [c.code for c in self.components]
        if len(codes) != len(set(codes)):
            duplicates = [c for c in codes if codes.count(c) > 1]
            raise ValueError(f"BookDepreciableAssetBasis.components has duplicate codes: {duplicates!r}")

    @property
    def total_keur(self) -> float:
        return sum(c.amount_keur for c in self.components)
