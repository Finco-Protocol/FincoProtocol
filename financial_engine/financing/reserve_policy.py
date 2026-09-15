"""financial_engine.financing.reserve_policy — Shared CASH_DSRA reserve resolver.

ONE shared resolver for the effective CASH_DSRA reserve amount.
Consumed by BOTH:
  - financial_engine.financing.project_uses.compute_project_uses()
  - financial_engine.adapters.project_inputs.build_senior_debt_model_input_from_project_inputs()

Do NOT duplicate this resolution arithmetic elsewhere. Any caller that needs the
effective CASH_DSRA requirement must call resolve_cash_dsra_requirement_keur().

Reserve authority hierarchy:
  PRIMARY_TYPED_AUTHORITY:   FinancingParams.debt_service_reserve_requirement_keur
  LEGACY_COMPATIBILITY_FALLBACK: CapexStructure.reserve_accounts_keur
      (allowed only via this resolver; fallback remains for backward compatibility
       until all projects migrate to the primary typed field)

The primary field (debt_service_reserve_requirement_keur) is truly independent of
the legacy capex field (reserve_accounts_keur). Using the primary alone (with
legacy = 0) is valid and is the intended migration path.
"""
from __future__ import annotations

import math

from finco_core.inputs import DebtServiceReserveSupportMode, ProjectInputs


def _validate_reserve_field(name: str, value: float) -> None:
    """Fail closed on any invalid reserve amount at the financial boundary."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"CASH_DSRA_INVALID_FIELD: {name}={value!r} must be numeric."
        )
    if not math.isfinite(value):
        raise ValueError(
            f"CASH_DSRA_INVALID_FIELD: {name}={value!r} must be finite (NaN and ±inf rejected)."
        )
    if value < 0.0:
        raise ValueError(
            f"CASH_DSRA_INVALID_FIELD: {name}={value!r} must be >= 0."
        )


def resolve_cash_dsra_requirement_keur(project_inputs: ProjectInputs) -> float:
    """Resolve the effective CASH_DSRA reserve requirement from ProjectInputs.

    Returns the single authoritative reserve amount (kEUR) for:
    - CASH_DSRA mode: the operating opening balance and Project Uses reserve use
    - NONE mode: 0.0 (raises if either reserve field is non-zero)
    - DSRF mode: 0.0 (no cash reserve; DSRF sufficiency is handled separately)

    COD_FUNDING_HANDSHAKE invariant:
        resolve_cash_dsra_requirement_keur(pi)
        == ProjectUses.reserve_account_funding_keur
        == CashDsraInput.requirement_keur
        == first operating CashDsraPeriodResult.opening_balance_keur

    The primary field debt_service_reserve_requirement_keur is truly independent
    of reserve_accounts_keur — using primary alone (legacy=0) is fully supported
    and does not require the legacy capex field to be populated.

    Raises ValueError for:
    - Non-finite or negative values in either reserve field
    - NONE mode with any positive reserve amount
    - CASH_DSRA mode with conflicting non-zero primary and legacy values
    """
    fin = project_inputs.financing
    capex = project_inputs.capex
    mode = fin.dsra_support_mode
    req = getattr(fin, "debt_service_reserve_requirement_keur", 0.0) or 0.0
    legacy_cap = capex.reserve_accounts_keur

    # Validate both fields at the financial boundary before any logic.
    _validate_reserve_field("debt_service_reserve_requirement_keur", req)
    _validate_reserve_field("capex.reserve_accounts_keur", legacy_cap)

    if mode == DebtServiceReserveSupportMode.NONE:
        if legacy_cap > 0.0:
            raise ValueError(
                "G2A_RESERVE_ACCOUNTS_SET_BUT_MODE_IS_NONE: "
                f"reserve_accounts_keur={legacy_cap} but dsra_support_mode=NONE. "
                "Set reserve_accounts_keur=0 or change dsra_support_mode to CASH_DSRA."
            )
        if req > 0.0:
            raise ValueError(
                "G2A_RESERVE_REQUIREMENT_SET_BUT_MODE_IS_NONE: "
                f"debt_service_reserve_requirement_keur={req} but dsra_support_mode=NONE."
            )
        return 0.0

    if mode == DebtServiceReserveSupportMode.CASH_DSRA:
        if req > 0.0 and legacy_cap > 0.0 and abs(req - legacy_cap) > 1e-6:
            raise ValueError(
                "G2A_RESERVE_REQUIREMENT_CONFLICT: "
                f"debt_service_reserve_requirement_keur={req} != "
                f"capex.reserve_accounts_keur={legacy_cap}. "
                "Set one to 0 or align them."
            )
        # Primary authority: if req > 0, it controls. Otherwise fall back to legacy.
        return req if req > 0.0 else legacy_cap

    # DSRF: no cash reserve at close; DSRF sufficiency handled separately.
    return 0.0
