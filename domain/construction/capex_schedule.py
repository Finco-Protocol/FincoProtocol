"""Monthly construction uses schedule helpers."""

from __future__ import annotations

from domain.construction.config import CapexProfileType, ConstructionConfig


def build_monthly_uses(config: ConstructionConfig) -> tuple[float, ...]:
    """Return monthly construction cash requirements in kEUR."""

    if config.construction_months <= 0:
        raise ValueError("construction_months must be positive")
    if config.total_uses_keur < 0:
        raise ValueError("total_uses_keur cannot be negative")

    if config.profile_type == CapexProfileType.LINEAR:
        monthly = config.total_uses_keur / config.construction_months
        return tuple(monthly for _ in range(config.construction_months))

    if config.profile_type == CapexProfileType.CUSTOM:
        if len(config.monthly_uses_keur) != config.construction_months:
            raise ValueError("custom monthly_uses_keur length must equal construction_months")
        if any(value < 0 for value in config.monthly_uses_keur):
            raise ValueError("monthly construction uses cannot be negative")
        return tuple(float(value) for value in config.monthly_uses_keur)

    raise ValueError(f"Unsupported capex profile type: {config.profile_type}")


def validate_monthly_uses_total(
    monthly_uses_keur: tuple[float, ...],
    expected_total_keur: float,
    *,
    tolerance_keur: float = 0.01,
) -> float:
    """Validate and return the total-vs-expected delta."""

    total = sum(monthly_uses_keur)
    delta = total - expected_total_keur
    if abs(delta) > tolerance_keur:
        raise ValueError(
            f"Monthly construction uses sum to {total:.3f} kEUR, "
            f"expected {expected_total_keur:.3f} kEUR"
        )
    return delta


__all__ = ["build_monthly_uses", "validate_monthly_uses_total"]
