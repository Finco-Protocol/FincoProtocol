"""Phase 6A — Tax template inputs: CITTier, TaxDepreciationRule, TaxTemplate, TaxTemplateOverride."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ── CIT Tier ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CITTier:
    """Single CIT bracket for progressive tax systems.

    Attributes
    ----------
    min_profit_keur : float
        Lower bound of the profit range (inclusive). Must be >= 0.
    max_profit_keur : float | None
        Upper bound (exclusive). None represents unbounded (no ceiling).
        Must be > min_profit_keur if provided.
    tax_rate : float
        Effective tax rate for profits in this bracket.
        Must be between 0 and 1 (inclusive).

    Example
    -------
    Flat 10% CIT: CITTier(min_profit=0.0, max_profit=None, tax_rate=0.10)
    Progressive Generic Market A (0-500k: 10%, 500k+: 15%):
      - CITTier(min=0.0, max=500.0, tax_rate=0.10)
      - CITTier(min=500.0, max=None, tax_rate=0.15)
    """
    min_profit_keur: float
    max_profit_keur: Optional[float]
    tax_rate: float

    def __post_init__(self):
        if self.min_profit_keur < 0.0:
            raise ValueError(
                f"CITTier min_profit_keur must be >= 0, got {self.min_profit_keur}"
            )
        if not (0.0 <= self.tax_rate <= 1.0):
            raise ValueError(
                f"CITTier tax_rate must be between 0 and 1, got {self.tax_rate}"
            )
        if self.max_profit_keur is not None and self.max_profit_keur <= self.min_profit_keur:
            raise ValueError(
                f"CITTier max_profit_keur ({self.max_profit_keur}) must be > "
                f"min_profit_keur ({self.min_profit_keur})"
            )


# ── Depreciation Rule ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TaxDepreciationRule:
    """Depreciation rule for one asset category under a given tax regime.

    Supports straight-line, declining balance, capped depreciation, and
    non-deductible categories.

    Attributes
    ----------
    asset_category : str
        Identifier for the asset class (e.g., "buildings", "equipment",
        "vehicles", "intangibles"). Must be unique within a TaxTemplate.
    method : str
        Depreciation method. Common values:
        - "straight_line": equal annual deductions over useful life
        - "declining_balance": fixed percentage of remaining book value
        - "units_of_production": based on output units
        Acceptable values are not enforced here — invalid methods should
        be caught by a tax engine downstream.
    annual_rate : float | None
        Annual depreciation rate (decimal). For straight-line this is
        1 / useful_life_years. For declining balance this is the
        multiplicative rate (e.g., 0.25 for 25% DB). None when method
        is "units_of_production" or when rate is derived from useful_life.
    useful_life_years : float | None
        Expected economic life in years. Used to derive annual_rate when
        annual_rate is None. Accepts fractional years (e.g., 2.5).
    max_deductible_rate : float | None
        Cap on deductible portion (decimal). E.g., 0.025 means maximum
        2.5% of asset value can be deducted per year regardless of
        actual depreciation schedule. None = no cap.
    bonus_depreciation_pct : float
        One-time bonus deduction at period 0 as a fraction of cost
        (e.g., 0.20 = 20% bonus in year 1). 0.0 = no bonus.
    deductible : bool
        Whether this category is tax-deductible at all. False means
        no depreciation deduction is ever claimed even if annual_rate
        is set.
    notes : str
        Human-readable description of this rule (e.g., "20-year buildings,
        capped at 2.5% per year for Generic Market C").
    """
    asset_category: str
    method: str
    annual_rate: Optional[float]
    useful_life_years: Optional[float]
    max_deductible_rate: Optional[float]
    bonus_depreciation_pct: float
    deductible: bool
    notes: str

    def __post_init__(self):
        if self.max_deductible_rate is not None and self.max_deductible_rate < 0.0:
            raise ValueError(
                f"TaxDepreciationRule max_deductible_rate must be >= 0, "
                f"got {self.max_deductible_rate}"
            )
        if not (0.0 <= self.bonus_depreciation_pct <= 1.0):
            raise ValueError(
                f"TaxDepreciationRule bonus_depreciation_pct must be between 0 and 1, "
                f"got {self.bonus_depreciation_pct}"
            )


# ── Tax Template ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TaxTemplate:
    """Complete tax configuration template for one country and tax year.

    This is a declarative schema — no calculations are performed here.
    It defines the parameters that a downstream tax engine uses.

    Attributes
    ----------
    country_code : str
        Uppercase ISO 3166-1 alpha-2 country code (e.g., "XA", "XB", "XC").
    template_name : str
        Human-readable name (e.g., "Generic Market A Standard", "Generic Market C Infrastructure").
    tax_year : int
        Calendar year the template applies to.
    cit_tiers : tuple[CITTier, ...]
        CIT brackets. Empty tuple = no CIT configured (e.g., tax-exempt entity).
        Must have no overlapping profit ranges.
    depreciation_rules : tuple[TaxDepreciationRule, ...]
        Asset-category-specific depreciation rules. No two rules may share
        the same asset_category.
    withholding_tax_dividends : float
        WHT rate applied to dividend repatriation (decimal, 0-1).
        0.0 = no withholding on dividends.
    withholding_tax_interest : float
        WHT rate applied to interest payments (decimal, 0-1).
        0.0 = no withholding on interest.
    loss_carryforward_years : int | None
        Number of years tax losses can be carried forward. None = unlimited
        (subject to anti-abuse rules in the tax engine). 0 = no carryforward.
    thin_cap_ratio : float | None
        Thin capitalisation ratio limit (debt / equity ceiling). E.g., 4.0
        means debt cannot exceed 4x equity. None = no thin-cap limit.
    interest_limitation_pct_ebitda : float | None
        ATAD-style EBITDA-based interest limitation (decimal). E.g., 0.30
        means interest deduction limited to 30% of EBITDA. None = no limit.
    metadata : dict[str, str]
        Arbitrary key-value annotations (e.g., {"note": "illustrative only",
        "legal_ref": "ZI-2024"}). Not used by the tax engine directly.
    """
    country_code: str
    template_name: str
    tax_year: int
    cit_tiers: tuple[CITTier, ...] = ()
    depreciation_rules: tuple[TaxDepreciationRule, ...] = ()
    withholding_tax_dividends: float = 0.0
    withholding_tax_interest: float = 0.0
    loss_carryforward_years: Optional[int] = None
    thin_cap_ratio: Optional[float] = None
    interest_limitation_pct_ebitda: Optional[float] = None
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        # Country code: uppercase ISO-style
        if not self.country_code:
            raise ValueError("TaxTemplate country_code must be non-empty")
        if len(self.country_code) != 2:
            raise ValueError(
                f"TaxTemplate country_code must be 2 characters, got {self.country_code!r}"
            )
        if not self.country_code.isupper():
            raise ValueError(
                f"TaxTemplate country_code must be uppercase, got {self.country_code!r}"
            )

        # Tax rates in range
        if not (0.0 <= self.withholding_tax_dividends <= 1.0):
            raise ValueError(
                f"withholding_tax_dividends must be 0-1, got {self.withholding_tax_dividends}"
            )
        if not (0.0 <= self.withholding_tax_interest <= 1.0):
            raise ValueError(
                f"withholding_tax_interest must be 0-1, got {self.withholding_tax_interest}"
            )

        # No duplicate asset_category in depreciation_rules
        seen_categories: set[str] = set()
        for rule in self.depreciation_rules:
            if rule.asset_category in seen_categories:
                raise ValueError(
                    f"TaxTemplate depreciation_rules contains duplicate asset_category "
                    f"{rule.asset_category!r}"
                )
            seen_categories.add(rule.asset_category)

        # No overlapping CIT tiers + continuity / unbounded validation
        if self.cit_tiers:
            sorted_tiers = sorted(self.cit_tiers, key=lambda t: t.min_profit_keur)

            # First tier must start at 0.0
            if sorted_tiers[0].min_profit_keur != 0.0:
                raise ValueError(
                    f"CIT tiers must start at 0.0; first tier has "
                    f"min_profit_keur={sorted_tiers[0].min_profit_keur}"
                )

            unbounded_count = 0
            for i, tier in enumerate(sorted_tiers):
                # No overlapping ranges
                if i < len(sorted_tiers) - 1:
                    next_tier = sorted_tiers[i + 1]
                    if tier.max_profit_keur is not None and tier.max_profit_keur > next_tier.min_profit_keur:
                        raise ValueError(
                            f"CIT tiers overlap: {tier} and {next_tier}"
                        )
                    # Contiguous: next.min == current.max (exact match)
                    if tier.max_profit_keur is not None and tier.max_profit_keur != next_tier.min_profit_keur:
                        raise ValueError(
                            f"CIT tiers have gap: {tier} (max={tier.max_profit_keur}) "
                            f"vs next tier min={next_tier.min_profit_keur}"
                        )
                # Count unbounded tiers
                if tier.max_profit_keur is None:
                    unbounded_count += 1
                    # Unbounded tier must be last
                    if i != len(sorted_tiers) - 1:
                        raise ValueError(
                            f"CIT tier with unbounded max_profit_keur must be last; "
                            f"found at index {i} but {len(sorted_tiers)-1} tiers exist"
                        )

            # Only one unbounded tier allowed
            if unbounded_count > 1:
                raise ValueError(
                    f"Only one CIT tier may have unbounded max_profit_keur; "
                    f"found {unbounded_count} unbounded tiers"
                )

        # metadata as tuple of tuples (immutable)
        if not isinstance(self.metadata, tuple):
            object.__setattr__(
                self, 'metadata',
                tuple((str(k), str(v)) for k, v in (dict(self.metadata).items() if isinstance(self.metadata, dict) else self.metadata))
            )

    @property
    def metadata_dict(self) -> dict[str, str]:
        """Return metadata as a dict for convenience."""
        return dict(self.metadata)


# ── Template Override ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TaxTemplateOverride:
    """A single override applied to a TaxTemplate to produce a ResolvedTaxConfig.

    Represents an intentional modification of one template field, together
    with the reason for the change (audit trail). Overrides are stored in
    the ResolvedTaxConfig and can be inspected, serialized, or reversed.

    Attributes
    ----------
    override_name : str
        Short identifier (e.g., "custom_wht_2027", "relax_thin_cap").
    field_path : str
        Override target. Supports:
        - Top-level TaxTemplate fields (e.g., "withholding_tax_interest")
        - Metadata keys (e.g., "metadata.note")

        Phase 6A does NOT support arbitrary nested paths like "cit_tiers.0.tax_rate".
        Only "metadata.<key>" is accepted as a special metadata key override.

    override_value : object
        New value for the field. Type must match the field type or be
        coercible by the resolver.
    reason : str
        Human-readable justification (e.g., "Treaty rate between Generic Market A and Generic Market C",
        "User-specified override for special purpose vehicle").
    """
    override_name: str
    field_path: str
    override_value: object
    reason: str

    def __post_init__(self):
        if not self.field_path:
            raise ValueError("TaxTemplateOverride field_path must be non-empty")
        # Allow simple top-level fields OR metadata.<key> patterns
        if "." in self.field_path:
            if self.field_path.startswith("metadata."):
                key = self.field_path[len("metadata."):]
                if not key:
                    raise ValueError(
                        f"TaxTemplateOverride field_path 'metadata.' "
                        f"requires a non-empty key after the dot. "
                        f"Got: {self.field_path!r}"
                    )
            else:
                raise ValueError(
                    f"TaxTemplateOverride nested field_path '{self.field_path}' "
                    f"is not supported in Phase 6A. "
                    f"Only simple top-level fields and 'metadata.<key>' are allowed. "
                    f"Got: {self.field_path!r}"
                )


# ── Resolved Config ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ResolvedTaxConfig:
    """Immutable resolved tax configuration.

    Produced by ``resolve_tax_template()`` — applies overrides to a base
    TaxTemplate without mutating the original. Contains both the base
    template and the effective resolved template, plus metadata about
    how it was resolved.

    Attributes
    ----------
    base_template : TaxTemplate
        The original TaxTemplate (never mutated).
    resolved_template : TaxTemplate
        The effective TaxTemplate after applying all overrides.
        When no overrides are present, this equals base_template.
    overrides : tuple[TaxTemplateOverride, ...]
        All overrides applied, in order. Duplicate field paths resolve to
        the last override's value.
    resolved_metadata : tuple[tuple[str, str], ...]
        Combined metadata from base_template.metadata plus any override
        metadata changes. Override metadata takes priority on key conflict.
    """
    base_template: TaxTemplate
    resolved_template: TaxTemplate
    overrides: tuple[TaxTemplateOverride, ...] = ()
    resolved_metadata: tuple[tuple[str, str], ...] = ()

    @property
    def resolved_metadata_dict(self) -> dict[str, str]:
        """Return resolved metadata as a dict."""
        return dict(self.resolved_metadata)

    def __post_init__(self):
        if not isinstance(self.overrides, tuple):
            object.__setattr__(self, 'overrides', tuple(self.overrides))
        if not isinstance(self.resolved_metadata, tuple):
            object.__setattr__(
                self, 'resolved_metadata',
                tuple((str(k), str(v)) for k, v in
                      (dict(self.resolved_metadata).items() if isinstance(self.resolved_metadata, dict) else self.resolved_metadata))
            )
