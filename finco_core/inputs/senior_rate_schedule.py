"""Senior debt rate and day-count schedule helpers.

Authoritative location: finco_core.inputs.senior_rate_schedule (V2-2).
Legacy location finco_core.inputs.senior_rate_schedule re-exports from here.

This module is deliberately small and independent from the waterfall engine.
It builds the existing per-period ``rate_schedule`` input used by the senior
debt calculations, leaving legacy flat-rate behavior untouched unless a caller
explicitly opts in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Sequence


class SeniorRateMode(Enum):
    """Supported ways to derive the annual all-in senior debt rate."""

    FLAT_ALL_IN = "flat_all_in"
    FIXED_PLUS_MARGIN = "fixed_plus_margin"
    FLOATING_PLUS_MARGIN = "floating_plus_margin"
    HEDGE_BLEND = "hedge_blend"
    EXPLICIT_ALL_IN_SCHEDULE = "explicit_all_in_schedule"


class SeniorDayCountConvention(Enum):
    """Supported senior debt interest period-fraction conventions."""

    FIXED_SEMIANNUAL = "fixed_semiannual"
    ACT_360 = "act_360"
    ACT_365 = "act_365"
    EXPLICIT_FRACTIONS = "explicit_fractions"


@dataclass(frozen=True)
class SeniorHedgeConfig:
    """Parameters for blending fixed and floating base-rate components."""

    hedge_pct: float = 0.0
    fixed_base_rate: float = 0.0
    floating_base_rate_curve: tuple[float, ...] = ()
    floating_curve_buffer_pct: float = 0.0


@dataclass(frozen=True)
class SeniorRateSchedule:
    """Annual senior all-in rate schedule configuration."""

    mode: SeniorRateMode = SeniorRateMode.FLAT_ALL_IN
    flat_all_in_rate: float = 0.0
    fixed_base_rate: float = 0.0
    margin_rate: float = 0.0
    hedge: SeniorHedgeConfig | None = None
    explicit_all_in_rates: tuple[float, ...] = ()

    def all_in_rate_for_period(self, period_index: int) -> float:
        """Return the annual all-in senior debt rate for a 0-based period."""
        if period_index < 0:
            raise ValueError("period_index must be non-negative")

        if self.mode == SeniorRateMode.FLAT_ALL_IN:
            return _validate_rate(self.flat_all_in_rate)

        if self.mode == SeniorRateMode.FIXED_PLUS_MARGIN:
            return _validate_rate(self.fixed_base_rate + self.margin_rate)

        if self.mode == SeniorRateMode.FLOATING_PLUS_MARGIN:
            hedge = self._require_hedge()
            floating = _curve_value(hedge.floating_base_rate_curve, period_index)
            floating *= 1 + hedge.floating_curve_buffer_pct
            return _validate_rate(floating + self.margin_rate)

        if self.mode == SeniorRateMode.HEDGE_BLEND:
            hedge = self._require_hedge()
            if not 0 <= hedge.hedge_pct <= 1:
                raise ValueError("hedge_pct must be between 0 and 1")
            floating = _curve_value(hedge.floating_base_rate_curve, period_index)
            floating *= 1 + hedge.floating_curve_buffer_pct
            fixed_component = hedge.hedge_pct * hedge.fixed_base_rate
            floating_component = (1 - hedge.hedge_pct) * floating
            return _validate_rate(fixed_component + floating_component + self.margin_rate)

        if self.mode == SeniorRateMode.EXPLICIT_ALL_IN_SCHEDULE:
            return _validate_rate(_curve_value(self.explicit_all_in_rates, period_index))

        raise ValueError(f"Unsupported senior rate mode: {self.mode}")

    def _require_hedge(self) -> SeniorHedgeConfig:
        if self.hedge is None:
            raise ValueError(f"{self.mode.value} requires SeniorHedgeConfig")
        return self.hedge


@dataclass(frozen=True)
class SeniorDebtInterestConfig:
    """Opt-in senior debt interest schedule configuration."""

    enabled: bool = False
    rate_schedule: SeniorRateSchedule = field(default_factory=SeniorRateSchedule)
    day_count: SeniorDayCountConvention = SeniorDayCountConvention.FIXED_SEMIANNUAL
    explicit_period_fractions: tuple[float, ...] = ()


def build_senior_period_rate_schedule(
    config: SeniorDebtInterestConfig,
    periods: Sequence[object],
    tenor_periods: int,
) -> list[float]:
    """Build per-period senior rate factors for the existing waterfall path.

    The returned values are period rates, not annual rates:
    ``annual_all_in_rate[t] * period_fraction[t]``.
    """
    if tenor_periods < 0:
        raise ValueError("tenor_periods must be non-negative")
    if tenor_periods == 0:
        return []
    if len(periods) < tenor_periods:
        raise ValueError("periods must cover tenor_periods")

    _validate_schedule_lengths(config, tenor_periods)

    factors: list[float] = []
    for idx in range(tenor_periods):
        annual_rate = config.rate_schedule.all_in_rate_for_period(idx)
        fraction = senior_period_fraction(config, idx, periods[idx])
        factors.append(annual_rate * fraction)
    return factors


def senior_period_fraction(
    config: SeniorDebtInterestConfig,
    period_index: int,
    period: object,
) -> float:
    """Return the period fraction for one senior debt interest period."""
    if config.day_count == SeniorDayCountConvention.FIXED_SEMIANNUAL:
        return 0.5

    if config.day_count == SeniorDayCountConvention.EXPLICIT_FRACTIONS:
        return _validate_fraction(config.explicit_period_fractions[period_index])

    start = getattr(period, "start_date", None)
    end = getattr(period, "end_date", None)
    if not isinstance(start, date) or not isinstance(end, date):
        raise ValueError(f"{config.day_count.value} requires period start_date and end_date")
    if end < start:
        raise ValueError("period end_date must be on or after start_date")

    days = (end - start).days + 1
    if config.day_count == SeniorDayCountConvention.ACT_360:
        return _validate_fraction(days / 360.0)
    if config.day_count == SeniorDayCountConvention.ACT_365:
        return _validate_fraction(days / 365.0)

    raise ValueError(f"Unsupported day-count convention: {config.day_count}")


def _validate_schedule_lengths(config: SeniorDebtInterestConfig, tenor_periods: int) -> None:
    if config.day_count == SeniorDayCountConvention.EXPLICIT_FRACTIONS:
        if len(config.explicit_period_fractions) < tenor_periods:
            raise ValueError("explicit_period_fractions must cover tenor_periods")
        for value in config.explicit_period_fractions[:tenor_periods]:
            _validate_fraction(value)

    if config.rate_schedule.mode == SeniorRateMode.EXPLICIT_ALL_IN_SCHEDULE:
        if len(config.rate_schedule.explicit_all_in_rates) < tenor_periods:
            raise ValueError("explicit_all_in_rates must cover tenor_periods")
        for value in config.rate_schedule.explicit_all_in_rates[:tenor_periods]:
            _validate_rate(value)


def _curve_value(values: Sequence[float], period_index: int) -> float:
    if not values:
        raise ValueError("rate curve must not be empty")
    if period_index >= len(values):
        raise ValueError("rate curve must cover requested period")
    return values[period_index]


def _validate_rate(value: float) -> float:
    if value < 0:
        raise ValueError("senior rate values must be non-negative")
    return value


def _validate_fraction(value: float) -> float:
    if value < 0:
        raise ValueError("senior period fractions must be non-negative")
    return value
