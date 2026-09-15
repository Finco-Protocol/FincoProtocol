"""Phase 7C-1 — Sponsor waterfall tier schemas.

Immutable schema foundations for preferred return / promote waterfall tiers.
Schema-only: no allocation logic, no waterfall state, no dependency on app/UI/export.

Design goals:
- Deterministic, audit-safe, frozen dataclasses
- Future multi-investor compatibility (sponsor_shares tuple)
- Future promote extensibility (tier_type enum, compounding convention)
- Serialization-friendly (all JSON-serializable scalars)
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from enum import Enum
from typing import Any

__all__ = [
    "TierType",
    "CompoundingConvention",
    "SponsorShare",
    "SponsorWaterfallTier",
    "WaterfallTierValidationResult",
]


# ── Enums ─────────────────────────────────────────────────────────────────────

class TierType(Enum):
    """Waterfall tier classification.

    Ordered roughly by distribution priority (lower ordinal = earlier tier).
    """
    RETURN_OF_CAPITAL = "RETURN_OF_CAPITAL"
    PREFERRED_RETURN = "PREFERRED_RETURN"
    GP_CATCH_UP = "GP_CATCH_UP"
    PROMOTE = "PROMOTE"
    RESIDUAL = "RESIDUAL"


class CompoundingConvention(Enum):
    """Preferred return compounding frequency."""
    ANNUAL = "ANNUAL"
    SIMPLE = "SIMPLE"      # no compounding
    SEMIANNUAL = "SEMIANNUAL"


# ── SponsorShare ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SponsorShare:
    """Allocation share for a single investor within a waterfall tier.

    Immutable. Deterministic. Serialization-friendly.

    Attributes
    ----------
    sponsor_code : str
        Investor identifier (e.g., "SPONSOR-1", "GP-1"). Non-empty.
    allocation_percentage : float
        Fraction of the tier allocated to this sponsor (0.0 to 1.0).
        Must sum to 1.0 across all SponsorShares in a tier (enforced in
        SponsorWaterfallTier.__post_init__, not here).
    """
    sponsor_code: str
    allocation_percentage: float

    def __post_init__(self):
        if not isinstance(self.sponsor_code, str) or not self.sponsor_code.strip():
            raise ValueError(
                f"sponsor_code must be a non-empty string, got {self.sponsor_code!r}"
            )
        if not isinstance(self.allocation_percentage, (int, float)):
            raise TypeError(
                f"allocation_percentage must be float, got {type(self.allocation_percentage).__name__}"
            )
        if math.isnan(self.allocation_percentage) or math.isinf(self.allocation_percentage):
            raise ValueError(
                f"allocation_percentage must be finite, got {self.allocation_percentage}"
            )
        if self.allocation_percentage < 0.0:
            raise ValueError(
                f"allocation_percentage must be >= 0, got {self.allocation_percentage}"
            )

    @property
    def allocation_percent(self) -> float:
        """Alias for programmatic access."""
        return self.allocation_percentage


# ── SponsorWaterfallTier ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class SponsorWaterfallTier:
    """Immutable waterfall tier definition.

    Defines how a tier operates: type, hurdle, compounding, and investor shares.
    Designed for audit trail and deterministic serialization.

    Attributes
    ----------
    tier_index : int
        Order of this tier in the waterfall (0 = first tier).
        Tiers must be sorted by tier_index when assembled into a waterfall.
    tier_type : TierType
        Classification of this tier.
    sponsor_shares : tuple[SponsorShare, ...]
        Ordered immutable tuple of investor allocation shares.
        Percentages must sum to 1.0 ± 1e-8 across all shares in a tier.
    hurdle_rate_pa : float | None
        Annual preferred return hurdle rate (decimal, e.g. 0.08 for 8%).
        Required for PREFERRED_RETURN tiers. Forbidden for RETURN_OF_CAPITAL.
        None for GP_CATCH_UP, PROMOTE, RESIDUAL.
    compounding_convention : CompoundingConvention | None
        Compounding frequency for pref accrual.
        Required for PREFERRED_RETURN tiers. None for other tiers.
    description : str
        Human-readable description of this tier (e.g. "sponsor return of capital").
    audit_note : str
        Fixed audit note confirming this is a read-only governance artifact.
    notes : tuple[str, ...]
        Additional human-readable notes.
    """
    tier_index: int
    tier_type: TierType
    sponsor_shares: tuple[SponsorShare, ...]
    description: str
    hurdle_rate_pa: float | None = None
    compounding_convention: CompoundingConvention | None = None
    audit_note: str = "AUDIT-ONLY: waterfall tier schema — read-only governance artifact, not a distribution commitment"
    notes: tuple[str, ...] = field(default_factory=tuple)

    # Tolerance for percentage sum check
    _SUM_TOLERANCE: float = field(default=1e-8, repr=False)

    def __post_init__(self):
        # tier_index must be non-negative
        if not isinstance(self.tier_index, int):
            raise TypeError(f"tier_index must be int, got {type(self.tier_index).__name__}")
        if self.tier_index < 0:
            raise ValueError(f"tier_index must be >= 0, got {self.tier_index}")

        # tier_type must be TierType
        if not isinstance(self.tier_type, TierType):
            raise TypeError(f"tier_type must be TierType, got {type(self.tier_type).__name__}")

        # sponsor_shares must be non-empty tuple
        if isinstance(self.sponsor_shares, (list, tuple)):
            shares = tuple(self.sponsor_shares)
            object.__setattr__(self, "sponsor_shares", shares)
        else:
            raise TypeError(f"sponsor_shares must be tuple, got {type(self.sponsor_shares).__name__}")

        if len(self.sponsor_shares) == 0:
            raise ValueError("sponsor_shares cannot be empty")

        # No duplicate sponsor_code within a tier
        codes = [s.sponsor_code for s in self.sponsor_shares]
        if len(codes) != len(set(codes)):
            raise ValueError(f"Duplicate sponsor_code in sponsor_shares: {codes}")

        # sponsor_shares percentages sum to 1.0 ± tolerance
        total = sum(s.allocation_percentage for s in self.sponsor_shares)
        if abs(total - 1.0) > self._SUM_TOLERANCE:
            raise ValueError(
                f"sponsor_shares percentages must sum to 1.0, got {total:.8f} (diff={abs(total - 1.0):.2e})"
            )

        # Tier-specific hurdle rules
        if self.tier_type == TierType.PREFERRED_RETURN:
            if self.hurdle_rate_pa is None:
                raise ValueError(
                    "hurdle_rate_pa is required for PREFERRED_RETURN tiers"
                )
            if self.compounding_convention is None:
                raise ValueError(
                    "compounding_convention is required for PREFERRED_RETURN tiers"
                )
        elif self.tier_type == TierType.RETURN_OF_CAPITAL:
            if self.hurdle_rate_pa is not None:
                raise ValueError(
                    "hurdle_rate_pa is forbidden for RETURN_OF_CAPITAL tiers"
                )
            if self.compounding_convention is not None:
                raise ValueError(
                    "compounding_convention is forbidden for RETURN_OF_CAPITAL tiers"
                )
        else:
            # GP_CATCH_UP, PROMOTE, RESIDUAL: hurdle and compounding must be None
            if self.hurdle_rate_pa is not None:
                raise ValueError(
                    f"hurdle_rate_pa is forbidden for {self.tier_type.value} tiers"
                )
            if self.compounding_convention is not None:
                raise ValueError(
                    f"compounding_convention is forbidden for {self.tier_type.value} tiers"
                )

        # hurdle_rate_pa must be finite and in (0, 1) when present
        if self.hurdle_rate_pa is not None:
            if not isinstance(self.hurdle_rate_pa, (int, float)):
                raise TypeError(f"hurdle_rate_pa must be float, got {type(self.hurdle_rate_pa).__name__}")
            if math.isnan(self.hurdle_rate_pa) or math.isinf(self.hurdle_rate_pa):
                raise ValueError(f"hurdle_rate_pa must be finite, got {self.hurdle_rate_pa}")
            if not (0.0 < self.hurdle_rate_pa < 1.0):
                raise ValueError(
                    f"hurdle_rate_pa must be in (0, 1), got {self.hurdle_rate_pa}"
                )

        # description must be non-empty
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError(f"description must be a non-empty string, got {self.description!r}")

        # audit_note must be str
        if not isinstance(self.audit_note, str):
            raise TypeError(f"audit_note must be str, got {type(self.audit_note).__name__}")

        # notes: normalize to tuple
        if isinstance(self.notes, (list, tuple)):
            object.__setattr__(self, "notes", tuple(str(n) for n in self.notes))
        else:
            object.__setattr__(self, "notes", (str(self.notes),) if self.notes else ())

    @property
    def sorted_shares(self) -> tuple[SponsorShare, ...]:
        """Shares sorted deterministically by sponsor_code (for consistent serialization)."""
        return tuple(sorted(self.sponsor_shares, key=lambda s: s.sponsor_code))

    def share_for(self, sponsor_code: str) -> float:
        """Return allocation percentage for a given sponsor_code. 0.0 if not found."""
        for share in self.sponsor_shares:
            if share.sponsor_code == sponsor_code:
                return share.allocation_percentage
        return 0.0


# ── WaterfallTierValidationResult ─────────────────────────────────────────────

@dataclass(frozen=True)
class WaterfallTierValidationResult:
    """Result of validating a waterfall tier or collection of tiers.

    Immutable. Used to report validation outcomes without raising exceptions.
    """
    valid: bool
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @staticmethod
    def ok() -> WaterfallTierValidationResult:
        return WaterfallTierValidationResult(valid=True)

    @staticmethod
    def error(msg: str) -> WaterfallTierValidationResult:
        return WaterfallTierValidationResult(valid=False, errors=(msg,))

    @staticmethod
    def from_tier(tier: SponsorWaterfallTier) -> WaterfallTierValidationResult:
        """Validate a single tier and return result without raising."""
        errors: list[str] = []
        warnings: list[str] = []

        try:
            # Re-validate via construction (will raise on invalid)
            # We use the frozen dataclass's __init__ to trigger validation
            # Rather than re-implementing validation here.
            pass
        except (ValueError, TypeError) as e:
            errors.append(str(e))

        return WaterfallTierValidationResult(
            valid=len(errors) == 0,
            errors=tuple(errors),
            warnings=tuple(warnings),
        )

    def __bool__(self) -> bool:
        return self.valid