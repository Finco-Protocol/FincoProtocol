"""
CAPEX Source Model — isolated schema stubs.

This module defines the CAPEX source model and input schema design.
It is completely isolated from runtime model code — NOT imported by any
runtime calculation, construction, returns, or debt module.

Purpose: Provide type-safe schema definitions for CAPEX input wiring
(Phase 21E and beyond).

NOTE: Do not import this module from any runtime-capable module.
      It exists only for design/type-safe schema documentation.
"""

from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Source type classification — where does this line's value come from?
# ─────────────────────────────────────────────────────────────────────────────

class CapexSourceType:
    """Origin/source classification for a CAPEX line value."""

    EXCEL_REFERENCE = "excel_reference"
    # Taken from the Excel CapEx sheet reference.
    # Not present in the app runtime CapexStructure.

    APP_INPUT = "app_input"
    # User-specified or app-template value.
    # May or may not be wired to runtime.

    RUNTIME_COMPUTED = "runtime_computed"
    # Derived by model calculations (IDC, bank fees, commitment fees).
    # Not user-editable directly.

    USER_OVERRIDE = "user_override"
    # User-edited override that replaces the prior computed or reference value.

    IMPORTED_SCHEDULE = "imported_schedule"
    # From an imported file or schedule (e.g., project rights payment schedule).

    STATIC_REFERENCE = "static_reference"
    # Hard-coded reference value, not editable by user.


# ─────────────────────────────────────────────────────────────────────────────
# Scope classification — what does this amount mean temporally/structurally?
# ─────────────────────────────────────────────────────────────────────────────

class CapexScope:
    """Temporal/structural scope classification for a CAPEX line amount."""

    AGGREGATE_TOTAL = "aggregate_total"
    # Total across all periods/batches (e.g., total EPC contract over construction)

    COMPONENT = "component"
    # Sub-component of a larger category (a piece of the full picture)

    PAYMENT_BATCH = "payment_batch"
    # One payment in a multi-batch schedule (e.g., one of 4 EPC batches)

    MONTHLY_SCHEDULE = "monthly_schedule"
    # Monthly M1-M18 distribution of a CAPEX total (timing only)

    FEE_ONLY = "fee_only"
    # Fee or prerequisite only (e.g., GPA administrative fee), not the full scope

    PROJECT_RIGHTS = "project_rights"
    # Acquisition premium / project rights premium.
    # Deferred wiring until tax/accounting treatment is confirmed.

    FINANCING_COST = "financing_cost"
    # IDC, commitment fees, bank fees — financing overhead

    RESERVE_ACCOUNT = "reserve_account"
    # DSRA, MMRA, working capital reserve

    LAND = "land"
    # Land lease / acquisition — non-depreciable, tax-basis treatment differs

    GENERIC = "generic"
    # Default fallback — no specific scope classification


# ─────────────────────────────────────────────────────────────────────────────
# Payment schedule schema
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CapexPaymentSchedule:
    """
    Payment schedule for a CAPEX line — defines TIMING, not total amount.

    The monthly payment schedule is used to:
    1. Distribute total CAPEX across construction months forIDC capitalization
    2. Drive senior debt drawdown in proportion to spend
    3. Provide monthly cash flow timing for the construction period

    It is separate from the CAPEX line total: the same total can have
    different payment schedules depending on source and profile.
    """

    schedule_type: str
    # "excel_m1_m18"  — from imported Excel 18-month schedule
    # "app_profile"   — from app construction profile (6-mo Generic Wind Reference, 12-mo Generic Solar Reference)
    # "static_reference" — hard-coded reference, not user-editable
    # "missing"        — no schedule data available

    periods: tuple[float, ...]
    # 18 fractions f₀..f₁₇ summing to 1.0.
    # Multiply total_keur by each period to get monthly spend amount.

    amounts_keur: Optional[tuple[float, ...]] = None
    # Optional explicit 18-month amounts.
    # If None: computed as [total_keur × p for p in periods].

    total_keur: float = 0.0
    # The total CAPEX amount this schedule applies to.

    source: str = ""
    # Human-readable source: "excel_capex_sheet", "app_construction_profile", etc.

    authority_status: str = ""
    # Mirrors the row authority_status for this schedule.

    notes: str = ""
    # Free-text notes about schedule source and intended use.


