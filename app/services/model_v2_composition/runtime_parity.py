"""Model V2 revenue runtime parity bridge (Workflow 05B, Correction A).

PRODUCTION-PATH-VERIFIED mapping of reviewed RevenuePlan structures onto the
canonical runtime revenue authority. The production chain (traced in
Correction A — do not claim parity past the fields this chain forwards):

    compose_project_inputs → ProjectInputs(revenue=...)
    → run_clean_production (app.services.production_financial_authority)
    → financial_engine.adapters.project_inputs.from_project_inputs
    → OperatingModelInput.revenue : RevenueInput  (clean contract,
      financial_engine/inputs.py)
    → financial_engine.orchestrator.run_operating_model
    → finco_core ProjectInputs proxy → revenue_decomposition_schedule

The clean ``RevenueInput`` contract forwards: ``ppa_base_tariff``,
``ppa_term_years``, ``ppa_index``, ``ppa_production_share``,
``market_prices_curve``, ``market_inflation``, ``balancing_cost_pv``,
``balancing_cost_wind_eur_mwh``, ``balancing_cost_eur_per_mwh``, CO2 fields,
``first_merchant_operating_period_index``, ``ppa_indexation_start_policy`` /
``_date`` and the merchant calendar-year fields. It has NO field for
``ppa_tariff_by_operating_period`` — the orchestrator derives its own
per-period schedule solely from the indexation policy. A per-period tariff
schedule composed here would therefore NEVER reach the engine.

Correction A consequences, enforced below:

1.  Production parity is claimed ONLY for structures expressible through
    the fields the adapter actually forwards (one year-1-start fixed-tariff
    contract on the analytic path + one merchant curve).
2.  A selected RevenuePlan is THE revenue authority: the bridge ALWAYS
    writes the full set of plan-governed ``RevenueParams`` fields —
    including explicit neutralization of every higher-precedence or
    orthogonal base schedule (per-period tariff schedule, calendar-year
    merchant schedule, indexation policy, first-merchant switch,
    merchant balancing percentage). No stale base authority survives a
    selection.
3.  PPA balancing is NOT mappable: plan semantics deduct
    ``PPAParams.balancing_cost_pct`` from PPA revenue; the runtime deducts
    ``balancing_cost_pv`` from MERCHANT revenue only (Excel CF row 40).
    A non-zero plan PPA balancing fails closed.

FAIL-CLOSED SEAMS (typed, documented — never approximated):

- ``RUNTIME_SUPPORT_OVERLAY_SEAM_MISSING``       CfD / premium-FiT overlay
  settlement (no additive field in the frozen core).
- ``RUNTIME_TARIFF_PATH_MULTIPLE_UNSUPPORTED``   more than one enabled
  fixed-tariff-family stream — the runtime expresses exactly ONE tariff
  path and ONE horizon-constant share, so sequential, gapped or
  different-share contract chains are inexpressible even when their price
  schedules could be concatenated.
- ``RUNTIME_DELAYED_START_TARIFF_SEAM_MISSING``  start_year > 1: the
  runtime PPA-active window always opens at COD; pre-start volume cannot
  be released to merchant (share is horizon-constant and there is no
  delayed-open authority).
- ``RUNTIME_TARIFF_TERM_GRAIN_SEAM_MISSING``     fractional term_years: the
  plan authority is model-year-granular, the engine window is date-anchored
  from COD — boundary half-periods would diverge.
- ``RUNTIME_UNALLOCATED_VOLUME_WITHOUT_MERCHANT`` a term-limited or
  partial-share tariff contract without a selected merchant stream: the
  runtime sells unallocated volume at ``market_price_at_year``, which
  falls back to the PPA tariff when the curve is empty — it cannot
  express "unallocated volume earns nothing".
- ``RUNTIME_INDEXED_FIT_AUTHORITY_MISSING``      an ACTIVE indexed-FiT
  year without a factor (MISSING ≠ ZERO — typed unavailable).
- ``RUNTIME_INDEXED_FIT_SCHEDULE_SEAM_MISSING``  indexed FiT with complete
  factors: requires a per-year tariff schedule, which the production
  adapter does not forward.
- ``RUNTIME_PPA_BALANCING_SEAM_MISSING``         non-zero plan PPA
  balancing / imbalance penalty (deduction-basis mismatch, see above).
- ``RUNTIME_CAPTURE_RATE_INVALID`` / ``RUNTIME_MERCHANT_PRICE_INVALID`` /
  ``RUNTIME_PERIOD_FREQUENCY_UNSUPPORTED``       degenerate inputs.
"""
from __future__ import annotations

