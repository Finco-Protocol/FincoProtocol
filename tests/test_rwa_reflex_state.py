from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.radar_rwa.reflex import BasisHistoryStats, LiquidityContext, MarketSession, RwaReflexContext, build_reflex_state
from finco_radar.assets.contracts import AssetKey
from finco_radar.authority.contracts import AuthoritySnapshot, AuthorityState, BasisPointQuantity, ExecutionGap, ExecutionLayer, ReferenceLayer
from finco_radar.quotes.contracts import QuoteSide

NOW = datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc)
UID = "0x" + "11" * 32
KEY = AssetKey(4663, "0x" + "22" * 20)


def _snapshot(*, premium_state=AuthorityState.AVAILABLE, underlying_state=AuthorityState.AVAILABLE,
              token_state=AuthorityState.AVAILABLE, uid=UID, key=KEY) -> AuthoritySnapshot:
    underlying = ReferenceLayer(underlying_state, uid, key, "Example", Decimal("195") if underlying_state is AuthorityState.AVAILABLE else None,
                                "ROBINHOOD_STOCK_TOKEN_BOUND_PRICE", NOW, None if underlying_state is AuthorityState.AVAILABLE else "STALE_REFERENCE")
    token = ReferenceLayer(token_state, uid, key, "Example", Decimal("197.769") if token_state is AuthorityState.AVAILABLE else None,
                           "CHAINLINK_INDEPENDENT_TOKEN_REFERENCE", NOW, None if token_state is AuthorityState.AVAILABLE else "STALE_TOKEN_REFERENCE")
    available = premium_state is AuthorityState.AVAILABLE
    premium = BasisPointQuantity(premium_state, Decimal("142") if available else None,
                                 Decimal("197.769") if available else None, Decimal("195") if available else None,
                                 "(token / underlying - 1) * 10000",
                                 ("ROBINHOOD_STOCK_TOKEN_BOUND_PRICE", "CHAINLINK_INDEPENDENT_TOKEN_REFERENCE") if available else (),
                                 (NOW, NOW) if available else (), None if available else "REFERENCE_EVIDENCE_NOT_AVAILABLE")
    execution = ExecutionLayer(AuthorityState.AVAILABLE, key, QuoteSide.BUY, Decimal("1000"), Decimal("198.315"),
                               "TEST_EXECUTION_PROVIDER", (("4663:a", "4663:b", "pool"),), Decimal("1"), Decimal("0.1"), NOW)
    gap = ExecutionGap(AuthorityState.AVAILABLE if available else AuthorityState.UNAVAILABLE,
                       Decimal("142") if available else None, Decimal("28") if available else None,
                       Decimal("170") if available else None, "EVIDENCE_ONLY_INCLUSION_UNRESOLVED")
    return AuthoritySnapshot(uid, key, "ROBINHOOD_ASSET_REGISTRY", NOW, underlying, token, premium, execution, gap)


def _context(*, observed_at=NOW, median=Decimal("20"), session=MarketSession.OPEN) -> RwaReflexContext:
    return RwaReflexContext(
        market_session=session,
        session_source="NYSE_CALENDAR",
        basis_history=BasisHistoryStats(
            mean_bps=Decimal("12"), std_bps=Decimal("46"), sample_count=720,
            observed_at=observed_at, source="FINCO_CANONICAL_PREMIUM_HISTORY", window="trailing_5_regular_sessions",
            median_bps=median,
        ),
        liquidity=LiquidityContext(observed_at=observed_at, source="ROBINHOOD_CHAIN_DEX",
                                   liquidity_usd=Decimal("250000"), depth_1pct_usd=Decimal("84200"), venue_id="RH_DEX_POOL"),
    )


def test_reflex_state_reuses_authority_and_records_reconstructable_context():
    state = build_reflex_state(_snapshot(), as_of=NOW + timedelta(seconds=30), context=_context())
    assert state.state is AuthorityState.AVAILABLE
    assert state.reference_premium_bps == Decimal("142")
    assert state.structural_premium_bps == Decimal("20")
    assert state.premium_deviation_bps == Decimal("122")
    assert state.basis_z_score == Decimal("2.8261")
    assert state.provenance is not None
    assert state.provenance.history_sample_count == 720
    assert state.provenance.history_window == "trailing_5_regular_sessions"
    assert state.provenance.history_median_bps == Decimal("20")
    assert state.provenance.liquidity_venue_id == "RH_DEX_POOL"
    assert state.provenance.session_source == "NYSE_CALENDAR"


@pytest.mark.parametrize("layer", ["premium", "underlying", "token"])
def test_canonical_stale_fails_closed(layer):
    kwargs = {}
    if layer == "premium": kwargs["premium_state"] = AuthorityState.STALE
    if layer == "underlying": kwargs["underlying_state"] = AuthorityState.STALE
    if layer == "token": kwargs["token_state"] = AuthorityState.STALE
    state = build_reflex_state(_snapshot(**kwargs), as_of=NOW + timedelta(seconds=30), context=_context())
    assert state.state is AuthorityState.STALE
    assert state.reference_premium_bps is None
    assert state.premium_deviation_bps is None
    # RWA_REFLEX_CANONICAL_STALE_FAILS_CLOSED


def test_optional_stale_context_is_omitted_without_reviving_or_poisoning_authority():
    old = NOW - timedelta(hours=1)
    state = build_reflex_state(_snapshot(), as_of=NOW, context=_context(observed_at=old), max_context_age_seconds=300)
    assert state.state is AuthorityState.AVAILABLE
    assert state.basis_z_score is None
    assert state.structural_premium_bps is None
    assert state.liquidity_usd is None
    assert state.context_warnings == ("BASIS_HISTORY_STALE", "LIQUIDITY_CONTEXT_STALE")


def test_reflex_state_requires_canonical_identity_and_timezone():
    state = build_reflex_state(_snapshot(uid=None), as_of=NOW, context=_context())
    assert state.state is AuthorityState.IDENTITY_UNAVAILABLE
    with pytest.raises(ValueError, match="timezone-aware"):
        build_reflex_state(_snapshot(), as_of=datetime(2026, 9, 28, 9, 0), context=_context())
