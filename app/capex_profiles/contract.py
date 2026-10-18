"""Typed, deterministic monthly CAPEX spending-profile contract (pure; exact arithmetic; no I/O).

Weights are exact ``Fraction`` values, so uniform / front / back / milestone profiles sum to exactly 1.  Explicit user
percentages are accepted only if they are finite, non-negative, of the exact period count and sum to 100 % within the
repository's existing construction-weight tolerance (1e-9 of the whole).  Materially invalid input is REJECTED, never
normalised.  Monetary allocation is rounded to 1e-6 kEUR and the rounding residual is assigned to the last month that
carries weight, so the monthly uses always reconcile EXACTLY to the owning CAPEX amount.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from fractions import Fraction
from typing import Iterable, Sequence

WEIGHT_SUM_TOLERANCE = Fraction(1, 10**9)      # same tolerance the construction authority applies to payment weights
AMOUNT_QUANTUM = Decimal("0.000001")           # kEUR
MIN_MONTHS, MAX_MONTHS = 1, 60
SOURCE_USER_PREVIEW = "USER_PREVIEW_INPUT"


class ProfileError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


class ProfileShape(str, Enum):
    UNIFORM = "UNIFORM"
    FRONT_LOADED = "FRONT_LOADED"      # linearly declining monthly weights (user-selected SHAPE, not a market assumption)
    BACK_LOADED = "BACK_LOADED"        # linearly rising monthly weights
    EXPLICIT = "EXPLICIT"              # user-entered percentage per month
    MILESTONE = "MILESTONE"            # 100 % in one month


@dataclass(frozen=True)
class ProfileSpec:
    item_key: str
    shape: ProfileShape
    explicit_percent: tuple[str, ...] = ()
    milestone_month: int | None = None
    source: str = SOURCE_USER_PREVIEW


@dataclass(frozen=True)
class MonthlyAllocation:
    month: int                          # 1-based construction month
    weight: Fraction
    amount_keur: Decimal
    cumulative_keur: Decimal
    remaining_keur: Decimal


@dataclass(frozen=True)
class ProfileResult:
    item_key: str
    shape: ProfileShape
    source: str
    total_keur: Decimal
    months: tuple[MonthlyAllocation, ...]
    rounding_residual_keur: Decimal     # amount moved to the last weighted month to reconcile exactly (|.| <= months * quantum)
    unallocated_keur: Decimal           # always 0 for a valid profile

    @property
    def allocated_keur(self) -> Decimal:
        return sum((m.amount_keur for m in self.months), Decimal(0))


def check_months(months) -> int:
    if isinstance(months, bool) or not isinstance(months, int) or not MIN_MONTHS <= months <= MAX_MONTHS:
        raise ProfileError("CAPEX_PROFILE_DURATION_INVALID", f"construction months must be a whole number {MIN_MONTHS}..{MAX_MONTHS}, got {months!r}")
    return months


def parse_percent(text: str) -> Fraction:
    """Exact percent -> fraction of 1.  Rejects blanks, NaN, infinities, negatives and non-numeric text."""
    if not isinstance(text, str) or not text.strip():
        raise ProfileError("CAPEX_PROFILE_WEIGHT_INVALID", "blank weight")
    raw = text.strip()
    if "," in raw and "." not in raw:
        raw = raw.replace(",", ".")                    # decimal comma; a percentage can never use a thousands separator
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ProfileError("CAPEX_PROFILE_WEIGHT_INVALID", f"not a number: {text!r}") from exc
    if not value.is_finite():
        raise ProfileError("CAPEX_PROFILE_WEIGHT_NON_FINITE", repr(text))
    if value < 0:
        raise ProfileError("CAPEX_PROFILE_WEIGHT_NEGATIVE", repr(text))
    return Fraction(value) / 100


def build_weights(spec: ProfileSpec, months: int) -> tuple[Fraction, ...]:
    n = check_months(months)
    shape = ProfileShape(spec.shape)
    if shape is ProfileShape.UNIFORM:
        return tuple(Fraction(1, n) for _ in range(n))
    if shape is ProfileShape.FRONT_LOADED:
        return tuple(Fraction(2 * (n - k), n * (n + 1)) for k in range(n))
    if shape is ProfileShape.BACK_LOADED:
        return tuple(Fraction(2 * (k + 1), n * (n + 1)) for k in range(n))
    if shape is ProfileShape.MILESTONE:
        m = spec.milestone_month
        if isinstance(m, bool) or not isinstance(m, int) or not 1 <= m <= n:
            raise ProfileError("CAPEX_PROFILE_MILESTONE_MONTH_INVALID", f"{m!r} not in 1..{n}")
        return tuple(Fraction(1) if k == m - 1 else Fraction(0) for k in range(n))
    # EXPLICIT
    if len(spec.explicit_percent) != n:
        raise ProfileError("CAPEX_PROFILE_PERIOD_COUNT_MISMATCH", f"{len(spec.explicit_percent)} weights for {n} construction months")
    weights = tuple(parse_percent(p) for p in spec.explicit_percent)
    if abs(sum(weights) - 1) > WEIGHT_SUM_TOLERANCE:
        raise ProfileError("CAPEX_PROFILE_WEIGHT_SUM_INVALID", f"weights sum to {float(sum(weights) * 100):.9f} %, expected 100 %")
    return weights


def to_amount(value) -> Decimal:
    """kEUR amount from a float/str/Decimal; must be finite and non-negative."""
    if isinstance(value, bool):
        raise ProfileError("CAPEX_PROFILE_AMOUNT_INVALID", repr(value))
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ProfileError("CAPEX_PROFILE_AMOUNT_INVALID", repr(value)) from exc
    if not amount.is_finite() or amount < 0:
        raise ProfileError("CAPEX_PROFILE_AMOUNT_INVALID", repr(value))
    return amount.quantize(AMOUNT_QUANTUM)


def allocate(spec: ProfileSpec, amount_keur, months: int) -> ProfileResult:
    """Exact monthly allocation of ``amount_keur`` under ``spec`` (zero amount is valid and allocates zero)."""
    weights = build_weights(spec, months)
    total = to_amount(amount_keur)
    raw = [(Fraction(total) * w) for w in weights]
    amounts = [Decimal(r.numerator) / Decimal(r.denominator) for r in raw]
    amounts = [a.quantize(AMOUNT_QUANTUM) for a in amounts]
    residual = total - sum(amounts, Decimal(0))
    last = max((i for i, w in enumerate(weights) if w > 0), default=None)
    if last is None:                                   # all-zero weights can only come from a zero-sum explicit set (rejected above)
        raise ProfileError("CAPEX_PROFILE_WEIGHT_SUM_INVALID", "no month carries weight")
    if total > 0:
        allowance = AMOUNT_QUANTUM * (len(weights) + 1) + total * Decimal(2) / Decimal(10**9)
        if abs(residual) > allowance:
            raise ProfileError("CAPEX_PROFILE_RECONCILIATION_FAILED", f"residual {residual}")
        amounts[last] += residual
    else:
        residual = Decimal(0)
        amounts = [Decimal(0).quantize(AMOUNT_QUANTUM)] * len(weights)
    cumulative = Decimal(0)
    rows = []
    for index, (w, a) in enumerate(zip(weights, amounts), start=1):
        cumulative += a
        rows.append(MonthlyAllocation(index, w, a, cumulative, total - cumulative))
    result = ProfileResult(spec.item_key, ProfileShape(spec.shape), spec.source, total, tuple(rows), residual, total - cumulative)
    if result.unallocated_keur != 0:
        raise ProfileError("CAPEX_PROFILE_RECONCILIATION_FAILED", f"unallocated {result.unallocated_keur}")
    return result


def reject_duplicates(specs: Iterable[ProfileSpec]) -> None:
    seen: set[str] = set()
    for spec in specs:
        if spec.item_key in seen:
            raise ProfileError("CAPEX_PROFILE_DUPLICATE_ITEM", spec.item_key)
        seen.add(spec.item_key)


def aggregate_by_group(result: ProfileResult, month_to_group: Sequence[int], groups: int) -> tuple[Decimal, ...]:
    """Sum monthly allocations into construction-period groups (used to show what the existing period-level consumer would receive)."""
    if len(month_to_group) != len(result.months):
        raise ProfileError("CAPEX_PROFILE_PERIOD_COUNT_MISMATCH", "month->period map length")
    out = [Decimal(0)] * groups
    for m, g in zip(result.months, month_to_group):
        out[g] += m.amount_keur
    return tuple(out)
