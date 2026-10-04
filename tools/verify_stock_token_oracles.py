"""One-shot on-chain verification of Stock Token oracle candidates (PR #190)."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

RPC_URL = os.getenv("FINCO_ROBINHOOD_RPC_URL",
                    "https://rpc.mainnet.chain.robinhood.com")
CHAIN_ID = 4663

SEL_DESCRIPTION = "0x7284e416"
SEL_DECIMALS = "0x313ce567"
SEL_LATEST_ROUND = "0xfeaf968c"
SEL_ORACLE_PAUSED = "0x7706ba52"

CANDIDATES_PATH = REPO / "app" / "radar_rwa" / "data" / "stock_token_oracle_candidates.json"


def _rpc(client: httpx.Client, method: str, params: list) -> Any:
    r = client.post(RPC_URL, json={"jsonrpc": "2.0", "id": 1,
                                   "method": method, "params": params})
    r.raise_for_status()
    body = r.json()
    if body.get("error"):
        raise RuntimeError(f"RPC error: {body['error']}")
    return body.get("result")


def _call_string(client: httpx.Client, to: str, data: str) -> str:
    raw = _rpc(client, "eth_call", [{"to": to, "data": data}, "latest"])
    if not raw or raw == "0x":
        return ""
    raw = raw.removeprefix("0x")
    if len(raw) >= 128:
        length = int(raw[64:128], 16)
        return bytes.fromhex(raw[128:128 + length * 2]).decode("utf-8", errors="replace")
    return raw


def _call_uint(client, to, data):
    raw = _rpc(client, "eth_call", [{"to": to, "data": data}, "latest"])
    if not raw or len(raw.removeprefix("0x")) < 64:
        return None
    return int(raw.removeprefix("0x"), 16)


def _call_round(client, to, data):
    raw = _rpc(client, "eth_call", [{"to": to, "data": data}, "latest"])
    clean = raw.removeprefix("0x")
    words = [clean[i:i+64] for i in range(0, len(clean), 64)]
    if len(words) < 5:
        return {}
    return {"roundId": int(words[0], 16), "answer": int(words[1], 16),
            "startedAt": int(words[2], 16), "updatedAt": int(words[3], 16),
            "answeredInRound": int(words[4], 16)}


def main():
    candidates = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
    with httpx.Client(timeout=15.0) as client:
        chain_hex = _rpc(client, "eth_chainId", [])
        chain_id = int(chain_hex, 16)
        print(json.dumps({"step": "chain_identity", "chain_id": chain_id,
                          "match": chain_id == CHAIN_ID}))
        if chain_id != CHAIN_ID:
            print(json.dumps({"error": "CHAIN_MISMATCH"}))
            return 2

        results = []
        for c in candidates["candidates"]:
            sym = c["symbol"]
            proxy = c["candidate_feed_proxy"]
            token = c["token_contract"]
            row = {"symbol": sym, "canonical_id": c["canonical_id"],
                   "token_contract": token, "candidate_feed_proxy": proxy}

            code = _rpc(client, "eth_getCode", [proxy, "latest"])
            deployed = bool(code and code != "0x")
            row["proxy_deployed"] = deployed
            if not deployed:
                row["result"] = "NOT_DEPLOYED_ON_4663"
                results.append(row)
                continue

            desc = _call_string(client, proxy, SEL_DESCRIPTION)
            row["description"] = desc

            dec = _call_uint(client, proxy, SEL_DECIMALS)
            row["decimals"] = dec if dec is not None and 0 <= dec <= 77 else None

            try:
                rd = _call_round(client, proxy, SEL_LATEST_ROUND)
                row["latest_round"] = rd
                row["round_sane"] = (rd.get("roundId", 0) > 0 and
                                     rd.get("answer", 0) > 0 and
                                     rd.get("updatedAt", 0) > 0 and
                                     rd.get("answeredInRound", 0) >= rd.get("roundId", 0))
            except Exception as exc:
                row["latest_round"] = None
                row["round_error"] = str(exc)[:100]

            try:
                paused = _call_uint(client, token, SEL_ORACLE_PAUSED)
                row["oracle_paused"] = bool(paused) if paused is not None else None
            except Exception as exc:
                row["oracle_paused"] = None
                row["oracle_paused_error"] = str(exc)[:100]

            eligible = (deployed and bool(desc) and
                        row.get("decimals") is not None and
                        row.get("round_sane") is True)
            row["result"] = ("PROMOTION_ELIGIBLE" if eligible
                             else "VERIFICATION_FAILED")
            results.append(row)

        eligible_count = sum(1 for r in results
                             if r.get("result") == "PROMOTION_ELIGIBLE")
        output = {"chain_id": CHAIN_ID, "rpc": RPC_URL,
                  "verified_at": datetime.now(timezone.utc).isoformat(),
                  "total": len(results), "eligible": eligible_count,
                  "rejected": len(results) - eligible_count,
                  "results": results}
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
