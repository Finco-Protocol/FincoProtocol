from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.radar_rwa.reflex import BasisHistoryStats, LiquidityContext, MarketSession, RwaReflexContext, build_reflex_state
from finco_radar.assets.contracts import AssetKey
from finco_radar.authority.contracts import AuthoritySnapshot, AuthorityState, BasisPointQuantity, ExecutionGap, ExecutionLayer, ReferenceLayer
from finco_radar.quotes.contracts import QuoteSide

NOW = datetime(2026, 9, 28, 14, 0, tzinfo=timezone.utc)
UID = "0x" + "55" * 32
KEY = AssetKey(4663, "0x" + "66" * 20)


def authority(*, uid=UID, key=KEY, premium_bps=Decimal("142"), observed_at=NOW,
              premium_state=AuthorityState.AVAILABLE, underlying_state=AuthorityState.AVAILABLE,
              token_state=AuthorityState.AVAILABLE, registry_source="ROBINHOOD_ASSET_REGISTRY"):
    underlying = ReferenceLayer(underlying_state, uid, key, "Example", Decimal("100") if underlying_state is AuthorityState.AVAILABLE else None,
                                "ROBINHOOD_STOCK_TOKEN_BOUND_PRICE", observed_at, None if underlying_state is AuthorityState.AVAILABLE else "STALE")
    token_price = Decimal("100") * (Decimal("1") + premium_bps / Decimal("10000"))
    token = ReferenceLayer(token_state, uid, key, "Example", token_price if token_state is AuthorityState.AVAILABLE else None,
                           "CHAINLINK_INDEPENDENT_TOKEN_REFERENCE", observed_at, None if token_state is AuthorityState.AVAILABLE else "STALE")
    available = premium_state is AuthorityState.AVAILABLE
    premium = BasisPointQuantity(premium_state, premium_bps if available else None,
                                 token_price if available else None, Decimal("100") if available else None,
                                 "(token / underlying - 1) * 10000",
                                 (underlying.source, token.source) if available else (),
                                 (observed_at, observed_at) if available else (), None if available else "NOT_AVAILABLE")
    execution = ExecutionLayer(AuthorityState.AVAILABLE, key, QuoteSide.BUY, Decimal("1000"), token_price + Decimal("0.2"),
                               "TEST_EXECUTION_PROVIDER", (("4663:a", "4663:b", "pool"),), Decimal("1"), Decimal("0.1"), observed_at)
    gap = ExecutionGap(AuthorityState.AVAILABLE if available else AuthorityState.UNAVAILABLE,
                       premium_bps if available else None, Decimal("20") if available else None,
                       premium_bps + Decimal("20") if available else None, "EVIDENCE_ONLY_INCLUSION_UNRESOLVED")
    return AuthoritySnapshot(uid, key, registry_source, observed_at, underlying, token, premium, execution, gap)


def context(*, observed_at=NOW, history_observed_at=None, median=Decimal("20"), session=MarketSession.OPEN,
            history_source="FINCO_CANONICAL_PREMIUM_HISTORY", history_window="trailing_5_regular_sessions",
            history_methodology="RWA_REFLEX_PREMIUM_HISTORY_V2", history_sample_count=50,
            depth=Decimal("84200"), session_open_at=None, session_close_at=None):
    history_observed_at = history_observed_at or (observed_at - timedelta(seconds=1))
    session_open_at = session_open_at or (observed_at - timedelta(hours=4))
    session_close_at = session_close_at or (observed_at + timedelta(hours=2))
    return RwaReflexContext(
        market_session=session,
        session_source="NYSE_CALENDAR",
        regular_session_date=observed_at.date().isoformat(),
        regular_session_open_at=session_open_at,
        regular_session_close_at=session_close_at,
        basis_history=BasisHistoryStats(
            mean_bps=Decimal("12"), std_bps=Decimal("46"), sample_count=history_sample_count,
            observed_at=history_observed_at, source=history_source, window=history_window,
            median_bps=median, methodology_version=history_methodology,
        ),
        liquidity=LiquidityContext(
            observed_at=observed_at, source="ROBINHOOD_CHAIN_DEX", liquidity_usd=Decimal("250000"),
            depth_1pct_usd=depth, venue_id="RH_DEX_POOL",
        ),
    )


def state(*, premium_bps=Decimal("142"), observed_at=NOW, median=Decimal("20"), session=MarketSession.OPEN,
          history_source="FINCO_CANONICAL_PREMIUM_HISTORY", history_observed_at=None,
          history_window="trailing_5_regular_sessions", history_methodology="RWA_REFLEX_PREMIUM_HISTORY_V2",
          history_sample_count=50, depth=Decimal("84200"), uid=UID, key=KEY, session_close_at=None):
    return build_reflex_state(
        authority(uid=uid, key=key, premium_bps=premium_bps, observed_at=observed_at),
        as_of=observed_at + timedelta(seconds=10),
        context=context(
            observed_at=observed_at, history_observed_at=history_observed_at, median=median,
            session=session, history_source=history_source, history_window=history_window,
            history_methodology=history_methodology, history_sample_count=history_sample_count,
            depth=depth, session_close_at=session_close_at,
        ),
    )
