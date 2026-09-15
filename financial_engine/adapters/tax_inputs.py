"""financial_engine.adapters.tax_inputs — Generic ProjectInputs → TaxCalculationInput adapter.

Maps canonical ProjectInputs to a TaxCalculationInput for the clean Phase 2B / 2C engine.
No project-name dispatch, no snapshot loading, no factory invocations.

Tax policy is derived exclusively from explicit project input fields and, when
selected, an approved versioned country-policy profile:
  - country_tax_policy_id → explicit profile selection (country alone does nothing)
  - corporate_rate_override → project override over an approved profile default
  - corporate_rate        → TaxPolicy.corporate_rate
  - atad_enabled          → TaxPolicy.atad_enabled (C3B3D0: independent of thin_cap_enabled)
  - atad_ebitda_limit     → TaxPolicy.atad_ebitda_limit
  - atad_min_interest_keur→ TaxPolicy.atad_de_minimis_threshold_keur_annual
  - loss_carryforward_years → TaxPolicy.loss_carryforward_years
  - period_frequency      → TaxPolicy.periods_per_tax_year

C3B1 source evidence (Generic Solar Reference):
  - ATAD gated by BS!G45 = thin_cap_enabled = False → atad_enabled=False for Generic Solar Reference
  - cash_tax_timing = TAX_YEAR_LAST_PERIOD, lag=0

C3B3D0: atad_enabled and thin_cap_enabled are independent. This adapter reads
  tax.atad_enabled directly — it no longer derives ATAD from thin_cap_enabled.

Opening loss vintages are mapped only from explicit typed project vintages.
The legacy scalar remains accepted only when zero because it carries no origin year.
"""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from finco_core.inputs import ProjectInputs

from finco_core.inputs._models import PeriodFrequency


_POLICY_ID = "clean-project-tax-v1"
_POLICY_VERSION = "1.0.0"


class FinancingInterestContext(str, Enum):
    """Authority for the empty financing-interest vector returned by this adapter."""

    STANDARD_RUNTIME = "STANDARD_RUNTIME"
    COMPLETE_FINANCING_INTEREST_WILL_BE_INJECTED = (
        "COMPLETE_FINANCING_INTEREST_WILL_BE_INJECTED"
    )
    UNLEVERED_ZERO_FINANCING_INTEREST = "UNLEVERED_ZERO_FINANCING_INTEREST"


