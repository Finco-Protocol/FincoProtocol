"""Read-only, review-time R-LIVE candidate scan. Never used at runtime.

Identity comes exclusively from the official Robinhood asset registry. Pool
discovery in this script is admission evidence only, not production fallback.
Uses only the official public RPC; no secret-bearing configuration is read.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime, timezone

import httpx

from finco_radar.authority.r_live_onchain import (
    JsonRpc, SWAP_TOPIC0, _abi_string, _observe_calldata, _tick_cumulatives, _words,
)
from finco_radar.authority.r_live_policy import APPROVED_RLIVE_ASSETS, AAPL_POOL


REGISTRY_URL = "https://api.robinhood.com/rhj/assets"
PUBLIC_RPC = "https://rpc.mainnet.chain.robinhood.com"
FEE_TIERS = (100, 500, 3000, 10000)
BATCH_SIZE = 8  # Small public-RPC batches, never runtime discovery.


def _batch(client: httpx.Client, calls: list[tuple[str, list]]) -> list:
    """Pinned read-only JSON-RPC batch; reject partial/malformed results."""
    output = []
    for offset in range(0, len(calls), BATCH_SIZE):
        part = calls[offset:offset + BATCH_SIZE]
        request = [{"jsonrpc": "2.0", "id": i, "method": method, "params": params}
                   for i, (method, params) in enumerate(part)]
        for attempt in range(3):
            try:
                response = client.post(PUBLIC_RPC, json=request)
                response.raise_for_status()
                payload = response.json()
                break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in (429, 502, 503, 504) or attempt == 2:
                    raise ValueError(f"PUBLIC_RPC_HTTP_{exc.response.status_code}") from None
            except (httpx.TransportError, ValueError):
                if attempt == 2:
                    raise ValueError("PUBLIC_RPC_BATCH_UNAVAILABLE") from None
            time.sleep(1 + attempt)
        if not isinstance(payload, list) or len(payload) != len(part):
            raise ValueError("PUBLIC_RPC_BATCH_INCOMPLETE")
        by_id = {row.get("id"): row for row in payload if isinstance(row, dict)}
        if len(by_id) != len(part) or any(i not in by_id or by_id[i].get("error") is not None
                                        or "result" not in by_id[i] for i in range(len(part))):
            raise ValueError("PUBLIC_RPC_BATCH_INVALID")
        output.extend(by_id[i]["result"] for i in range(len(part)))
    return output


def _registry_candidates(assets: list[dict], approved: set[str]) -> tuple[list[tuple], list[tuple]]:
    """Objective source-field enumeration, never a display-symbol shortlist."""
    eligible = []
    for row in assets:
        deployments = [d for d in row.get("deployments", []) if d.get("chainId") == 4663]
        if (row.get("status") != "ASSET_STATUS_ACTIVE" or len(deployments) != 1
                or not row.get("isin")
                or not str(row.get("tokenName", "")).endswith("Robinhood Token")):
            continue
        token = str(deployments[0].get("contractAddress", "")).lower()
        uid = str(row.get("id", "")).lower()
        if len(token) != 42 or len(uid) != 66 or not token.startswith("0x") or not uid.startswith("0x"):
            raise ValueError("REGISTRY_IDENTITY_INVALID")
        eligible.append((row["tokenSymbol"], uid, token))
    uid_counts = Counter(uid for _, uid, _ in eligible)
    token_counts = Counter(token for _, _, token in eligible)
    if any(uid_counts[uid] != 1 or token_counts[token] != 1 for _, uid, token in eligible):
        raise ValueError("REGISTRY_IDENTITY_CONFLICT")
    candidates = [(symbol, uid, token) for symbol, uid, token in eligible
                  if token not in approved]
    return eligible, candidates


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
    approved = {policy.asset_key.contract_address for policy in APPROVED_RLIVE_ASSETS.values()}
    with httpx.Client(timeout=45) as client:
        response = client.get(REGISTRY_URL)
        response.raise_for_status()
        assets = response.json()["assets"]
        eligible, candidates = _registry_candidates(assets, approved)

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
            quote_valid = (_abi_string(feed_description) == "USDG / USD" and feed_decimals == 8
                           and feed_round[0] > 0 and feed_round[1] > 0
                           and feed_round[2] > 0 and feed_round[3] >= feed_round[2]
                           and feed_round[4] >= feed_round[0]
                           and 0 <= block_time - feed_round[3] <= 86400)
            if not quote_valid:
                raise ValueError("QUOTE_AUTHORITY_UNAVAILABLE")
            quote_decimals = _words(_call(rpc, AAPL_POOL.quote_token_address, "0x313ce567", block), 1)[0]
            if quote_decimals != 6:
                raise ValueError("QUOTE_TOKEN_DECIMALS_INVALID")

            # Stage A1: factory getPool for every exact registry deployment at
            # all reviewed fee tiers. Batches reduce HTTP round trips without
            # increasing per-call authority or using runtime pool discovery.
            factory_queries = []
            for symbol, uid, token in candidates:
                for fee in FEE_TIERS:
                    data = ("0x1698ee82" + token[2:].zfill(64)
                            + AAPL_POOL.quote_token_address[2:].zfill(64) + f"{fee:064x}")
                    factory_queries.append(("eth_call", [{"to": AAPL_POOL.factory_address,
                                                           "data": data}, block]))
            factory_results = _batch(client, factory_queries)
            candidate_pools = []
            no_pool = 0
            for index, (_, uid, token) in enumerate(candidates):
                found = False
                for tier, fee in enumerate(FEE_TIERS):
                    pool = _address(factory_results[index * len(FEE_TIERS) + tier])
                    if pool != "0x" + "0" * 40:
                        candidate_pools.append((index, uid, token, pool, fee))
                        found = True
                if not found:
                    no_pool += 1

            # Stage A2: cheap source/provenance/shape checks. Only pools that
            # pass are permitted into Stage B's observe and Swap-log calls.
            cheap_reasons = Counter()
            plausible = []
            metadata_queries = []
            for index, uid, token, pool, fee in candidate_pools:
                metadata_queries.append(("eth_getCode", [pool, block]))
                for target, data in ((pool, "0xc45a0155"), (pool, "0x0dfe1681"),
                                     (pool, "0xd21220a7"), (pool, "0xddca3f43"),
                                     (token, "0x313ce567"), (pool, "0x1a686502"),
                                     (pool, "0x3850c7bd")):
                    metadata_queries.append(("eth_call", [{"to": target, "data": data}, block]))
            metadata_results = _batch(client, metadata_queries)
            for position, (index, uid, token, pool, fee) in enumerate(candidate_pools):
                values = metadata_results[position * 8:(position + 1) * 8]
                reason = None
                if values[0] in (None, "0x"):
                    reason = "POOL_CODE_MISSING"
                elif _address(values[1]) != AAPL_POOL.factory_address:
                    reason = "POOL_FACTORY_MISMATCH"
                elif {_address(values[2]), _address(values[3])} != {token, AAPL_POOL.quote_token_address}:
                    reason = "POOL_PAIR_MISMATCH"
                elif _words(values[4], 1)[0] != fee:
                    reason = "POOL_FEE_MISMATCH"
                else:
                    token_decimals = _words(values[5], 1)[0]
                    liquidity = _words(values[6], 1)[0]
                    cardinality = _words(values[7], 7)[3]
                    if token_decimals != 18 or liquidity <= 0 or cardinality < 2:
                        reason = "POOL_LIQUIDITY_CARDINALITY_OR_DECIMALS_INSUFFICIENT"
                if reason:
                    cheap_reasons[reason] += 1
                else:
                    plausible.append((index, uid, token, pool, fee))

            # Stage B: complete exact-pool TWAP, bounded Swap and quote review.
            reviews = {}
            for index, uid, token, pool, fee in plausible:
                symbol = candidates[index][0]
                entry = reviews.setdefault(index, {"symbol": symbol, "economic_asset_uid": uid,
                    "canonical_asset_key": f"4663:{token}", "pools": [],
                    "admission": "REJECTED", "reason": "NO_QUALIFYING_REVIEWED_POOL"})
                try:
                    review = _pool_review(rpc, token, pool, fee, block, block_number, block_time)
                    if (review["bounded_swap_count"] >= 2
                            and review["last_swap_age_seconds"] is not None
                            and 0 <= review["last_swap_age_seconds"] <= 300):
                        review["admission"] = "QUALIFIED_FOR_POLICY_REVIEW"
                        entry["admission"] = "QUALIFIED_FOR_POLICY_REVIEW"
                        entry["reason"] = None
                    else:
                        review["admission"] = "REJECTED"
                        review["reason"] = "SWAP_ACTIVITY_INSUFFICIENT"
                    entry["pools"].append(review)
                except Exception as exc:
                    safe = str(exc) if isinstance(exc, ValueError) else "CHAIN_EVIDENCE_INVALID"
                    if safe not in {"SWAP_LOGS_UNAVAILABLE", "SWAP_LOG_INVALID",
                                    "SWAP_BLOCK_PROVENANCE_INVALID", "CHAIN_RESPONSE_INVALID"}:
                        safe = "CHAIN_EVIDENCE_INVALID"
                    entry["pools"].append({"pool": pool, "fee": fee,
                                           "admission": "REJECTED", "reason": safe})
            print(json.dumps({"registry": REGISTRY_URL, "chain_id": 4663,
                              "reviewed_block": block_number, "reviewed_block_hash": head["hash"],
                              "reviewed_block_at": datetime.fromtimestamp(block_time, timezone.utc).isoformat(),
                              "candidate_rule": "ACTIVE + one chain-4663 deployment + ISIN + official Robinhood Token name, excluding approved exact deployments",
                              "eligible_registry_count": len(eligible),
                              "authoritative_candidate_count": len(candidates),
                              "factory_pool_count": len(candidate_pools),
                              "cheap_prefilter_passed": len(plausible),
                              "cheap_prefilter_rejections": dict(cheap_reasons),
                              "no_pool_candidate_count": no_pool,
                              "full_pool_reviews": len(plausible),
                              "quote_feed_valid": quote_valid,
                              "full_review_candidates": list(reviews.values())},
                             separators=(",", ":")))
        finally:
            rpc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
