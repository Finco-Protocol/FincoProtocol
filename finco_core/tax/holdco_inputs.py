"""Phase 6C.1 — HoldCo / intercompany tax input models.

Schema only — no active calculation, no waterfall wiring.

CAVEAT: These are pure input containers. No CIT calculation,
no WHT engine, no deferred tax accounting.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import math


__all__ = [
    "HoldCoTaxInputs",
    "IntercompanyTaxFlow",
    "WithholdingTaxConfig",
    "InterestDeductibilityConfig",
]


# ── Validation helpers ────────────────────────────────────────────────────────

def _non_empty(value: str, name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{name} must be non-empty, got {value!r}")


def _rate_in_0_1(value: float, name: str) -> None:
    if not (0.0 <= value <= 1.0):
        raise ValueError(f"{name} must be between 0 and 1, got {value}")


def _non_negative(value: float, name: str) -> None:
    if value < 0.0:
        raise ValueError(f"{name} must be non-negative, got {value}")


def _no_nan_inf(value: float, name: str) -> None:
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"{name} must not be NaN or Inf, got {value}")


# ── WithholdingTaxConfig ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class WithholdingTaxConfig:
    """WHT configuration for a HoldCo entity.

    Stores WHT rates but does NOT apply them — calculation is future Phase 6C.2.

    Attributes
    ----------
    rate_dividends : float
        WHT rate on dividend receipts. Between 0 and 1.
    rate_interest : float
        WHT rate on interest receipts. Between 0 and 1.
    notes : str | None
        Optional note, e.g. "EU Parent-Subsidiary exemption applies".
    """
    rate_dividends: float
    rate_interest: float
    notes: Optional[str] = None

    def __post_init__(self):
        _rate_in_0_1(self.rate_dividends, "rate_dividends")
        _rate_in_0_1(self.rate_interest, "rate_interest")


# ── InterestDeductibilityConfig ────────────────────────────────────────────────

@dataclass(frozen=True)
class InterestDeductibilityConfig:
    """Interest deductibility limitation configuration.

    Stores thin-cap ratio and EBITDA limitation percentage but does NOT
    apply them — calculation is future Phase 6C.2.

    Attributes
    ----------
    thin_cap_ratio : float | None
        Debt-to-equity ratio above which interest is non-deductible (e.g., 4.0).
        None = no thin-cap rule applies.
    interest_limitation_pct_ebitda : float | None
        Fraction of EBITDA to which net interest is limited (ATAD rule).
        None = no EBITDA limitation (unlimited deductibility).
    notes : str | None
        Optional note.
    """
    thin_cap_ratio: Optional[float] = None
    interest_limitation_pct_ebitda: Optional[float] = None
    notes: Optional[str] = None

    def __post_init__(self):
        if self.thin_cap_ratio is not None and self.thin_cap_ratio <= 0.0:
            raise ValueError(f"thin_cap_ratio must be positive, got {self.thin_cap_ratio}")
        if (self.interest_limitation_pct_ebitda is not None
                and not (0.0 <= self.interest_limitation_pct_ebitda <= 1.0)):
            raise ValueError(
                f"interest_limitation_pct_ebitda must be between 0 and 1, "
                f"got {self.interest_limitation_pct_ebitda}"
            )


# ── IntercompanyTaxFlow ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class IntercompanyTaxFlow:
    """Single intercompany cash flow with WHT configuration.

    Models a dividend or interest payment from SPV to HoldCo, with
    applicable WHT rates stored (not yet applied).

    Attributes
    ----------
    period_index : int
        Period index (0-based). Must be >= 0.
    flow_type : str
        "dividend" or "interest".
    gross_amount_keur : float
        Gross amount before WHT. Must be >= 0, no NaN/inf.
    withholding_tax_rate : float
        Applicable WHT rate (0 = no WHT). Must be in [0, 1], no NaN/inf.
    country_of_origin : str
        ISO country code of the paying entity (for WHT treaty lookup).
        Must be non-empty (whitespace stripped).
    notes : str | None
        Optional note.
    """
    period_index: int
    flow_type: str  # "dividend" | "interest"
    gross_amount_keur: float
    withholding_tax_rate: float
    country_of_origin: str
    notes: Optional[str] = None

    def __post_init__(self):
        if self.period_index < 0:
            raise ValueError(
                f"period_index must be >= 0, got {self.period_index}"
            )
        if self.flow_type not in ("dividend", "interest"):
            raise ValueError(f"flow_type must be 'dividend' or 'interest', got {self.flow_type!r}")
        _non_negative(self.gross_amount_keur, "gross_amount_keur")
        _no_nan_inf(self.gross_amount_keur, "gross_amount_keur")
        _rate_in_0_1(self.withholding_tax_rate, "withholding_tax_rate")
        _no_nan_inf(self.withholding_tax_rate, "withholding_tax_rate")
        _non_empty(self.country_of_origin, "country_of_origin")


# ── HoldCoTaxInputs ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HoldCoTaxInputs:
    """Complete inputs for future HoldCo tax engine.

    Schema only — no active calculation.

    All amounts in kEUR. Income fields are per-period tuples.
    Principal receipts are tracked separately as non-taxable.

    Attributes
    ----------
    entity_code : str
        HoldCo entity identifier. Must be non-empty.
    country_code : str
        ISO country code for HoldCo's tax jurisdiction.
    tax_year : int
        Tax year (e.g., 2026).
    dividend_income_by_period_keur : tuple[float, ...]
        Dividend receipts per period in kEUR. Non-negative.
    shl_interest_income_by_period_keur : tuple[float, ...]
        SHL interest income per period in kEUR. Non-negative.
    shl_principal_received_by_period_keur : tuple[float, ...]
        SHL principal repayments received per period in kEUR.
        Principal is NOT taxable income — tracked separately.
    holdco_opex_by_period_keur : tuple[float, ...]
        HoldCo operating expenses per period in kEUR.
    withholding_tax_config : WithholdingTaxConfig
        WHT rates on dividends and interest receipts.
    interest_deductibility : InterestDeductibilityConfig
        Thin-cap and EBITDA limitation parameters.
    metadata : tuple[tuple[str, str], ...]
        Key-value metadata pairs as tuple of 2-tuples (immutable).
        Accepts dict on input — normalized to tuple in __post_init__.
        Use metadata_dict property for dict-style access.
    """
    entity_code: str
    country_code: str
    tax_year: int
    dividend_income_by_period_keur: tuple[float, ...]
    shl_interest_income_by_period_keur: tuple[float, ...]
    shl_principal_received_by_period_keur: tuple[float, ...]
    holdco_opex_by_period_keur: tuple[float, ...]
    withholding_tax_config: WithholdingTaxConfig
    interest_deductibility: InterestDeductibilityConfig
    metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def metadata_dict(self) -> dict[str, str]:
        """Metadata as a dict for convenience."""
        return dict(self.metadata)

    def __post_init__(self):
        _non_empty(self.entity_code, "entity_code")
        _non_empty(self.country_code, "country_code")
        if not (2000 <= self.tax_year <= 2100):
            raise ValueError(f"tax_year must be between 2000 and 2100, got {self.tax_year}")

        for name, values in [
            ("dividend_income_by_period_keur", self.dividend_income_by_period_keur),
            ("shl_interest_income_by_period_keur", self.shl_interest_income_by_period_keur),
            ("shl_principal_received_by_period_keur", self.shl_principal_received_by_period_keur),
            ("holdco_opex_by_period_keur", self.holdco_opex_by_period_keur),
        ]:
            for i, v in enumerate(values):
                if v < 0.0:
                    raise ValueError(f"{name}[{i}] must be non-negative, got {v}")

        n = len(self.dividend_income_by_period_keur)
        for name, values in [
            ("shl_interest_income_by_period_keur", self.shl_interest_income_by_period_keur),
            ("shl_principal_received_by_period_keur", self.shl_principal_received_by_period_keur),
            ("holdco_opex_by_period_keur", self.holdco_opex_by_period_keur),
        ]:
            if len(values) != n:
                raise ValueError(
                    f"{name} length ({len(values)}) must match "
                    f"dividend_income_by_period_keur length ({n})"
                )

        # Negative principal is rejected — principal is not taxable income
        for i, v in enumerate(self.shl_principal_received_by_period_keur):
            if v < 0.0:
                raise ValueError(
                    f"shl_principal_received_by_period_keur[{i}] must be non-negative "
                    f"(principal repayment received), got {v}"
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