def build_tax_contract_from_project_inputs(
    project_inputs: "ProjectInputs",
    *,
    complete_financing_interest_will_be_injected: bool = False,
    financing_interest_context: FinancingInterestContext | None = None,
) -> object:
    """Map canonical ProjectInputs to a TaxCalculationInput.

    Parameters
    ----------
    project_inputs:
        Canonical project inputs (finco_core.inputs.ProjectInputs).
    complete_financing_interest_will_be_injected:
        Backward-compatible selector for callers that merge a complete Senior,
        SHL and other financing-interest schedule after this adapter returns.
    financing_interest_context:
        Typed authority for the empty period-interest vector. C1 Project Return
        uses UNLEVERED_ZERO_FINANCING_INTEREST because zero financing interest is
        complete by definition and no later injection is promised.

    Returns
    -------
    TaxCalculationInput — ready for calculate_tax() or run_senior_debt_model().

    Notes
    -----
    * period_interest is returned EMPTY — senior interest is supplied by the
      fixed-point solver in run_senior_debt_model(); SHL interest is omitted
      because no authoritative canonical per-period SHL interest source existed
      before C3B3D1/D2B. Once D2B supplies gross_accrued_interest_keur, TaxPolicy
      determines deductibility (for Generic Solar Reference: FULLY_NON_DEDUCTIBLE → deductible=0).
      This is NOT a "cancellation through fiscal reintegration."
    * period_adjustments is returned EMPTY.
    * Callers that need SHL in the tax input must merge it after this call.

    Fail-closed conditions (raises rather than silently computing wrong results):
    * ATAD enabled with empty period_interest and STANDARD_RUNTIME context:
      raises NotImplementedError. ATAD requires either a complete financing-
      interest injection contract or the explicit unlevered-zero context.
    * Nonzero legacy initial_tax_loss_keur: raises NotImplementedError.
      Explicit typed vintages are the only non-zero opening-loss authority.
    * Unsupported period_frequency: raises ValueError.
      Only SEMESTRIAL (2 periods/year) is supported.
    * Clean cash-tax timing not enabled: raises NotImplementedError.
      The clean engine uses TAX_YEAR_LAST_PERIOD (calendar-year CIT accrual), lag=0.
      The payment lag of 0 is policy-defined for Generic Solar Reference (C3B1). TAX_YEAR_LAST_PERIOD
      itself differs from workbook H2+H1 pairing (WORKBOOK_PERIODISATION_MISMATCH).
      Projects without clean_cash_tax_timing_enabled=True fail closed.
    """
    from financial_engine.inputs import TaxCalculationInput, OpeningTaxLossVintageInput
    from financial_engine.policies.tax import (
        CapitalisationGatePolicy,
        CashTaxTiming,
        InterestLimitationCarryforwardMode,
        InterestLimitationCombinationMode,
        InterestLimitationPolicy,
        ShlInterestDeductibilityMode,
        TaxLossUtilisationGate,
        TaxPolicy,
    )

    if not isinstance(complete_financing_interest_will_be_injected, bool):
        raise TypeError(
            "complete_financing_interest_will_be_injected must be exact bool"
        )
    if financing_interest_context is None:
        interest_context = (
            FinancingInterestContext.COMPLETE_FINANCING_INTEREST_WILL_BE_INJECTED
            if complete_financing_interest_will_be_injected
            else FinancingInterestContext.STANDARD_RUNTIME
        )
    else:
        if not isinstance(financing_interest_context, FinancingInterestContext):
            raise TypeError(
                "financing_interest_context must be FinancingInterestContext or None"
            )
        interest_context = financing_interest_context
        if (
            complete_financing_interest_will_be_injected
            and interest_context
            is not FinancingInterestContext.COMPLETE_FINANCING_INTEREST_WILL_BE_INJECTED
        ):
            raise ValueError("FINANCING_INTEREST_CONTEXT_CONFLICT")

    complete_interest_will_be_injected = (
        interest_context
        is FinancingInterestContext.COMPLETE_FINANCING_INTEREST_WILL_BE_INJECTED
    )

    tax = project_inputs.tax
    info = project_inputs.info

    corporate_rate = tax.corporate_rate
    policy_id = _POLICY_ID
    policy_version = _POLICY_VERSION
    if tax.country_tax_policy_id is not None:
        from financial_engine.tax.jurisdiction import (
            ProjectTaxOverrides,
            get_profile,
            get_tax_jurisdiction_defaults,
            resolve_tax_assumptions,
        )

        profile = get_profile(tax.country_tax_policy_id)
        if profile.country_iso.upper() != info.country_iso.upper():
            raise ValueError(
                "COUNTRY_TAX_POLICY_COUNTRY_MISMATCH: selected policy "
                f"{profile.profile_id!r} is for {profile.country_iso}, but project "
                f"country_iso is {info.country_iso!r}."
            )
        defaults = get_tax_jurisdiction_defaults(profile.profile_id)
        resolved = resolve_tax_assumptions(
            profile,
            defaults,
            ProjectTaxOverrides(
                corporate_tax_rate_override=tax.corporate_rate_override,
            ),
        )
        if resolved.corporate_tax_rate is None:
            # Identification-only/illustrative profiles carry no production
            # legal default. Existing explicit TaxParams behavior is preserved.
            corporate_rate = tax.corporate_rate
        else:
            corporate_rate = resolved.corporate_tax_rate
            if (
                tax.corporate_rate_override is None
                and abs(tax.corporate_rate - corporate_rate) > 1e-12
            ):
                raise ValueError(
                    "COUNTRY_TAX_LEGACY_FIELD_CONFLICT: corporate_rate differs "
                    "from the selected approved policy default. Preserve the "
                    "default value or provide corporate_rate_override explicitly."
                )
        policy_id = profile.profile_id
        policy_version = profile.profile_version

    # Periods per tax year from period frequency — fail-closed for unsupported values.
    freq = info.period_frequency
    if freq == PeriodFrequency.SEMESTRIAL:
        periods_per_tax_year = 2
    else:
        raise ValueError(
            f"build_tax_contract_from_project_inputs: unsupported period_frequency "
            f"{freq!r}. Only SEMESTRIAL (2 periods/year) is supported."
        )

    # C3B3D0: Read atad_enabled directly from TaxParams — independent of thin_cap_enabled.
    # Previously this adapter derived atad_enabled from thin_cap_enabled (wrong coupling).
    # Field default is False (generic/multi-jurisdiction safe). Old payloads without
    # atad_enabled fall back to the serialised thin_cap_enabled value via deserialization;
    # after materialisation the two fields are fully independent.
    atad_enabled: bool = tax.atad_enabled
    typed_interest_limitation = None
    if tax.interest_limitation_policy is not None:
        source_policy = tax.interest_limitation_policy
        if source_policy.enabled and atad_enabled:
            raise ValueError(
                "INTEREST_LIMITATION_AUTHORITY_CONFLICT: an enabled typed source-model "
                "interest limitation cannot be sequenced with ATAD unless an explicit "
                "combination contract is introduced"
            )
        typed_interest_limitation = InterestLimitationPolicy(
            enabled=source_policy.enabled,
            absolute_interest_limit_keur=source_policy.absolute_interest_limit_keur,
            ebitda_interest_limit_pct=source_policy.ebitda_interest_limit_pct,
            capitalisation_gate_policy=CapitalisationGatePolicy(
                enabled=source_policy.capitalisation_gate_policy.enabled,
                threshold=source_policy.capitalisation_gate_policy.threshold,
                subtotal_is_reincluded_in_denominator=(
                    source_policy.capitalisation_gate_policy
                    .subtotal_is_reincluded_in_denominator
                ),
            ),
            combination_mode=InterestLimitationCombinationMode(
                source_policy.combination_mode.value
            ),
            carryforward_mode=InterestLimitationCarryforwardMode(
                source_policy.carryforward_mode.value
            ),
            additional_non_deductible_share=(
                source_policy.additional_non_deductible_share
            ),
            source_model_convention=source_policy.source_model_convention,
        )

    # FAIL-CLOSED: ATAD with an unexplained empty period_interest is silently wrong.
    # COMPLETE_FINANCING_INTEREST_WILL_BE_INJECTED promises a later complete merge.
    # UNLEVERED_ZERO_FINANCING_INTEREST is already complete by definition.
    if (
        atad_enabled
        and interest_context is FinancingInterestContext.STANDARD_RUNTIME
    ):
        raise NotImplementedError(
            "build_tax_contract_from_project_inputs: atad_enabled=True requires complete "
            "financing-interest authority: either "
            "COMPLETE_FINANCING_INTEREST_WILL_BE_INJECTED or "
            "UNLEVERED_ZERO_FINANCING_INTEREST. STANDARD_RUNTIME cannot explain an "
            "empty period_interest vector."
        )

    # Clean cash-tax timing — fail-closed for projects without explicit opt-in.
    #
    # Two separate facts:
    #   (1) SOURCE-PROVEN: cash-tax payment lag = 0 periods (Generic Solar Reference, C3B1 evidence).
    #   (2) CLEAN ENGINE CONVENTION: annual CIT placed in last period of calendar
    #       year (TAX_YEAR_LAST_PERIOD). The workbook uses H2+H1 model-year pairing —
    #       a structurally different periodisation measured by WORKBOOK_PERIODISATION_MISMATCH.
    #       TAX_YEAR_LAST_PERIOD is NOT policy-defined for Generic Solar Reference; it is the engine convention.
    #
    # clean_cash_tax_timing_enabled=True means: "this project is explicitly permitted to
    # use the currently supported clean tax timing convention". It does NOT claim that
    # TAX_YEAR_LAST_PERIOD matches the workbook periodisation.
    if not tax.clean_cash_tax_timing_enabled:
        raise NotImplementedError(
            "build_tax_contract_from_project_inputs: clean_cash_tax_timing_enabled=False. "
            "Projects must explicitly opt in to the clean engine's cash-tax timing convention "
            "(TAX_YEAR_LAST_PERIOD, lag=0). The payment lag of 0 periods is policy-defined "
            "for Generic Solar Reference (C3B1); TAX_YEAR_LAST_PERIOD is the engine's periodisation convention "
            "and differs from the workbook H2+H1 model-year pairing. "
            "Set clean_cash_tax_timing_enabled=True in TaxParams after confirming payment lag."
        )

    policy = TaxPolicy(
        policy_id=policy_id,
        policy_version=policy_version,
        corporate_rate=corporate_rate,
        periods_per_tax_year=periods_per_tax_year,
        loss_carryforward_years=tax.loss_carryforward_years,
        atad_enabled=atad_enabled,
        atad_ebitda_limit=tax.atad_ebitda_limit,
        atad_de_minimis_threshold_keur_annual=tax.atad_min_interest_keur,
        # Clean engine convention: annual CIT in last period of each calendar year.
        # SOURCE-PROVEN (C3B1): payment lag = 0 periods.
        # NOT SOURCE-PROVEN: TAX_YEAR_LAST_PERIOD periodisation (workbook uses H2+H1).
        cash_tax_timing=CashTaxTiming.TAX_YEAR_LAST_PERIOD,
        cash_tax_payment_lag_periods=0,
        shl_interest_tax_treatment_enabled=complete_interest_will_be_injected,
        shl_interest_deductibility=ShlInterestDeductibilityMode(
            tax.shl_interest_deductibility.value
        ),
        shl_interest_deductible_pct=tax.shl_interest_deductible_pct,
        # PR-1 / P0-2: forward the typed gate from TaxParams so the clean engine
        # receives the configured policy rather than the TaxPolicy default.
        loss_utilisation_gate=TaxLossUtilisationGate(
            tax.tax_loss_utilisation_gate.value
        ),
        # Correction G: forward thin_cap_enabled so the runtime capability gate fires
        # before tax output is produced. thin_cap_enabled=True means the thin-cap
        # formula is source metadata; the runtime will raise SHL_THIN_CAP_RUNTIME_NOT_IMPLEMENTED
        # when SUBJECT_TO_LIMITATIONS is requested with thin_cap_enabled=True.
        # Do NOT silence this — no partial result, no fallback.
        thin_cap_enabled=tax.thin_cap_enabled,
        interest_limitation_policy=typed_interest_limitation,
        # NOTE: shl_limitation_enabled and shl_interest_cap_keur_annual have been removed.
        # SUBJECT_TO_LIMITATIONS is implemented via ATAD (atad_enabled=True).
    )

    # Explicit typed vintages are canonical. The legacy scalar cannot be active
    # at the same time because it has no origin year and would be a second authority.
    if tax.initial_tax_loss_keur > 0:
        raise NotImplementedError(
            "build_tax_contract_from_project_inputs: non-zero legacy "
            "initial_tax_loss_keur "
            f"({tax.initial_tax_loss_keur} kEUR) requires a vintage origin_tax_year "
            "and cannot coexist with the canonical typed authority. Set the legacy "
            "scalar to zero and provide opening_tax_loss_vintages explicitly."
        )
    opening_loss_vintages = tuple(
        OpeningTaxLossVintageInput(
            origin_tax_year=vintage.origin_tax_year,
            amount_keur=vintage.opening_amount_keur,
            source_label=vintage.source_label,
        )
        for vintage in tax.opening_tax_loss_vintages
    )

    return TaxCalculationInput(
        policy=policy,
        opening_loss_vintages=opening_loss_vintages,
        period_interest=(),
        period_adjustments=(),
    )
