"""Read-only chain identity gate for the Deepstate collector."""
from __future__ import annotations

import json
import urllib.request


def ensure_chain(rpc_url: str, *, expected_chain_id: int, timeout: int = 20) -> bool:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1,
                          "method": "eth_chainId", "params": []}).encode()
    request = urllib.request.Request(
        rpc_url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.load(response)
    return int(body.get("result", "0x0"), 16) == expected_chain_id
