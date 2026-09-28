"""Blinded, deterministic feature state shared by Jev and the control baseline."""
from __future__ import annotations

from decimal import Decimal

from finco_radar.authority.contracts import AuthorityState

from .contracts import MarketSession, RwaReflexState


FEATURE_SCHEMA_VERSION = "RWA_REFLEX_FEATURES_V2"
FIRST_SAMPLE_DEPTH_POLICY = "SINGLE_COMPARABLE_ASSET_COHORT_ABSOLUTE_DEPTH_BUCKETS"
OUTBOUND_FIELD_ALLOWLIST = frozenset({
    "schema_version", "market_session", "deviation_bucket", "depth_bucket",
})


def _deviation_bucket(value: Decimal | None) -> str:
    if value is None:
        return "UNKNOWN"
    magnitude = abs(value)
    if magnitude < Decimal("50"):
        return "LT_50_BPS"
    if magnitude < Decimal("100"):
        return "50_TO_99_BPS"
    if magnitude < Decimal("200"):
        return "100_TO_199_BPS"
    return "GE_200_BPS"


def _depth_bucket(value: Decimal | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value < Decimal("25000"):
        return "LT_25K_USD"
    if value < Decimal("100000"):
        return "25K_TO_99K_USD"
    return "GE_100K_USD"


def build_parity_feature_state(state: RwaReflexState) -> dict[str, str]:
    """Return the exact information set permitted to both Jev and baseline.

    RWA_REFLEX_JEV_BASELINE_INFORMATION_PARITY: no identity, ticker, contract,
    wallet, entitlement, workspace, raw prices, private model inputs, warnings or
    provider-specific labels can enter this payload.

    The first calibration sample deliberately keeps absolute depth buckets only
    for one pre-declared comparable asset cohort. Heterogeneous-asset sampling is
    blocked by live preflight until an asset-relative depth feature is designed.
    """
    if state.state is not AuthorityState.AVAILABLE:
        raise ValueError("feature state requires AVAILABLE canonical Reflex state")
    payload = {
        "schema_version": FEATURE_SCHEMA_VERSION,
        "market_session": state.market_session.value,
        "deviation_bucket": _deviation_bucket(state.premium_deviation_bps),
        "depth_bucket": _depth_bucket(state.depth_1pct_usd),
    }
    if set(payload) != OUTBOUND_FIELD_ALLOWLIST:
        raise AssertionError("RWA_REFLEX_OUTBOUND_ALLOWLIST_VIOLATION")
    return payload


def feature_cell_key(features: dict[str, str]) -> str:
    if set(features) != OUTBOUND_FIELD_ALLOWLIST:
        raise ValueError("feature key requires exact parity feature schema")
    return "|".join((features["market_session"], features["deviation_bucket"], features["depth_bucket"]))


def eligible_regular_session(features: dict[str, str]) -> bool:
    return features.get("market_session") == MarketSession.OPEN.value
