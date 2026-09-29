"""Read-only, review-time R-LIVE candidate scan. Never used at runtime.

Identity comes exclusively from the official Robinhood asset registry. Pool
discovery in this script is admission evidence only, not production fallback.
Uses only the official public RPC; no secret-bearing configuration is read.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from finco_radar.authority.r_live_onchain import (
    JsonRpc, SWAP_TOPIC0, _abi_string, _observe_calldata, _tick_cumulatives, _words,
)
from finco_radar.authority.r_live_policy import APPROVED_RLIVE_ASSETS, AAPL_POOL


REGISTRY_URL = "https://api.robinhood.com/rhj/assets"
PUBLIC_RPC = "https://rpc.mainnet.chain.robinhood.com"
REVIEW_SYMBOLS = (
    "MSFT", "META", "ORCL", "PLTR", "CRM", "TSM", "INTC", "CRWD",
    "JPM", "COIN", "HOOD", "UBER", "QCOM", "IBM", "WMT", "COST",
    "DELL", "SMCI", "SNOW", "GE", "TEAM", "WDAY", "NU", "RUN",
    "APLD", "FICO", "SNAP", "MTSI", "ON", "CIEN", "QBTS", "NNE",
)
FEE_TIERS = (100, 500, 3000, 10000)


def _address(raw: str) -> str:
    if not isinstance(raw, str) or not raw.startswith("0x") or len(raw) != 66:
        raise ValueError("CHAIN_RESPONSE_INVALID")
    return "0x" + raw[-40:].lower()


def _call(rpc: JsonRpc, to: str, data: str, block: str) -> str:
    result = rpc.call("eth_call", [{"to": to, "data": data}, block])
    if not isinstance(result, str) or not result.startswith("0x"):
        raise ValueError("CHAIN_RESPONSE_INVALID")
    return result


def _pool_review(rpc: JsonRpc, token: str, pool: str, fee: int,
                 block: str, block_number: int, block_time: int) -> dict:
    result = {"pool": pool, "fee": fee}
    if rpc.call("eth_getCode", [pool, block]) in (None, "0x"):
        raise ValueError("POOL_CODE_MISSING")
    if _address(_call(rpc, pool, "0xc45a0155", block)) != AAPL_POOL.factory_address:
        raise ValueError("POOL_FACTORY_MISMATCH")
    token0 = _address(_call(rpc, pool, "0x0dfe1681", block))
    token1 = _address(_call(rpc, pool, "0xd21220a7", block))
    if {token0, token1} != {token, AAPL_POOL.quote_token_address}:
        raise ValueError("POOL_PAIR_MISMATCH")
    if _words(_call(rpc, pool, "0xddca3f43", block), 1)[0] != fee:
        raise ValueError("POOL_FEE_MISMATCH")
    token_decimals = _words(_call(rpc, token, "0x313ce567", block), 1)[0]
    quote_decimals = _words(_call(rpc, AAPL_POOL.quote_token_address, "0x313ce567", block), 1)[0]
    liquidity = _words(_call(rpc, pool, "0x1a686502", block), 1)[0]
    slot = _words(_call(rpc, pool, "0x3850c7bd", block), 7)
    result.update(token_orientation="USDG/token" if token0 == AAPL_POOL.quote_token_address else "token/USDG",
                  token_decimals=token_decimals, quote_decimals=quote_decimals,
                  liquidity=str(liquidity), observation_cardinality=slot[3])
    if (token_decimals, quote_decimals) != (18, 6) or liquidity <= 0 or slot[3] < 2:
        raise ValueError("POOL_LIQUIDITY_CARDINALITY_OR_DECIMALS_INSUFFICIENT")
    _tick_cumulatives(_call(rpc, pool, _observe_calldata(300), block))
    result["twap_supported"] = True
    start = max(0, block_number - 4999)
    logs = rpc.call("eth_getLogs", [{"address": pool, "fromBlock": hex(start),
                                     "toBlock": block, "topics": [SWAP_TOPIC0]}])
    if not isinstance(logs, list):
        raise ValueError("SWAP_LOGS_UNAVAILABLE")
    qualifying = []
    for log in logs:
        if (not isinstance(log, dict) or log.get("removed") is True
                or str(log.get("address", "")).lower() != pool
                or not isinstance(log.get("topics"), list)
                or len(log["topics"]) != 3 or log["topics"][0] != SWAP_TOPIC0):
            raise ValueError("SWAP_LOG_INVALID")
        amount0, amount1, sqrt_price, _, _ = _words(log["data"], 5)
        if amount0 == 0 or amount1 == 0 or sqrt_price == 0:
            raise ValueError("SWAP_LOG_INVALID")
        qualifying.append(log)
    result["bounded_swap_count"] = len(qualifying)
    result["last_swap_age_seconds"] = None
    if qualifying:
        last = max(qualifying, key=lambda log: (int(log["blockNumber"], 16), int(log["logIndex"], 16)))
        last_block = rpc.call("eth_getBlockByNumber", [last["blockNumber"], False])
        if not isinstance(last_block, dict) or last_block.get("hash") != last.get("blockHash"):
            raise ValueError("SWAP_BLOCK_PROVENANCE_INVALID")
        result["last_swap_age_seconds"] = block_time - int(last_block["timestamp"], 16)
    return result


def main() -> int:
    with httpx.Client(timeout=30) as client:
        response = client.get(REGISTRY_URL)
        response.raise_for_status()
        assets = response.json()["assets"]
    approved = {policy.asset_key.contract_address for policy in APPROVED_RLIVE_ASSETS.values()}
    requested = set(REVIEW_SYMBOLS)
    candidates = []
    for row in assets:
        deployments = [d for d in row.get("deployments", []) if d.get("chainId") == 4663]
        if (row.get("tokenSymbol") not in requested or row.get("status") != "ASSET_STATUS_ACTIVE"
                or len(deployments) != 1):
            continue
        token = str(deployments[0]["contractAddress"]).lower()
        if token not in approved:
            candidates.append((row["tokenSymbol"], row["id"].lower(), token))
    rpc = JsonRpc(PUBLIC_RPC)
    try:
        if int(rpc.call("eth_chainId", []), 16) != 4663:
            raise ValueError("CHAIN_ID_MISMATCH")
        head = rpc.call("eth_getBlockByNumber", ["latest", False])
        block_number = int(head["number"], 16)
        block = hex(block_number)
        block_time = int(head["timestamp"], 16)
        feed_description = _call(rpc, AAPL_POOL.quote_feed_address, "0x7284e416", block)
        feed_decimals = _words(_call(rpc, AAPL_POOL.quote_feed_address, "0x313ce567", block), 1)[0]
        feed_round = _words(_call(rpc, AAPL_POOL.quote_feed_address, "0xfeaf968c", block), 5)
        # Description decoding is already production-validated. Admission here
        # additionally requires the reviewed decimals and a valid positive round.
        quote_valid = (_abi_string(feed_description) == "USDG / USD" and feed_decimals == 8
                       and feed_round[0] > 0 and feed_round[1] > 0
                       and feed_round[2] > 0 and feed_round[3] >= feed_round[2]
                       and feed_round[4] >= feed_round[0]
                       and 0 <= block_time - feed_round[3] <= 86400)
        reviews = []
        for symbol, uid, token in candidates:
            entry = {"symbol": symbol, "economic_asset_uid": uid,
                     "canonical_asset_key": f"4663:{token}", "pools": [],
                     "admission": "REJECTED", "reason": "NO_QUALIFYING_REVIEWED_POOL"}
            for fee in FEE_TIERS:
                pool = None
                data = ("0x1698ee82" + token[2:].zfill(64)
                        + AAPL_POOL.quote_token_address[2:].zfill(64) + f"{fee:064x}")
                try:
                    pool = _address(_call(rpc, AAPL_POOL.factory_address, data, block))
                    if pool == "0x" + "0" * 40:
                        continue
                    review = _pool_review(rpc, token, pool, fee, block, block_number, block_time)
                    entry["pools"].append(review)
                    if (quote_valid and review["bounded_swap_count"] >= 2
                            and review["last_swap_age_seconds"] is not None
                            and 0 <= review["last_swap_age_seconds"] <= 300):
                        entry["admission"] = "QUALIFIED_FOR_POLICY_REVIEW"
                        entry["reason"] = None
                except Exception as exc:
                    reason = str(exc) if isinstance(exc, ValueError) else "RPC_UNAVAILABLE"
                    if reason not in {
                        "POOL_CODE_MISSING", "POOL_FACTORY_MISMATCH", "POOL_PAIR_MISMATCH",
                        "POOL_FEE_MISMATCH", "POOL_LIQUIDITY_CARDINALITY_OR_DECIMALS_INSUFFICIENT",
                        "SWAP_LOGS_UNAVAILABLE", "SWAP_LOG_INVALID", "SWAP_BLOCK_PROVENANCE_INVALID",
                        "CHAIN_RESPONSE_INVALID",
                    }:
                        reason = "CHAIN_EVIDENCE_INVALID"
                    entry["pools"].append({"pool": pool,
                                           "fee": fee, "reason": reason})
            reviews.append(entry)
        print(json.dumps({"registry": REGISTRY_URL, "chain_id": 4663,
                          "reviewed_block": block_number, "reviewed_block_hash": head["hash"],
                          "reviewed_block_at": datetime.fromtimestamp(block_time, timezone.utc).isoformat(),
                          "quote_feed_valid": quote_valid, "candidates": reviews},
                         separators=(",", ":")))
    finally:
        rpc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
