"""Dashboard composition for Hyperliquid-bound BTC/ETH perpetual context V2."""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import fmean

from app.radar_derivatives.contracts import DerivativesState
from app.radar_derivatives.hyperliquid import HyperliquidDerivativesProvider

_SOURCE_URL = "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals"
_PUBLISHER = "Hyperliquid"
_TRANSPORT = "Hyperliquid Info API"
_ENDPOINT = "POST /info"
_VENUE_CODES = (
    ("HlPerp", "Hyperliquid"),
    ("BinPerp", "Binance"),
    ("BybitPerp", "Bybit"),
)


def _usd(value: float) -> str:
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if absolute >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if absolute >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:,.2f}"


def _price(value: float | None) -> str:
    return "—" if value is None else f"${value:,.2f}"


def _bps(value: float | None) -> str:
    return "—" if value is None else f"{value:+.2f} bp"


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:+.2f}%"


def _ratio(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}x"


def _next_time(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


class DerivativesDashboardService:
    def __init__(self, provider=None) -> None:
        self.provider = provider or HyperliquidDerivativesProvider()

    @staticmethod
    def _asset_row(asset) -> dict:
        oi_usd = asset.open_interest_base * asset.mark_price
        basis_bps = ((asset.mark_price / asset.oracle_price) - 1.0) * 10_000.0
        funding_bps = asset.funding_rate * 10_000.0
        premium_bps = asset.premium_rate * 10_000.0 if asset.premium_rate is not None else None
        change_24h_pct = ((asset.mark_price / asset.prev_day_price) - 1.0) * 100.0
        oi_turnover = asset.day_notional_volume_usd / oi_usd if oi_usd > 0 else None
        impact_spread_bps = None
        if (
            asset.impact_bid_price is not None
            and asset.impact_ask_price is not None
            and asset.mid_price is not None
            and asset.mid_price > 0
        ):
            impact_spread_bps = (
                (asset.impact_ask_price - asset.impact_bid_price) / asset.mid_price
            ) * 10_000.0

        return {
            "symbol": asset.symbol,
            "state": "AVAILABLE",
            "mark_price": asset.mark_price,
            "mark_price_display": _price(asset.mark_price),
            "prev_day_price": asset.prev_day_price,
            "prev_day_price_display": _price(asset.prev_day_price),
            "change_24h_pct": change_24h_pct,
            "change_24h_display": _pct(change_24h_pct),
            "oracle_price": asset.oracle_price,
            "oracle_price_display": _price(asset.oracle_price),
            "mid_price": asset.mid_price,
            "mid_price_display": _price(asset.mid_price),
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
            "oi_turnover": oi_turnover,
            "oi_turnover_display": _ratio(oi_turnover),
            "impact_bid_price": asset.impact_bid_price,
            "impact_ask_price": asset.impact_ask_price,
            "impact_spread_bps": impact_spread_bps,
            "impact_spread_bps_display": _bps(impact_spread_bps),
            "max_leverage": asset.max_leverage,
            "max_leverage_display": f"{asset.max_leverage}x",
            "premium_bps": premium_bps,
            "premium_bps_display": _bps(premium_bps),
            "retrieved_at": asset.retrieved_at.isoformat(),
            "publisher": asset.publisher,
            "transport": asset.transport,
            "source_endpoint": asset.source_endpoint,
            "source_id": asset.source_id,
            "source_url": _SOURCE_URL,
        }

    @staticmethod
    def _funding_history_rows(snapshot, assets: list[dict]) -> list[dict]:
        points_by_symbol = {asset["symbol"]: [] for asset in assets}
        for point in snapshot.funding_history:
            if point.symbol in points_by_symbol:
                points_by_symbol[point.symbol].append(point)

        current_by_symbol = {asset["symbol"]: asset["funding_bps"] for asset in assets}
        rows = []
        for symbol in points_by_symbol:
            points = sorted(points_by_symbol[symbol], key=lambda point: point.observed_at)
            rate_bps = [point.funding_rate * 10_000.0 for point in points]
            average_bps = fmean(rate_bps) if rate_bps else None
            sum_bps = sum(rate_bps) if rate_bps else None
            latest_at = points[-1].observed_at if points else None
            rows.append(
                {
                    "symbol": symbol,
                    "current_funding_bps": current_by_symbol[symbol],
                    "current_funding_bps_display": _bps(current_by_symbol[symbol]),
                    "average_24h_bps": average_bps,
                    "average_24h_bps_display": _bps(average_bps),
                    "sum_24h_bps": sum_bps,
                    "sum_24h_bps_display": _bps(sum_bps),
                    "sample_count": len(points),
                    "latest_observed_at": latest_at.isoformat() if latest_at else None,
                    "latest_observed_at_display": _next_time(latest_at),
                }
            )
        return rows

    @staticmethod
    def _predicted_rows(snapshot, assets: list[dict]) -> list[dict]:
        lookup = {
            (row.symbol, row.venue_code): row
            for row in snapshot.predicted_funding
            if row.symbol in {"BTC", "ETH"}
        }
        rows = []
        for asset in assets:
            symbol = asset["symbol"]
            venues = {}
            available_rates = []
            for code, name in _VENUE_CODES:
                point = lookup.get((symbol, code))
                if point is None:
                    venues[code] = {
                        "name": name,
                        "rate_bps": None,
                        "rate_bps_display": "—",
                        "next_funding_at": None,
                        "next_funding_at_display": "—",
                    }
                    continue
                rate_bps = point.funding_rate * 10_000.0
                available_rates.append(rate_bps)
                venues[code] = {
                    "name": name,
                    "rate_bps": rate_bps,
                    "rate_bps_display": _bps(rate_bps),
                    "next_funding_at": point.next_funding_at.isoformat(),
                    "next_funding_at_display": _next_time(point.next_funding_at),
                }
            spread_bps = (
                max(available_rates) - min(available_rates)
                if len(available_rates) >= 2
                else None
            )
            rows.append(
                {
                    "symbol": symbol,
                    "venues": venues,
                    "spread_bps": spread_bps,
                    "spread_bps_display": (
                        "—" if spread_bps is None else f"{spread_bps:.2f} bp"
                    ),
                }
            )
        return rows

    @staticmethod
    def _funding_sign(rows: list[dict]) -> str:
        positives = sum(1 for row in rows if row["funding_bps"] > 0)
        negatives = sum(1 for row in rows if row["funding_bps"] < 0)
        if positives == len(rows):
            return "Both positive"
        if negatives == len(rows):
            return "Both negative"
        if positives == 0 and negatives == 0:
            return "Both flat"
        return "Mixed / flat"

    def read_dashboard(self) -> dict:
        try:
            snapshot = self.provider.read()
            if snapshot.state is not DerivativesState.AVAILABLE:
                raise ValueError("PROVIDER_RETURNED_UNAVAILABLE")
            rows = [self._asset_row(asset) for asset in snapshot.assets]
            combined_oi = sum(row["open_interest_usd"] for row in rows)
            combined_volume = sum(row["day_notional_volume_usd"] for row in rows)
            combined_turnover = combined_volume / combined_oi if combined_oi > 0 else None

            funding_history_rows = self._funding_history_rows(snapshot, rows)
            funding_history_state = (
                "AVAILABLE"
                if snapshot.funding_history and snapshot.funding_history_reason is None
                else "UNAVAILABLE"
            )
            predicted_rows = self._predicted_rows(snapshot, rows)
            predicted_state = (
                "AVAILABLE"
                if snapshot.predicted_funding and snapshot.predicted_funding_reason is None
                else "UNAVAILABLE"
            )

            return {
                "state": "AVAILABLE",
                "asset_count": len(rows),
                "assets": rows,
                "summary": {
                    "combined_open_interest_usd": combined_oi,
                    "combined_open_interest_usd_display": _usd(combined_oi),
                    "combined_day_notional_volume_usd": combined_volume,
                    "combined_day_notional_volume_usd_display": _usd(combined_volume),
                    "combined_oi_turnover": combined_turnover,
                    "combined_oi_turnover_display": _ratio(combined_turnover),
                    "funding_sign": self._funding_sign(rows),
                },
                "funding_history_state": funding_history_state,
                "funding_history_reason": (
                    snapshot.funding_history_reason
                    or (
                        "NO_FUNDING_HISTORY_IN_24H_WINDOW"
                        if not snapshot.funding_history
                        else None
                    )
                ),
                "funding_history": funding_history_rows,
                "predicted_funding_state": predicted_state,
                "predicted_funding_reason": (
                    snapshot.predicted_funding_reason
                    or (
                        "NO_PREDICTED_FUNDING_ROWS"
                        if not snapshot.predicted_funding
                        else None
                    )
                ),
                "predicted_funding": predicted_rows,
                "retrieved_at": snapshot.retrieved_at.isoformat(),
                "publisher": snapshot.publisher,
                "transport": snapshot.transport,
                "source_endpoint": snapshot.source_endpoint,
                "source_url": _SOURCE_URL,
                "freshness_note": (
                    "metaAndAssetCtxs has no source observation timestamp; current context "
                    "shows FINCO retrieval time only. fundingHistory carries event timestamps. "
                    "predictedFundings carries next-funding timestamps."
                ),
                "cross_venue_note": (
                    "Binance and Bybit predicted rates are read from Hyperliquid's "
                    "predictedFundings aggregation; FINCO does not claim direct venue authority."
                ),
            }
        except Exception as exc:  # noqa: BLE001 — domain boundary fails closed
            now = datetime.now(timezone.utc)
            return {
                "state": "UNAVAILABLE",
                "asset_count": 0,
                "assets": [],
                "summary": {},
                "funding_history_state": "UNAVAILABLE",
                "funding_history_reason": "PRIMARY_CONTEXT_UNAVAILABLE",
                "funding_history": [],
                "predicted_funding_state": "UNAVAILABLE",
                "predicted_funding_reason": "PRIMARY_CONTEXT_UNAVAILABLE",
                "predicted_funding": [],
                "retrieved_at": now.isoformat(),
                "publisher": _PUBLISHER,
                "transport": _TRANSPORT,
                "source_endpoint": _ENDPOINT,
                "source_url": _SOURCE_URL,
                "reason": f"DERIVATIVES_READ_FAILED:{type(exc).__name__}",
                "freshness_note": (
                    "No substitute exchange data is emitted when the primary "
                    "Hyperliquid context is unavailable."
                ),
                "cross_venue_note": (
                    "Cross-venue predictions are auxiliary Hyperliquid-aggregated evidence."
                ),
            }
