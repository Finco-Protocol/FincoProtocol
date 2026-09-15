"""Small fail-closed numeric validators shared by canonical engine boundaries."""
from __future__ import annotations

import math
from numbers import Real


def require_finite_real(
    name: str,
    value: object,
    *,
    minimum: float | None = None,
    strictly_greater: bool = False,
    error_code: str = "INVALID_FINANCIAL_NUMERIC",
) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(
            f"{error_code}: {name} must be a real non-bool value, got {value!r}"
        )
    resolved = float(value)
    if not math.isfinite(resolved):
        raise ValueError(f"{error_code}: {name} must be finite, got {value!r}")
    if minimum is not None:
        invalid = resolved <= minimum if strictly_greater else resolved < minimum
        if invalid:
            operator = ">" if strictly_greater else ">="
            raise ValueError(
                f"{error_code}: {name} must be {operator} {minimum}, got {value!r}"
            )
    return resolved


def require_positive_int(
    name: str,
    value: object,
    *,
    error_code: str = "INVALID_FINANCIAL_INTEGER",
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(
            f"{error_code}: {name} must be a positive int, got {value!r}"
        )
    return value


def require_bool(
    name: str,
    value: object,
    *,
    error_code: str = "INVALID_FINANCIAL_BOOLEAN",
) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{error_code}: {name} must be bool, got {value!r}")
    return value
