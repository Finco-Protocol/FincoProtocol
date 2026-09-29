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
    JsonRpc, RpcUnavailable, SWAP_TOPIC0, _abi_string, _observe_calldata,
    _tick_cumulatives, _words,
)
from finco_radar.authority.r_live_policy import APPROVED_RLIVE_ASSETS, AAPL_POOL


REGISTRY_URL = "https://api.robinhood.com/rhj/assets"
PUBLIC_RPC = "https://rpc.mainnet.chain.robinhood.com"
FEE_TIERS = (100, 500, 3000, 10000)
BATCH_SIZE = 4  # Conservative public-RPC batches; never runtime discovery.


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
            time.sleep(2 ** attempt)
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


_RPC_TRANSPORT_REASONS = {"RPC_TRANSPORT_UNAVAILABLE", "RPC_RESPONSE_UNAVAILABLE",
                           "PUBLIC_RPC_BATCH_UNAVAILABLE", "PUBLIC_RPC_BATCH_INCOMPLETE",
                           "PUBLIC_RPC_BATCH_INVALID", "PUBLIC_RPC_HTTP_429",
                           "PUBLIC_RPC_HTTP_502", "PUBLIC_RPC_HTTP_503", "PUBLIC_RPC_HTTP_504"}


def _is_rpc_transport_error(exc: Exception) -> bool:
    if isinstance(exc, RpcUnavailable):
        return True
    if isinstance(exc, ValueError):
        s = str(exc)
        if s in _RPC_TRANSPORT_REASONS or s.startswith("PUBLIC_RPC_HTTP_"):
            return True
    return False


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

            # Stage A1: per-candidate factory getPool for all reviewed fee tiers.
            # Each candidate uses exactly one batch of 4 (one call per fee tier).
            # A transport failure marks the candidate REVIEW_INCOMPLETE_RPC, not rejected.
            candidate_pools: list[tuple[int, str, str, str, int]] = []
            no_pool = 0
            rpc_incomplete_a1: list[tuple[str, str, str]] = []
            for index, (symbol, uid, token) in enumerate(candidates):
                queries = [
                    ("eth_call", [{"to": AAPL_POOL.factory_address,
                                   "data": ("0x1698ee82" + token[2:].zfill(64)
                                            + AAPL_POOL.quote_token_address[2:].zfill(64)
                                            + f"{fee:064x}")}, block])
                    for fee in FEE_TIERS
                ]
                try:
                    results = _batch(client, queries)  # exactly 4 calls = 1 batch
                    found = False
                    for fee, res in zip(FEE_TIERS, results):
                        pool = _address(res)
                        if pool != "0x" + "0" * 40:
                            candidate_pools.append((index, uid, token, pool, fee))
                            found = True
                    if not found:
                        no_pool += 1
                except Exception as exc:
                    if _is_rpc_transport_error(exc):
                        rpc_incomplete_a1.append((symbol, uid, token))
                    else:
                        no_pool += 1  # e.g. CHAIN_RESPONSE_INVALID → count as no usable result

            # Stage A2: per-candidate cheap source/provenance/shape checks.
            # 8 metadata queries per pool, split into 2 batches of 4.
            cheap_reasons: Counter[str] = Counter()
            plausible: list[tuple[int, str, str, str, int]] = []
            rpc_incomplete_a2: list[tuple[int, str, str, str, int]] = []
            for index, uid, token, pool, fee in candidate_pools:
                queries = [("eth_getCode", [pool, block])]
                for target, data in ((pool, "0xc45a0155"), (pool, "0x0dfe1681"),
                                     (pool, "0xd21220a7"), (pool, "0xddca3f43"),
                                     (token, "0x313ce567"), (pool, "0x1a686502"),
                                     (pool, "0x3850c7bd")):
                    queries.append(("eth_call", [{"to": target, "data": data}, block]))
                try:
                    values = _batch(client, queries)  # 8 calls, 2 batches of 4
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
                except Exception as exc:
                    if _is_rpc_transport_error(exc):
                        rpc_incomplete_a2.append((index, uid, token, pool, fee))
                    else:
                        cheap_reasons["CHAIN_RESPONSE_INVALID"] += 1

            # Collect all A1/A2 RPC-incomplete candidates
            rpc_incomplete_count = len(rpc_incomplete_a1) + len(rpc_incomplete_a2)
            rpc_incomplete_symbols = (
                [s for s, _, _ in rpc_incomplete_a1]
                + [candidates[i][0] for i, _, _, _, _ in rpc_incomplete_a2]
            )

            # Stage B: complete exact-pool TWAP, bounded Swap and quote review.
            # Transport failures → REVIEW_INCOMPLETE_RPC (not REJECTED).
            reviews: dict[int, dict] = {}
            stage_b_rpc_incomplete = 0
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
                    if _is_rpc_transport_error(exc):
                        stage_b_rpc_incomplete += 1
                        rpc_incomplete_count += 1
                        rpc_incomplete_symbols.append(symbol)
                        entry["pools"].append({"pool": pool, "fee": fee,
                                               "admission": "REVIEW_INCOMPLETE_RPC",
                                               "reason": "RPC_TRANSPORT_FAILURE"})
                        # Do not mark entry as REJECTED; it remains at its current state.
                        # If this is the only pool attempt, entry stays REJECTED with
                        # reason NO_QUALIFYING_REVIEWED_POOL (which is technically correct
                        # as a placeholder), but admission is overridden if all pools were
                        # RPC-incomplete.
                        if all(p.get("admission") == "REVIEW_INCOMPLETE_RPC"
                               for p in entry["pools"]):
                            entry["admission"] = "REVIEW_INCOMPLETE_RPC"
                            entry["reason"] = "RPC_TRANSPORT_FAILURE"
                    else:
                        safe = str(exc) if isinstance(exc, ValueError) else "CHAIN_EVIDENCE_INVALID"
                        if safe not in {"SWAP_LOGS_UNAVAILABLE", "SWAP_LOG_INVALID",
                                        "SWAP_BLOCK_PROVENANCE_INVALID", "CHAIN_RESPONSE_INVALID",
                                        "POOL_CODE_MISSING", "POOL_FACTORY_MISMATCH",
                                        "POOL_PAIR_MISMATCH", "POOL_FEE_MISMATCH",
                                        "POOL_LIQUIDITY_CARDINALITY_OR_DECIMALS_INSUFFICIENT"}:
                            safe = "CHAIN_EVIDENCE_INVALID"
                        entry["pools"].append({"pool": pool, "fee": fee,
                                               "admission": "REJECTED", "reason": safe})

            total_rpc_incomplete = rpc_incomplete_count + stage_b_rpc_incomplete
            print(json.dumps({"registry": REGISTRY_URL, "chain_id": 4663,
                              "reviewed_block": block_number, "reviewed_block_hash": head["hash"],
                              "reviewed_block_at": datetime.fromtimestamp(block_time, timezone.utc).isoformat(),
                              "candidate_rule": "ACTIVE + one chain-4663 deployment + ISIN + official Robinhood Token name, excluding approved exact deployments",
                              "eligible_registry_count": len(eligible),
                              "authoritative_candidate_count": len(candidates),
                              "factory_pool_count": len(candidate_pools),
                              "no_pool_candidate_count": no_pool,
                              "cheap_prefilter_passed": len(plausible),
                              "cheap_prefilter_rejections": dict(cheap_reasons),
                              "full_pool_reviews": len(plausible),
                              "rpc_incomplete_count": rpc_incomplete_count,
                              "rpc_incomplete_symbols": rpc_incomplete_symbols,
                              "quote_feed_valid": quote_valid,
                              "full_review_candidates": list(reviews.values())},
                             separators=(",", ":")))
        finally:
            rpc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
