"""Dashboard composition for Hyperliquid-bound BTC/ETH perpetual context."""
from __future__ import annotations

from datetime import datetime, timezone

from app.radar_derivatives.contracts import DerivativesState
from app.radar_derivatives.hyperliquid import HyperliquidDerivativesProvider

_SOURCE_URL = "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals"
_PUBLISHER = "Hyperliquid"
_TRANSPORT = "Hyperliquid Info API"
_ENDPOINT = "POST /info · metaAndAssetCtxs"


def _usd(value: float) -> str:
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if absolute >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if absolute >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:,.2f}"


def _price(value: float) -> str:
    return f"${value:,.2f}"


def _bps(value: float) -> str:
    return f"{value:+.2f} bp"


class DerivativesDashboardService:
    def __init__(self, provider=None) -> None:
        self.provider = provider or HyperliquidDerivativesProvider()

    @staticmethod
    def _asset_row(asset) -> dict:
        oi_usd = asset.open_interest_base * asset.mark_price
        basis_bps = ((asset.mark_price / asset.oracle_price) - 1.0) * 10_000.0
        funding_bps = asset.funding_rate * 10_000.0
        premium_bps = asset.premium_rate * 10_000.0 if asset.premium_rate is not None else None
        return {
            "symbol": asset.symbol,
            "state": "AVAILABLE",
            "mark_price": asset.mark_price,
            "mark_price_display": _price(asset.mark_price),
            "oracle_price": asset.oracle_price,
            "oracle_price_display": _price(asset.oracle_price),
            "basis_bps": basis_bps,
            "basis_bps_display": _bps(basis_bps),
            "funding_rate": asset.funding_rate,
            "funding_bps": funding_bps,
            "funding_bps_display": _bps(funding_bps),
            "open_interest_base": asset.open_interest_base,
            "open_interest_usd": oi_usd,
            "open_interest_usd_display": _usd(oi_usd),
            "day_notional_volume_usd": asset.day_notional_volume_usd,
            "day_notional_volume_usd_display": _usd(asset.day_notional_volume_usd),
            "premium_bps": premium_bps,
            "premium_bps_display": _bps(premium_bps) if premium_bps is not None else "—",
            "retrieved_at": asset.retrieved_at.isoformat(),
            "publisher": asset.publisher,
            "transport": asset.transport,
            "source_endpoint": asset.source_endpoint,
            "source_id": asset.source_id,
            "source_url": _SOURCE_URL,
        }

    def read_dashboard(self) -> dict:
        try:
            snapshot = self.provider.read()
            if snapshot.state is not DerivativesState.AVAILABLE:
                raise ValueError("PROVIDER_RETURNED_UNAVAILABLE")
            rows = [self._asset_row(asset) for asset in snapshot.assets]
            combined_oi = sum(row["open_interest_usd"] for row in rows)
            combined_volume = sum(row["day_notional_volume_usd"] for row in rows)
            return {
                "state": "AVAILABLE",
                "asset_count": len(rows),
                "assets": rows,
                "summary": {
                    "combined_open_interest_usd": combined_oi,
                    "combined_open_interest_usd_display": _usd(combined_oi),
                    "combined_day_notional_volume_usd": combined_volume,
                    "combined_day_notional_volume_usd_display": _usd(combined_volume),
                },
                "retrieved_at": snapshot.retrieved_at.isoformat(),
                "publisher": snapshot.publisher,
                "transport": snapshot.transport,
                "source_endpoint": snapshot.source_endpoint,
                "source_url": _SOURCE_URL,
                "freshness_note": (
                    "Hyperliquid metaAndAssetCtxs does not include a source observation timestamp; "
                    "FINCO shows retrieval time and does not infer freshness."
                ),
            }
        except Exception as exc:  # noqa: BLE001 — domain boundary fails closed
            now = datetime.now(timezone.utc)
            return {
                "state": "UNAVAILABLE",
                "asset_count": 0,
                "assets": [],
                "summary": {},
                "retrieved_at": now.isoformat(),
                "publisher": _PUBLISHER,
                "transport": _TRANSPORT,
                "source_endpoint": _ENDPOINT,
                "source_url": _SOURCE_URL,
                "reason": f"DERIVATIVES_READ_FAILED:{type(exc).__name__}",
                "freshness_note": (
                    "No exchange observation timestamp is available from this endpoint; "
                    "no substitute exchange data is emitted."
                ),
            }
