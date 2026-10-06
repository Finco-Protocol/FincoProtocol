"""Model V2 revenue runtime parity bridge (Workflow 05B).

Maps reviewed RevenuePlan structures onto the CANONICAL runtime revenue
authority — ``finco_core.revenue.generation.revenue_decomposition_schedule``
consumed through ``RevenueParams`` — using only EXISTING canonical fields:

- PPA lifecycle: ``ppa_term_years`` drives the engine's ``is_ppa_active``
  (start-at-COD, expire after term) — exact for year-1-start contracts.
- PPA tariff: ``ppa_base_tariff`` + ``ppa_index`` (existing analytic
  authority) or ``ppa_tariff_by_operating_period`` (existing explicit
  per-operating-period schedule authority) — zero tariff outside the
  contract window; no interpolation; missing indexed years fail closed.
- Merchant: ``market_prices_curve`` per operating year with the plan's
  escalation, technology capture rate embedded into the curve (the runtime
  market path sells at curve price), plus ``market_inflation``.
- FIT_FIXED / AUCTION_AWARDED_TARIFF / INDEXED_FIT: fixed-tariff contracts
  compose through the SAME tariff path (Workflow 02: fixed-tariff and
  indexed authority reuse); contract identity stays in the RevenuePlan
  layer, the runtime seam is the canonical fixed-tariff authority.

DECOMPOSITION AUTHORITY PRECEDENCE (locked, Workflow 02): when a canonical
parent is governed by decomposition, the ACTIVE child set is authoritative.
A parent stream with ``default_active=False`` does NOT suppress its active
children; all children OFF means parent amount 0 and inactive.

FAIL-CLOSED SEAMS (documented, not approximated — Correction-tier
decision required in the frozen core to add them):

- CfD overlay (two-way/one-way settlement): the frozen RevenueParams has
  no additive support-settlement field; stuffing CfD into PPA tariffs or
  pre-netting into merchant prices is forbidden. Fail closed.
- Premium FiT overlay (cap/floor on top of market): same missing additive
  seam. Fail closed.
- Delayed-start PPA share release: the runtime ``ppa_production_share`` is
  horizon-constant, so the pre-start window cannot receive the released
  100% merchant residual exactly. Fail closed.
- Overlapping fixed-tariff-family streams: the runtime has ONE tariff path
  and ONE production share; overlapping active fixed-tariff streams fail
  closed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

from domain.revenue.plan import ContractRole, RevenueStreamType

# Periods per year by the canonical PeriodFrequency vocabulary.
PERIODS_PER_YEAR = {"Semestrial": 2, "Annual": 1, "Quarterly": 4}

# Tariff-path family: streams the canonical fixed-tariff runtime authority
# can express exactly (price x eligible volume, with indexation).
TARIFF_PATH_STREAM_TYPES = frozenset({
    RevenueStreamType.PPA,
    RevenueStreamType.FIT_FIXED,
    RevenueStreamType.FIT_PREMIUM,
    RevenueStreamType.INDEXED_FIT,
    RevenueStreamType.AUCTION_AWARDED_TARIFF,
})

# Overlay family: settlement/support economics on top of the market sale —
# NOT expressible in the frozen core (documented missing seam).
OVERLAY_STREAM_TYPES = frozenset({
    RevenueStreamType.CFD,
    RevenueStreamType.FIT_PREMIUM,
})


class RevenueRuntimeSeamMissing(ValueError):
    """Raised when a plan structure is economically valid at the RevenuePlan
    layer but the canonical runtime has no seam to express it without a
    frozen-core change. Never approximated."""


@dataclass(frozen=True)
class RuntimeRevenueOverrides:
    """RevenueParams field overrides produced by the parity bridge."""

    ppa_base_tariff: Optional[float] = None
    ppa_term_years: Optional[float] = None
    ppa_index: Optional[float] = None
    ppa_production_share: Optional[float] = None
    ppa_tariff_by_operating_period: Optional[tuple[float, ...]] = None
    market_prices_curve: Optional[tuple[float, ...]] = None
    market_inflation: Optional[float] = None
    balancing_cost_pv: Optional[float] = None
    first_merchant_operating_period_index: Optional[int] = None


def periods_per_year_for(base_inputs: Any) -> int:
    """Periods per operating year from the canonical PeriodFrequency."""
    frequency = getattr(getattr(base_inputs, "info", None),
                        "period_frequency", None)
    name = getattr(frequency, "value", frequency)
    if name in PERIODS_PER_YEAR:
        return PERIODS_PER_YEAR[name]
    raise RevenueRuntimeSeamMissing(
        f"RUNTIME_PERIOD_FREQUENCY_UNSUPPORTED: {name!r} has no periods-per-"
        "year authority in the composition bridge"
    )


def horizon_periods(base_inputs: Any) -> int:
    ppy = periods_per_year_for(base_inputs)
    horizon = int(getattr(getattr(base_inputs, "info", None),
                          "horizon_years", 0) or 0)
    return max(1, horizon) * ppy


def _capture_rate_for(merchant: Any, technology: str) -> float:
    rate = getattr(merchant, f"capture_rate_{technology}", None)
    if rate is None:
        rate = merchant.capture_rate_solar
    rate = float(rate)
    if math.isnan(rate) or rate < 0.0 or rate > 1.0:
        raise RevenueRuntimeSeamMissing(
            f"RUNTIME_CAPTURE_RATE_INVALID: capture rate for {technology!r} "
            f"must be within [0, 1], got {rate!r}"
        )
    return rate


def bridge_plan_to_runtime_revenue(
    plan: Any,
    *,
    base_inputs: Any,
    technology: str,
) -> dict[str, Any]:
    """Bridge a validated RevenuePlan to canonical RevenueParams overrides.

    Fail-closed seams:
      - CfD overlay / premium FiT overlay (no additive support-settlement
        field in the frozen core);
      - overlapping ACTIVE fixed-tariff-family streams (one tariff path);
      - delayed-start PPA share release (horizon-constant share cannot
        express the pre-start 100% merchant residual);
      - INDEXED_FIT missing factor years (typed unavailable, no
        extrapolation);
      - unsupported period frequency.

    Everything else maps onto existing canonical fields with exact
    economics.
    """
    ppy = periods_per_year_for(base_inputs)
    horizon_periods_count = horizon_periods(base_inputs)

    enabled = [s for s in plan.ordered_streams() if s.enabled]

    overlays = [s for s in enabled
                if s.stream_type in OVERLAY_STREAM_TYPES]
    tariff_family = [s for s in enabled
                     if s.stream_type in TARIFF_PATH_STREAM_TYPES]

    overrides: dict[str, Any] = {}
    diagnostics: list[str] = []

    # ---- Merchant authority -------------------------------------------------
    merchant = next((s.merchant for s in enabled
                     if s.stream_type is RevenueStreamType.MERCHANT
                     and s.merchant is not None), None)
    if merchant is not None:
        capture = _capture_rate_for(merchant, technology)
        curve: list[float] = []
        horizon = int(getattr(getattr(base_inputs, "info", None),
                              "horizon_years", 0) or 0)
        for year in range(1, max(horizon, len(
                getattr(merchant, "custom_price_curve", ()) or ())) + 1):
            price = float(merchant.price_at_year(year))
            if math.isnan(price) or math.isinf(price) or price < 0.0:
                raise RevenueRuntimeSeamMissing(
                    f"RUNTIME_MERCHANT_PRICE_INVALID: merchant price for year "
                    f"{year} is {price!r}"
                )
            # Technology capture rate embedded into the runtime curve (the
            # market path sells at curve price; capture is part of the
            # plan's merchant economics).
            curve.append(price * capture)
        overrides["market_prices_curve"] = tuple(curve)
        overrides["market_inflation"] = float(merchant.price_escalation_annual)
        diagnostics.append(
            f"merchant: curve for {len(curve)} years, capture={capture}")

    # ---- PPA lifecycle + tariff path ---------------------------------------
    ppa_streams = [s for s in enabled
                   if s.stream_type is RevenueStreamType.PPA]
    ppa_stream = ppa_streams[0] if ppa_streams else None
    if ppa_stream is not None:
        ppa = ppa_stream.ppa
        overrides["ppa_base_tariff"] = float(ppa.ppa_base_price_eur_mwh)
        overrides["ppa_index"] = float(ppa.ppa_price_index)
        overrides["ppa_production_share"] = float(ppa_stream.volume_share)
        if ppa_stream.term_years is not None:
            overrides["ppa_term_years"] = float(ppa_stream.term_years)
        overrides["balancing_cost_pv"] = float(ppa.balancing_cost_pct)

        # Delayed-start share release: pre-start the PPA holds no allocation
        # and the residual merchant must receive 100% — not expressible with
        # a horizon-constant production share. Fail closed.
        if ppa_stream.start_year > 1 and ppa_stream.volume_share not in (None, 1.0):
            raise RevenueRuntimeSeamMissing(
                "RUNTIME_DELAYED_START_SHARE_RELEASE_UNSUPPORTED: a "
                "delayed-start PPA releases its share to the residual "
                "merchant before start; the runtime production share is "
                "horizon-constant"
            )

        # Delayed-start or expiring window → explicit per-operating-period
        # tariff schedule (existing authority): tariff inside the contract
        # window, 0.0 outside. Annual tariff, constant within the year
        # (Workflow 02 annual index semantics).
        if ppa_stream.start_year > 1 or (
            ppa_stream.term_years is not None
        ):
            schedule = []
            for idx in range(horizon_periods_count):
                year = idx // ppy + 1
                if ppa_stream.is_active(year):
                    schedule.append(float(
                        ppa.price_at_year(year)))
                else:
                    schedule.append(0.0)
            overrides["ppa_tariff_by_operating_period"] = tuple(schedule)

    # ---- Fixed-tariff family (FIT_FIXED / AUCTION / INDEXED_FIT) -----------
    fixed_tariff_streams = [s for s in enabled
                            if s.stream_type in (
                                RevenueStreamType.FIT_FIXED,
                                RevenueStreamType.AUCTION_AWARDED_TARIFF,
                                RevenueStreamType.INDEXED_FIT)]

    # Overlap detection among simultaneously ACTIVE fixed-tariff streams.
    if len(fixed_tariff_streams) > 1:
        windows = []
        for s in fixed_tariff_streams:
            start = int(s.start_year)
            end = (start + int(s.term_years) - 1) \
                if s.term_years is not None else 10 ** 6
            windows.append((start, end, s.item_id))
        windows.sort()
        for (s1, e1, id1), (s2, e2, id2) in zip(windows, windows[1:]):
            if s2 <= e1:
                raise RevenueRuntimeSeamMissing(
                    f"RUNTIME_TARIFF_PATH_OVERLAP: fixed-tariff streams "
                    f"{id1!r} and {id2!r} are simultaneously active "
                    f"({s1}-{e1} vs {s2}-{e2}); the canonical runtime has "
                    "one tariff path"
                )

    for s in fixed_tariff_streams:
        fit = s.fit
        if s.stream_type in (RevenueStreamType.FIT_FIXED,
                             RevenueStreamType.AUCTION_AWARDED_TARIFF):
            # Fixed tariff authority: price_at_year covers the indexation.
            # Also set ppa_base_tariff so the analytic fallback (used when
            # the per-period schedule is absent for early periods) carries
            # the FiT price, not a stale PPA price.
            overrides["ppa_base_tariff"] = float(fit.fit_price_eur_mwh)
            schedule = tuple(
                float(fit.price_at_year(idx + 1))
                if s.is_active(idx + 1) else 0.0
                for idx in range(horizon_periods_count)
            )
            overrides["ppa_tariff_by_operating_period"] = schedule
        elif s.stream_type is RevenueStreamType.INDEXED_FIT:
            factors = s.indexed_fit_index_factors or ()
            base_tariff = s.indexed_fit_base_tariff_eur_mwh
            if base_tariff is None or not factors:
                raise RevenueRuntimeSeamMissing(
                    "RUNTIME_INDEXED_FIT_AUTHORITY_MISSING: indexed tariff "
                    "requires base tariff and explicit factor schedule"
                )
            schedule = tuple(
                (float(base_tariff) * float(factors[year - 1])
                 if year - 1 < len(factors) else 0.0)
                if s.is_active(year) else 0.0
                for year in range(1, horizon_periods_count + 1)
            )
            overrides["ppa_tariff_by_operating_period"] = schedule

    # ---- Fail-closed seams (documented, not approximated) ------------------
    if overlays:
        kinds = sorted({s.stream_type.value for s in overlays})
        raise RevenueRuntimeSeamMissing(
            f"RUNTIME_SUPPORT_OVERLAY_SEAM_MISSING: {kinds} overlay "
            "settlement/support economics have no additive field in the "
            "frozen core RevenueParams; documented in "
            "REVENUE_RUNTIME_PARITY_CONTRACT.md — fail closed rather than "
            "stuffing settlements into PPA tariffs or merchant prices"
        )

    return overrides
