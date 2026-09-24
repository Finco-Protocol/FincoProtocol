"""Canonical metric registry for FINCO Radar Crypto Overview."""
from __future__ import annotations

from app.radar_crypto.contracts import CryptoMetricDefinition, CryptoSection

COINGECKO_PUBLISHER = "CoinGecko"
COINGECKO_TRANSPORT = "CoinGecko Demo API"
GLOBAL_DOCS = "https://docs.coingecko.com/reference/crypto-global"
SIMPLE_PRICE_DOCS = "https://docs.coingecko.com/reference/simple-price"

SERIES: tuple[CryptoMetricDefinition, ...] = (
    CryptoMetricDefinition(
        key="total_market_cap_usd",
        title="Total Crypto Market Cap",
        section=CryptoSection.MARKET_OVERVIEW,
        source_endpoint="/global",
        source_id="data.total_market_cap.usd",
        publisher=COINGECKO_PUBLISHER,
        transport=COINGECKO_TRANSPORT,
        source_url=GLOBAL_DOCS,
        unit="usd_compact",
    ),
    CryptoMetricDefinition(
        key="total_volume_24h_usd",
        title="24h Market Volume",
        section=CryptoSection.MARKET_OVERVIEW,
        source_endpoint="/global",
        source_id="data.total_volume.usd",
        publisher=COINGECKO_PUBLISHER,
        transport=COINGECKO_TRANSPORT,
        source_url=GLOBAL_DOCS,
        unit="usd_compact",
    ),
    CryptoMetricDefinition(
        key="btc_dominance",
        title="BTC Dominance",
        section=CryptoSection.MARKET_OVERVIEW,
        source_endpoint="/global",
        source_id="data.market_cap_percentage.btc",
        publisher=COINGECKO_PUBLISHER,
        transport=COINGECKO_TRANSPORT,
        source_url=GLOBAL_DOCS,
        unit="percent",
    ),
    CryptoMetricDefinition(
        key="eth_dominance",
        title="ETH Dominance",
        section=CryptoSection.MARKET_OVERVIEW,
        source_endpoint="/global",
        source_id="data.market_cap_percentage.eth",
        publisher=COINGECKO_PUBLISHER,
        transport=COINGECKO_TRANSPORT,
        source_url=GLOBAL_DOCS,
        unit="percent",
    ),
    CryptoMetricDefinition(
        key="active_cryptocurrencies",
        title="Active Cryptocurrencies",
        section=CryptoSection.MARKET_OVERVIEW,
        source_endpoint="/global",
        source_id="data.active_cryptocurrencies",
        publisher=COINGECKO_PUBLISHER,
        transport=COINGECKO_TRANSPORT,
        source_url=GLOBAL_DOCS,
        unit="count",
    ),
    CryptoMetricDefinition(
        key="btc_price_usd",
        title="Bitcoin",
        section=CryptoSection.MAJOR_ASSETS,
        source_endpoint="/simple/price",
        source_id="bitcoin.usd",
        publisher=COINGECKO_PUBLISHER,
        transport=COINGECKO_TRANSPORT,
        source_url=SIMPLE_PRICE_DOCS,
        unit="usd_price",
    ),
    CryptoMetricDefinition(
        key="eth_price_usd",
        title="Ethereum",
        section=CryptoSection.MAJOR_ASSETS,
        source_endpoint="/simple/price",
        source_id="ethereum.usd",
        publisher=COINGECKO_PUBLISHER,
        transport=COINGECKO_TRANSPORT,
        source_url=SIMPLE_PRICE_DOCS,
        unit="usd_price",
    ),
    CryptoMetricDefinition(
        key="eth_btc_ratio",
        title="ETH / BTC",
        section=CryptoSection.MAJOR_ASSETS,
        source_endpoint="/simple/price",
        source_id="derived:ethereum.usd/bitcoin.usd",
        publisher=COINGECKO_PUBLISHER,
        transport=COINGECKO_TRANSPORT,
        source_url=SIMPLE_PRICE_DOCS,
        unit="ratio",
    ),
)


def metric_for_key(key: str) -> CryptoMetricDefinition:
    for definition in SERIES:
        if definition.key == key:
            return definition
    raise KeyError(key)


def metrics_for_section(section: CryptoSection) -> tuple[CryptoMetricDefinition, ...]:
    return tuple(definition for definition in SERIES if definition.section is section)


def validate_registry() -> None:
    keys = [definition.key for definition in SERIES]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate crypto metric key")
    identities = [
        (definition.source_endpoint, definition.source_id)
        for definition in SERIES
    ]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate crypto source binding")


validate_registry()
