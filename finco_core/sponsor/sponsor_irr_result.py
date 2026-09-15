"""Phase 7B — Sponsor IRR & MOIC result schemas.

Immutable, audit-safe result structures for sponsor-level IRR and MOIC.
All IRR outputs are computed from immutable SponsorCashflowResult inputs only.
Deterministic. No mutation. No hidden state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "SponsorIrrResult",
    "SponsorMoicResult",
]


# ── Validation helpers ────────────────────────────────────────────────────────

def _finite(value: float, name: str) -> None:
    """Raise if value is NaN or Inf."""
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be float, got {type(value).__name__}")
    import math as _math

    if _math.isnan(value) or _math.isinf(value):
        raise ValueError(f"{name} must be finite, got {value}")


def _non_negative(value: float, name: str) -> None:
    """Raise if value is negative or non-finite."""
    _finite(value, name)
    if value < 0.0:
        raise ValueError(f"{name} must be >= 0, got {value}")


def _positive(value: float, name: str) -> None:
    """Raise if value is not strictly positive."""
    _finite(value, name)
    if value <= 0.0:
        raise ValueError(f"{name} must be > 0, got {value}")


def _non_empty_str(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string, got {value!r}")


# ── SponsorIrrResult ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SponsorIrrResult:
    """Immutable sponsor IRR result.

    Consumed by downstream waterfall, reporting, and multi-investor
    allocation engines. Designed for audit trail and golden validation.

    Attributes
    ----------
    investor_id : str
        Sponsor/investor identifier (e.g., "SPONSOR-1").
    gross_sponsor_irr : float | None
        Gross IRR (no fees/carry deducted). None if XIRR did not converge
        or there is no sign change in cashflows.
    net_sponsor_irr_placeholder : float | None
        Net IRR placeholder for future carry/preferred-return deduction.
        Currently always None (not yet implemented). Kept for schema
        compatibility with future waterfall engine.
    xirr_converged : bool
        True if XIRR solver converged within tolerance; False otherwise.
    xirr_iterations : int
        Number of iterations the XIRR solver used. 0 if not attempted.
    xirr_tolerance : float
        Convergence tolerance used (relative rate change).
    audit_note : str
        Fixed audit note confirming read-only governance artifact.
    metadata : tuple[tuple[str, Any], ...]
        Key-value metadata as frozen sorted tuple of JSON-serializable pairs.
    notes : tuple[str, ...]
        Human-readable notes (convergence warnings, edge-case flags).
    """
    investor_id: str
    gross_sponsor_irr: float | None
    net_sponsor_irr_placeholder: float | None = None
    xirr_converged: bool = False
    xirr_iterations: int = 0
    xirr_tolerance: float = 1e-7
    audit_note: str = "AUDIT-ONLY: sponsor IRR result — read-only governance artifact, not a distribution commitment"
    metadata: tuple[tuple[str, Any], ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        _non_empty_str(self.investor_id, "investor_id")
        if self.gross_sponsor_irr is not None:
            _finite(self.gross_sponsor_irr, "gross_sponsor_irr")
        if self.net_sponsor_irr_placeholder is not None:
            _finite(self.net_sponsor_irr_placeholder, "net_sponsor_irr_placeholder")
        if self.xirr_iterations < 0:
            raise ValueError(f"xirr_iterations must be >= 0, got {self.xirr_iterations}")
        if self.xirr_tolerance <= 0.0:
            raise ValueError(f"xirr_tolerance must be > 0, got {self.xirr_tolerance}")
        # Validate metadata as flat tuple of (key, value) pairs
        if not isinstance(self.metadata, tuple):
            object.__setattr__(self, "metadata", tuple(self.metadata))
        for k, v in self.metadata:
            if not isinstance(k, str):
                raise TypeError(f"metadata keys must be str, got {type(k).__name__}")
        # Normalize notes
        if not isinstance(self.notes, tuple):
            object.__setattr__(self, "notes", tuple(str(n) for n in (
                self.notes if isinstance(self.notes, (list, tuple)) else [self.notes]
            )))

    @property
    def gross_irr_percent(self) -> float | None:
        """Gross IRR expressed as percentage (e.g., 11.5 for 11.5%)."""
        if self.gross_sponsor_irr is None:
            return None
        return self.gross_sponsor_irr * 100.0

    @property
    def metadata_dict(self) -> dict[str, Any]:
        """Return metadata as a plain dict."""
        return dict(self.metadata)


# ── SponsorMoicResult ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SponsorMoicResult:
    """Immutable sponsor MOIC (Multiple on Invested Capital) result.

    MOIC = total_distributions_received / total_equity_injected.

    Attributes
    ----------
    investor_id : str
        Sponsor/investor identifier.
    gross_sponsor_moic : float | None
        Gross MOIC (distributions / injections). None if total injections
        are zero or negative (no meaningful MOIC).
    total_equity_injected_keur : float
        Sum of all equity injections (kEUR). Always >= 0.
    total_distributions_received_keur : float
        Sum of all distributions received (kEUR). Always >= 0.
    net_multiple_placeholder : float | None
        Net MOIC placeholder for future carry/preferred-return deduction.
        Currently always None. Kept for future waterfall compatibility.
    audit_note : str
        Fixed audit note.
    metadata : tuple[tuple[str, Any], ...]
        Key-value metadata as frozen sorted tuple.
    notes : tuple[str, ...]
        Human-readable notes.
    """
    investor_id: str
    gross_sponsor_moic: float | None
    total_equity_injected_keur: float
    total_distributions_received_keur: float
    net_multiple_placeholder: float | None = None
    audit_note: str = "AUDIT-ONLY: sponsor MOIC result — read-only governance artifact, not a distribution commitment"
    metadata: tuple[tuple[str, Any], ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        _non_empty_str(self.investor_id, "investor_id")
        _non_negative(self.total_equity_injected_keur, "total_equity_injected_keur")
        _non_negative(self.total_distributions_received_keur, "total_distributions_received_keur")
        if self.gross_sponsor_moic is not None:
            _positive(self.gross_sponsor_moic, "gross_sponsor_moic")
        if self.net_multiple_placeholder is not None:
            _finite(self.net_multiple_placeholder, "net_multiple_placeholder")
        # Validate metadata
        if not isinstance(self.metadata, tuple):
            object.__setattr__(self, "metadata", tuple(self.metadata))
        for k, v in self.metadata:
            if not isinstance(k, str):
                raise TypeError(f"metadata keys must be str, got {type(k).__name__}")
        # Normalize notes
        if not isinstance(self.notes, tuple):
            object.__setattr__(self, "notes", tuple(str(n) for n in (
                self.notes if isinstance(self.notes, (list, tuple)) else [self.notes]
            )))

    @property
    def metadata_dict(self) -> dict[str, Any]:
        return dict(self.metadata)

    @property
    def multiple_expressed(self) -> str:
        """Human-readable MOIC string (e.g., "1.45x")."""
        if self.gross_sponsor_moic is None:
            return "N/A"
        return f"{self.gross_sponsor_moic:.2f}x"