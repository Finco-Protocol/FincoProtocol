"""financial_engine.policies.tax — TaxPolicy immutable contract.

Phase 2B full contract. No calculation performed here.
"""
from __future__ import annotations

import math
import numbers
from dataclasses import dataclass
from enum import Enum


class CashTaxTiming(str, Enum):
    """When does the CIT cash payment crystallise relative to accrual?"""
    SAME_PERIOD = "same_period"
    TAX_YEAR_LAST_PERIOD = "tax_year_last_period"
    MODEL_YEAR_PAYMENT_PERIOD = "model_year_payment_period"


class TaxBasisPeriodisation(str, Enum):
    """How semi-annual model periods are grouped into tax calculation years."""
    CALENDAR_YEAR = "calendar_year"
    MODEL_YEAR_PAIRING = "model_year_pairing"


class TaxLossUtilisationGate(str, Enum):
    """Gate for using carried-forward losses against positive taxable income."""
    TAXABLE_INCOME_POSITIVE = "taxable_income_positive"
    EBT_POSITIVE = "ebt_positive"


class ShlInterestDeductibilityMode(str, Enum):
    """Clean-engine SHL interest deductibility policy.

    The value strings mirror finco_core.inputs.ShlInterestDeductibilityMode so
    adapters can map canonical ProjectInputs without importing finco_core into
    the clean tax engine.
    """

    FULLY_DEDUCTIBLE = "fully_deductible"
    FULLY_NON_DEDUCTIBLE = "fully_non_deductible"
    SUBJECT_TO_LIMITATIONS = "subject_to_limitations"
    CUSTOM_DEDUCTIBLE_PERCENTAGE = "custom_deductible_percentage"


class InterestLimitationCombinationMode(str, Enum):
    """How independently calculated non-deductible components combine."""

    MAX_DISALLOWED = "max_disallowed"
    SUM_DISALLOWED = "sum_disallowed"


class InterestLimitationCarryforwardMode(str, Enum):
    """Treatment of interest restricted by the source-model policy."""

    NONE = "none"
    CARRY_FORWARD = "carry_forward"


@dataclass(frozen=True)
class CapitalisationGatePolicy:
    """Literal balance-sheet gate used by a typed interest-limitation policy.

    ``subtotal_is_reincluded_in_denominator`` preserves source models where the
    equity/liability subtotal is itself included again in the denominator.  It
    intentionally does not reinterpret that convention as a standard D/E ratio.
    """

    enabled: bool
    threshold: float
    subtotal_is_reincluded_in_denominator: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("CapitalisationGatePolicy.enabled must be exact bool")
        if not isinstance(self.subtotal_is_reincluded_in_denominator, bool):
            raise TypeError(
                "CapitalisationGatePolicy.subtotal_is_reincluded_in_denominator "
                "must be exact bool"
            )
        if isinstance(self.threshold, bool) or not isinstance(self.threshold, numbers.Real):
            raise TypeError("CapitalisationGatePolicy.threshold must be a real number")
        if not math.isfinite(float(self.threshold)) or float(self.threshold) < 0.0:
            raise ValueError(
                "CapitalisationGatePolicy.threshold must be finite and non-negative"
            )


