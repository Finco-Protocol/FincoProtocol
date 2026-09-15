"""Phase 6C.1 — HoldCo / intercompany tax result models.

Schema only — no active calculation, no waterfall wiring.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import math


__all__ = [
    "HoldCoTaxPeriodResult",
    "HoldCoTaxResult",
]


# ── Validation helpers ────────────────────────────────────────────────────────

def _non_negative(value: float, name: str) -> None:
    if value < 0.0:
        raise ValueError(f"{name} must be non-negative, got {value}")


def _no_nan_inf(value: float, name: str) -> None:
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"{name} must not be NaN or Inf, got {value}")


def _non_empty(value: str, name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{name} must be non-empty, got {value!r}")


def _to_tuple_str(value) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    if isinstance(value, tuple):
        return tuple(str(v) for v in value)
    return (str(value),)


# ── HoldCoTaxPeriodResult ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class HoldCoTaxPeriodResult:
    """Audit-ready per-period result for HoldCo tax.

    Stores all income components and WHT fields — no active CIT calculation.

    Attributes
    ----------
    period_index : int
        Period index (0-based). Must be >= 0.
    taxable_dividend_income_keur : float
        Dividend income subject to CIT (gross, before WHT). Must be >= 0.
    taxable_interest_income_keur : float
        SHL interest income subject to CIT. Must be >= 0.
    non_taxable_principal_keur : float
        SHL principal — tracked as non-taxable recovery of investment.
        Must be >= 0.
    deductible_opex_keur : float
        Deductible operating expenses for the period. Must be >= 0.
    taxable_income_before_limitations_keur : float
        Pre-thin-cap/EBITDA-limit taxable income.
    withholding_tax_dividends_keur : float
        WHT withheld on dividends at applicable rate. Must be >= 0.
    withholding_tax_interest_keur : float
        WHT withheld on interest at applicable rate. Must be >= 0.
    interest_limited_keur : float
        Excess interest over EBITDA limitation (ATAD). Must be >= 0.
    notes : tuple[str, ...]
        Audit notes (e.g., "SHL principal excluded from taxable income").
        Stored as tuple — list input is normalized.
    warnings : tuple[str, ...]
        Warnings for review (e.g., "thin-cap exceeded in period 3").
        Stored as tuple — list input is normalized.
    """
    period_index: int
    taxable_dividend_income_keur: float
    taxable_interest_income_keur: float
    non_taxable_principal_keur: float
    deductible_opex_keur: float
    taxable_income_before_limitations_keur: float
    withholding_tax_dividends_keur: float
    withholding_tax_interest_keur: float
    interest_limited_keur: float
    notes: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if self.period_index < 0:
            raise ValueError(
                f"period_index must be >= 0, got {self.period_index}"
            )
        for name, val in [
            ("taxable_dividend_income_keur", self.taxable_dividend_income_keur),
            ("taxable_interest_income_keur", self.taxable_interest_income_keur),
            ("non_taxable_principal_keur", self.non_taxable_principal_keur),
            ("deductible_opex_keur", self.deductible_opex_keur),
            ("taxable_income_before_limitations_keur", self.taxable_income_before_limitations_keur),
            ("withholding_tax_dividends_keur", self.withholding_tax_dividends_keur),
            ("withholding_tax_interest_keur", self.withholding_tax_interest_keur),
            ("interest_limited_keur", self.interest_limited_keur),
        ]:
            _non_negative(val, name)
            _no_nan_inf(val, name)

        # Normalize notes/warnings to tuple
        if not isinstance(self.notes, tuple):
            object.__setattr__(self, "notes", _to_tuple_str(self.notes))
        if not isinstance(self.warnings, tuple):
            object.__setattr__(self, "warnings", _to_tuple_str(self.warnings))


# ── HoldCoTaxResult ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HoldCoTaxResult:
    """Complete HoldCo tax result across all periods.

    Schema only — no active CIT calculation.

    Attributes
    ----------
    entity_code : str
        HoldCo entity identifier. Must be non-empty.
    country_code : str
        HoldCo tax jurisdiction. Must be non-empty.
    tax_year : int
        Tax year (between 2000 and 2100).
    period_results : tuple[HoldCoTaxPeriodResult, ...]
        Per-period breakdown.
    total_taxable_dividend_keur : float
        Sum of all taxable dividend income. Must be >= 0, no NaN/inf.
    total_taxable_interest_keur : float
        Sum of all taxable interest income. Must be >= 0, no NaN/inf.
    total_non_taxable_principal_keur : float
        Sum of all SHL principal (non-taxable). Must be >= 0, no NaN/inf.
    total_withholding_tax_dividends_keur : float
        Total WHT on dividends (stored, not paid). Must be >= 0, no NaN/inf.
    total_withholding_tax_interest_keur : float
        Total WHT on interest (stored, not paid). Must be >= 0, no NaN/inf.
    metadata : tuple[tuple[str, str], ...]
        Key-value metadata pairs as tuple of 2-tuples.
        Dict input is normalized on construction.
    notes : tuple[str, ...]
        Top-level audit notes. Stored as tuple — list input is normalized.
    """
    entity_code: str
    country_code: str
    tax_year: int
    period_results: tuple[HoldCoTaxPeriodResult, ...]
    total_taxable_dividend_keur: float
    total_taxable_interest_keur: float
    total_non_taxable_principal_keur: float
    total_withholding_tax_dividends_keur: float
    total_withholding_tax_interest_keur: float
    metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def metadata_dict(self) -> dict[str, str]:
        """Metadata as a dict for convenience."""
        return dict(self.metadata)

    def __post_init__(self):
        _non_empty(self.entity_code, "entity_code")
        _non_empty(self.country_code, "country_code")
        if not (2000 <= self.tax_year <= 2100):
            raise ValueError(f"tax_year must be between 2000 and 2100, got {self.tax_year}")

        for name, val in [
            ("total_taxable_dividend_keur", self.total_taxable_dividend_keur),
            ("total_taxable_interest_keur", self.total_taxable_interest_keur),
            ("total_non_taxable_principal_keur", self.total_non_taxable_principal_keur),
            ("total_withholding_tax_dividends_keur", self.total_withholding_tax_dividends_keur),
            ("total_withholding_tax_interest_keur", self.total_withholding_tax_interest_keur),
        ]:
            _non_negative(val, name)
            _no_nan_inf(val, name)

        # Reconcile totals against period_results (within 1e-6 tolerance)
        eps = 1e-6
        for total_name, period_field in [
            ("total_taxable_dividend_keur", "taxable_dividend_income_keur"),
            ("total_taxable_interest_keur", "taxable_interest_income_keur"),
            ("total_non_taxable_principal_keur", "non_taxable_principal_keur"),
            ("total_withholding_tax_dividends_keur", "withholding_tax_dividends_keur"),
            ("total_withholding_tax_interest_keur", "withholding_tax_interest_keur"),
        ]:
            expected = sum(getattr(p, period_field) for p in self.period_results)
            actual = getattr(self, total_name)
            if abs(expected - actual) > eps:
                raise ValueError(
                    f"{total_name} ({actual}) does not reconcile with "
                    f"period_results sum ({expected}); diff={abs(expected - actual):.2e}"
                )

        # Normalize metadata: dict -> tuple[tuple[str, str], ...]
        if isinstance(self.metadata, dict):
            object.__setattr__(
                self,
                "metadata",
                tuple((str(k), str(v)) for k, v in self.metadata.items()),
            )
        elif not isinstance(self.metadata, tuple):
            object.__setattr__(self, "metadata", tuple(self.metadata))

        # Normalize notes to tuple
        if not isinstance(self.notes, tuple):
            object.__setattr__(self, "notes", _to_tuple_str(self.notes))