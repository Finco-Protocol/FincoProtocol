"""Distribution accounting policy for the dividend accounting layer.

Controls whether the WHT, legal reserve, and accounting-cap second pass
runs in the shareholder waterfall model.

Authority:
    Projects with SOURCE_PROVEN authority have had their dividend accounting
    formulas traced to a workbook source. Projects without this policy
    preserve frozen G2C semantics (gross == net == legal_equity_distribution).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class DistributionAccountingAuthority(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    GENERIC_FINCO_POLICY = "GENERIC_FINCO_POLICY"
    SOURCE_PROVEN = "SOURCE_PROVEN"


class OpeningUCAuthority(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    SOURCE_PROVEN_EXPLICIT_ZERO = "SOURCE_PROVEN_EXPLICIT_ZERO"
    CAUSALLY_DERIVED_ZERO = "CAUSALLY_DERIVED_ZERO"


# Q.8: Valid opening UC authorities — project-level typed contract.
# SOURCE_PROVEN_EXPLICIT_ZERO: workbook cell reference provided.
# CAUSALLY_DERIVED_ZERO: greenfield axiom (O.9) — no uncommitted cash at FC.
# UNRESOLVED: fails closed; must be resolved before enabling distribution accounting.
OPENING_UC_AUTHORITY_VALID: frozenset[str] = frozenset({
    OpeningUCAuthority.SOURCE_PROVEN_EXPLICIT_ZERO,
    OpeningUCAuthority.CAUSALLY_DERIVED_ZERO,
})


@dataclass(frozen=True)
class DistributionAccountingPolicy:
    """Authority for the dividend accounting layer (WHT, legal reserve, accounting cap)."""
    enabled: bool = False
    authority: DistributionAccountingAuthority = DistributionAccountingAuthority.UNRESOLVED
    dividend_wht_rate: float = 0.0        # e.g. 0.05 for Generic Solar Reference, 0.0 for Generic Wind Reference
    legal_reserve_cap_fraction: float = 0.10  # default 10%
    # Q.8: Project-level opening UC authority. Must be SOURCE_PROVEN_EXPLICIT_ZERO or
    # CAUSALLY_DERIVED_ZERO when enabled=True. UNRESOLVED fails closed.
    # Default UNRESOLVED fails closed when enabled=True. Projects must explicitly configure CAUSALLY_DERIVED_ZERO or SOURCE_PROVEN_EXPLICIT_ZERO.
    opening_uc_authority: str = OpeningUCAuthority.UNRESOLVED

    def __post_init__(self) -> None:
        if self.enabled and self.authority == DistributionAccountingAuthority.UNRESOLVED:
            raise ValueError(
                "DistributionAccountingPolicy: enabled=True requires authority != UNRESOLVED. "
                "Resolve authority before enabling the dividend accounting layer."
            )
        if self.enabled and self.opening_uc_authority not in OPENING_UC_AUTHORITY_VALID:
            raise ValueError(
                f"DistributionAccountingPolicy: opening_uc_authority="
                f"{self.opening_uc_authority!r} is not in {sorted(OPENING_UC_AUTHORITY_VALID)}. "
                "Provide SOURCE_PROVEN_EXPLICIT_ZERO (workbook cell) or CAUSALLY_DERIVED_ZERO "
                "(greenfield axiom O.9). UNRESOLVED fails closed."
            )
        if not (0.0 <= self.dividend_wht_rate <= 1.0):
            raise ValueError(
                f"DistributionAccountingPolicy: dividend_wht_rate={self.dividend_wht_rate!r} "
                "must be in [0, 1]."
            )
        if not (0.0 <= self.legal_reserve_cap_fraction <= 1.0):
            raise ValueError(
                f"DistributionAccountingPolicy: legal_reserve_cap_fraction="
                f"{self.legal_reserve_cap_fraction!r} must be in [0, 1]."
            )


def assert_wht_authority_consistent(
    tax_wht: float,
    policy: "DistributionAccountingPolicy | None",
) -> None:
    """O.3: Fail closed if TaxParams.wht_sponsor_dividends disagrees with
    DistributionAccountingPolicy.dividend_wht_rate when the policy is enabled.

    DistributionAccountingPolicy.dividend_wht_rate is the canonical owner.
    TaxParams.wht_sponsor_dividends is the legacy field (kept for backward
    compatibility with serialised payloads). When a distribution accounting
    policy is active, both must agree or the project inputs are rejected.
    """
    if policy is None or not policy.enabled:
        return
    if abs(tax_wht - policy.dividend_wht_rate) > 1e-12:
        raise ValueError(
            f"O.3 WHT authority conflict: TaxParams.wht_sponsor_dividends="
            f"{tax_wht!r} disagrees with "
            f"DistributionAccountingPolicy.dividend_wht_rate="
            f"{policy.dividend_wht_rate!r}. "
            "DistributionAccountingPolicy.dividend_wht_rate is canonical. "
            "Update TaxParams.wht_sponsor_dividends to match, or disable the policy."
        )