@dataclass(frozen=True)
class InterestLimitationPolicy:
    """Generic source-model contract for SHL interest deductibility.

    This contract deliberately uses neutral financial terminology.  It records
    a model mechanic and does not assert that the mechanic is a complete or
    current implementation of any jurisdiction's tax law.
    """

    enabled: bool
    absolute_interest_limit_keur: float
    ebitda_interest_limit_pct: float
    capitalisation_gate_policy: CapitalisationGatePolicy
    combination_mode: InterestLimitationCombinationMode
    carryforward_mode: InterestLimitationCarryforwardMode
    additional_non_deductible_share: float = 0.0
    source_model_convention: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("InterestLimitationPolicy.enabled must be exact bool")
        if not isinstance(self.capitalisation_gate_policy, CapitalisationGatePolicy):
            raise TypeError(
                "InterestLimitationPolicy.capitalisation_gate_policy must be "
                "CapitalisationGatePolicy"
            )
        if not isinstance(self.combination_mode, InterestLimitationCombinationMode):
            raise TypeError(
                "InterestLimitationPolicy.combination_mode must be "
                "InterestLimitationCombinationMode"
            )
        if not isinstance(self.carryforward_mode, InterestLimitationCarryforwardMode):
            raise TypeError(
                "InterestLimitationPolicy.carryforward_mode must be "
                "InterestLimitationCarryforwardMode"
            )
        for name in (
            "absolute_interest_limit_keur",
            "ebitda_interest_limit_pct",
            "additional_non_deductible_share",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, numbers.Real):
                raise TypeError(f"InterestLimitationPolicy.{name} must be a real number")
            if not math.isfinite(float(value)):
                raise ValueError(f"InterestLimitationPolicy.{name} must be finite")
        if self.absolute_interest_limit_keur < 0.0:
            raise ValueError("absolute_interest_limit_keur must be non-negative")
        if not 0.0 <= self.ebitda_interest_limit_pct <= 1.0:
            raise ValueError("ebitda_interest_limit_pct must be in [0, 1]")
        if not 0.0 <= self.additional_non_deductible_share <= 1.0:
            raise ValueError("additional_non_deductible_share must be in [0, 1]")
        if self.carryforward_mode is InterestLimitationCarryforwardMode.CARRY_FORWARD:
            raise NotImplementedError(
                "INTEREST_LIMITATION_CARRY_FORWARD_NOT_IMPLEMENTED: the typed mode "
                "exists so restricted interest is never silently discarded, but the "
                "carryforward ledger is not implemented."
            )


