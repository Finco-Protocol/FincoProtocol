"""Phase 7A — Sponsor capital account skeleton.

Tracks sponsor equity contributions and distributions through the investment life.
Immutable. Audit-safe. Designed for future waterfall and multi-investor compatibility.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

__all__ = [
    "CapitalAccountEntry",
    "SponsorCapitalAccount",
]


def _finite_non_negative(value: float, name: str) -> None:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be float, got {type(value).__name__}")
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"{name} must be finite, got {value}")
    if value < 0.0:
        raise ValueError(f"{name} must be non-negative, got {value}")


def _finite(value: float, name: str) -> None:
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be float, got {type(value).__name__}")
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"{name} must be finite, got {value}")


def _to_tuple_str(value) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return (str(value),)


# ── CapitalAccountEntry ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class CapitalAccountEntry:
    """Single capital account ledger entry.

    Immutable. Represents either a contribution or a distribution at a point in time.

    Attributes
    ----------
    entry_type : str
        "contribution" | "distribution" | "adjustment"
    period_index : int
        Period index (0-based). Must be >= 0.
    amount_keur : float
        Amount in kEUR. Must be >= 0 and finite.
    running_balance_keur : float
        Capital account balance after this entry is applied.
        May be negative when cumulative distributions exceed
        cumulative equity injected (return phase). Must be finite.
    investor_id : str
        Sponsor/investor identifier.
    source : str
        Source of the entry: "equity_injection", "distribution_from_holdco",
        "regan", "topup", "return_of_capital", "other".
    audit_note : str
        Fixed audit note.
    notes : tuple[str, ...]
        Human-readable notes for this entry.
    """
    entry_type: str
    period_index: int
    amount_keur: float
    running_balance_keur: float
    investor_id: str
    source: str
    audit_note: str = "AUDIT-ONLY: capital account entry — read-only governance artifact"
    notes: tuple[str, ...] = field(default_factory=tuple)

    _VALID_TYPES = ("contribution", "distribution", "adjustment")
    # Maps EquityInjection.purpose to canonical source values
    _PURPOSE_TO_SOURCE = {
        "equityContribution": "equity_injection",
        "regan": "regan",
        "topUp": "topup",
        "deferredEquity": "equity_injection",
        "returnOfCapital": "return_of_capital",
    }

    _VALID_SOURCES = (
        "equity_injection",
        "distribution_from_holdco",
        "regan",
        "topup",
        "return_of_capital",
        "other",
    )

    def __post_init__(self):
        if self.period_index < 0:
            raise ValueError(f"period_index must be >= 0, got {self.period_index}")
        if self.entry_type not in self._VALID_TYPES:
            raise ValueError(
                f"entry_type must be one of {self._VALID_TYPES}, got {self.entry_type!r}"
            )
        # Resolve source: map EquityInjection purpose values to canonical sources
        resolved_source = self._PURPOSE_TO_SOURCE.get(self.source, self.source)
        if resolved_source not in self._VALID_SOURCES:
            raise ValueError(
                f"source must be one of {self._VALID_SOURCES}, got {self.source!r}"
            )
        _finite_non_negative(self.amount_keur, "amount_keur")
        _finite(self.running_balance_keur, "running_balance_keur")  # may be negative in return phase
        if not isinstance(self.notes, tuple):
            object.__setattr__(self, "notes", _to_tuple_str(self.notes))


# ── SponsorCapitalAccount ────────────────────────────────────────────────────

@dataclass(frozen=True)
class SponsorCapitalAccount:
    """Complete capital account for a sponsor investor.

    Immutable. Ordered ledger of contributions and distributions.

    Attributes
    ----------
    investor_id : str
        Sponsor/investor identifier.
    entity_code : str
        Target entity code (e.g., "HOLDCO", "PORTFOLIO").
    entries : tuple[CapitalAccountEntry, ...]
        Ordered ledger entries (by period_index then entry order within period).
    total_contributed_keur : float
        Sum of all contribution entries. Must be >= 0.
    total_distributions_keur : float
        Sum of all distribution entries. Must be >= 0.
    net_contributed_keur : float
        total_contributed - total_distributions (can be negative if distributions > contributions).
    final_balance_keur : float | None
        Final capital account balance. May be negative when cumulative
        distributions exceed cumulative equity injected (return phase).
        None if not yet finalised.
    metadata : tuple[tuple[str, Any], ...]
        Key-value metadata as frozen sorted tuple.
    notes : tuple[str, ...]
        Top-level audit notes.
    """
    investor_id: str
    entity_code: str
    entries: tuple[CapitalAccountEntry, ...]
    total_contributed_keur: float
    total_distributions_keur: float
    net_contributed_keur: float
    final_balance_keur: float | None = None
    metadata: tuple[tuple[str, Any], ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def audit_note(self) -> str:
        return (
            "AUDIT-ONLY: sponsor capital account is a read-only governance artifact. "
            "It does not modify any waterfall result or trigger payments."
        )

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    @property
    def contributions_by_period(self) -> tuple[tuple[int, float], ...]:
        """Contributions as (period_index, amount) tuples."""
        return tuple(
            (e.period_index, e.amount_keur)
            for e in self.entries
            if e.entry_type == "contribution"
        )

    @property
    def distributions_by_period(self) -> tuple[tuple[int, float], ...]:
        """Distributions as (period_index, amount) tuples."""
        return tuple(
            (e.period_index, e.amount_keur)
            for e in self.entries
            if e.entry_type == "distribution"
        )

    def __post_init__(self):
        for name, val in [
            ("total_contributed_keur", self.total_contributed_keur),
            ("total_distributions_keur", self.total_distributions_keur),
        ]:
            _finite_non_negative(val, name)
        _finite(self.net_contributed_keur, "net_contributed_keur")
        if self.final_balance_keur is not None:
            _finite(self.final_balance_keur, "final_balance_keur")  # may be negative in return phase

        # Reconcile totals with entries
        eps = 1e-6
        total_contrib = sum(e.amount_keur for e in self.entries if e.entry_type == "contribution")
        total_distrib = sum(e.amount_keur for e in self.entries if e.entry_type == "distribution")
        if abs(total_contrib - self.total_contributed_keur) > eps:
            raise ValueError(
                f"total_contributed_keur ({self.total_contributed_keur}) does not reconcile "
                f"with entries sum ({total_contrib:.6f})"
            )
        if abs(total_distrib - self.total_distributions_keur) > eps:
            raise ValueError(
                f"total_distributions_keur ({self.total_distributions_keur}) does not reconcile "
                f"with entries sum ({total_distrib:.6f})"
            )

        # Normalize metadata: validate and normalize all (key, value) pairs
        if isinstance(self.metadata, dict):
            items = tuple(sorted((str(k), _normalize(v)) for k, v in self.metadata.items()))
            object.__setattr__(self, "metadata", items)
        elif not isinstance(self.metadata, tuple):
            object.__setattr__(self, "metadata", tuple(self.metadata))
        else:
            # Validate every value in existing tuple pairs
            items = tuple(sorted((str(k), _normalize(v)) for k, v in self.metadata))
            object.__setattr__(self, "metadata", items)

        if not isinstance(self.notes, tuple):
            object.__setattr__(self, "notes", _to_tuple_str(self.notes))


_IMMUTABLE_JSON_SCALARS = (str, int, float, bool, type(None))


def _normalize(v: Any) -> Any:
    """Normalize a metadata value to an immutable JSON scalar.

    Rejects dict/list. Values must be one of: str, int, float, bool, None.
    Raises TypeError for list/dict/nested containers.
    """
    if isinstance(v, _IMMUTABLE_JSON_SCALARS):
        return v
    if isinstance(v, dict):
        raise TypeError(
            f"Metadata dict values not allowed; use flat tuple of (key, value) pairs. "
            f"Got dict with keys: {list(v.keys())}"
        )
    if isinstance(v, list):
        raise TypeError(
            f"Metadata list values not allowed; use tuple of (key, value) pairs. "
            f"Got list: {v!r}"
        )
    if isinstance(v, tuple):
        normalized = tuple(_normalize(x) for x in v)
        for x in normalized:
            if isinstance(x, (list, dict)):
                raise TypeError(
                    f"Metadata tuple must contain only JSON scalars, "
                    f"got nested container {type(x).__name__}"
                )
        return normalized
    raise TypeError(
        f"Metadata value must be a JSON scalar (str, int, float, bool, None), "
        f"got {type(v).__name__}: {v!r}"
    )