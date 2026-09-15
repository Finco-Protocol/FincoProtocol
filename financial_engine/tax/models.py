"""financial_engine.tax.models — Immutable result types for Phase 2B tax.

All types are frozen dataclasses.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class TaxYearPeriodFragment:
    """One calendar-year slice of a model period.

    When a semi-annual period crosses 31 December, it is split into two
    fragments — one per calendar year.  All fragments of a period share
    the same ``source_period_index`` and their ``allocation_fraction`` values
    sum to 1.0.

    ``days`` uses the convention (frag_end − frag_start).days so that
    ``sum(f.days for f in fragments) == (period_end − period_start).days``.

    The allocated amount fields carry the period's amounts × allocation_fraction,
    so a year's basis totals can be derived purely by summing its fragments.
    """
    tax_year: int                  # calendar year, e.g. 2030
    source_period_index: int
    start_date: date
    end_date: date
    days: int                      # (end_date - start_date).days for this fragment
    source_period_days: int        # (period_end - period_start).days for the full source period
    allocation_fraction: float     # = days / source_period_days (last fragment adjusted for exact 1.0)
    # Pre-allocated amounts: period amount × allocation_fraction
    ebitda_keur: float
    tax_depreciation_keur: float
    total_interest_keur: float
    other_fiscal_reintegration_keur: float
    shl_tax_eligible_interest_keur: float = 0.0
    shl_non_deductible_interest_keur: float = 0.0
    # U2: Cash/reserve financing income — separate from EBITDA.
    # EBITDA = revenue - opex (unchanged). Financing income enters taxable income directly.
    financing_income_keur: float = 0.0


@dataclass(frozen=True)
class TaxYearCalculationBasis:
    """Aggregated annual inputs for one calendar tax year.

    ``tax_year`` is the 4-digit calendar year (e.g. 2030), not a model index.
    ``fragments`` carries the per-period fragments that contribute to this year;
    ``period_indices`` is the distinct set of source period indices.

    ``payment_period_index`` is the period_index to use for TAX_YEAR_LAST_PERIOD
    cash-tax assignment.  It is the period whose ``period_end`` falls within
    ``tax_year`` and has the latest chronological position.  This avoids
    assigning cash tax to periods that barely cross a year boundary (Dec 31
    start date = 1-day fragment in the previous year).
    """
    tax_year: int
    fragments: tuple[TaxYearPeriodFragment, ...]
    period_indices: tuple[int, ...]
    payment_period_index: int   # period that receives TAX_YEAR_LAST_PERIOD cash tax
    ebitda_keur: float
    tax_depreciation_keur: float
    total_interest_keur: float
    other_fiscal_reintegration_keur: float
    shl_tax_eligible_interest_keur: float = 0.0
    shl_non_deductible_interest_keur: float = 0.0
    # U2: Cash/reserve financing income per tax year. Separate from EBITDA.
    financing_income_keur: float = 0.0


@dataclass(frozen=True)
class AtadAnnualResult:
    """ATAD result for one tax year, with per-period allocation."""
    tax_year: int
    total_interest_keur: float
    deduction_capacity_keur: float
    deductible_interest_keur: float
    disallowed_interest_keur: float
    binding_rule: str  # "ebitda_30pct" | "min_threshold" | "disabled"
    # Per-period allocation in chronological order (same length as basis.period_indices)
    period_deductible_keur: tuple[float, ...]
    period_disallowed_keur: tuple[float, ...]


@dataclass(frozen=True)
class TaxLossVintage:
    """One loss vintage and its lifecycle within a single tax year.

    A new instance is produced for each (vintage, year) pair by the ledger.
    The reconciliation identity holds per vintage:

        closing_keur = opening_keur + generated_keur − used_keur − expired_keur
    """
    vintage_id: str               # stable identifier across years
    origin_tax_year: int          # calendar year the loss was generated
    last_usable_tax_year: int     # last calendar year in which it may be used
    opening_keur: float           # balance at start of this tax year
    generated_keur: float         # new loss created this year (0 unless origin == this year)
    used_keur: float              # amount absorbed against taxable income
    expired_keur: float           # amount that lapsed (last_usable < this year)
    closing_keur: float           # balance at end of year
    source_label: str             # human-readable origin description


@dataclass(frozen=True)
class TaxAnnualLedgerEntry:
    """Full vintage-level loss ledger for one tax year.

    Aggregate reconciliation:
        opening_loss_pre_expiry_keur
        + loss_generated_keur
        − loss_used_keur
        − loss_expired_keur
        == closing_loss_keur
    """
    tax_year: int
    # Vintage snapshots
    opening_vintages: tuple[TaxLossVintage, ...]
    expired_vintages: tuple[TaxLossVintage, ...]
    used_vintages: tuple[TaxLossVintage, ...]
    generated_vintages: tuple[TaxLossVintage, ...]
    closing_vintages: tuple[TaxLossVintage, ...]
    # Scalar aggregates (derived from vintage tuples for convenience)
    opening_loss_pre_expiry_keur: float
    loss_expired_keur: float
    loss_used_keur: float
    loss_generated_keur: float
    closing_loss_keur: float
    # Taxable income
    taxable_income_before_lcf_keur: float
    taxable_income_after_lcf_keur: float


@dataclass(frozen=True)
class TaxAnnualResult:
    """Full tax result for one tax year."""
    tax_year: int
    period_indices: tuple[int, ...]
    # ATAD
    total_interest_keur: float
    deduction_capacity_keur: float
    deductible_interest_keur: float
    disallowed_interest_keur: float
    atad_binding_rule: str
    # Taxable income
    ebitda_keur: float
    tax_depreciation_keur: float
    other_fiscal_reintegration_keur: float
    taxable_income_before_lcf_keur: float
    # LCF (aggregate scalars for fast access)
    loss_opening_keur: float
    loss_expired_keur: float
    loss_used_keur: float
    loss_generated_keur: float
    loss_closing_keur: float
    taxable_income_after_lcf_keur: float
    # LCF vintage detail
    ledger_entry: TaxAnnualLedgerEntry
    # CIT
    current_tax_liability_keur: float
    # Per-period ATAD allocation (same length as period_indices)
    period_atad_deductible: tuple[float, ...]
    period_atad_disallowed: tuple[float, ...]
    # U2: Cash/reserve financing income for this tax year. Below EBITDA.
    financing_income_keur: float = 0.0


@dataclass(frozen=True)
class PeriodTaxYearAllocation:
    """Per-calendar-year allocation share for one model period.

    A cross-year period produces one instance per calendar year it spans.
    ``cit_accrual_keur`` is the period's proportional share of that year's CIT
    liability (annual CIT × allocation_fraction).  It is an accrual figure, NOT
    the cash payment date — cash timing is determined by the period-level
    ``cash_tax_keur`` field on ``PeriodCashTaxResult``.
    """
    tax_year: int
    allocation_fraction: float
    ebitda_keur: float
    deductible_interest_keur: float
    disallowed_interest_keur: float
    other_fiscal_reintegration_keur: float
    shl_tax_eligible_interest_keur: float
    shl_non_deductible_interest_keur: float
    taxable_income_share_keur: float
    cit_accrual_keur: float
    financing_income_keur: float = 0.0


@dataclass(frozen=True)
class PeriodCashTaxResult:
    """Cash tax payment assignment for one model period.

    ``primary_tax_year`` is the calendar year with the largest allocation
    fraction (display-only; must not control any calculation).
    ``tax_year_allocations`` carries the per-year accrual contract; cross-year
    periods have len > 1.
    ``cash_tax_keur`` is the actual cash outflow in this period (determined by
    the configured cash timing rule — TAX_YEAR_LAST_PERIOD or SAME_PERIOD).
    """
    period_index: int
    is_operation: bool
    ebitda_keur: float
    primary_tax_year: int            # display-only: year with largest allocation fraction
    tax_year_allocations: tuple[PeriodTaxYearAllocation, ...]
    # Aggregate convenience fields (sum over all years)
    deductible_interest_keur: float
    disallowed_interest_keur: float
    other_fiscal_reintegration_keur: float
    taxable_income_before_lcf_share_keur: float
    cit_accrual_share_keur: float
    cash_tax_keur: float             # actual cash payment in this period
    shl_tax_eligible_interest_keur: float = 0.0
    shl_non_deductible_interest_keur: float = 0.0
    capitalisation_ratio: float | None = None
    capitalisation_gate_active: bool | None = None
    shl_absolute_limit_component_keur: float = 0.0
    shl_ebitda_limit_component_keur: float = 0.0
    shl_additional_non_deductible_component_keur: float = 0.0
    # U2: Cash/reserve financing income for this period. Below EBITDA.
    financing_income_keur: float = 0.0


@dataclass(frozen=True)
class TaxAndCfadsResult:
    """Complete Phase 2B tax and CFADS result."""
    annual_results: tuple[TaxAnnualResult, ...]
    period_results: tuple[PeriodCashTaxResult, ...]
    terminal_unpaid_tax_keur: float