# ─────────────────────────────────────────────────────────────────────────────
# Line definition schema
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CapexLineDefinition:
    """
    Schema record for one CAPEX line item (C.01–C.18 child row).

    This is the design/future-wiring record type used to document:
    - Source type: where does the value come from?
    - Scope: what does the amount mean?
    - Runtime wiring: does it affect financial model calculations?
    - Tax/funding metadata: how is it treated for depreciation, tax shield, funding?

    This is NOT currently the runtime row format — it is the *schema design*
    that will guide Phase 21E wiring implementation.
    """

    code: str
    # "C", "C.02", "C.02.01" — hierarchical code in the CapEx sheet

    label: str
    # Human-readable label

    parent_code: Optional[str]
    # Parent code: "C" for top-level categories (C.01, C.02, ...),
    # "C.02" for child rows (C.02.01, C.02.02, ...), None for "C" itself.

    source_type: str
    # One of CapexSourceType values.
    # Use the constant, not the string value directly.

    scope: str
    # One of CapexScope values.
    # Use the constant, not the string value directly.

    amount_keur: Optional[float]
    # Amount in kEUR. None if not_applicable or not yet mapped.

    affects_runtime: bool
    # True if this line feeds into the financial model's CFADS or debt sizing.

    runtime_field: Optional[str]
    # e.g. "capex.epc_contract.amount_keur" — app CapexStructure field name.
    # None if source_type=EXCEL_REFERENCE or not yet wired.

    depreciation_category: Optional[str] = None
    # Depreciation category for tax/accounting purposes.
    # e.g. "plant_machinery", "land", "rights", "intangible"
    # None = not yet determined.

    tax_basis_category: Optional[str] = None
    # Tax basis treatment.
    # e.g. "tax_shield_eligible", "land_rights_excluded"
    # None = not yet determined.

    funding_category: Optional[str] = None
    # Funding source category.
    # e.g. "equity", "senior_debt", "mezzanine", "grant"
    # None = not yet determined.

    mapping_note: str = ""
    # Human-readable note: scope explanation, mismatch reason, deferred status, etc.

    monthly_schedule: Optional[CapexPaymentSchedule] = None
    # Payment schedule (M1-M18 fractions) if applicable for this line.
    # None for non-construction lines or lines without schedule data.


# ─────────────────────────────────────────────────────────────────────────────
# Schema container
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CapexInputSchemaDesign:
    """
    Top-level container for a project's CAPEX input schema.

    Provides a versioned, typed container for all line definitions,
    schedules, and metadata for a given project.
    """

    project_code: str
    # e.g. "Generic Wind Reference", "GENERIC_SOLAR_REFERENCE"

    lines: tuple[CapexLineDefinition, ...] = field(default_factory=tuple)
    # All C.01–C.18 line definitions for this project

    schedules: tuple[CapexPaymentSchedule, ...] = field(default_factory=tuple)
    # Payment schedules referenced by lines

    version: str = ""
    # Schema version, e.g. "2026.05.28-v1"

    notes: str = ""
    # Overall schema notes, open questions, deferred items


# ─────────────────────────────────────────────────────────────────────────────
# Phase 21F: CAPEX Line Item Treatment Options
# ─────────────────────────────────────────────────────────────────────────────
# Design: user-selectable treatment for each CAPEX line item.
# These enums are inert — not imported by runtime calculation modules.
# Future Phase (21G): wire treatment choices to depreciation/tax/funding/IDC.

from enum import StrEnum, auto
from dataclasses import dataclass, field
from typing import Literal


class AccountingTreatment(StrEnum):
    """How this CAPEX line is treated on the accounting balance sheet."""
    DEPRECIABLE_CAPEX      = auto()  # standard PP&E depreciation
    INTANGIBLE_ASSET       = auto()  # amortizable intangible (rights, licenses)
    DEVELOPMENT_COST        = auto()  # capitalised development expenditure
    ACQUISITION_PREMIUM     = auto()  # premium over fair value — often not depreciable
    LAND_OR_NON_DEPRECIABLE = auto() # land — not depreciable
    FINANCING_COST          = auto()  # capitalised financing charges (IDC)
    RESERVE_ACCOUNT        = auto()  # reserve / sinking fund account
    EXCLUDED_FROM_CAPEX    = auto()  # out of scope for capitalisation
    CUSTOM                 = auto()  # user-defined treatment


class DepreciationTreatment(StrEnum):
    """How this CAPEX line is depreciated / amortised on the income statement."""
    DEPRECIABLE            = auto()  # straight-line or reducing balance on PP&E
    AMORTIZABLE            = auto()  # amortisation of intangible / right-of-use
    NON_DEPRECIABLE        = auto()  # no depreciation — e.g. land
    EXPENSED               = auto()  # immediately expensed (often development costs)
    EXCLUDED               = auto()  # excluded from depreciation schedule
    CUSTOM                 = auto()  # user-defined depreciation profile


