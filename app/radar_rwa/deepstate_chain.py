"""Read-only chain identity gate for the Deepstate collector."""
from __future__ import annotations

import json
import urllib.request

from finco_radar.venues.deepstate_live import DEEPSTATE_RPC_HEADERS


def ensure_chain(rpc_url: str, *, expected_chain_id: int, timeout: int = 20) -> bool:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1,
                          "method": "eth_chainId", "params": []}).encode()
    request = urllib.request.Request(
        rpc_url, data=payload, headers=DEEPSTATE_RPC_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.load(response)
    return int(body.get("result", "0x0"), 16) == expected_chain_id


def eth_block_number(rpc_url: str, timeout: int = 20) -> int:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1,
                          "method": "eth_blockNumber", "params": []}).encode()
    request = urllib.request.Request(
        rpc_url, data=payload, headers=DEEPSTATE_RPC_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.load(response)
    return int(body.get("result", "0x0"), 16)
