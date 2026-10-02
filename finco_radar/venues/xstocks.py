"""Official xStocks public API adapter (dependency-light, httpx).

Discovers the xStocks universe: symbol → underlying mapping, ISIN,
network deployments, trading-halt state.  Deterministic pagination, typed
failures, explicit timeout.  There is NO fallback to CoinGecko or any other
identity source: if the official API is unavailable the adapter fails
typed, and callers present UNAVAILABLE — never a substitute identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

XSTOCKS_ASSETS_URL = "https://api.xstocks.fi/api/v2/public/assets"
DEFAULT_TIMEOUT_SECONDS = 15.0
PAGE_SIZE_ASSUMED = 100  # observed; pagination follows hasNextPage regardless


class XStocksUnavailable(RuntimeError):
    """The official xStocks API could not be reached (typed, fail-closed)."""


class XStocksParseError(RuntimeError):
    """The official xStocks API responded with an unusable payload."""


@dataclass(frozen=True)
class XStocksDeployment:
    network: str | None
    contract_address: str
    decimals: int | None


@dataclass(frozen=True)
class XStocksAsset:
    symbol: str
    name: str | None
    isin: str | None
    underlying_symbol: str | None
    underlying_isin: str | None
    is_trading_halted: bool | None
    deployments: tuple[XStocksDeployment, ...]


def _require_mapping(value: Any, what: str) -> dict:
    if not isinstance(value, dict):
        raise XStocksParseError(f"{what} must be an object")
    return value


def _parse_asset(node: Any) -> XStocksAsset | None:
    """Parse one asset node.  Returns None for rows without an exact
    symbol (structural noise), never fabricates fields."""
    node = _require_mapping(node, "asset node")
    symbol = node.get("symbol")
    if not isinstance(symbol, str) or not symbol.strip():
        return None
    underlying = node.get("underlying")
    underlying = underlying if isinstance(underlying, dict) else {}
    halted = node.get("isTradingHalted")
    if not isinstance(halted, bool):
        halted = (node.get("trading") or {}).get("isTradingHalted")
        if not isinstance(halted, bool):
            halted = None
    deployments: list[XStocksDeployment] = []
    raw_deployments = node.get("deployments")
    if isinstance(raw_deployments, list):
        for deployment in raw_deployments:
            deployment = _require_mapping(deployment, "deployment")
            address = deployment.get("address")
            if not isinstance(address, str) or not address.strip():
                continue  # deployment without exact address is unusable
            decimals = deployment.get("decimals")
            deployments.append(XStocksDeployment(
                network=deployment.get("network")
                if isinstance(deployment.get("network"), str) else None,
                contract_address=address,
                decimals=decimals if isinstance(decimals, int) else None,
            ))
    return XStocksAsset(
        symbol=symbol,
        name=node.get("name") if isinstance(node.get("name"), str) else None,
        isin=node.get("isin") if isinstance(node.get("isin"), str) else None,
        underlying_symbol=node.get("underlyingSymbol")
        if isinstance(node.get("underlyingSymbol"), str) else None,
        underlying_isin=node.get("underlyingIsin")
        if isinstance(node.get("underlyingIsin"), str) else None,
        is_trading_halted=halted,
        deployments=tuple(deployments),
    )


def fetch_assets(
    *, base_url: str = XSTOCKS_ASSETS_URL,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    client: httpx.Client | None = None,
    max_pages: int = 100,
) -> tuple[tuple[XStocksAsset, ...], int]:
    """Fetch the full xStocks universe with deterministic pagination.

    Returns (assets, pages_fetched).  Raises XStocksUnavailable on
    transport/HTTP failure and XStocksParseError on an unusable payload —
    there is no partial-guess fallback.
    """
    owns = client is None
    client = client or httpx.Client(timeout=timeout_seconds)
    assets: list[XStocksAsset] = []
    pages = 0
    try:
        page = 0
        while page <= max_pages:
            try:
                response = client.get(base_url, params={"page": page})
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise XStocksUnavailable(
                    f"xstocks api unavailable: {type(exc).__name__}") from exc
            try:
                payload = _require_mapping(response.json(), "response")
            except ValueError as exc:
                raise XStocksParseError("response is not JSON") from exc
            nodes = payload.get("nodes")
            if not isinstance(nodes, list):
                raise XStocksParseError("response.nodes must be a list")
            for node in nodes:
                asset = _parse_asset(node)
                if asset is not None:
                    assets.append(asset)
            pages += 1
            meta = payload.get("page")
            meta = meta if isinstance(meta, dict) else {}
            if not meta.get("hasNextPage"):
                break
            page += 1
    finally:
        if owns:
            client.close()
    return tuple(assets), pages
