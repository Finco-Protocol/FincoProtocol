"""Advanced Revenue V4 candidate (WF-04A / Harvest V4 follow-up).

RELEASE-CLOSED CANDIDATE — this package is not released financial
authority, is not read by any production path, and adds no product
surface. See ``contracts.py`` for the typed scope and
``docs/model_v2/REVENUE_V4_CANDIDATE_OWNER_DECISION_PACKET.md`` for the
open financial decisions.

Naming: "Revenue V3" is taken on main (Capacity/Ancillary/REC release-
closed candidate); this candidate uses ``REVENUE_V4_*`` throughout.
"""
from app.revenue_v4_candidate.contracts import (  # noqa: F401
    ACTIVATION_ENABLED,
    FEE_BASES,
    ESCALATION_TIMINGS,
    NPH_ACTIONS,
    NPH_SCOPES,
    PRICE_MODES,
    VOLUME_MODES,
    AdvancedRevenueV4Candidate,
    ContractedVolume,
    NegativePriceHoursPolicy,
    PriceModeRule,
    RouteToMarketFee,
    StreamCandidate,
    parse_candidate,
    parse_contracted_volume,
    parse_negative_price_hours,
    parse_price_mode,
    parse_route_to_market,
    parse_stream_candidate,
    require_release,
)
from app.revenue_v4_candidate.pure import (  # noqa: F401
    NegativePriceSettlement,
    aggregate_monthly_to_periods,
    apply_negative_price_policy,
    apply_route_to_market_fee,
    classify_hourly_prices,
    completed_annual_reviews,
    convert_monthly_mw,
    fixed_annual_mwh_to_periods,
    period_negative_share,
    resolve_market_mode_price,
)

__all__ = [
    "ACTIVATION_ENABLED", "require_release",
    "NPH_SCOPES", "NPH_ACTIONS", "VOLUME_MODES", "PRICE_MODES",
    "FEE_BASES", "ESCALATION_TIMINGS",
    "NegativePriceHoursPolicy", "ContractedVolume", "PriceModeRule",
    "RouteToMarketFee", "StreamCandidate", "AdvancedRevenueV4Candidate",
    "parse_negative_price_hours", "parse_contracted_volume",
    "parse_price_mode", "parse_route_to_market", "parse_stream_candidate",
    "parse_candidate",
    "NegativePriceSettlement", "classify_hourly_prices",
    "apply_negative_price_policy", "period_negative_share",
    "fixed_annual_mwh_to_periods", "convert_monthly_mw",
    "aggregate_monthly_to_periods", "resolve_market_mode_price",
    "completed_annual_reviews", "apply_route_to_market_fee",
]
