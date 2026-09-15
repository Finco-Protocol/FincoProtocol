"""Phase 7D-1 — Investor registry and identity schema.

Defines investor roles (LP, GP, CO_INVESTOR), investor identity, committed
capital, and the InvestorRegistry — a validated, immutable collection of investors.

All schemas are frozen/immutable. No mutation of inputs. Deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

__all__ = [
    "InvestorRole",
    "InvestorEntry",
    "InvestorRegistry",
]


# ── Investor Role ───────────────────────────────────────────────────────────

class InvestorRole:
    """Investor role classification.

    Attributes
    ----------
    value : str
        Role identifier: "LP", "GP", or "CO_INVESTOR".
    is_gp : bool
        True for GP role.
    is_lp : bool
        True for LP role.
    is_co_investor : bool
        True for CO_INVESTOR role.
    """
    LP = "LP"
    GP = "GP"
    CO_INVESTOR = "CO_INVESTOR"

    def __init__(self, value: str):
        if value not in (self.LP, self.GP, self.CO_INVESTOR):
            raise ValueError(
                f"InvestorRole must be one of ({self.LP!r}, {self.GP!r}, {self.CO_INVESTOR!r}), "
                f"got {value!r}"
            )
        self._value = value

    @property
    def value(self) -> str:
        return self._value

    @property
    def is_gp(self) -> bool:
        return self._value == self.GP

    @property
    def is_lp(self) -> bool:
        return self._value == self.LP

    @property
    def is_co_investor(self) -> bool:
        return self._value == self.CO_INVESTOR

    def __repr__(self) -> str:
        return f"InwestorRole({self._value!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, InvestorRole):
            return self._value == other._value
        if isinstance(other, str):
            return self._value == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._value)


# ── Investor Entry ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class InvestorEntry:
    """Immutable investor identity and commitment record.

    Attributes
    ----------
    investor_id : str
        Unique investor identifier (e.g., "LP-1", "GP-1", "COINV-1").
        Must be non-empty and non-whitespace.
    role : InvestorRole
        Role classification: LP, GP, or CO_INVESTOR.
    ownership_percentage : float
        Ownership percentage expressed as a decimal (e.g., 0.80 for 80%).
        Must be >= 0 and finite.
    committed_capital_keur : float
        Total committed capital in kEUR. Must be >= 0 and finite.
    metadata : tuple[tuple[str, Any], ...]
        Frozen key-value metadata.
    notes : tuple[str, ...]
        Human-readable notes.
    """
    investor_id: str
    role: InvestorRole
    ownership_percentage: float
    committed_capital_keur: float
    metadata: tuple[tuple[str, Any], ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.investor_id, str) or not self.investor_id.strip():
            raise ValueError("investor_id must be non-empty string")
        if not isinstance(self.role, InvestorRole):
            raise TypeError(f"role must be InvestorRole, got {type(self.role).__name__}")
        for name, val in [("ownership_percentage", self.ownership_percentage),
                           ("committed_capital_keur", self.committed_capital_keur)]:
            if not isinstance(val, (int, float)):
                raise TypeError(f"{name} must be float, got {type(val).__name__}")
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"{name} must be finite, got {val}")
            if val < 0.0:
                raise ValueError(f"{name} must be >= 0, got {val}")
        # Normalize metadata to tuple
        if isinstance(self.metadata, dict):
            object.__setattr__(
                self, "metadata",
                tuple(sorted((str(k), _normalize(v)) for k, v in self.metadata.items()))
            )
        elif isinstance(self.metadata, (list, tuple)):
            object.__setattr__(
                self, "metadata",
                tuple(sorted((str(k), _normalize(v)) for k, v in self.metadata))
            )
        if not isinstance(self.notes, tuple):
            object.__setattr__(self, "notes", _to_tuple_str(self.notes))


# ── Investor Registry ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class InvestorRegistry:
    """Immutable, validated registry of all investors in a capital stack.

    Attributes
    ----------
    entries : tuple[InvestorEntry, ...]
        Ordered tuple of investor entries. Must contain at least one entry.
    total_ownership_pct : float
        Sum of all ownership_percentage values.
    total_committed_keur : float
        Sum of all committed_capital_keur values.
    """
    entries: tuple[InvestorEntry, ...]
    total_ownership_pct: float
    total_committed_keur: float

    def __post_init__(self):
        if not isinstance(self.entries, (list, tuple)):
            raise TypeError("entries must be tuple")
        object.__setattr__(self, "entries", tuple(self.entries))
        if len(self.entries) == 0:
            raise ValueError("InvestorRegistry must contain at least one investor")

        # Check for duplicate investor IDs
        seen_ids: set[str] = set()
        for e in self.entries:
            if not isinstance(e, InvestorEntry):
                raise TypeError(f"entries must contain InvestorEntry, got {type(e).__name__}")
            if e.investor_id in seen_ids:
                raise ValueError(f"Duplicate investor_id: {e.investor_id!r}")
            seen_ids.add(e.investor_id)

        # Check exactly one GP
        gp_count = sum(1 for e in self.entries if e.role.is_gp)
        if gp_count != 1:
            raise ValueError(f"Must have exactly one GP, got {gp_count}")

        # Validate totals
        eps = 1e-6
        total_own = sum(e.ownership_percentage for e in self.entries)
        total_cap = sum(e.committed_capital_keur for e in self.entries)
        if abs(total_own - self.total_ownership_pct) > eps:
            raise ValueError(
                f"total_ownership_pct ({self.total_ownership_pct}) does not reconcile "
                f"with entries sum ({total_own:.6f})"
            )
        if abs(total_cap - self.total_committed_keur) > eps:
            raise ValueError(
                f"total_committed_keur ({self.total_committed_keur}) does not reconcile "
                f"with entries sum ({total_cap:.6f})"
            )
        # Ownership must sum to 1.0 (within tolerance)
        if abs(total_own - 1.0) > eps:
            raise ValueError(
                f"Ownership percentages must sum to 1.0, got {total_own:.6f}"
            )

    @property
    def gp(self) -> InvestorEntry:
        """Return the GP entry. Raises if not exactly one GP."""
        gps = [e for e in self.entries if e.role.is_gp]
        if len(gps) != 1:
            raise ValueError(f"Must have exactly one GP, got {len(gps)}")
        return gps[0]

    @property
    def lps(self) -> tuple[InvestorEntry, ...]:
        """Return all LP entries."""
        return tuple(e for e in self.entries if e.role.is_lp)

    @property
    def co_investors(self) -> tuple[InvestorEntry, ...]:
        """Return all co-investor entries."""
        return tuple(e for e in self.entries if e.role.is_co_investor)

    def investor_for(self, investor_id: str) -> InvestorEntry:
        """Return the InvestorEntry for a given investor_id."""
        for e in self.entries:
            if e.investor_id == investor_id:
                return e
        raise KeyError(f"Investor not found: {investor_id!r}")

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)


# ── Helpers ──────────────────────────────────────────────────────────────────

_IMMUTABLE_JSON_SCALARS = (str, int, float, bool, type(None))


def _normalize(v: Any) -> Any:
    """Normalize a metadata value to an immutable JSON scalar."""
    if isinstance(v, _IMMUTABLE_JSON_SCALARS):
        return v
    if isinstance(v, (dict, list)):
        raise TypeError(f"Metadata values must be JSON scalars, got {type(v).__name__}")
    if isinstance(v, tuple):
        return tuple(_normalize(x) for x in v)
    return v


def _to_tuple_str(value) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return (str(value),)
