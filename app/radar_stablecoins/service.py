"""Stablecoin liquidity dashboard composition."""
from __future__ import annotations

from datetime import datetime, timezone

from app.radar_stablecoins.contracts import StablecoinSnapshot, StablecoinState
from app.radar_stablecoins.defillama import DefiLlamaStablecoinProvider

_EXPECTED_PUBLISHER = "DefiLlama"
_EXPECTED_TRANSPORT = "DefiLlama Stablecoins API"
_EXPECTED_ENDPOINT = "/stablecoins?includePrices=true"
_SOURCE_URL = "https://defillama.com/stablecoins"


def _compact_usd(value: float | None) -> str:
    if value is None:
        return "—"
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if absolute >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    return f"${value:,.0f}"


def _pct(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return ((current / previous) - 1.0) * 100.0


def _pct_display(value: float | None) -> str:
    return "—" if value is None else f"{value:+.2f}%"


def _sum_previous(assets, attr: str) -> float | None:
    values = [getattr(asset, attr) for asset in assets]
    if any(value is None for value in values):
        return None
    return sum(values)


def _summary_row(
    *,
    key: str,
    title: str,
    value: float | None,
    unit: str,
    source_id: str,
    current_for_changes: float | None = None,
    previous_day: float | None = None,
    previous_week: float | None = None,
    previous_month: float | None = None,
    price: float | None = None,
    reason: str | None = None,
) -> dict:
    available = value is not None and reason is None
    if unit == "percent":
        display = "—" if value is None else f"{value:.2f}%"
    elif unit == "count":
        display = "—" if value is None else f"{value:,.0f}"
    else:
        display = _compact_usd(value)
    basis = value if current_for_changes is None else current_for_changes
    return {
        "key": key,
        "title": title,
        "state": "AVAILABLE" if available else "UNAVAILABLE",
        "value": value,
        "value_display": display,
        "change_1d": _pct(basis, previous_day) if available else None,
        "change_7d": _pct(basis, previous_week) if available else None,
        "change_30d": _pct(basis, previous_month) if available else None,
        "change_1d_display": _pct_display(_pct(basis, previous_day)) if available else "—",
        "change_7d_display": _pct_display(_pct(basis, previous_week)) if available else "—",
        "change_30d_display": _pct_display(_pct(basis, previous_month)) if available else "—",
        "price": price,
        "price_display": "—" if price is None else f"${price:.4f}".rstrip("0").rstrip("."),
        "source_id": source_id,
        "reason": reason,
    }


def _unavailable_dashboard(reason: str, retrieved_at: datetime | None = None) -> dict:
    retrieved_at = retrieved_at or datetime.now(timezone.utc)
    keys = (
        ("total_supply_usd", "USD Stablecoin Supply", "sum:peggedUSD"),
        ("usdt_supply_usd", "USDT Supply", "asset:1:USDT"),
        ("usdc_supply_usd", "USDC Supply", "asset:2:USDC"),
        ("usdt_share", "USDT Share", "derived:USDT/total"),
        ("usdc_share", "USDC Share", "derived:USDC/total"),
        ("tracked_count", "Tracked USD Stablecoins", "count:peggedUSD"),
    )
    return {
        "state": "UNAVAILABLE",
        "retrieved_at": retrieved_at.isoformat(),
        "summary_rows": [
            _summary_row(
                key=key,
                title=title,
                value=None,
                unit="percent" if "share" in key else "count" if key == "tracked_count" else "usd",
                source_id=source_id,
                reason=reason,
            )
            for key, title, source_id in keys
        ],
        "top_assets": [],
        "publisher": _EXPECTED_PUBLISHER,
        "transport": _EXPECTED_TRANSPORT,
        "source_endpoint": _EXPECTED_ENDPOINT,
        "source_url": _SOURCE_URL,
        "reason": reason,
    }


class StablecoinDashboardService:
    def __init__(self, provider=None, *, top_n: int = 8) -> None:
        self.provider = provider or DefiLlamaStablecoinProvider()
        self.top_n = top_n

    @staticmethod
    def _bound(snapshot: StablecoinSnapshot) -> bool:
        return (
            snapshot.publisher == _EXPECTED_PUBLISHER
            and snapshot.transport == _EXPECTED_TRANSPORT
            and snapshot.source_endpoint == _EXPECTED_ENDPOINT
        )

    def read_dashboard(self) -> dict:
        try:
            snapshot = self.provider.read_snapshot()
        except Exception as exc:
            return _unavailable_dashboard(f"PROVIDER_READ_FAILED:{type(exc).__name__}")
        if not self._bound(snapshot):
            return _unavailable_dashboard("SOURCE_BINDING_MISMATCH", snapshot.retrieved_at)
        if snapshot.state is StablecoinState.UNAVAILABLE:
            return _unavailable_dashboard(snapshot.reason or "STABLECOINS_UNAVAILABLE", snapshot.retrieved_at)

        assets = tuple(snapshot.assets)
        total = sum(asset.current for asset in assets)
        prev_day = _sum_previous(assets, "previous_day")
        prev_week = _sum_previous(assets, "previous_week")
        prev_month = _sum_previous(assets, "previous_month")

        def exact(asset_id: str, symbol: str):
            matches = [a for a in assets if a.asset_id == asset_id and a.symbol.upper() == symbol]
            return matches[0] if len(matches) == 1 else None

        usdt = exact("1", "USDT")
        usdc = exact("2", "USDC")
        summary = [
            _summary_row(
                key="total_supply_usd",
                title="USD Stablecoin Supply",
                value=total,
                unit="usd",
                source_id="sum:peggedAssets[*].circulating.peggedUSD|pegType=peggedUSD",
                previous_day=prev_day,
                previous_week=prev_week,
                previous_month=prev_month,
            ),
        ]
        for key, title, asset, source_id in (
            ("usdt_supply_usd", "USDT Supply", usdt, "asset:1:USDT"),
            ("usdc_supply_usd", "USDC Supply", usdc, "asset:2:USDC"),
        ):
            if asset is None:
                summary.append(_summary_row(
                    key=key, title=title, value=None, unit="usd", source_id=source_id,
                    reason="CANONICAL_ASSET_BINDING_UNAVAILABLE"))
            else:
                summary.append(_summary_row(
                    key=key,
                    title=title,
                    value=asset.current,
                    unit="usd",
                    source_id=source_id,
                    previous_day=asset.previous_day,
                    previous_week=asset.previous_week,
                    previous_month=asset.previous_month,
                    price=asset.price,
                ))

        for key, title, asset, source_id in (
            ("usdt_share", "USDT Share", usdt, "derived:asset:1:USDT/total_supply_usd"),
            ("usdc_share", "USDC Share", usdc, "derived:asset:2:USDC/total_supply_usd"),
        ):
            if asset is None or total <= 0:
                summary.append(_summary_row(
                    key=key, title=title, value=None, unit="percent", source_id=source_id,
                    reason="CANONICAL_ASSET_BINDING_UNAVAILABLE"))
            else:
                summary.append(_summary_row(
                    key=key, title=title, value=(asset.current / total) * 100.0,
                    unit="percent", source_id=source_id))

        summary.append(_summary_row(
            key="tracked_count",
            title="Tracked USD Stablecoins",
            value=float(len(assets)),
            unit="count",
            source_id="count:peggedAssets|pegType=peggedUSD",
        ))

        top_assets = []
        for asset in sorted(assets, key=lambda item: item.current, reverse=True)[: self.top_n]:
            top_assets.append({
                "asset_id": asset.asset_id,
                "name": asset.name,
                "symbol": asset.symbol,
                "supply": asset.current,
                "supply_display": _compact_usd(asset.current),
                "price": asset.price,
                "price_display": "—" if asset.price is None else f"${asset.price:.4f}".rstrip("0").rstrip("."),
                "change_1d": _pct(asset.current, asset.previous_day),
                "change_7d": _pct(asset.current, asset.previous_week),
                "change_30d": _pct(asset.current, asset.previous_month),
                "change_1d_display": _pct_display(_pct(asset.current, asset.previous_day)),
                "change_7d_display": _pct_display(_pct(asset.current, asset.previous_week)),
                "change_30d_display": _pct_display(_pct(asset.current, asset.previous_month)),
            })

        unavailable = sum(row["state"] == "UNAVAILABLE" for row in summary)
        state = "PARTIAL" if unavailable else "AVAILABLE"
        return {
            "state": state,
            "retrieved_at": snapshot.retrieved_at.isoformat(),
            "summary_rows": summary,
            "top_assets": top_assets,
            "publisher": snapshot.publisher,
            "transport": snapshot.transport,
            "source_endpoint": snapshot.source_endpoint,
            "source_url": _SOURCE_URL,
            "reason": None,
        }
