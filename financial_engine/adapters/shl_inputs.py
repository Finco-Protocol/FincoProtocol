"""financial_engine.adapters.shl_inputs — ProjectInputs → ShlSchedulePolicy adapter (C3B3D1).

Maps canonical ProjectInputs.financing to ShlSchedulePolicy.

IMPORTANT: This adapter is NOT wired into orchestrator.py, waterfall_engine.py,
or any existing production path. It is adapter foundation only.
Production runtime wiring is deferred to C3B3D2.

Lineage notes:
  GENERIC_SOLAR_REFERENCE_SHL_BALANCE_LINEAGE_UNRESOLVED — construction → operating opening balance
      transition cannot be proven from committed source evidence alone. The adapter
      does NOT promote Generic Solar Reference or Generic Wind Reference to the canonical schedule runtime.
  REFERENCE_WIND_SHL_BALANCE_LINEAGE_UNRESOLVED — same boundary status as Generic Solar Reference.

Payment mode status (C3B3D1_BLOCKED_PAYMENT_MODE_SEMANTICS):
  shl_pik_switch_period is defined in FinancingParams but is NOT consumed by any
  runtime code outside serialization. The legacy waterfall engine computes
  pik_switch_triggered at runtime from (cf_for_shl > shl_balance × shl_rate) —
  it does NOT read shl_pik_switch_period. Therefore shl_pik_switch_period=0 does
  not have a proven semantic mapping to CASH_PAID for every operating period.
  Payment mode derivation is fail-closed until D2 source evidence is established.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from finco_core.inputs import ProjectInputs

from financial_engine.shl.contracts import (
    ShlRepaymentMode,
    ShlSchedulePolicy,
)

# SHL repayment method strings that require FCF-waterfall cash integration (D2 scope).
_FCF_WATERFALL_METHODS = frozenset({
    "fcf_waterfall",
    "cash_sweep",
    "partial_pay_sweep",
    "pik_then_sweep",
})

# SHL repayment method strings that map to BULLET.
_BULLET_METHODS = frozenset({"bullet"})


def build_shl_repayment_mode_from_project_inputs(
    project: "ProjectInputs",
) -> ShlRepaymentMode:
    """Derive ShlRepaymentMode from ProjectInputs.financing.shl_repayment_method.

    Raises
    ------
    NotImplementedError
        C3B3D1_BLOCKED_FCF_REPAYMENT — FCF-waterfall methods.
        C3B3D1_BLOCKED_LEGACY_REPAYMENT_SEMANTICS — pik/accrued (no proven mapping).
        C3B3D1_BLOCKED_UNKNOWN_REPAYMENT — unrecognised method string.
    """
    financing = project.financing
    method_raw: str = getattr(financing, "shl_repayment_method", "bullet")
    method = (method_raw or "bullet").strip().lower()

    if method in _FCF_WATERFALL_METHODS:
        raise NotImplementedError(
            f"C3B3D1_BLOCKED_FCF_REPAYMENT: shl_repayment_method={method_raw!r} "
            "requires FCF-waterfall cash integration (C3B3D2 scope). "
            "Canonical SHL schedule cannot be built for this configuration in C3B3D1."
        )
    elif method in _BULLET_METHODS:
        return ShlRepaymentMode.BULLET
    elif method in ("pik", "accrued"):
        raise NotImplementedError(
            f"C3B3D1_BLOCKED_LEGACY_REPAYMENT_SEMANTICS: shl_repayment_method={method_raw!r} "
            "has no proven mapping to ShlRepaymentMode.EXPLICIT_SCHEDULE. "
            "Canonical adapter cannot silently assume period-principal semantics "
            "for this method string. Deferred to C3B3D2 with source evidence."
        )
    else:
        raise NotImplementedError(
            f"C3B3D1_BLOCKED_UNKNOWN_REPAYMENT: shl_repayment_method={method_raw!r} "
            "is not recognised by the C3B3D1 canonical adapter. "
            "Add mapping or check FinancingParams SHLRepaymentMethod enum."
        )


def build_shl_schedule_policy_from_project_inputs(
    project: "ProjectInputs",
) -> ShlSchedulePolicy:
    """Map ProjectInputs.financing to ShlSchedulePolicy.

    Parameters
    ----------
    project : ProjectInputs
        Canonical project inputs.

    Returns
    -------
    ShlSchedulePolicy
        Policy derived from the project's financing parameters.

    Notes
    -----
    * shl_amount_keur is used only for validation/reference. The canonical
      opening balance is NOT shl_amount_keur — it comes from the construction
      output (seam deferred to C3B3D2, labelled C3B3D2_CONSTRUCTION_SEAM).
    * Payment mode (CASH_PAID vs PIK) cannot be derived from FinancingParams
      in C3B3D1. shl_pik_switch_period is not consumed by any runtime and has
      no proven semantic: shl_pik_switch_period=0 does NOT mean CASH_PAID.
      Fail-closed: C3B3D1_BLOCKED_PAYMENT_MODE_SEMANTICS.
    * No project.name or project.code dispatch.

    Raises
    ------
    NotImplementedError
        C3B3D1_BLOCKED_FCF_REPAYMENT — FCF-waterfall repayment methods.
        C3B3D1_BLOCKED_LEGACY_REPAYMENT_SEMANTICS — pik/accrued method strings.
        C3B3D1_BLOCKED_MIXED_PAYMENT_MODE — shl_pik_switch_period > 0.
        C3B3D1_BLOCKED_PAYMENT_MODE_SEMANTICS — shl_pik_switch_period == 0 has
          no proven mapping to CASH_PAID; payment mode cannot be derived safely.
        C3B3D1_BLOCKED_UNKNOWN_REPAYMENT — unrecognised repayment method string.
    ValueError
        When shl_rate is not finite or is negative.
    """
    financing = project.financing

    # ── annual rate ─────────────────────────────────────────────────────────
    annual_rate: float = financing.shl_rate
    # Validation is delegated to ShlSchedulePolicy.__post_init__.

    # ── repayment mode ───────────────────────────────────────────────────────
    repayment_mode = build_shl_repayment_mode_from_project_inputs(project)

    # ── interest payment mode ────────────────────────────────────────────────
    # shl_pik_switch_period > 0 → mixed PIK→cash (fail-closed, D2 scope).
    # shl_pik_switch_period == 0 → NOT proven to mean CASH_PAID (fail-closed,
    #   shl_pik_switch_period is unused by runtime; legacy waterfall computes
    #   pik_switch_triggered from cf_for_shl > shl_balance × shl_rate at runtime).
    pik_switch: int = getattr(financing, "shl_pik_switch_period", 0) or 0
    if pik_switch > 0:
        raise NotImplementedError(
            f"C3B3D1_BLOCKED_MIXED_PAYMENT_MODE: shl_pik_switch_period={pik_switch!r} "
            "requires period-level payment mode switching (C3B3D2 scope). "
            "Canonical SHL schedule cannot model PIK→cash transitions in C3B3D1."
        )
    # pik_switch == 0: still blocked — no committed source evidence proves
    # this means CASH_PAID for every operating period.
    raise NotImplementedError(
        "C3B3D1_BLOCKED_PAYMENT_MODE_SEMANTICS: shl_pik_switch_period=0 has no "
        "proven semantic mapping to ShlInterestPaymentMode.CASH_PAID. "
        "The field is unused by any runtime (legacy waterfall derives pik_switch_triggered "
        "from cf_for_shl > shl_balance × shl_rate at runtime). "
        "Interest payment mode cannot be derived safely from FinancingParams in C3B3D1. "
        "Deferred to C3B3D2 with authoritative source evidence."
    )
