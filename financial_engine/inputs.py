"""
financial_engine.inputs — Immutable input contracts (Phase 2A + 2B).

All types are frozen dataclasses. No mutable state.
No imports from app, finco_core, fastapi, jinja2, requests, openpyxl, pandas.
No file I/O. No project-name dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import TYPE_CHECKING, Any

from financial_engine.ppa_indexation import PpaIndexationStartPolicy
from financial_engine.shl.contracts import ShlRepaymentMode
from finco_core.inputs._models import ShlConstructionInterestMethod
from financial_engine.shl.construction import ShlConstructionPeriodInput

if TYPE_CHECKING:
    from financial_engine.policies.tax import TaxPolicy
    from finco_core.opex.hierarchical import OpexModelInput


class YieldScenario(str, Enum):
    P50 = "P_50"
    P90_10Y = "P90-10y"


class PeriodAxisConvention(str, Enum):
    """Clean-engine calendar convention selected by explicit input metadata."""
    COD_ANCHOR_TWO_CONSTRUCTION_COLUMNS = "cod_anchor_two_construction_columns"
    OPERATING_BOUNDARY_SINGLE_CONSTRUCTION_COLUMN = "operating_boundary_single_construction_column"


@dataclass(frozen=True)
class CalendarInput:
    financial_close: date
    construction_months: int
    horizon_years: int
    ppa_years: float
    cod_date: date | None = None
    period_axis_convention: PeriodAxisConvention = (
        PeriodAxisConvention.COD_ANCHOR_TWO_CONSTRUCTION_COLUMNS
    )


@dataclass(frozen=True)
class TechnicalInput:
    capacity_mw: float
    yield_scenario: YieldScenario
    operating_hours_p50: float
    operating_hours_p90_10y: float
    pv_degradation: float
    plant_availability: float
    grid_availability: float


@dataclass(frozen=True)
class RevenueInput:
    ppa_base_tariff_eur_mwh: float
    ppa_term_years: float
    ppa_index: float
    ppa_production_share: float
    market_prices_curve_eur_mwh: tuple[float, ...]
    market_inflation: float
    balancing_cost_pv_fraction: float
    balancing_cost_wind_eur_mwh: float
    co2_enabled: bool
    co2_price_eur_mwh: float
    first_merchant_operating_period_index: int | None = None
    co2_price_semiannual_eur_mwh: tuple[float, ...] = ()
    co2_price_eur_per_mwh_scalar: float = 0.0
    balancing_cost_eur_per_mwh: float = 0.0
    # PPA indexation policy — explicit timing convention chosen for this project.
    # None = not yet explicitly migrated; the legacy tariff_at_year path is preserved.
    # None is a migration state, not a financial policy assumption.
    ppa_indexation_start_policy: PpaIndexationStartPolicy | None = None
    # Required only for CONTRACT_ANNIVERSARY; raises ValueError if None when that policy is used.
    ppa_indexation_start_date: date | None = None
    # Calendar-year merchant price schedule (matches Excel CF row 30 / Inputs row 106).
    # When supplied, the orchestrator passes these through to RevenueParams instead of
    # market_prices_curve_eur_mwh.  market_inflation is NOT re-applied.
    merchant_price_calendar_start_year: int | None = None
    merchant_prices_by_calendar_year_eur_mwh: tuple[float, ...] = ()


@dataclass(frozen=True)
class OpexLineInput:
    name: str
    y1_amount_keur: float
    annual_inflation: float
    step_changes: tuple[tuple[int, float], ...]
    percentage_of_opex: float


@dataclass(frozen=True)
class OpexInput:
    items: tuple[OpexLineInput, ...]
    # Hierarchical OPEX capability — present when the source project carries a
    # HierarchicalOpexCapability.  None = flat-item path (default, backward-compatible).
    # TYPE_CHECKING import only; no runtime finco_core dependency at import time.
    hierarchical_model: "OpexModelInput | None" = None
    hierarchical_external_annual_series: "tuple[tuple[str, tuple[float, ...]], ...]" = ()
    # Senior debt tenor in years — required when hierarchical_model is present (OPEX004),
    # ignored for flat projects. Explicit field decouples OPEX activation from the
    # depreciation contract (financial_cost_useful_life_years is a different concept).
    senior_debt_tenor_years: "int | None" = None


@dataclass(frozen=True)
class CapexItemForDep:
    """Minimal capex item description for straight-line depreciation."""
    name: str
    amount_keur: float
    asset_class_code: str  # e.g. "civil_grid", "solar_panels", "financial_costs"
    useful_life_override: int | None = None


@dataclass(frozen=True)
class DepreciationInput:
    """CAPEX items for straight-line depreciation — book and tax treated separately.

    All fields are required — no defaults.

    book_capex_items_for_depreciation:
        Items entering the BOOK depreciable basis. Includes hard capex plus
        capitalised bank financing costs (IDC, commitment fees, bank fees, VAT)
        where Excel Dep-sheet evidence confirms these are depreciated.

    tax_capex_items_for_depreciation:
        Items entering the TAX depreciable basis. Currently hard capex only.
        Tax treatment of capitalised financing costs is OPEN — each item
        requires separate authoritative tax-source evidence before inclusion.

    financial_cost_useful_life_years:
        Amortization period for items with asset_class_code == "financial_costs".
        Mapped from financing.senior_tenor_years in the adapter.
        OPEN: Excel Dep-sheet formula for useful life is unverified from
        data_only extraction. Do not tune to eliminate delta.
    """
    book_capex_items_for_depreciation: tuple[CapexItemForDep, ...]
    tax_capex_items_for_depreciation: tuple[CapexItemForDep, ...]
    financial_cost_useful_life_years: int


# ---------------------------------------------------------------------------
# Phase 2B tax input contracts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OpeningTaxLossVintageInput:
    """One pre-existing loss vintage carried into the model start.

    origin_tax_year : calendar tax year in which the loss was generated.
        Synthetic unit tests may use an internally consistent integer axis, but
        production adapters supply four-digit calendar years.
    amount_keur : outstanding loss (must be non-negative and finite)
    source_label : optional human-readable label for audit trail
    """
    origin_tax_year: int
    amount_keur: float
    source_label: str = ""

    def __post_init__(self) -> None:
        import math as _math
        import numbers as _numbers
        # origin_tax_year: must be int, not bool
        if isinstance(self.origin_tax_year, bool) or not isinstance(self.origin_tax_year, int):
            raise ValueError(
                "TAX_OPENING_LOSS_VINTAGE_INVALID_YEAR: origin_tax_year must be an integer, "
                f"got {type(self.origin_tax_year).__name__!r}."
            )
        # amount_keur: must be numbers.Real, not bool, not complex, not string, not NaN/Inf,
        # not negative.  fractions.Fraction and other Real implementations are accepted.
        if isinstance(self.amount_keur, bool):
            raise ValueError(
                "TAX_OPENING_LOSS_VINTAGE_INVALID_AMOUNT: amount_keur must be numeric, not bool."
            )
        if isinstance(self.amount_keur, complex) and not isinstance(self.amount_keur, _numbers.Real):
            raise ValueError(
                "TAX_OPENING_LOSS_VINTAGE_INVALID_AMOUNT: amount_keur must be a real numeric "
                f"value, got {type(self.amount_keur).__name__!r}."
            )
        if not isinstance(self.amount_keur, _numbers.Real):
            raise ValueError(
                "TAX_OPENING_LOSS_VINTAGE_INVALID_AMOUNT: amount_keur must be a real numeric "
                f"value, got {type(self.amount_keur).__name__!r}."
            )
        # NaN/Inf: only representable for float-like types
        try:
            _finite = _math.isfinite(float(self.amount_keur))
        except (OverflowError, ValueError):
            _finite = False
        if not _finite:
            raise ValueError(
                f"TAX_OPENING_LOSS_VINTAGE_INVALID_AMOUNT: amount_keur must be finite, "
                f"got {self.amount_keur!r}."
            )
        if self.amount_keur < 0:
            raise ValueError(
                f"TAX_OPENING_LOSS_VINTAGE_INVALID_AMOUNT: amount_keur must be non-negative, "
                f"got {self.amount_keur!r}."
            )
        # source_label: must be str
        if not isinstance(self.source_label, str):
            raise ValueError(
                "TAX_OPENING_LOSS_VINTAGE_INVALID_LABEL: source_label must be a string, "
                f"got {type(self.source_label).__name__!r}."
            )


@dataclass(frozen=True)
class PeriodInterestInput:
    """Exogenous interest expense for one model period.

    Phase 2B does not size debt — interest is provided externally.

    All three components are optional (default 0). At least one must be
    provided for the period to carry non-zero interest.
    """
    period_index: int
    senior_interest_keur: float = 0.0
    shl_interest_keur: float = 0.0
    other_interest_keur: float = 0.0
    shl_deductible_interest_keur: float | None = None
    capitalisation_ratio: float | None = None
    capitalisation_gate_active: bool | None = None
    absolute_limit_component_keur: float = 0.0
    ebitda_limit_component_keur: float = 0.0
    additional_non_deductible_component_keur: float = 0.0

    @property
    def total_interest_keur(self) -> float:
        return self.senior_interest_keur + self.shl_interest_keur + self.other_interest_keur


@dataclass(frozen=True)
class PeriodTaxAdjustmentInput:
    """Additional fiscal adjustments for one model period.

    other_fiscal_reintegration_keur : addbacks not already captured by the
        ATAD interest-limitation mechanism. Positive = addback to taxable income.

    Contract note for debt sizing:
        This is an explicit fiscal-policy/value input, not an operating-model
        derived output. When supplied to SeniorDebtModelInput it is therefore
        intentionally shared by Base and Bank cases. A Base-case-derived
        adjustment must not be encoded here; it requires its own derived
        bank-case calculation contract.
    """
    period_index: int
    other_fiscal_reintegration_keur: float = 0.0


@dataclass(frozen=True)
class PeriodFinancingIncomeInput:
    """U2: Cash/reserve interest income for one model period.

    financing_income_keur: gross interest income on eligible cash/reserve accounts.
    authority: provenance string from CashReserveInterestPolicy.authority.value.
    Financing income is BELOW EBITDA. It enters taxable income directly.
    """
    period_index: int
    financing_income_keur: float = 0.0
    authority: str = "UNRESOLVED"


@dataclass(frozen=True)
class TaxCalculationInput:
    """All tax-specific inputs for a Phase 2B run.

    policy : the jurisdiction's TaxPolicy
    opening_loss_vintages : pre-model loss pool in vintage order (oldest first)
    period_interest : one entry per model period that carries interest; periods
        not listed default to zero interest
    period_adjustments : explicit case-invariant fiscal adjustments only; do not
        place Base-case-derived economics here when running a separate bank case
    period_financing_income : U2 — per-period cash/reserve interest income.
        Financing income is below EBITDA and enters taxable income directly.
        Periods not listed default to zero income. UNRESOLVED authority yields 0.
    """
    policy: "TaxPolicy"
    opening_loss_vintages: tuple[OpeningTaxLossVintageInput, ...]
    period_interest: tuple[PeriodInterestInput, ...]
    period_adjustments: tuple[PeriodTaxAdjustmentInput, ...] = ()
    period_financing_income: tuple[PeriodFinancingIncomeInput, ...] = ()


@dataclass(frozen=True)
class InputProvenance:
    source_id: str
    baseline_commit_sha: str


# ---------------------------------------------------------------------------
# Phase 2C senior debt input contracts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DebtSizingCaseInput:
    """Bank/debt-sizing economic case — assumptions that differ from the Base case.

    Contains ONLY the fields that deviate from the Base/equity performance case.
    All project fundamentals (calendar, opex, capex, PPA, tax policy, etc.) are
    inherited from the Base OperatingModelInput unchanged.

    GENERIC_DEBT_SIZING_CASE_IS_EXPLICIT_AND_PROJECT_IDENTITY_FREE:
    No project-name dispatch, no project-code dispatch. The bank case is
    described entirely by explicit user-supplied field values.

    production_yield_scenario:
        Yield scenario for the bank/debt-sizing case (typically P90_10Y).
        Replaces technical.yield_scenario from the Base operating input.
        GENERIC_BANK_SIZING_DEFAULT_POLICY_IS_P90_10Y.

    merchant_price_calendar_start_year / merchant_prices_by_calendar_year_eur_mwh:
        Optional calendar-year merchant price override for the bank case.
        When supplied, replaces the Base merchant price curve. market_inflation
        is NOT re-applied. Mirror of RevenueInput.merchant_price_calendar_start_year.
        Mutually exclusive with market_prices_curve_eur_mwh.

    market_prices_curve_eur_mwh:
        Optional relative (inflation-grown) merchant price curve override.
        When empty AND merchant_price_calendar_start_year is None, Base revenue
        merchant price assumptions are inherited unchanged.

    tax_periodisation_mode_override:
        Optional bank-case-only tax periodisation policy. When None, the Base tax
        periodisation policy is inherited. This is explicit data-owned source
        compatibility metadata, not project identity dispatch.

    source_label:
        Audit-only label (e.g. "p90_10y_lender_case"). Never used in any
        financial calculation; present solely for human-readable provenance.
        Excluded from the engine fingerprint.
    """
    production_yield_scenario: YieldScenario
    merchant_price_calendar_start_year: int | None = None
    merchant_prices_by_calendar_year_eur_mwh: tuple[float, ...] = ()
    market_prices_curve_eur_mwh: tuple[float, ...] = ()
    tax_periodisation_mode_override: str | None = None
    source_label: str = ""

    def __post_init__(self) -> None:
        # PR-7: single shared validator owned by finco_core — the canonical
        # DebtSizingCaseConfig and this runtime contract must never drift.
        from finco_core.inputs._models import (
            validate_debt_sizing_case_merchant_price_fields,
        )

        validate_debt_sizing_case_merchant_price_fields(
            merchant_price_calendar_start_year=self.merchant_price_calendar_start_year,
            merchant_prices_by_calendar_year_eur_mwh=(
                self.merchant_prices_by_calendar_year_eur_mwh
            ),
            market_prices_curve_eur_mwh=self.market_prices_curve_eur_mwh,
            context="DebtSizingCaseInput",
        )


@dataclass(frozen=True)
class CapitalisationGateEquityInput:
    """Minimum project equity inputs for a dynamic tax capitalisation gate."""

    share_capital_keur: float
    legal_reserve_cap_fraction: float
    opening_legal_reserve_keur: float = 0.0
    opening_retained_earnings_keur: float = 0.0


@dataclass(frozen=True)
class SeniorDebtModelInput:
    """Phase 2C input: Phase 2B inputs + senior debt policy + senior debt inputs.

    operating: Phase 2A OperatingModelInput (Base/equity performance case)
    tax: Phase 2B TaxCalculationInput (interest from Phase 2C solver feeds back here)
    senior_debt_policy: SeniorDebtPolicy (sizing mode, DSCR target, rates, etc.)
    senior_debt_inputs: SeniorDebtInputs (cost base, initial guess, rate schedule, etc.)
    debt_sizing_case: DebtSizingCaseInput (bank-case assumptions differing from Base)
        Required. Use DebtSizingCaseInput(production_yield_scenario=YieldScenario.P90_10Y)
        for the generic bank case (GENERIC_BANK_SIZING_DEFAULT_POLICY_IS_P90_10Y).
    dsra: PR-3 CASH_DSRA roll-forward input. None = NONE mode (neutral pass-through).
        Source authority: FinancingParams.dsra_support_mode + debt_service_reserve_requirement_keur.
        Mapped by financial_engine.adapters.project_inputs.
    """
    operating: "OperatingModelInput"
    tax: "TaxCalculationInput"
    senior_debt_policy: object   # SeniorDebtPolicy (avoid circular imports)
    senior_debt_inputs: object   # SeniorDebtInputs
    debt_sizing_case: "DebtSizingCaseInput"
    shareholder_loan: object | None = None
    dsra: object | None = None  # CashDsraInput | None (avoid circular imports)
    capitalisation_gate_equity: CapitalisationGateEquityInput | None = None
    # U2 Correction F: typed cash/reserve interest policy for post-solver injection.
    # None → no financing income computed (fail-closed to 0.0).
    # Set by project_inputs adapter from ProjectInputs.cash_reserve_interest_policy.
    # min_unrestricted_cash_floor_keur is carried inside the policy object.
    cash_reserve_interest_policy: object | None = None  # CashReserveInterestPolicy | None


@dataclass(frozen=True)
class ShareholderLoanModelInput:
    """Generic SHL fixed-point input contract.

    The contract is explicit and project-identity-free. It supplies the SHL
    principal, rate, day-count convention, cash-sweep window, and convergence
    settings needed by the B5 fixed-point layer. Tax treatment is owned by
    TaxPolicy, not by the financing instrument.
    """
    initial_principal_keur: float
    annual_fixed_rate: float
    day_count_convention: object
    construction_day_count_fraction: float
    repayment_start_period_index: int
    maturity_period_index: int
    repayment_mode: ShlRepaymentMode = ShlRepaymentMode.CASH_SWEEP
    # SHL construction interest method (Fix 2 C3B3FIX2A). Default SIMPLE preserves
    # all existing behaviour. Set COMPOUND_PERIODIC for projects with geometric accrual.
    construction_interest_method: ShlConstructionInterestMethod = ShlConstructionInterestMethod.SIMPLE
    # Fix 3: timing-resolved opening operating SHL override (deprecated — use construction_periods_override).
    # When set, the production SHL model uses this as the effective opening balance for
    # operating period chains (bypassing the single-draw construction PIK re-computation).
    # None = no override; production model computes construction PIK internally as before.
    # Superseded by construction_periods_override when both are set.
    opening_operating_shl_override_keur: float | None = None
    # Fix 3 canonical: multi-period construction draw schedule for the SHL model.
    # When set, compute_shareholder_loan_schedules uses this to compute construction PIK
    # canonically per-period. model_result construction PIK == ProjectFinancingResult PIK.
    construction_periods_override: tuple[ShlConstructionPeriodInput, ...] | None = None
    # End dates for each timing-resolved construction row. When supplied, the
    # SHL model aggregates those rows into the canonical model construction
    # periods by date instead of assuming both axes have identical lengths.
    construction_period_end_dates_override: tuple[date, ...] | None = None
    # Principal contributed at FC/COD after construction accrual. This is used by
    # typed construction financing for non-construction FC uses such as CASH_DSRA.
    post_construction_principal_contribution_keur: float = 0.0
    convergence_tolerance_keur: float = 1e-6
    convergence_relative_tolerance: float = 1e-9
    maximum_iterations: int = 50
    source_label: str = ""


@dataclass(frozen=True)
class OperatingModelInput:
    calendar: CalendarInput
    technical: TechnicalInput
    revenue: RevenueInput
    opex: OpexInput
    depreciation: DepreciationInput
    source: InputProvenance


@dataclass(frozen=True)
class TaxCfadsModelInput:
    """Phase 2B input: operating core inputs + tax inputs.

    operating: the Phase 2A OperatingModelInput
    tax: tax policy and per-period interest / adjustment inputs
    """
    operating: OperatingModelInput
    tax: TaxCalculationInput