class DepreciationLifeYears(StrEnum):
    """Predefined depreciation / amortisation lives."""
    USE_TEMPLATE_DEFAULT   = auto()
    YEARS_5                 = auto()
    YEARS_10                = auto()
    YEARS_15                = auto()
    YEARS_20                = auto()
    YEARS_30                = auto()
    CUSTOM_YEARS            = auto()  # user specifies custom life in CapexLineTreatment


class TaxTreatment(StrEnum):
    """How this CAPEX line is treated for tax depreciation / deduction purposes."""
    TAX_DEPRECIABLE        = auto()  # tax depreciation (e.g. 5-year MACRS in US)
    TAX_AMORTIZABLE        = auto()  # tax amortisation of intangibles
    NON_DEDUCTIBLE         = auto()  # no tax deduction ever
    IMMEDIATELY_DEDUCTIBLE = auto()  # expensed in year 1 (e.g. certain development costs)
    EXCLUDED_FROM_TAX_BASIS = auto() # excluded from taxable income calculation
    JURISDICTION_SPECIFIC   = auto()  # jurisdiction-dependent (Generic Market A/B/C, etc.)
    CUSTOM                 = auto()  # user-defined tax treatment


class FundingTreatment(StrEnum):
    """How this CAPEX line contributes to the project's funding structure."""
    SENIOR_DEBT_ELIGIBLE   = auto()  # eligible for senior debt (lenders)
    EQUITY_ONLY            = auto()  # equity-funded only (no debt)
    SHL_ELIGIBLE           = auto()  # subordinated hybrid loan eligible
    INCLUDED_IN_TOTAL_FUNDING = auto()  # included in total funding need
    EXCLUDED_FROM_FUNDING  = auto()  # excluded from funding model
    CUSTOM                 = auto()  # user-defined funding treatment


class ConstructionTimingTreatment(StrEnum):
    """When / how this CAPEX line is paid during the construction phase."""
    INCLUDED_IN_CONSTRUCTION_DRAW = auto()  # drawn monthly via construction draw schedule
    EXCLUDED_FROM_IDC     = auto()  # no interest during construction (already paid)
    PAID_AT_FINANCIAL_CLOSE = auto()  # paid in full at financial close
    PAID_AT_COD           = auto()  # paid in full at commercial operational date
    PAID_ON_CUSTOM_SCHEDULE = auto()  # user-defined payment schedule
    TIMING_ONLY           = auto()  # schedule used for IDC timing only, not a CAPEX total


class ScheduleType(StrEnum):
    """Payment distribution type for this CAPEX line."""
    M1_M18_IMPORTED       = auto()  # imported monthly schedule (M1–M18)
    LINEAR                = auto()  # equal monthly instalments
    S_CURVE               = auto()  # S-curve (front-loaded or back-loaded)
    ONE_OFF               = auto()  # single payment
    CUSTOM                = auto()  # user-defined schedule


@dataclass
class CapexLineTreatment:
    """
    Per-line-item treatment specification.
    Inert design schema — not wired to runtime calculations.
    Future Phase (21G): wire instances to depreciation / tax / funding / IDC engine.
    """
    excel_code: str                    # e.g. "C.16.01"
    excel_name: str                    # e.g. "Synthetic Development Rights"

    accounting: AccountingTreatment | None = None
    depreciation: DepreciationTreatment | None = None
    depreciation_life: DepreciationLifeYears | None = None
    depreciation_custom_years: int | None = None  # used when depreciation_life == CUSTOM_YEARS

    tax: TaxTreatment | None = None
    tax_jurisdiction: str | None = None  # e.g. "XB", "XA", "EU"

    funding: FundingTreatment | None = None

    construction_timing: ConstructionTimingTreatment | None = None

    schedule_type: ScheduleType | None = None

    # Metadata
    user_selectable: bool = True         # False = locked by system
    treatment_resolved: bool = False    # False = awaiting user decision
    treatment_note: str = ""             # Human-readable note

    @property
    def is_unresolved(self) -> bool:
        return self.user_selectable and not self.treatment_resolved

    def summarise(self) -> str:
        parts = [f"accounting={self.accounting.value if self.accounting else '?'}"]
        if self.depreciation:
            parts.append(f"depreciation={self.depreciation.value}")
        if self.depreciation_life:
            parts.append(f"life={self.depreciation_life.value}")
        if self.tax:
            parts.append(f"tax={self.tax.value}")
        if self.funding:
            parts.append(f"funding={self.funding.value}")
        if self.construction_timing:
            parts.append(f"construction={self.construction_timing.value}")
        if self.is_unresolved:
            parts.append("⚠ unresolved")
        return ", ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 21F: C.16 Project Rights — Example Unresolved Treatment