@dataclass(frozen=True)
class TaxPolicy:
    """Complete jurisdiction tax policy for Phase 2B.

    Attributes
    ----------
    policy_id : unique identifier (e.g. "HR_CIT_2026")
    policy_version : semantic version of this policy record
    corporate_rate : flat CIT rate (e.g. 0.18)
    periods_per_tax_year : number of model periods per calendar tax year (2 = semi-annual)
    loss_carryforward_years : LCF window in tax years (5 for Generic Market A)
    atad_enabled : whether ATAD interest limitation applies
    atad_ebitda_limit : fraction of annual tax EBITDA allowed as max deductible interest (0.30)
    atad_de_minimis_threshold_keur_annual : annual safe harbour kEUR (3 000 for Generic Market A)
    cash_tax_timing : controls when the CIT cash payment crystallises
    cash_tax_payment_lag_periods : additional periods after the last-period trigger before
        cash is paid (0 = paid in the triggering period itself)
    shl_interest_tax_treatment_enabled : enables clean SHL deductibility treatment
        when the caller has supplied a complete financing-interest contract
    shl_interest_deductibility : tax treatment for gross accounting SHL interest
    shl_interest_deductible_pct : deductible fraction when CUSTOM_DEDUCTIBLE_PERCENTAGE
    thin_cap_enabled : thin-cap source metadata flag (forwarded from TaxParams).
        True = thin-cap limitation recorded in source model. The thin-cap formula is
        NOT yet implemented in the production runtime. When SUBJECT_TO_LIMITATIONS is
        requested with thin_cap_enabled=True, the runtime gate raises
        SHL_THIN_CAP_RUNTIME_NOT_IMPLEMENTED. Only the ATAD path (thin_cap_enabled=False,
        atad_enabled=True) is currently executable.

    NOTE: shl_limitation_enabled and shl_interest_cap_keur_annual have been REMOVED.
    SUBJECT_TO_LIMITATIONS is now implemented via the ATAD mechanism (atad_enabled=True).
    The ATAD EBITDA-based limitation is the approved authority for EU interest limitations.
    An absolute annual SHL cap separate from ATAD has no approved non-workbook authority.
    """
    policy_id: str
    policy_version: str
    corporate_rate: float
    periods_per_tax_year: int
    loss_carryforward_years: int
    atad_enabled: bool
    atad_ebitda_limit: float
    atad_de_minimis_threshold_keur_annual: float
    cash_tax_timing: CashTaxTiming
    cash_tax_payment_lag_periods: int = 0
    shl_interest_tax_treatment_enabled: bool = False
    shl_interest_deductibility: ShlInterestDeductibilityMode = (
        ShlInterestDeductibilityMode.FULLY_DEDUCTIBLE
    )
    shl_interest_deductible_pct: float | None = None
    tax_basis_periodisation: TaxBasisPeriodisation = TaxBasisPeriodisation.CALENDAR_YEAR
    loss_utilisation_gate: TaxLossUtilisationGate = (
        TaxLossUtilisationGate.TAXABLE_INCOME_POSITIVE
    )
    thin_cap_enabled: bool = False
    interest_limitation_policy: InterestLimitationPolicy | None = None

    def __post_init__(self) -> None:
        """Fail-closed typed validation for all TaxPolicy fields."""
        # ── boolean fields must be exact bool ─────────────────────────────────
        for name in (
            "atad_enabled",
            "shl_interest_tax_treatment_enabled",
            "thin_cap_enabled",
        ):
            val = getattr(self, name)
            if not isinstance(val, bool):
                raise TypeError(
                    f"TaxPolicy.{name} must be exact bool, got {type(val).__name__!r}: {val!r}"
                )

        # ── enum fields must be correct enum type ──────────────────────────────
        if not isinstance(self.cash_tax_timing, CashTaxTiming):
            raise TypeError(
                f"TaxPolicy.cash_tax_timing must be CashTaxTiming, got {type(self.cash_tax_timing)!r}"
            )
        if not isinstance(self.shl_interest_deductibility, ShlInterestDeductibilityMode):
            raise TypeError(
                "TaxPolicy.shl_interest_deductibility must be ShlInterestDeductibilityMode, "
                f"got {type(self.shl_interest_deductibility)!r}"
            )
        if not isinstance(self.tax_basis_periodisation, TaxBasisPeriodisation):
            raise TypeError(
                "TaxPolicy.tax_basis_periodisation must be TaxBasisPeriodisation, "
                f"got {type(self.tax_basis_periodisation)!r}"
            )
        if not isinstance(self.loss_utilisation_gate, TaxLossUtilisationGate):
            raise TypeError(
                "TaxPolicy.loss_utilisation_gate must be TaxLossUtilisationGate, "
                f"got {type(self.loss_utilisation_gate)!r}"
            )
        if (
            self.interest_limitation_policy is not None
            and not isinstance(self.interest_limitation_policy, InterestLimitationPolicy)
        ):
            raise TypeError(
                "TaxPolicy.interest_limitation_policy must be InterestLimitationPolicy or None"
            )

        # ── atad_ebitda_limit: numbers.Real, not bool, finite, in approved range ──
        if isinstance(self.atad_ebitda_limit, bool):
            raise TypeError(
                "TaxPolicy.atad_ebitda_limit must not be bool"
            )
        if not isinstance(self.atad_ebitda_limit, numbers.Real):
            raise TypeError(
                f"TaxPolicy.atad_ebitda_limit must be numbers.Real, got {type(self.atad_ebitda_limit)!r}"
            )
        _lim = float(self.atad_ebitda_limit)
        if math.isnan(_lim) or math.isinf(_lim):
            raise ValueError(
                f"TaxPolicy.atad_ebitda_limit must be finite, got {self.atad_ebitda_limit!r}"
            )
        # Business-range enforcement (atad_ebitda_limit in [0,1]) is handled by the
        # canonical validation layer (TAX004) so that invalid financial inputs are
        # classified with a structured code rather than a raw ValueError from the
        # constructor. Only finiteness (structural invariant) is enforced here.

        # ── atad_de_minimis_threshold_keur_annual: numbers.Real, not bool, finite, non-negative ─
        if isinstance(self.atad_de_minimis_threshold_keur_annual, bool):
            raise TypeError(
                "TaxPolicy.atad_de_minimis_threshold_keur_annual must not be bool"
            )
        if not isinstance(self.atad_de_minimis_threshold_keur_annual, numbers.Real):
            raise TypeError(
                "TaxPolicy.atad_de_minimis_threshold_keur_annual must be numbers.Real, "
                f"got {type(self.atad_de_minimis_threshold_keur_annual)!r}"
            )
        _dm = float(self.atad_de_minimis_threshold_keur_annual)
        if math.isnan(_dm) or math.isinf(_dm):
            raise ValueError(
                "TaxPolicy.atad_de_minimis_threshold_keur_annual must be finite, "
                f"got {self.atad_de_minimis_threshold_keur_annual!r}"
            )
        # Business-range enforcement (de_minimis >= 0) is handled by the canonical
        # validation layer (TAX005) so that invalid financial inputs are classified
        # with a structured code rather than a raw ValueError from the constructor.

        # ── shl_interest_deductible_pct: if supplied, numbers.Real, finite, in [0,1] ──
        pct = self.shl_interest_deductible_pct
        if pct is not None:
            if isinstance(pct, bool):
                raise TypeError(
                    "TaxPolicy.shl_interest_deductible_pct must not be bool"
                )
            if not isinstance(pct, numbers.Real):
                raise TypeError(
                    "TaxPolicy.shl_interest_deductible_pct must be numbers.Real, "
                    f"got {type(pct)!r}"
                )
            _p = float(pct)
            if math.isnan(_p) or math.isinf(_p):
                raise ValueError(
                    f"TaxPolicy.shl_interest_deductible_pct must be finite, got {pct!r}"
                )
            if _p < 0.0:
                raise ValueError(
                    f"TaxPolicy.shl_interest_deductible_pct must be ≥ 0, got {pct!r}"
                )
            if _p > 1.0:
                raise ValueError(
                    f"TaxPolicy.shl_interest_deductible_pct must be ≤ 1, got {pct!r}"
                )

        # ── corporate_rate: numbers.Real, not bool, finite ──────────────────────
        if isinstance(self.corporate_rate, bool):
            raise TypeError("TaxPolicy.corporate_rate must not be bool")
        if not isinstance(self.corporate_rate, numbers.Real):
            raise TypeError(
                f"TaxPolicy.corporate_rate must be numbers.Real, got {type(self.corporate_rate)!r}"
            )
        _cr = float(self.corporate_rate)
        if math.isnan(_cr) or math.isinf(_cr):
            raise ValueError(
                f"TaxPolicy.corporate_rate must be finite, got {self.corporate_rate!r}"
            )

        # ── mode/pct consistency ───────────────────────────────────────────────
        mode = self.shl_interest_deductibility
        if mode == ShlInterestDeductibilityMode.CUSTOM_DEDUCTIBLE_PERCENTAGE:
            if pct is None:
                raise ValueError(
                    "TaxPolicy: shl_interest_deductible_pct is required for "
                    "CUSTOM_DEDUCTIBLE_PERCENTAGE"
                )
        elif mode in (
            ShlInterestDeductibilityMode.FULLY_DEDUCTIBLE,
            ShlInterestDeductibilityMode.FULLY_NON_DEDUCTIBLE,
        ):
            if pct is not None:
                expected = 1.0 if mode == ShlInterestDeductibilityMode.FULLY_DEDUCTIBLE else 0.0
                if abs(float(pct) - expected) > 1e-9:
                    raise ValueError(
                        f"TaxPolicy: shl_interest_deductible_pct must be absent or {expected} "
                        f"for {mode.value}, got {pct!r}"
                    )

    def require_stl_mechanism_ready(self) -> None:
        """Gate: raise if SUBJECT_TO_LIMITATIONS is configured but not executable.

        Runtime capability matrix:
          thin_cap_enabled=False, atad_enabled=True  → OK (execute ATAD path)
          thin_cap_enabled=True,  atad_enabled=False → SHL_THIN_CAP_RUNTIME_NOT_IMPLEMENTED
          thin_cap_enabled=True,  atad_enabled=True  → SHL_THIN_CAP_RUNTIME_NOT_IMPLEMENTED
          thin_cap_enabled=False, atad_enabled=False → SHL_LIMITATION_MECHANISM_MISSING

        Must be called before any tax output is produced when
        shl_interest_deductibility == SUBJECT_TO_LIMITATIONS.

        Gate is capability-driven only — no project name/code/identity check.
        Does NOT implement thin-cap formula.
        """
        if (
            self.interest_limitation_policy is not None
            and self.interest_limitation_policy.enabled
        ):
            return
        if self.thin_cap_enabled:
            raise NotImplementedError(
                "SHL_THIN_CAP_RUNTIME_NOT_IMPLEMENTED: "
                "thin_cap_enabled=True is recorded as source metadata but the thin-cap "
                "formula is not implemented in the production runtime. "
                "Only the ATAD path (thin_cap_enabled=False, atad_enabled=True) is "
                "currently executable for SUBJECT_TO_LIMITATIONS. "
                "Do not implement the thin-cap formula without a dedicated proof stage."
            )
        if not self.atad_enabled:
            raise NotImplementedError(
                "SHL_LIMITATION_MECHANISM_MISSING: "
                "shl_interest_deductibility=SUBJECT_TO_LIMITATIONS requires a supported "
                "limitation mechanism. Set atad_enabled=True for the ATAD execution path, "
                "or thin_cap_enabled=True to record source metadata (runtime-blocked)."
            )

    def shl_tax_deductible_fraction(self) -> float:
        """Return the fraction of gross SHL interest eligible for tax deduction.

        For SUBJECT_TO_LIMITATIONS, this method enforces the runtime capability gate
        BEFORE returning any value. If thin_cap_enabled=True or atad_enabled=False,
        it raises (SHL_THIN_CAP_RUNTIME_NOT_IMPLEMENTED or SHL_LIMITATION_MECHANISM_MISSING).
        Only when thin_cap_enabled=False and atad_enabled=True does it return 1.0.

        For SUBJECT_TO_LIMITATIONS, SHL interest is treated as fully deductible
        at the year-builder level (fraction=1.0). The ATAD mechanism (atad_enabled=True)
        then applies the EBITDA-based annual limitation to total interest including SHL.
        """
        if not self.shl_interest_tax_treatment_enabled:
            return 1.0
        mode = self.shl_interest_deductibility
        if mode == ShlInterestDeductibilityMode.FULLY_DEDUCTIBLE:
            return 1.0
        if mode == ShlInterestDeductibilityMode.FULLY_NON_DEDUCTIBLE:
            return 0.0
        if mode == ShlInterestDeductibilityMode.CUSTOM_DEDUCTIBLE_PERCENTAGE:
            pct = self.shl_interest_deductible_pct
            if pct is None:
                raise ValueError(
                    "shl_interest_deductible_pct is required for CUSTOM_DEDUCTIBLE_PERCENTAGE"
                )
            if not 0.0 <= float(pct) <= 1.0:
                raise ValueError(
                    f"shl_interest_deductible_pct must be in [0, 1], got {pct!r}"
                )
            return float(pct)
        # SUBJECT_TO_LIMITATIONS: enforce capability gate before producing any output.
        if mode == ShlInterestDeductibilityMode.SUBJECT_TO_LIMITATIONS:
            self.require_stl_mechanism_ready()
            if (
                self.interest_limitation_policy is not None
                and self.interest_limitation_policy.enabled
            ):
                raise ValueError(
                    "DYNAMIC_INTEREST_LIMITATION_PERIOD_INPUT_REQUIRED: a typed dynamic "
                    "policy cannot be reduced to one constant deductible fraction"
                )
            # Gate passed: only ATAD path reachable here (thin_cap_enabled=False, atad_enabled=True).
            # SHL is fully included in total interest; ATAD provides the annual limitation.
            return 1.0
        raise NotImplementedError(
            f"REFERENCE_WIND_SHL_TAX_POLICY_UNHANDLED_MODE: unrecognised ShlInterestDeductibilityMode {mode!r}"
        )

    def is_subject_to_limitations_active(self) -> bool:
        """Return True if and only if SUBJECT_TO_LIMITATIONS is fully active and executable.

        Active requires ALL of:
        - shl_interest_tax_treatment_enabled is True (financing interest injected)
        - shl_interest_deductibility is SUBJECT_TO_LIMITATIONS
        - atad_enabled is True (ATAD provides the interest limitation for STL)
        - thin_cap_enabled is False (thin-cap is not implemented; if True, raises at runtime)

        Architecture: the unsourced absolute annual SHL cap (shl_limitation_enabled +
        shl_interest_cap_keur_annual) has been removed. ATAD is now the sole limitation
        mechanism for SUBJECT_TO_LIMITATIONS. ATAD must be enabled and thin_cap_enabled
        must be False for STL to be active.
        """
        if not self.shl_interest_tax_treatment_enabled:
            return False
        if self.shl_interest_deductibility is not ShlInterestDeductibilityMode.SUBJECT_TO_LIMITATIONS:
            return False
        if (
            self.interest_limitation_policy is not None
            and self.interest_limitation_policy.enabled
        ):
            return True
        # thin_cap_enabled=True means the runtime gate will raise — not active/executable.
        if self.thin_cap_enabled:
            return False
        # ATAD must be enabled for STL to have any actual limitation effect
        if not self.atad_enabled:
            return False
        return True
