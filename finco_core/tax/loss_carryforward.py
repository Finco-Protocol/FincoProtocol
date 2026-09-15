"""Offline rolling tax loss carry-forward engine.

The engine is intentionally standalone: it does not change the legacy tax
engine and callers must explicitly feed signed taxable income before losses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class LossCarryforwardConfig:
    """Configuration for a rolling loss carry-forward schedule."""

    duration_years: int = 5
    periods_per_year: int = 2
    explicit_override_periods: int | None = None
    expiry_method: str = "fifo_per_vintage"
    country_template: str = "generic"
    loss_usage_order: str = "fifo"
    expire_before_use: bool = False

    def __init__(
        self,
        duration_years: int = 5,
        periods_per_year: int = 2,
        explicit_override_periods: int | None = None,
        expiry_method: str = "fifo_per_vintage",
        country_template: str = "generic",
        loss_usage_order: str = "fifo",
        expire_before_use: bool = False,
        max_carryforward_years: int | None = None,
    ) -> None:
        if max_carryforward_years is not None:
            if max_carryforward_years <= 0:
                raise ValueError("max_carryforward_years must be positive")
            duration_years = max_carryforward_years

        object.__setattr__(self, "duration_years", duration_years)
        object.__setattr__(self, "periods_per_year", periods_per_year)
        object.__setattr__(self, "explicit_override_periods", explicit_override_periods)
        object.__setattr__(self, "expiry_method", expiry_method)
        object.__setattr__(self, "country_template", country_template)
        object.__setattr__(self, "loss_usage_order", loss_usage_order)
        object.__setattr__(self, "expire_before_use", expire_before_use)
        self.__post_init__()

    @property
    def duration_periods(self) -> int:
        if self.explicit_override_periods is not None:
            return self.explicit_override_periods
        return self.duration_years * self.periods_per_year

    @property
    def max_carryforward_years(self) -> int:
        """Backward-compatible alias for the original config field."""

        return self.duration_years

    @property
    def max_carryforward_periods(self) -> int:
        """Backward-compatible alias for duration_periods."""

        return self.duration_periods

    def __post_init__(self) -> None:
        if self.duration_years <= 0:
            raise ValueError("duration_years must be positive")
        if self.periods_per_year <= 0:
            raise ValueError("periods_per_year must be positive")
        if self.explicit_override_periods is not None and self.explicit_override_periods <= 0:
            raise ValueError("explicit_override_periods must be positive")
        if self.expiry_method != "fifo_per_vintage":
            raise ValueError("Only fifo_per_vintage expiry is implemented")
        if self.loss_usage_order != "fifo":
            raise ValueError("Only FIFO loss usage is implemented")

    @classmethod
    def excel_compatibility(
        cls,
        *,
        override_periods: int,
        duration_years: int = 5,
        periods_per_year: int = 2,
        country_template: str = "excel_compatibility",
    ) -> "LossCarryforwardConfig":
        """Build an explicit workbook-parity config for non-law windows."""

        return cls(
            duration_years=duration_years,
            periods_per_year=periods_per_year,
            explicit_override_periods=override_periods,
            country_template=country_template,
            expire_before_use=True,
        )


@dataclass(frozen=True)
class LossCarryforwardBucket:
    """One loss vintage, tracked from generation through expiry and usage."""

    amount_keur: float
    periods_remaining: int
    source_period_index: int | None = None
    source_label: str = ""
    generated_loss_keur: float | None = None
    remaining_loss_keur: float | None = None
    expiry_period_index: int | None = None

    def __post_init__(self) -> None:
        if self.amount_keur < 0:
            raise ValueError("Loss bucket amount must be non-negative")
        if self.periods_remaining < 0:
            raise ValueError("Loss bucket periods_remaining must be non-negative")
        if self.generated_loss_keur is not None and self.generated_loss_keur < 0:
            raise ValueError("Loss bucket generated_loss_keur must be non-negative")
        if self.remaining_loss_keur is not None and self.remaining_loss_keur < 0:
            raise ValueError("Loss bucket remaining_loss_keur must be non-negative")
        if self.expiry_period_index is not None and self.expiry_period_index < 0:
            raise ValueError("Loss bucket expiry_period_index must be non-negative")
        if self.generated_loss_keur is None:
            object.__setattr__(self, "generated_loss_keur", self.amount_keur)
        if self.remaining_loss_keur is None:
            object.__setattr__(self, "remaining_loss_keur", self.amount_keur)
        if abs(self.amount_keur - float(self.remaining_loss_keur)) > 1e-9:
            raise ValueError("Loss bucket amount_keur must equal remaining_loss_keur")


def _bucket_is_expired(
    bucket: LossCarryforwardBucket,
    period_index: int,
    config: LossCarryforwardConfig,
) -> bool:
    if not config.expire_before_use:
        return False
    if bucket.expiry_period_index is not None:
        return period_index >= bucket.expiry_period_index
    return bucket.periods_remaining <= 1


def _periods_remaining_after_period(
    bucket: LossCarryforwardBucket,
    period_index: int,
) -> int:
    if bucket.expiry_period_index is not None:
        return max(bucket.expiry_period_index - period_index, 0)
    return max(bucket.periods_remaining - 1, 0)


@dataclass(frozen=True)
class LossCarryforwardPeriodInput:
    """Single-period signed taxable income input before loss usage."""

    period_index: int
    taxable_income_before_losses_keur: float
    opening_buckets: tuple[LossCarryforwardBucket, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LossCarryforwardPeriodResult:
    """Audit result matching Excel loss carry-forward rows R36-R41."""

    period_index: int
    taxable_income_before_losses_keur: float
    losses_n_1_keur: float
    allocated_losses_keur: float
    losses_n_keur: float
    carriable_losses_keur: float
    losses_generated_keur: float
    expired_losses_keur: float
    taxable_profit_after_losses_keur: float
    opening_buckets: tuple[LossCarryforwardBucket, ...]
    closing_buckets: tuple[LossCarryforwardBucket, ...]


@dataclass(frozen=True)
class LossCarryforwardResult:
    """Full rolling loss carry-forward result."""

    periods: tuple[LossCarryforwardPeriodResult, ...]
    config: LossCarryforwardConfig

    @property
    def total_losses_used_keur(self) -> float:
        return sum(period.allocated_losses_keur for period in self.periods)

    @property
    def total_losses_generated_keur(self) -> float:
        return sum(period.losses_generated_keur for period in self.periods)

    @property
    def total_expired_losses_keur(self) -> float:
        return sum(period.expired_losses_keur for period in self.periods)


def compute_loss_carryforward_period(
    period_input: LossCarryforwardPeriodInput,
    config: LossCarryforwardConfig,
) -> LossCarryforwardPeriodResult:
    """Compute one FIFO rolling loss carry-forward period."""

    raw_opening_buckets = tuple(
        bucket for bucket in period_input.opening_buckets if bucket.amount_keur > 0
    )
    expired_at_open = tuple(
        bucket
        for bucket in raw_opening_buckets
        if _bucket_is_expired(bucket, period_input.period_index, config)
    )
    opening_buckets = tuple(
        bucket
        for bucket in raw_opening_buckets
        if not _bucket_is_expired(bucket, period_input.period_index, config)
    )
    opening_loss = sum(bucket.amount_keur for bucket in opening_buckets)
    taxable_before = period_input.taxable_income_before_losses_keur
    expired_losses = sum(bucket.amount_keur for bucket in expired_at_open)

    losses_used = 0.0
    taxable_profit = 0.0
    retained_buckets: list[LossCarryforwardBucket] = []

    if taxable_before > 0:
        remaining_income = taxable_before
        for bucket in opening_buckets:
            use_amount = min(bucket.amount_keur, remaining_income)
            losses_used += use_amount
            remaining_income -= use_amount
            residual = bucket.amount_keur - use_amount
            if residual > 0:
                retained_buckets.append(
                    LossCarryforwardBucket(
                        amount_keur=residual,
                        periods_remaining=bucket.periods_remaining,
                        source_period_index=bucket.source_period_index,
                        source_label=bucket.source_label,
                        generated_loss_keur=bucket.generated_loss_keur,
                        remaining_loss_keur=residual,
                        expiry_period_index=bucket.expiry_period_index,
                    )
                )
        taxable_profit = max(0.0, remaining_income)
        generated_loss = 0.0
    else:
        retained_buckets.extend(opening_buckets)
        taxable_profit = 0.0
        generated_loss = -taxable_before

    aged_buckets: list[LossCarryforwardBucket] = []
    for bucket in retained_buckets:
        remaining = _periods_remaining_after_period(bucket, period_input.period_index)
        if not config.expire_before_use and remaining <= 0:
            expired_losses += bucket.amount_keur
            continue
        if remaining >= 0:
            aged_buckets.append(
                LossCarryforwardBucket(
                    amount_keur=bucket.amount_keur,
                    periods_remaining=remaining,
                    source_period_index=bucket.source_period_index,
                    source_label=bucket.source_label,
                    generated_loss_keur=bucket.generated_loss_keur,
                    remaining_loss_keur=bucket.amount_keur,
                    expiry_period_index=bucket.expiry_period_index,
                )
            )

    if generated_loss > 0:
        aged_buckets.append(
            LossCarryforwardBucket(
                amount_keur=generated_loss,
                periods_remaining=config.duration_periods,
                source_period_index=period_input.period_index,
                source_label=f"generated_period_{period_input.period_index}",
                generated_loss_keur=generated_loss,
                remaining_loss_keur=generated_loss,
                expiry_period_index=period_input.period_index + config.duration_periods,
            )
        )

    closing_loss = sum(bucket.amount_keur for bucket in aged_buckets)

    return LossCarryforwardPeriodResult(
        period_index=period_input.period_index,
        taxable_income_before_losses_keur=taxable_before,
        losses_n_1_keur=opening_loss,
        allocated_losses_keur=losses_used,
        losses_n_keur=closing_loss,
        carriable_losses_keur=closing_loss,
        losses_generated_keur=generated_loss,
        expired_losses_keur=expired_losses,
        taxable_profit_after_losses_keur=taxable_profit,
        opening_buckets=opening_buckets,
        closing_buckets=tuple(aged_buckets),
    )


def compute_loss_carryforward_schedule(
    taxable_income_before_losses_keur: Sequence[float],
    config: LossCarryforwardConfig | None = None,
    opening_loss_keur: float = 0.0,
) -> LossCarryforwardResult:
    """Compute a rolling FIFO loss carry-forward schedule."""

    cfg = config or LossCarryforwardConfig()
    if opening_loss_keur < 0:
        raise ValueError("opening_loss_keur must be non-negative")

    buckets: tuple[LossCarryforwardBucket, ...] = ()
    if opening_loss_keur > 0:
        buckets = (
            LossCarryforwardBucket(
                amount_keur=opening_loss_keur,
                periods_remaining=cfg.duration_periods,
                source_period_index=None,
                source_label="opening_loss",
                generated_loss_keur=opening_loss_keur,
                remaining_loss_keur=opening_loss_keur,
                expiry_period_index=cfg.duration_periods,
            ),
        )

    results: list[LossCarryforwardPeriodResult] = []
    for period_index, taxable_before in enumerate(taxable_income_before_losses_keur):
        period_result = compute_loss_carryforward_period(
            LossCarryforwardPeriodInput(
                period_index=period_index,
                taxable_income_before_losses_keur=float(taxable_before),
                opening_buckets=buckets,
            ),
            cfg,
        )
        results.append(period_result)
        buckets = period_result.closing_buckets

    return LossCarryforwardResult(periods=tuple(results), config=cfg)


__all__ = [
    "LossCarryforwardConfig",
    "LossCarryforwardBucket",
    "LossCarryforwardPeriodInput",
    "LossCarryforwardPeriodResult",
    "LossCarryforwardResult",
    "compute_loss_carryforward_period",
    "compute_loss_carryforward_schedule",
]