# ─────────────────────────────────────────────────────────────────────────────
# C.16 Project Rights (legacy source total removed from public runtime):
#   C.16.01 Synthetic Development Rights       = 2,500 kEUR
#   C.16.02 Other Development Costs         = 2,000 kEUR
#   C.16.03 Land / Purchase                = 10,000 kEUR
#
# Treatment is UNRESOLVED because:
#   1. Jurisdiction (Generic Market A vs Generic Market B) affects whether development costs are
#      intangible assets (amortised) or deductible immediately.
#   2. Acquisition premium (10,000) may or may not be depreciable
#      depending on accounting policy (IFRS vs local GAAP).
#   3. Funding treatment (senior debt eligible vs equity only) depends
#      on lender's interpretation of project rights as collateral.
#
# User must decide before C.16 can be wired to runtime.

C16_TREATMENT_EXAMPLE = CapexLineTreatment(
    excel_code="C.16",
    excel_name="Project Rights",
    accounting=None,           # unresolved — user must choose
    depreciation=None,        # unresolved
    depreciation_life=None,   # unresolved
    tax=None,                 # unresolved — jurisdiction_specific likely
    funding=None,             # unresolved — equity_only or senior_debt_eligible TBD
    construction_timing=ConstructionTimingTreatment.EXCLUDED_FROM_IDC,
    schedule_type=ScheduleType.ONE_OFF,
    user_selectable=True,
    treatment_resolved=False,
    treatment_note=(
        "Legacy source-specific project-rights calibration is not part of the public runtime. "
        "Treatment pending: accounting policy (IFRS/local GAAP), jurisdiction (Generic Market A/B), "
        "depreciation life, and funding eligibility must be confirmed by user. "
        "Do NOT hard-code — await user decision."
    ),
)

C16_CHILD_TREATMENTS = {
    "C.16.01": CapexLineTreatment(
        excel_code="C.16.01",
        excel_name="Synthetic Development Rights (2,500 kEUR)",
        accounting=AccountingTreatment.DEVELOPMENT_COST,
        depreciation=DepreciationTreatment.AMORTIZABLE,
        depreciation_life=DepreciationLifeYears.YEARS_10,
        tax=TaxTreatment.JURISDICTION_SPECIFIC,
        tax_jurisdiction=None,  # generic market profile TBD
        funding=FundingTreatment.EQUITY_ONLY,
        construction_timing=ConstructionTimingTreatment.PAID_AT_FINANCIAL_CLOSE,
        schedule_type=ScheduleType.ONE_OFF,
        user_selectable=True,
        treatment_resolved=False,
        treatment_note="Synthetic development rights: amortisation life and tax jurisdiction pending.",
    ),
    "C.16.02": CapexLineTreatment(
        excel_code="C.16.02",
        excel_name="Other Development Costs (2,000 kEUR)",
        accounting=AccountingTreatment.DEVELOPMENT_COST,
        depreciation=DepreciationTreatment.EXPENSED,
        depreciation_life=None,
        tax=TaxTreatment.IMMEDIATELY_DEDUCTIBLE,
        funding=FundingTreatment.EQUITY_ONLY,
        construction_timing=ConstructionTimingTreatment.PAID_AT_FINANCIAL_CLOSE,
        schedule_type=ScheduleType.ONE_OFF,
        user_selectable=True,
        treatment_resolved=False,
        treatment_note="Other development costs: check selected market tax treatment (immediately deductible vs amortisation).",
    ),
    "C.16.03": CapexLineTreatment(
        excel_code="C.16.03",
        excel_name="Land / Purchase (10,000 kEUR)",
        accounting=AccountingTreatment.LAND_OR_NON_DEPRECIABLE,
        depreciation=DepreciationTreatment.NON_DEPRECIABLE,
        depreciation_life=None,
        tax=TaxTreatment.NON_DEDUCTIBLE,
        funding=FundingTreatment.SENIOR_DEBT_ELIGIBLE,
        construction_timing=ConstructionTimingTreatment.PAID_AT_FINANCIAL_CLOSE,
        schedule_type=ScheduleType.ONE_OFF,
        user_selectable=True,
        treatment_resolved=False,
        treatment_note="Land purchase: non-depreciable for accounting, non-deductible for tax, but senior-debt eligible (collateral). User must confirm.",
    ),
}
