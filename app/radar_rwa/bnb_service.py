"""Read-only BNB RWA market presentation over typed provider observations."""
from __future__ import annotations

from decimal import Decimal

from .bnb_coingecko import CoinGeckoBnbRwaProvider
from .bnb_contracts import BnbRwaMarketObservation, BnbRwaMarketSnapshot


_CATEGORY_URL = "https://www.coingecko.com/en/categories/tokenized-products"
_MARKETS_DOC_URL = "https://docs.coingecko.com/reference/coins-markets"
_DEPLOYMENTS_DOC_URL = "https://docs.coingecko.com/reference/coins-list"


def _decimal(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _money(value: Decimal | None) -> str:
    if value is None:
        return "Unavailable"
    for threshold, suffix in (
        (Decimal("1000000000000"), "T"),
        (Decimal("1000000000"), "B"),
        (Decimal("1000000"), "M"),
        (Decimal("1000"), "K"),
    ):
        if abs(value) >= threshold:
            return f"${value / threshold:,.2f}{suffix}"
    return f"${value:,.2f}"


def _percent(value: Decimal | None) -> str:
    return "Unavailable" if value is None else f"{value:+.2f}%"


def _row(row: BnbRwaMarketObservation) -> dict:
    key = row.asset_key
    return {
        "provider_id": row.provider_id,
        "symbol": row.symbol,
        "name": row.name,
        "asset_key": None if key is None else {
            "chain_id": key.chain_id,
            "contract_address": key.contract_address,
            "canonical_id": key.canonical_id,
        },
        "deployment_reason": row.deployment_reason,
        "robinhood_binding": row.robinhood_binding.value,
        "state": row.state.value,
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        "price_usd": _decimal(row.price_usd),
        "market_cap_usd": _decimal(row.market_cap_usd),
        "volume_24h_usd": _decimal(row.volume_24h_usd),
        "price_change_24h_pct": _decimal(row.price_change_24h_pct),
        "circulating_supply": _decimal(row.circulating_supply),
        "total_supply": _decimal(row.total_supply),
        "unavailable_fields": list(row.unavailable_fields),
        "source": row.source,
        "provider_asset_id": row.provider_id,
        "market_endpoint": row.market_endpoint,
        "deployment_endpoint": row.deployment_endpoint,
        "classification": row.classification,
        "market_scope": row.market_scope,
        "price_display": _money(row.price_usd),
        "market_cap_display": _money(row.market_cap_usd),
        "volume_display": _money(row.volume_24h_usd),
        "change_display": _percent(row.price_change_24h_pct),
    }


def serialize_bnb_snapshot(snapshot: BnbRwaMarketSnapshot) -> dict:
    rows = [_row(row) for row in snapshot.observations]
    rows.sort(key=lambda row: (
        row["state"] != "AVAILABLE",
        row["market_cap_usd"] is None,
        -(Decimal(row["market_cap_usd"]) if row["market_cap_usd"] is not None else Decimal(0)),
        row["provider_id"],
    ))
    return {
        "chain": {"name": "BNB Smart Chain", "chain_id": snapshot.chain_id},
        "state": snapshot.state.value,
        "retrieved_at": snapshot.retrieved_at.isoformat(),
        "category_id": snapshot.category_id,
        "category_source_url": _CATEGORY_URL,
        "selection": "Top 250 CoinGecko tokenized-products category rows by market cap; BNB-listed subset",
        "source": snapshot.source,
        "source_endpoints": list(snapshot.source_endpoints),
        "market_source_url": _MARKETS_DOC_URL,
        "deployment_source_url": _DEPLOYMENTS_DOC_URL,
        "market_scope": snapshot.market_scope,
        "observed_count": len(snapshot.observations),
        "deployment_available_count": snapshot.deployment_available_count,
        "deployment_unavailable_count": snapshot.deployment_unavailable_count,
        "current_count": snapshot.current_count,
        "stale_count": snapshot.stale_count,
        "observed_market_cap_usd": _decimal(snapshot.observed_market_cap_usd),
        "observed_volume_24h_usd": _decimal(snapshot.observed_volume_24h_usd),
        "observed_market_cap_display": _money(snapshot.observed_market_cap_usd),
        "observed_volume_24h_display": _money(snapshot.observed_volume_24h_usd),
        "market_cap_contributors": snapshot.market_cap_contributors,
        "volume_contributors": snapshot.volume_contributors,
        "rwa_tvl_usd": None,
        "rwa_tvl_reason": snapshot.rwa_tvl_reason,
        "degraded_reasons": list(snapshot.degraded_reasons),
        "reason": snapshot.reason,
        "observations": rows,
    }


class BnbRwaDashboardService:
    def __init__(self, provider=None) -> None:
        self.provider = provider or CoinGeckoBnbRwaProvider()

    def read_payload(self) -> dict:
        return serialize_bnb_snapshot(self.provider.read_snapshot())
