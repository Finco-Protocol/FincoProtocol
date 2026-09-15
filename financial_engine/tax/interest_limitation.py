"""Typed, identity-free SHL interest-limitation mechanics.

The module implements a source-model financial contract. It does not label
the contract as tax law and does not consume extracted validation artifacts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from financial_engine.policies.tax import (
    InterestLimitationCombinationMode,
    InterestLimitationPolicy,
)


@dataclass(frozen=True)
class CapitalisationState:
    """Minimum balance-sheet state required by the capitalisation gate."""

    share_capital_keur: float
    legal_reserve_keur: float
    retained_earnings_keur: float
    shl_closing_keur: float

    def __post_init__(self) -> None:
        for name in (
            "share_capital_keur",
            "legal_reserve_keur",
            "retained_earnings_keur",
            "shl_closing_keur",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"CapitalisationState.{name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"CapitalisationState.{name} must be finite")
        if self.share_capital_keur < 0.0:
            raise ValueError("share_capital_keur must be non-negative")
        if self.legal_reserve_keur < 0.0:
            raise ValueError("legal_reserve_keur must be non-negative")
        if self.shl_closing_keur < 0.0:
            raise ValueError("shl_closing_keur must be non-negative")

    @property
    def source_subtotal_keur(self) -> float:
        return (
            self.share_capital_keur
            + self.legal_reserve_keur
            + self.retained_earnings_keur
            + self.shl_closing_keur
        )


@dataclass(frozen=True)
class CapitalisationGateResult:
    source_subtotal_keur: float
    source_denominator_keur: float
    ratio: float
    threshold: float
    active: bool


@dataclass(frozen=True)
class InterestLimitationPeriodInput:
    period_index: int
    gross_shl_interest_keur: float
    ebitda_basis_keur: float
    capitalisation_state: CapitalisationState

    def __post_init__(self) -> None:
        for name in ("gross_shl_interest_keur", "ebitda_basis_keur"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"InterestLimitationPeriodInput.{name} must be numeric")
            if not math.isfinite(float(value)):
                raise ValueError(f"InterestLimitationPeriodInput.{name} must be finite")
        if self.gross_shl_interest_keur < 0.0:
            raise ValueError("gross_shl_interest_keur must be non-negative")


@dataclass(frozen=True)
class InterestLimitationPeriodResult:
    period_index: int
    gross_shl_interest_keur: float
    ebitda_basis_keur: float
    capitalisation_gate: CapitalisationGateResult
    absolute_limit_component_keur: float
    ebitda_limit_component_keur: float
    additional_non_deductible_component_keur: float
    disallowed_shl_interest_keur: float
    deductible_shl_interest_keur: float
    restricted_interest_carryforward_created_keur: float
    source_model_convention: str


@dataclass(frozen=True)
class EquityStatePeriodInput:
    period_index: int
    net_income_keur: float
    gross_dividends_keur: float = 0.0


@dataclass(frozen=True)
class EquityStatePeriodResult:
    period_index: int
    opening_legal_reserve_keur: float
    legal_reserve_transfer_keur: float
    closing_legal_reserve_keur: float
    opening_retained_earnings_keur: float
    retained_earnings_movement_keur: float
    closing_retained_earnings_keur: float
    residual_keur: float


def calculate_capitalisation_gate(
    state: CapitalisationState,
    policy: InterestLimitationPolicy,
) -> CapitalisationGateResult:
    """Calculate the literal typed balance-sheet gate.

    Equality is active because the source comparison is ``ratio < threshold``
    for OFF and TRUE otherwise.
    """

    gate_policy = policy.capitalisation_gate_policy
    subtotal = state.source_subtotal_keur
    denominator = subtotal
    if gate_policy.subtotal_is_reincluded_in_denominator:
        denominator += subtotal
    if not gate_policy.enabled:
        ratio = 0.0
        active = False
    else:
        if abs(denominator) <= 1e-12:
            raise ValueError(
                "CAPITALISATION_GATE_ZERO_DENOMINATOR: literal source denominator "
                "is zero; no ratio or tax result may be produced"
            )
        ratio = state.shl_closing_keur / denominator
        active = ratio >= gate_policy.threshold
    return CapitalisationGateResult(
        source_subtotal_keur=subtotal,
        source_denominator_keur=denominator,
        ratio=ratio,
        threshold=gate_policy.threshold,
        active=active,
    )


def calculate_interest_limitation_period(
    period_input: InterestLimitationPeriodInput,
    policy: InterestLimitationPolicy,
) -> InterestLimitationPeriodResult:
    """Calculate one period using deductible-only arithmetic."""

    gross = period_input.gross_shl_interest_keur
    gate = calculate_capitalisation_gate(period_input.capitalisation_state, policy)
    if not policy.enabled or not gate.active:
        absolute_component = 0.0
        ebitda_component = 0.0
    else:
        absolute_component = max(gross - policy.absolute_interest_limit_keur, 0.0)
        ebitda_component = max(
            gross - policy.ebitda_interest_limit_pct * period_input.ebitda_basis_keur,
            0.0,
        )

    additional = gross * policy.additional_non_deductible_share
    if policy.combination_mode is InterestLimitationCombinationMode.MAX_DISALLOWED:
        combined = max(absolute_component, ebitda_component) + additional
    elif policy.combination_mode is InterestLimitationCombinationMode.SUM_DISALLOWED:
        combined = absolute_component + ebitda_component + additional
    else:  # pragma: no cover - enum validation makes this unreachable
        raise ValueError(f"Unsupported combination mode: {policy.combination_mode!r}")

    disallowed = min(max(combined, 0.0), gross)
    deductible = gross - disallowed
    if abs((deductible + disallowed) - gross) > 1e-10:
        raise ArithmeticError("SHL_DEDUCTIBLE_DISALLOWED_IDENTITY_BROKEN")

    return InterestLimitationPeriodResult(
        period_index=period_input.period_index,
        gross_shl_interest_keur=gross,
        ebitda_basis_keur=period_input.ebitda_basis_keur,
        capitalisation_gate=gate,
        absolute_limit_component_keur=absolute_component,
        ebitda_limit_component_keur=ebitda_component,
        additional_non_deductible_component_keur=additional,
        disallowed_shl_interest_keur=disallowed,
        deductible_shl_interest_keur=deductible,
        restricted_interest_carryforward_created_keur=0.0,
        source_model_convention=policy.source_model_convention,
    )


def roll_forward_equity_state(
    period_inputs: tuple[EquityStatePeriodInput, ...],
    *,
    share_capital_keur: float,
    legal_reserve_cap_fraction: float,
    opening_legal_reserve_keur: float = 0.0,
    opening_retained_earnings_keur: float = 0.0,
) -> tuple[EquityStatePeriodResult, ...]:
    """Roll the minimum source equity state required by the gate.

    The legal reserve receives positive net income up to the configured share-
    capital cap.  Retained earnings receives net income less gross dividends
    and that reserve transfer.
    """

    if share_capital_keur < 0.0:
        raise ValueError("share_capital_keur must be non-negative")
    if not 0.0 <= legal_reserve_cap_fraction <= 1.0:
        raise ValueError("legal_reserve_cap_fraction must be in [0, 1]")
    reserve = opening_legal_reserve_keur
    retained = opening_retained_earnings_keur
    maximum_reserve = share_capital_keur * legal_reserve_cap_fraction
    results: list[EquityStatePeriodResult] = []
    for period in period_inputs:
        opening_reserve = reserve
        opening_retained = retained
        reserve_transfer = (
            min(period.net_income_keur, maximum_reserve - opening_reserve)
            if period.net_income_keur > 0.0 and opening_reserve < maximum_reserve
            else 0.0
        )
        reserve = opening_reserve + reserve_transfer
        retained_movement = (
            period.net_income_keur
            - period.gross_dividends_keur
            - reserve_transfer
        )
        retained = opening_retained + retained_movement
        residual = retained - (opening_retained + retained_movement)
        results.append(EquityStatePeriodResult(
            period_index=period.period_index,
            opening_legal_reserve_keur=opening_reserve,
            legal_reserve_transfer_keur=reserve_transfer,
            closing_legal_reserve_keur=reserve,
            opening_retained_earnings_keur=opening_retained,
            retained_earnings_movement_keur=retained_movement,
            closing_retained_earnings_keur=retained,
            residual_keur=residual,
        ))
    return tuple(results)


__all__ = [
    "CapitalisationState",
    "CapitalisationGateResult",
    "InterestLimitationPeriodInput",
    "InterestLimitationPeriodResult",
    "EquityStatePeriodInput",
    "EquityStatePeriodResult",
    "calculate_capitalisation_gate",
    "calculate_interest_limitation_period",
    "roll_forward_equity_state",
]
