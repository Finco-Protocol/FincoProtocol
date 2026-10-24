"""Advanced Revenue V4 candidate — pure calculation helpers.

RELEASE-CLOSED: every public function calls ``require_release()`` and is
never imported by any production path. All helpers are deterministic,
side-effect free and unit-explicit; they NEVER call the canonical engine
and never mutate any input. Missing evidence stays missing: a period with
no usable evidence yields a typed ``None`` contribution, never a silent
zero (MISSING != ZERO).

Conventions pinned here (the rest is OWNER DECISION REQUIRED — see
``docs/model_v2/REVENUE_V4_CANDIDATE_OWNER_DECISION_PACKET.md``):

- Energy units are MWh, money units are EUR unless a name says ``_keur``
  (kEUR, the engine's canonical revenue unit).
- Periods are addressed by caller-supplied declared hours; this module
  never derives a calendar itself.
- Decimal arithmetic for money splitting; exact halves never dropped.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping, Optional, Sequence, Tuple

from app.revenue_v4_candidate.contracts import (
    ACTIVATION_ENABLED,
    ContractedVolume,
    NegativePriceHoursPolicy,
    PriceModeRule,
    RouteToMarketFee,
    require_release,
)

# Backward-friendly re-export so acceptance fixtures can enable the gate
# exactly like the released-candidate tests do.
activation_enabled = lambda: ACTIVATION_ENABLED  # noqa: E731


# ── Negative price hours ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class NegativePriceSettlement:
    """Per-evidence-bucket outcome of applying one negative-price policy.

    ``delivered_mwh`` is the physically delivered energy (CURTAIL removes
    energy; NO_SETTLEMENT and SETTLE_NORMALLY deliver everything).
    ``settled_revenue_eur`` is the commercial settlement after the policy.
    The two are deliberately independent: NO_SETTLEMENT means energy is
    delivered but the negative-priced settlement is waived.
    """

    delivered_mwh: float
    settled_revenue_eur: Decimal
    policy_scope: str
    policy_action: str


def classify_hourly_prices(
    hourly_prices_eur_mwh: Sequence[float],
) -> Tuple[Tuple[int, ...], Tuple[int, ...]]:
    """Deterministic classification of hourly price indices.

    Returns ``(negative_indices, nonnegative_indices)``. Malformed entries
    (non-finite) fail closed — evidence quality is never silently patched.
    """
    require_release()
    negative, nonnegative = [], []
    for i, price in enumerate(hourly_prices_eur_mwh):
        if isinstance(price, bool) or not isinstance(price, (int, float)) \
                or not math.isfinite(float(price)):
            raise ValueError(
                f"REVENUE_V4_VALUE: hourly_prices_eur_mwh[{i}] must be a "
                "finite number (malformed evidence never collapses to zero)")
        (negative if price < 0 else nonnegative).append(i)
    return tuple(negative), tuple(nonnegative)


def apply_negative_price_policy(
    policy: NegativePriceHoursPolicy,
    *,
    negative_mwh: float,
    negative_price_eur_mwh: float,
    nonnegative_mwh: float,
    nonnegative_price_eur_mwh: float,
) -> NegativePriceSettlement:
    """Apply one negative-price policy to one evidence bucket pair.

    ``negative_mwh`` is the energy in negative-priced hours; the price
    arguments are the (declared) average settlement prices of each bucket.
    Prices may be negative ONLY in the negative bucket — the released
    authorities fail closed on negative prices and this candidate never
    introduces a negative price through the positive bucket.

    SETTLE_NORMALLY keeps the negative settlement. NO_SETTLEMENT delivers
    the energy but waives the negative-priced settlement (revenue of the
    negative bucket = 0; the positive bucket is untouched). CURTAIL
    removes the negative-bucket energy entirely (it is neither delivered
    nor settled). A zero-duration bucket contributes zero, never None
    (an empty bucket is a legitimate ZERO; missing evidence is the
    caller's typed responsibility).
    """
    require_release()
    policy.validate()
    if isinstance(negative_mwh, bool) or not isinstance(negative_mwh, (int, float)) \
            or not math.isfinite(float(negative_mwh)) or negative_mwh < 0:
        raise ValueError("REVENUE_V4_VALUE: negative_mwh must be finite non-negative")
    if isinstance(nonnegative_mwh, bool) or not isinstance(nonnegative_mwh, (int, float)) \
            or not math.isfinite(float(nonnegative_mwh)) or nonnegative_mwh < 0:
        raise ValueError("REVENUE_V4_VALUE: nonnegative_mwh must be finite non-negative")
    if not math.isfinite(float(negative_price_eur_mwh)) \
            or negative_price_eur_mwh > 0:
        raise ValueError(
            "REVENUE_V4_VALUE: negative_price_eur_mwh must be finite and "
            "negative or zero (it prices the negative-priced bucket)")
    if isinstance(nonnegative_price_eur_mwh, bool) \
            or not isinstance(nonnegative_price_eur_mwh, (int, float)) \
            or not math.isfinite(float(nonnegative_price_eur_mwh)) \
            or nonnegative_price_eur_mwh < 0:
        raise ValueError(
            "REVENUE_V4_VALUE: nonnegative_price_eur_mwh must be finite "
            "non-negative")

    if policy.action == "SETTLE_NORMALLY":
        delivered = negative_mwh + nonnegative_mwh
        revenue = (Decimal(str(negative_mwh)) * Decimal(str(negative_price_eur_mwh))
                   + Decimal(str(nonnegative_mwh)) * Decimal(str(nonnegative_price_eur_mwh)))
    elif policy.action == "NO_SETTLEMENT":
        delivered = negative_mwh + nonnegative_mwh
        revenue = Decimal(str(nonnegative_mwh)) * Decimal(str(nonnegative_price_eur_mwh))
    else:  # CURTAIL
        delivered = nonnegative_mwh
        revenue = Decimal(str(nonnegative_mwh)) * Decimal(str(nonnegative_price_eur_mwh))
    return NegativePriceSettlement(
        delivered_mwh=delivered,
        settled_revenue_eur=revenue,
        policy_scope=policy.scope,
        policy_action=policy.action,
    )


def period_negative_share(
    period_energy_mwh: float,
    negative_energy_mwh: float,
) -> float:
    """Declared period-level negative-priced energy share (evidence-derived).

    The period-declared accounting basis (decision packet D-01): the
    caller supplies evidence-derived energy quantities; this helper only
    normalizes them into a [0, 1] share, failing closed on an empty or
    inconsistent period.
    """
    require_release()
    if isinstance(period_energy_mwh, bool) or not isinstance(period_energy_mwh, (int, float)) \
            or not math.isfinite(float(period_energy_mwh)) or period_energy_mwh <= 0:
        raise ValueError(
            "REVENUE_V4_VALUE: period_energy_mwh must be finite and strictly "
            "positive")
    if isinstance(negative_energy_mwh, bool) or not isinstance(negative_energy_mwh, (int, float)) \
            or not math.isfinite(float(negative_energy_mwh)) or negative_energy_mwh < 0:
        raise ValueError(
            "REVENUE_V4_VALUE: negative_energy_mwh must be finite non-negative")
    if negative_energy_mwh > period_energy_mwh:
        raise ValueError(
            "REVENUE_V4_VALUE: negative_energy_mwh exceeds the period energy "
            "(inconsistent evidence)")
    return float(negative_energy_mwh) / float(period_energy_mwh)


# ── Contracted volume modes ──────────────────────────────────────────────────


def fixed_annual_mwh_to_periods(
    fixed_annual_mwh: float,
    period_hours: Sequence[float],
) -> Tuple[float, ...]:
    """Allocate a fixed annual MWh quantity across post-COD periods,
    pro-rata by DECLARED period hours (decision packet D-02 documents the
    pro-rata basis; equal-split or any other basis is a separate owner
    decision). Periods with zero declared hours receive zero. The sum of
    the allocation equals the annual quantity exactly (within float
    identity; the residual is assigned to the last non-zero period)."""
    require_release()
    if isinstance(fixed_annual_mwh, bool) or not isinstance(fixed_annual_mwh, (int, float)) \
            or not math.isfinite(float(fixed_annual_mwh)) or fixed_annual_mwh <= 0:
        raise ValueError(
            "REVENUE_V4_VALUE: fixed_annual_mwh must be finite and strictly "
            "positive")
    total_hours = 0.0
    for i, hours in enumerate(period_hours):
        if isinstance(hours, bool) or not isinstance(hours, (int, float)) \
                or not math.isfinite(float(hours)) or hours < 0:
            raise ValueError(
                f"REVENUE_V4_VALUE: period_hours[{i}] must be finite "
                "non-negative declared hours")
        total_hours += float(hours)
    if total_hours <= 0:
        raise ValueError(
            "REVENUE_V4_VALUE: the declared period hours cover no time; "
            "nothing can be allocated (missing evidence is not zero)")
    raw = [fixed_annual_mwh * float(h) / total_hours for h in period_hours]
    allocated = sum(raw)
    residual = fixed_annual_mwh - allocated
    if residual != 0.0:
        for i in range(len(raw) - 1, -1, -1):
            if period_hours[i] > 0:
                raw[i] += residual
                break
    return tuple(raw)


def convert_monthly_mw(
    monthly_mw: Sequence[float],
    month_hours: Sequence[float],
) -> Tuple[float, ...]:
    """Convert declared monthly capacity (MW) to monthly energy (MWh) with
    explicitly DECLARED month hours. Units are pinned: MW × h = MWh. The
    shape timezone/day-count convention behind ``month_hours`` is the
    caller's declared evidence (decision packet D-04)."""
    require_release()
    if len(monthly_mw) != 12 or len(month_hours) != 12:
        raise ValueError(
            "REVENUE_V4_VALUE: monthly_mw and month_hours must both have "
            "exactly 12 entries (January..December)")
    out = []
    for i, (mw, hours) in enumerate(zip(monthly_mw, month_hours)):
        if isinstance(mw, bool) or not isinstance(mw, (int, float)) \
                or not math.isfinite(float(mw)) or mw < 0:
            raise ValueError(
                f"REVENUE_V4_VALUE: monthly_mw[{i}] must be finite non-negative")
        if isinstance(hours, bool) or not isinstance(hours, (int, float)) \
                or not math.isfinite(float(hours)) or hours < 0:
            raise ValueError(
                f"REVENUE_V4_VALUE: month_hours[{i}] must be finite "
                "non-negative declared hours")
        out.append(float(mw) * float(hours))
    return tuple(out)


def aggregate_monthly_to_periods(
    monthly_mwh: Mapping[Tuple[int, int], float],
    periods: Sequence[Tuple[str, Tuple[Tuple[int, int], ...]]],
) -> Tuple[Tuple[str, float], ...]:
    """Aggregate declared monthly MWh into candidate periods.

    ``monthly_mwh`` maps (year, month 1..12) → MWh; ``periods`` maps each
    period id to its exact ordered (year, month) members. Fail closed on
    a missing month (never interpolated) and on a month used by more than
    one period (no double settlement)."""
    require_release()
    seen: dict = {}
    out = []
    for period_id, members in periods:
        if not isinstance(period_id, str) or not period_id.strip():
            raise ValueError("REVENUE_V4_SCHEMA: period ids must be non-empty")
        total = 0.0
        for key in members:
            if key not in monthly_mwh:
                raise ValueError(
                    f"REVENUE_V4_UNAVAILABLE: no declared monthly energy for "
                    f"{key[0]}-{key[1]:02d} (required by period "
                    f"{period_id!r}); months are never interpolated")
            if key in seen:
                raise ValueError(
                    f"REVENUE_V4_SCHEMA: month {key[0]}-{key[1]:02d} is "
                    f"claimed by both {seen[key]!r} and {period_id!r} (no "
                    "double settlement)")
            seen[key] = period_id
            value = monthly_mwh[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(float(value)) or value < 0:
                raise ValueError(
                    f"REVENUE_V4_VALUE: monthly energy for {key[0]}-"
                    f"{key[1]:02d} must be finite non-negative")
            total += float(value)
        out.append((period_id, total))
    return tuple(out)


# ── Merchant price modes ─────────────────────────────────────────────────────


def resolve_market_mode_price(
    rule: PriceModeRule,
    market_price_eur_mwh: float,
) -> Optional[Decimal]:
    """Resolve one candidate price for one market observation.

    Returns the effective EUR/MWh price as an exact Decimal, or ``None``
    when the market evidence itself is missing (MISSING != ZERO). The
    released non-negative rule is enforced for the RESULT of floor modes:
    floors/caps are non-negative by contract validation, so a floored
    result is non-negative; MARKET_CAP and REVENUE_SHARING pass a negative
    market price through unchanged (owner decision D-05 covers whether a
    negative market price may reach settlement at all — the released
    production authorities still fail closed on negative prices, and this
    candidate never feeds them).
    """
    require_release()
    rule.validate()
    if rule.mode == "FIXED":
        # a FIXED price needs no market evidence at all
        return Decimal(str(rule.fixed_price_eur_mwh))
    if isinstance(market_price_eur_mwh, bool) \
            or not isinstance(market_price_eur_mwh, (int, float)) \
            or not math.isfinite(float(market_price_eur_mwh)):
        return None
    market = Decimal(str(float(market_price_eur_mwh)))
    if rule.mode == "MARKET_FLOOR":
        return max(market, Decimal(str(rule.floor_eur_mwh)))
    if rule.mode == "MARKET_CAP":
        return min(market, Decimal(str(rule.cap_eur_mwh)))
    if rule.mode == "FLOOR_AND_CAP":
        bounded = max(market, Decimal(str(rule.floor_eur_mwh)))
        return min(bounded, Decimal(str(rule.cap_eur_mwh)))
    # REVENUE_SHARING: exact Decimal split, HALF_UP at 6 dp only for
    # reporting-friendliness of the split itself (order vs the released
    # PPA-01 rounding authority is decision packet D-07).
    raw = market * Decimal(str(rule.project_share))
    return raw.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


# ── Route-to-market fee ──────────────────────────────────────────────────────


def completed_annual_reviews(
    period_end: date,
    contract_start: date,
    review_month: int,
) -> int:
    """Count completed annual reviews at the FIRST day of ``review_month``
    strictly after ``contract_start`` and on/before ``period_end``.

    Deterministic and exact: a review lands on (year, review_month, 1).
    The review DAY inside the month is OWNER DECISION REQUIRED (D-06);
    this helper never interpolates partial months.
    """
    require_release()
    if not isinstance(review_month, int) or isinstance(review_month, bool) \
            or not 1 <= review_month <= 12:
        raise ValueError(
            "REVENUE_V4_SCHEMA: review_month must be an integer 1..12")
    if not isinstance(contract_start, date) or not isinstance(period_end, date):
        raise ValueError("REVENUE_V4_VALUE: dates must be datetime.date")
    if period_end < contract_start:
        raise ValueError(
            "REVENUE_V4_VALUE: period_end precedes contract_start")
    count = 0
    year = contract_start.year
    # walk forward year by year (bounded by period_end year + 1)
    while year <= period_end.year:
        review = date(year, review_month, 1)
        if contract_start < review <= period_end:
            count += 1
        year += 1
    return count


def apply_route_to_market_fee(
    fee: RouteToMarketFee,
    *,
    delivered_mwh: float,
    gross_revenue_eur: Decimal,
    completed_reviews: int,
) -> Decimal:
    """Net revenue after the route-to-market fee with up-only escalation.

    ``completed_reviews`` comes from :func:`completed_annual_reviews`
    (caller-supplied from exact dates — this helper stays date-free).
    EUR_PER_MWH fees escalate on the DECLARED delivered energy;
    PERCENT_OF_REVENUE fees take an exact Decimal fraction of gross
    revenue. Escalation is up-only by contract validation
    (``escalation_rate >= 0``).
    """
    require_release()
    fee.validate()
    if isinstance(delivered_mwh, bool) or not isinstance(delivered_mwh, (int, float)) \
            or not math.isfinite(float(delivered_mwh)) or delivered_mwh < 0:
        raise ValueError(
            "REVENUE_V4_VALUE: delivered_mwh must be finite non-negative")
    if not isinstance(gross_revenue_eur, Decimal):
        raise ValueError(
            "REVENUE_V4_VALUE: gross_revenue_eur must be an exact Decimal")
    if isinstance(completed_reviews, bool) or not isinstance(completed_reviews, int) \
            or completed_reviews < 0:
        raise ValueError(
            "REVENUE_V4_VALUE: completed_reviews must be a non-negative "
            "integer")
    factor = (Decimal(1) + Decimal(str(fee.escalation_rate))) ** completed_reviews
    if fee.fee_basis == "EUR_PER_MWH":
        charge = Decimal(str(float(delivered_mwh))) * Decimal(str(fee.fee_value)) * factor
    else:
        charge = gross_revenue_eur * Decimal(str(fee.fee_value)) * factor
    net = gross_revenue_eur - charge
    if net < 0:
        raise ValueError(
            "REVENUE_V4_VALUE: the route-to-market fee exceeds gross revenue "
            "(negative net revenue is unsupported in V1; OWNER DECISION "
            "REQUIRED for clamping vs failure, D-08)")
    return net
