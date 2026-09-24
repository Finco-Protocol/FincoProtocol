"""Composition service for the FINCO Radar RWA terminal."""
from __future__ import annotations

from app.radar_rwa.coingecko import CoinGeckoRwaProvider
from app.radar_rwa.contracts import RwaAssetMarket, RwaSnapshotState

_MARKETS_SOURCE_URL = "https://docs.coingecko.com/demo/reference/rwas-markets"
_LIST_SOURCE_URL = "https://docs.coingecko.com/demo/reference/rwas-list"


def _money(value: float | None) -> str:
    if value is None:
        return "—"
    magnitude = abs(value)
    if magnitude >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f}T"
    if magnitude >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if magnitude >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if magnitude >= 1_000:
        return f"${value / 1_000:.2f}K"
    return f"${value:,.2f}"


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:+.2f}%"


def _row(asset: RwaAssetMarket) -> dict:
    return {
        "id": asset.id,
        "symbol": asset.symbol,
        "name": asset.name,
        "asset_type": asset.asset_type.value,
        "state": asset.state.value,
        "current_price": asset.current_price,
        "current_price_display": _money(asset.current_price),
        "market_cap": asset.market_cap,
        "market_cap_display": _money(asset.market_cap),
        "total_volume": asset.total_volume,
        "total_volume_display": _money(asset.total_volume),
        "change_24h": asset.price_change_24h,
        "change_24h_display": _pct(asset.price_change_24h),
        "change_7d": asset.price_change_7d,
        "change_7d_display": _pct(asset.price_change_7d),
        "change_30d": asset.price_change_30d,
        "change_30d_display": _pct(asset.price_change_30d),
        "observed_at": asset.observed_at.isoformat(),
        "retrieved_at": asset.retrieved_at.isoformat(),
        "source_endpoint": asset.source_endpoint,
        "source_id": f"rwa:{asset.id}",
        "publisher": asset.publisher,
        "transport": asset.transport,
        "source_url": _MARKETS_SOURCE_URL,
    }


class RwaDashboardService:
    def __init__(self, provider=None) -> None:
        self.provider = provider or CoinGeckoRwaProvider()

    def read_dashboard(self) -> dict:
        snapshot = self.provider.read_snapshot()
        if snapshot.state is RwaSnapshotState.UNAVAILABLE:
            return {
                "state": "UNAVAILABLE",
                "counts": [],
                "sections": [],
                "reason": snapshot.reason,
                "retrieved_at": snapshot.retrieved_at.isoformat(),
                "publisher": snapshot.publisher,
                "transport": snapshot.transport,
                "list_source_url": _LIST_SOURCE_URL,
                "markets_source_url": _MARKETS_SOURCE_URL,
            }

        all_assets = snapshot.leaders + snapshot.stock_leaders
        stale_count = sum(asset.state.value == "STALE" for asset in all_assets)
        dashboard_state = "STALE" if stale_count else "AVAILABLE"
        counts = [
            {"key": "all", "title": "Tracked RWAs", "value": snapshot.total_count},
            {"key": "stock", "title": "Tokenized Stocks", "value": snapshot.stock_count},
            {"key": "commodity", "title": "Tokenized Commodities", "value": snapshot.commodity_count},
            {"key": "etf", "title": "Tokenized ETFs", "value": snapshot.etf_count},
        ]
        return {
            "state": dashboard_state,
            "counts": counts,
            "sections": [
                {
                    "key": "leaders",
                    "title": "Tokenized Market Leaders",
                    "subtitle": "Underlying RWA identities ranked by aggregated tokenized market cap",
                    "rows": [_row(asset) for asset in snapshot.leaders],
                },
                {
                    "key": "stocks",
                    "title": "Tokenized Stocks",
                    "subtitle": "Underlying equities aggregated across tracked token issuers",
                    "rows": [_row(asset) for asset in snapshot.stock_leaders],
                },
            ],
            "reason": None,
            "retrieved_at": snapshot.retrieved_at.isoformat(),
            "publisher": snapshot.publisher,
            "transport": snapshot.transport,
            "list_source_url": _LIST_SOURCE_URL,
            "markets_source_url": _MARKETS_SOURCE_URL,
        }
