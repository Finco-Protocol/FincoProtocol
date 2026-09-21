"""Robinhood Chain stock-token universe discovery.

Canonical live source: the official Robinhood Stock Token asset registry
documented at https://docs.robinhood.com/chain/stock-token-apis/
(GET https://api.robinhood.com/rhj/assets). The registry endpoint rejects
the default httpx UA, so we send a browser User-Agent.

Disappeared assets are marked inactive — never deleted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional

import httpx

from .domain import EquityAsset

REGISTRY_URL = "https://api.robinhood.com/rhj/assets"
REGISTRY_SOURCE = "ROBINHOOD_STOCK_TOKEN_ASSETS_API (docs.robinhood.com/chain/stock-token-apis)"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36"
)

_TOKEN_NAME_SUFFIX = " • Robinhood Token"


@dataclass(frozen=True)
class UniverseSnapshot:
    source: str
    observed_at: str
    assets: List[EquityAsset]


def _parse_assets(payload: Mapping[str, Any], observed_at: str) -> List[EquityAsset]:
    rows = payload.get("assets")
    if not isinstance(rows, list):
        raise ValueError("asset registry payload must contain an assets list")
    assets: List[EquityAsset] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        deployments = row.get("deployments") or []
        deployment = deployments[0] if deployments else {}
        name = str(row.get("tokenName") or "").replace(_TOKEN_NAME_SUFFIX, "")
        status = str(row.get("status") or "")
        assets.append(
            EquityAsset(
                robinhood_token_symbol=str(row.get("tokenSymbol") or ""),
                underlying_ticker=str(row.get("tokenSymbol") or ""),
                name=name or None,
                token_contract_address=deployment.get("contractAddress"),
                chain_network=str(deployment.get("networkName") or "Robinhood Chain")
                if deployment.get("chainId") == 4663 or deployment
                else None,
                active=status != "ASSET_STATUS_INACTIVE",
            )
        )
    return assets


def fetch_universe(
    *,
    url: str = REGISTRY_URL,
    client: Optional[httpx.Client] = None,
    observed_at: str = "",
) -> UniverseSnapshot:
    """Fetch the live registry. One HTTP call; not paced (Robinhood limit 60/s)."""
    from datetime import datetime, timezone

    if observed_at == "":
        observed_at = datetime.now(timezone.utc).isoformat()
    if client is not None:
        response = client.get(url)
        response.raise_for_status()
        payload = response.json()
    else:
        response = httpx.get(
            url, headers={"accept": "application/json", "User-Agent": USER_AGENT},
            timeout=30.0,
        )
        response.raise_for_status()
        payload = response.json()
    return UniverseSnapshot(
        source=REGISTRY_SOURCE,
        observed_at=observed_at,
        assets=_parse_assets(payload, observed_at),
    )