import math
from typing import Any

from domain.revenue.plan import RevenueStreamType

# Periods per year by the canonical PeriodFrequency vocabulary.
PERIODS_PER_YEAR = {"Semestrial": 2, "Annual": 1, "Quarterly": 4}

# Fixed-tariff family: streams that would claim the single canonical tariff
# path (ppa_base_tariff / ppa_index / ppa_term_years / ppa_production_share).
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
    frozen-core / clean-contract change. Never approximated."""


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


def horizon_years(base_inputs: Any) -> int:
    return int(getattr(getattr(base_inputs, "info", None),
                       "horizon_years", 0) or 0)


def _capture_rate_for(merchant: Any, technology: str) -> float:
    """Plan-authority capture rate (same authority as plan_engine)."""
    rate = merchant.capture_rate_for_tech(technology)
    rate = float(rate)
    if math.isnan(rate) or math.isinf(rate) or rate < 0.0 or rate > 1.0:
        raise RevenueRuntimeSeamMissing(
            f"RUNTIME_CAPTURE_RATE_INVALID: capture rate for {technology!r} "
            f"must be within [0, 1], got {rate!r}"
        )
    return rate


def _merchant_curve(merchant: Any, base_inputs: Any,
                    technology: str) -> tuple[tuple[float, ...], float]:
    """Expand the plan merchant authority into a runtime price curve.

    Uses ``MerchantParams.price_at_year`` — the SAME authority plan_engine
    uses — for every horizon year, with the technology capture rate
    embedded (the runtime market path sells at curve price; plan_engine
    multiplies capture at evaluation). Escalation and cannibalization are
    therefore baked in exactly; ``market_inflation`` is reported for the
    runtime's beyond-curve fallback (never exercised: the curve covers the
    full horizon).
    """
    capture = _capture_rate_for(merchant, technology)
    horizon = horizon_years(base_inputs)
    curve: list[float] = []
    for year in range(1, horizon + 1):
        price = float(merchant.price_at_year(year))
        if math.isnan(price) or math.isinf(price) or price < 0.0:
            raise RevenueRuntimeSeamMissing(
                f"RUNTIME_MERCHANT_PRICE_INVALID: merchant price for year "
                f"{year} is {price!r}"
            )
        curve.append(price * capture)
    return tuple(curve), float(merchant.price_escalation_annual)


def _finite(value: Any, label: str) -> float:
    out = float(value)
    if math.isnan(out) or math.isinf(out):
        raise RevenueRuntimeSeamMissing(
            f"RUNTIME_TARIFF_VALUE_NON_FINITE: {label}={value!r} is not "
            "finite; composition refuses to write non-finite economics"
        )
    return out


def bridge_plan_to_runtime_revenue(
    plan: Any,
    *,
    base_inputs: Any,
    technology: str,
) -> dict[str, Any]:
    """Bridge a validated RevenuePlan to canonical RevenueParams overrides.

    The returned dict is a COMPLETE plan-governed override set: applying it
    replaces every plan-governed base field (explicit supersession), so no
    stale base PPA / merchant / schedule authority can leak into a
    composed run. Fields the plan does not govern (CO2, EUR/MWh balancing
    authorities) are orthogonal project assumptions and are left to their
    own authorities.
    """
    horizon = horizon_years(base_inputs)
    if horizon <= 0:
        raise RevenueRuntimeSeamMissing(
            f"RUNTIME_HORIZON_INVALID: horizon_years={horizon!r}")

    enabled = [s for s in plan.ordered_streams() if s.enabled]

    overlays = [s for s in enabled if s.stream_type in OVERLAY_STREAM_TYPES]
    if overlays:
        kinds = sorted({s.stream_type.value for s in overlays})
        raise RevenueRuntimeSeamMissing(
            f"RUNTIME_SUPPORT_OVERLAY_SEAM_MISSING: {kinds} overlay "
            "settlement/support economics have no additive field in the "
            "frozen core RevenueParams; documented in "
            "REVENUE_RUNTIME_PARITY_CONTRACT.md — fail closed rather than "
            "stuffing settlements into PPA tariffs or merchant prices"
        )

    tariff_streams = [s for s in enabled
                      if s.stream_type in TARIFF_PATH_STREAM_TYPES]
    if len(tariff_streams) > 1:
        ids = sorted(s.stream_id for s in tariff_streams)
        raise RevenueRuntimeSeamMissing(
            "RUNTIME_TARIFF_PATH_MULTIPLE_UNSUPPORTED: the canonical "
            "runtime expresses exactly ONE tariff path and ONE "
            "horizon-constant production share; streams "
            f"{ids} cannot coexist — sequential, gapped or different-share "
            "fixed-tariff chains are inexpressible even when their price "
            "schedules could be concatenated"
        )

    merchant = next((s.merchant for s in enabled
                     if s.stream_type is RevenueStreamType.MERCHANT
                     and s.merchant is not None), None)

    # ---- Explicit supersession of every plan-governed base field ----------
    overrides: dict[str, Any] = {
        # A custom per-period schedule never reaches the engine (the clean
        # RevenueInput contract has no such field; the orchestrator derives
        # its own schedule from the indexation policy). Neutralize any base
        # schedule so the analytic path is authoritative.
        "ppa_tariff_by_operating_period": (),
        # V2 PPA index semantics = plan price_at_year (geometric from
        # operating year 1) = the legacy tariff_at_year path.
        "ppa_indexation_start_policy": None,
        "ppa_indexation_start_date": None,
        # A base first-merchant switch would override the PPA-active
        # boundary entirely (generation.py: ppa_active = op_idx < idx).
        "first_merchant_operating_period_index": None,
        # The calendar-year merchant schedule takes precedence over the
        # curve in market_price_for_period — neutralize so the selected
        # plan curve is authoritative.
        "market_price_calendar_start_year": None,
        "market_prices_by_calendar_year_eur_mwh": (),
        # V2 plan semantics carry NO merchant balancing percentage (the
        # runtime deducts balancing_cost_pv from MERCHANT revenue only).
        "balancing_cost_pv": 0.0,
    }

    # ---- Merchant authority -----------------------------------------------
    if merchant is not None:
        curve, escalation = _merchant_curve(merchant, base_inputs, technology)
        overrides["market_prices_curve"] = curve
        overrides["market_inflation"] = escalation
    else:
        overrides["market_prices_curve"] = ()
        overrides["market_inflation"] = 0.0

    # ---- Tariff path (at most one stream, enforced above) ------------------
    if tariff_streams:
        s = tariff_streams[0]

        if s.start_year > 1:
            raise RevenueRuntimeSeamMissing(
                f"RUNTIME_DELAYED_START_TARIFF_SEAM_MISSING: stream "
                f"{s.stream_id!r} starts in year {s.start_year}; the runtime "
                "PPA-active window always opens at COD and the "
                "horizon-constant production share cannot release pre-start "
                "volume to merchant"
            )

        share = float(s.volume_share)

        if s.stream_type is RevenueStreamType.PPA:
            ppa = s.ppa
            # Plan semantics deduct balancing_cost_pct from PPA revenue;
            # the runtime deducts balancing_cost_pv from MERCHANT revenue
            # only. Different deduction bases — not mappable.
            if float(ppa.balancing_cost_pct) != 0.0 or \
                    float(getattr(ppa, "imbalance_penalty_pct", 0.0)) != 0.0:
                raise RevenueRuntimeSeamMissing(
                    "RUNTIME_PPA_BALANCING_SEAM_MISSING: plan PPA "
                    f"balancing_cost_pct={ppa.balancing_cost_pct!r} / "
                    f"imbalance_penalty_pct="
                    f"{getattr(ppa, 'imbalance_penalty_pct', 0.0)!r} would "
                    "have to be charged to PPA revenue; the frozen core "
                    "deducts balancing_cost_pv from MERCHANT revenue only"
                )
            base_tariff = float(ppa.ppa_base_price_eur_mwh)
            index = float(ppa.ppa_price_index)
        elif s.stream_type is RevenueStreamType.INDEXED_FIT:
            factors = tuple(s.indexed_fit_index_factors or ())
            if s.indexed_fit_base_tariff_eur_mwh is None or not factors:
                raise RevenueRuntimeSeamMissing(
                    "RUNTIME_INDEXED_FIT_AUTHORITY_MISSING: indexed tariff "
                    "requires base tariff and an explicit factor schedule"
                )
            term = s.term_years
            last_active_year = term if term is not None else horizon
            for year in range(s.start_year, last_active_year + 1):
                if year - 1 >= len(factors):
                    raise RevenueRuntimeSeamMissing(
                        "RUNTIME_INDEXED_FIT_AUTHORITY_MISSING: stream "
                        f"{s.stream_id!r} is ACTIVE in year {year} but the "
                        f"factor schedule covers {len(factors)} year(s); "
                        "MISSING != ZERO and extrapolation is forbidden"
                    )
            # Factors exist — but expressing them still needs a per-year
            # tariff schedule, which the production adapter does not
            # forward (clean RevenueInput has no such field).
            raise RevenueRuntimeSeamMissing(
                "RUNTIME_INDEXED_FIT_SCHEDULE_SEAM_MISSING: the per-year "
                "indexed-FiT tariff schedule cannot reach the engine — "
                "financial_engine/adapters/project_inputs.py forwards no "
                "ppa_tariff_by_operating_period field; documented missing "
                "production seam"
            )
        else:
            # FIT_FIXED / AUCTION_AWARDED_TARIFF
            fit = s.fit
            base_tariff = float(fit.fit_price_eur_mwh)
            index = float(fit.fit_index)

        term = s.term_years
        if term is None:
            runtime_term = float(horizon)
        else:
            term_f = float(term)
            if not term_f.is_integer():
                raise RevenueRuntimeSeamMissing(
                    "RUNTIME_TARIFF_TERM_GRAIN_SEAM_MISSING: stream "
                    f"{s.stream_id!r} term_years={term_f!r} is fractional; "
                    "the plan authority is model-year-granular while the "
                    "engine window is date-anchored from COD — boundary "
                    "half-periods would diverge"
                )
            runtime_term = term_f
            # The engine PPA window is DATE-anchored (COD + term) on a
            # calendar period axis: an anniversary falling inside a period
            # leaves a partial period priced at the tariff while the plan
            # (model-year grain) has the whole year inactive. Exact only
            # when the anniversary coincides with a period start, or lies
            # beyond the horizon.
            from dateutil.relativedelta import relativedelta
            from finco_core.engine.period_engine import PeriodEngine
            info = base_inputs.info
            axis_kwargs: dict[str, Any] = {}
            if getattr(info, "period_frequency", None) is not None:
                axis_kwargs["frequency"] = info.period_frequency
            if getattr(info, "cod_date", None) is not None:
                axis_kwargs["cod_date"] = info.cod_date
            if getattr(info, "period_axis_convention", None) is not None:
                convention = info.period_axis_convention
                axis_kwargs["period_axis_convention"] = getattr(
                    convention, "value", convention)
            axis = PeriodEngine(
                info.financial_close,
                info.construction_months,
                info.horizon_years,
                int(runtime_term),
                **axis_kwargs,
            )
            op_periods = [p for p in axis.periods() if p.is_operation]
            anniversary = axis.cod + relativedelta(years=int(runtime_term))
            aligned = (
                anniversary > op_periods[-1].end_date
                or any(p.start_date == anniversary for p in op_periods)
            )
            if not aligned:
                raise RevenueRuntimeSeamMissing(
                    "RUNTIME_TARIFF_TERM_ALIGNMENT_SEAM_MISSING: stream "
                    f"{s.stream_id!r} term {int(runtime_term)}y expires on "
                    f"{anniversary.isoformat()}, which falls inside an "
                    "operating period; the date-anchored engine window "
                    "would price that partial period at the tariff while "
                    "the plan (model-year grain) has it inactive — exact "
                    "parity requires the term to land on a period boundary"
                )

        if share < 1.0 or term is not None:
            # Unallocated / post-term volume sells at market_price_at_year,
            # which falls back to the PPA tariff when the curve is empty —
            # "unallocated volume earns nothing" is inexpressible without a
            # selected merchant authority.
            if merchant is None:
                raise RevenueRuntimeSeamMissing(
                    "RUNTIME_UNALLOCATED_VOLUME_WITHOUT_MERCHANT: stream "
                    f"{s.stream_id!r} leaves volume unallocated "
                    f"(share={share!r}, term={term!r}) and the plan "
                    "selects no merchant authority; the runtime would sell "
                    "that volume at the tariff-price fallback instead of "
                    "the plan's zero"
                )

        overrides["ppa_base_tariff"] = _finite(base_tariff, "tariff base")
        overrides["ppa_index"] = _finite(index, "tariff index")
        overrides["ppa_production_share"] = _finite(share, "volume share")
        overrides["ppa_term_years"] = _finite(runtime_term, "term years")
    else:
        # No tariff path: kill the PPA window entirely (term 0 → no period
        # is PPA-active) and zero the tariff fields so no stale authority
        # (and no empty-curve fallback price) survives.
        overrides["ppa_base_tariff"] = 0.0
        overrides["ppa_index"] = 0.0
        overrides["ppa_term_years"] = 0.0
        overrides["ppa_production_share"] = 0.0

    return overrides
