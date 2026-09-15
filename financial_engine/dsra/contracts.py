"""financial_engine.dsra.contracts — Input/output contracts for CASH_DSRA roll-forward.

Pure typed dataclasses. No imports from app, legacy waterfall, project factories,
Excel fixtures, or diagnostic scripts. No project-name dispatch.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from finco_core.inputs import DebtServiceReserveSupportMode
from financial_engine.dsra.target import DsraTargetPolicy


@dataclass(frozen=True)
class CashDsraInput:
    """Input contract for the clean CASH_DSRA roll-forward engine.

    mode:
        NONE      — neutral pass-through; requirement_keur must be 0.
        CASH_DSRA — canonical roll-forward; opening at first operating period = requirement_keur
                    (COD funding handshake: construction financing funds reserve as a Project Use).
        DSRF      — pass-through; DSRF fee handled by financial_engine.financing.dsrf.
                    No draw engine added here.

    requirement_keur:
        Actual initial/COD reserve cash funded as a Project Use. For FIXED_AMOUNT
        it is also the static operating target. For FORWARD_DEBT_SERVICE_MONTHS
        it remains opening cash while required_balance_schedule supplies targets.
        Source authority: FinancingParams.debt_service_reserve_requirement_keur.
        NONE mode: must be 0.0 — raises if > 0.

    required_balance_schedule:
        Optional pre-built per-period required-balance tuple from
        financial_engine.dsra.target.build_dsra_required_balance_schedule().
        When provided (FORWARD_DEBT_SERVICE_MONTHS policy), the model uses this
        schedule period-by-period instead of the static scalar.
        Must be the same length as the period_indices passed to run_cash_dsra_model().
        Construction periods must have value 0.0 (enforced by build function).
        For FIXED_AMOUNT: must be None (CASH_DSRA_FIXED_AMOUNT_AUTHORITY_CONFLICT if set).
        For FORWARD_DEBT_SERVICE_MONTHS: must be provided (CASH_DSRA_DYNAMIC_TARGET_SCHEDULE_REQUIRED if None).

    CASH_DSRA_TARGET_AUTHORITY (PR-3B):
        Two explicit policies are supported:
          FIXED_AMOUNT — static scalar requirement_keur every operating period.
          FORWARD_DEBT_SERVICE_MONTHS — pre-built dynamic schedule via required_balance_schedule.
        Policy is determined by the EXPLICIT typed target_policy field, not inferred from nullable schedule.
    """
    mode: DebtServiceReserveSupportMode
    requirement_keur: float = 0.0
    required_balance_schedule: tuple[float, ...] | None = field(default=None)

    # Policy is explicit and typed. Never inferred from nullable required_balance_schedule.
    # FIXED_AMOUNT (default): static scalar requirement_keur. Backward-compatible.
    # FORWARD_DEBT_SERVICE_MONTHS: dynamic schedule from Senior DS.
    #     requires dsra_months > 0 and mode == CASH_DSRA.
    #     Orchestrator must build required_balance_schedule before calling run_cash_dsra_model.
    target_policy: DsraTargetPolicy = field(default=DsraTargetPolicy.FIXED_AMOUNT)

    # Number of Operation months of forward Senior DS to cover.
    # Only consumed when target_policy == FORWARD_DEBT_SERVICE_MONTHS.
    # Source: FinancingParams.dsra_months (operation-only compatibility alias).
    dsra_months: int = field(default=6)

    def __post_init__(self) -> None:
        if not isinstance(self.mode, DebtServiceReserveSupportMode):
            raise ValueError(
                f"CashDsraInput: mode must be DebtServiceReserveSupportMode, got {self.mode!r}."
            )
        if not isinstance(self.requirement_keur, (int, float)) or isinstance(self.requirement_keur, bool):
            raise ValueError(
                f"CashDsraInput: requirement_keur must be numeric, got {self.requirement_keur!r}."
            )
        if not math.isfinite(self.requirement_keur):
            raise ValueError(
                f"CashDsraInput: requirement_keur must be finite, got {self.requirement_keur!r}. "
                "NaN and ±inf are rejected."
            )
        if self.requirement_keur < 0.0:
            raise ValueError(
                f"CashDsraInput: requirement_keur must be >= 0, got {self.requirement_keur!r}."
            )
        if (
            self.mode == DebtServiceReserveSupportMode.NONE
            and self.requirement_keur > 0.0
        ):
            raise ValueError(
                "CashDsraInput: mode=NONE but requirement_keur > 0. "
                "NONE mode implies no reserve — set requirement_keur=0.0 "
                "or change mode to CASH_DSRA."
            )
        if not isinstance(self.target_policy, DsraTargetPolicy):
            raise ValueError(
                f"CashDsraInput: target_policy must be DsraTargetPolicy, got {self.target_policy!r}."
            )
        if not isinstance(self.dsra_months, int) or isinstance(self.dsra_months, bool):
            raise ValueError(
                f"CashDsraInput: dsra_months must be an integer, got {self.dsra_months!r}."
            )
        if (
            self.target_policy == DsraTargetPolicy.FORWARD_DEBT_SERVICE_MONTHS
            and self.dsra_months <= 0
        ):
            raise ValueError(
                "CashDsraInput: FORWARD_DEBT_SERVICE_MONTHS requires dsra_months > 0, "
                f"got {self.dsra_months!r}."
            )
        if (
            self.target_policy == DsraTargetPolicy.FORWARD_DEBT_SERVICE_MONTHS
            and self.mode != DebtServiceReserveSupportMode.CASH_DSRA
        ):
            raise ValueError(
                "CashDsraInput: FORWARD_DEBT_SERVICE_MONTHS policy requires mode=CASH_DSRA, "
                f"got mode={self.mode!r}."
            )
        if self.required_balance_schedule is not None:
            if not isinstance(self.required_balance_schedule, tuple):
                raise ValueError(
                    "CashDsraInput: required_balance_schedule must be a tuple or None."
                )
            for i, v in enumerate(self.required_balance_schedule):
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    raise ValueError(
                        f"CashDsraInput: required_balance_schedule[{i}]={v!r} must be numeric."
                    )
                if not math.isfinite(v):
                    raise ValueError(
                        f"CashDsraInput: required_balance_schedule[{i}]={v!r} must be finite."
                    )
                if v < 0.0:
                    raise ValueError(
                        f"CashDsraInput: required_balance_schedule[{i}]={v!r} must be >= 0."
                    )


@dataclass(frozen=True)
class CashDsraPeriodResult:
    """CASH_DSRA roll-forward result for one model period.

    Cash conservation identity (must hold per period):
        cash_before_dsra_keur - top_up_keur + draw_to_cover_shortfall_keur + release_keur
        == cash_after_dsra_keur

    Balance conservation identity (must hold per period):
        opening_balance_keur + top_up_keur - draw_to_cover_shortfall_keur - release_keur
        == closing_balance_keur
    """
    period_index: int
    is_construction: bool
    opening_balance_keur: float
    required_balance_keur: float
    cash_before_dsra_keur: float
    draw_to_cover_shortfall_keur: float
    top_up_keur: float
    release_keur: float
    closing_balance_keur: float
    cash_after_dsra_keur: float
    shortfall_keur: float
    target_met: bool


@dataclass(frozen=True)
class CashDsraSchedules:
    """Canonical CASH_DSRA roll-forward schedule for all model periods.

    PR-3 reserve authority. Exposes cash_after_dsra_keur per period as the
    reserve-adjusted downstream cash signal. DA / SHL routing is PR-4.

    SOURCE_PROVEN_EXCESS_RELEASE:
        In an operating period, reserve cash above required_balance_keur is
        released. This mirrors the workbook CF Operation row and preserves both
        reserve and cash conservation.

    COD_FUNDING_HANDSHAKE:
        For CASH_DSRA mode: opening_balance at first operating period == requirement_keur,
        including FORWARD_DEBT_SERVICE_MONTHS. A dynamic target never creates cash.
        This reconciles to the construction reserve use in project_uses.py
        (reserve_account_funding_keur == debt_service_reserve_requirement_keur at close).
    """
    mode: str
    requirement_keur: float
    period_results: tuple[CashDsraPeriodResult, ...]
    total_top_up_keur: float
    total_draw_keur: float
    total_release_keur: float
    final_closing_balance_keur: float
    diagnostics: tuple[str, ...]
