"""
Shared numeric safety guard for all user-controlled persisted V2 inputs.

All user-editable numeric model inputs must pass through here before
they can be stored in V2 persisted state or carried into financial
computations.
"""
from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation


class NumericGuardError(ValueError):
    """Raised when a numeric value violates the finite-number contract.

    Message is always user-displayable (no Python implementation jargon).
    """


# ---------------------------------------------------------------------------
# Float (FLOAT / MW / MWH / KEUR / PCT) contract
# ---------------------------------------------------------------------------

def assert_finite_float(value: float, label: str = "Value") -> float:
    """Assert that *value* is finite; return it unchanged.

    Raises NumericGuardError for NaN, +Inf, or -Inf.
    """
    if not math.isfinite(value):
        raise NumericGuardError(f"{label} must be a finite number.")
    return value


def parse_finite_float(raw: str, label: str = "Value") -> float:
    """Parse *raw* to a finite float.

    Raises NumericGuardError if the string is not numeric or result is
    non-finite (NaN, +Inf, -Inf, overflow-to-infinity such as "1e309").
    """
    try:
        v = float(raw)
    except (ValueError, TypeError) as exc:
        raise NumericGuardError(f"{label} must be a number.") from exc
    return assert_finite_float(v, label)


# ---------------------------------------------------------------------------
# Integer (INT / YEARS / MONTHS) contract
# ---------------------------------------------------------------------------

def parse_strict_int(raw: str, label: str = "Value") -> int:
    """Parse *raw* to a Python int, rejecting any fractional part.

    Accepted:
        "18"      → 18
        "18.0"    → 18   (numerically integral)
        "-5"      → -5

    Rejected:
        "18.9"    → NumericGuardError (must be a whole number)
        "NaN"     → NumericGuardError
        "Inf"     → NumericGuardError
        "1e309"   → NumericGuardError

    Uses Decimal for exact lexical integrality detection so that float
    precision loss cannot permit "18.9999999999999964" to slip through.
    """
    stripped = str(raw).strip()
    try:
        d = Decimal(stripped)
    except InvalidOperation as exc:
        raise NumericGuardError(f"{label} must be a whole number.") from exc
    if not d.is_finite():
        raise NumericGuardError(f"{label} must be a finite whole number.")
    if d != d.to_integral_value():
        raise NumericGuardError(
            f"{label} must be a whole number (got {raw!r})."
        )
    return int(d)
