"""Phase 3A HoldCo domain skeleton — inputs only.

No cash flow calculations. No SHL. No tax template.
No Excel export. No UI. Pure dataclass + validation layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SPVOwnership:
    """Ownership record for a single SPV within HoldCo.

    Phase 3 assumes 100% ownership (no minority modeling).
    Ownership percentage is expressed as a fraction (0.0–1.0).
    """
    spv_code: str
    ownership_pct: float  # 0.0–1.0

    def __post_init__(self):
        if not self.spv_code or not self.spv_code.strip():
            raise ValueError("spv_code is required")
        if not (0.0 < self.ownership_pct <= 1.0):
            raise ValueError(f"ownership_pct must be in (0.0, 1.0], got {self.ownership_pct}")


@dataclass
class HoldCoOpexInputs:
    """HoldCo-level operating expenditure inputs.

    Phase 3A: flat annual OpEx in kEUR.
    Future: could expand to per-period OpEx schedules.
    """
    annual_opex_keur: float = 0.0
    currency: str = "EUR"

    def __post_init__(self):
        if self.annual_opex_keur < 0:
            raise ValueError(f"annual_opex_keur must be >= 0, got {self.annual_opex_keur}")


@dataclass
class HoldCoEntity:
    """HoldCo entity metadata. Represents the intermediate holding company."""
    name: str
    currency: str = "EUR"
    tax_rate_pa: float = 0.0
    # PLACEHOLDER: flat HoldCo tax rate only.
    # Future tax template engine will replace this.
    # Do not add ATAD or detailed tax logic here.
    opex: HoldCoOpexInputs = field(default_factory=HoldCoOpexInputs)

    def __post_init__(self):
        if not self.name or not self.name.strip():
            raise ValueError("HoldCo name is required")
        if not (0.0 <= self.tax_rate_pa < 1.0):
            raise ValueError(f"tax_rate_pa must be in [0.0, 1.0), got {self.tax_rate_pa}")


@dataclass
class HoldCoInputs:
    """Top-level HoldCo configuration and inputs.

    Aggregates entity metadata + SPV ownership list.
    No cash flow calculations are performed in this class.

    Validation rules:
    - name is required
    - at least one SPV ownership row
    - ownership_pct must be > 0 and <= 1.0
    - duplicate SPV codes are rejected
    """
    name: str
    ownerships: list[SPVOwnership] = field(default_factory=list)
    entity: Optional[HoldCoEntity] = None
    horizon_years: int = 25  # planning horizon for HoldCo-level cash flows

    def __post_init__(self):
        if not self.name or not self.name.strip():
            raise ValueError("HoldCoInputs.name is required")

        if not self.ownerships:
            raise ValueError("HoldCoInputs must have at least one SPV ownership row")

        # Check for duplicate SPV codes
        spv_codes = [o.spv_code for o in self.ownerships]
        if len(spv_codes) != len(set(spv_codes)):
            seen = set()
            for code in spv_codes:
                if code in seen:
                    raise ValueError(f"Duplicate SPV code in ownerships: '{code}'")
                seen.add(code)

        # Validate each ownership entry
        for o in self.ownerships:
            if not (0.0 < o.ownership_pct <= 1.0):
                raise ValueError(
                    f"Ownership percentage for SPV '{o.spv_code}' must be in (0.0, 1.0], "
                    f"got {o.ownership_pct}"
                )

        # Default entity if not provided
        if self.entity is None:
            self.entity = HoldCoEntity(name=self.name)

    @property
    def spv_codes(self) -> list[str]:
        """List of SPV codes in this HoldCo configuration."""
        return [o.spv_code for o in self.ownerships]

    @property
    def is_100_percent(self) -> bool:
        """True if all SPVs are owned at 100%."""
        return all(o.ownership_pct == 1.0 for o in self.ownerships)

    def total_ownership_pct(self) -> float:
        """Sum of ownership percentages across all SPVs. Does NOT require sum = 1.0.

        Used for informational purposes only. Partial ownership fractions
        accumulate when HoldCo owns less than 100% of multiple SPVs.
        """
        return sum(o.ownership_pct for o in self.ownerships)