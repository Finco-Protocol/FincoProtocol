"""One-shot on-chain verification of Stock Token oracle candidates (PR #190 Correction A).

Read-only on Robinhood Chain mainnet (chain_id 4663).
Pins one block for the entire verification run.
No transactions, no signing, no credentials in output.

Results are typed on-chain verification outcomes only.  Promotion
eligibility additionally requires official heartbeat authority and
final provenance review outside this tool.

Outputs a sanitized JSON verification artifact (no RPC credentials).
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

RPC_URL = os.getenv(
    "FINCO_ROBINHOOD_RPC_URL",
    "https://rpc.mainnet.chain.robinhood.com")
CHAIN_ID = 4663
MAX_FUTURE_SECONDS = 120

SEL_DESCRIPTION = "0x7284e416"
SEL_DECIMALS = "0x313ce567"
SEL_LATEST_ROUND = "0xfeaf968c"
SEL_ORACLE_PAUSED = "0x7706ba52"

CANDIDATES_PATH = REPO / "app" / "radar_rwa" / "data" / "stock_token_oracle_candidates.json"

# Typed on-chain verification results (NOT promotion decisions)
RESULT_NOT_DEPLOYED = "NOT_DEPLOYED_ON_4663"
RESULT_ONCHAIN_VERIFIED = "ONCHAIN_VERIFIED"
RESULT_DESCRIPTION_MISMATCH = "DESCRIPTION_MISMATCH"
RESULT_DECIMALS_INVALID = "DECIMALS_INVALID"
RESULT_ROUND_INVALID = "ROUND_INVALID"
RESULT_ORACLE_PAUSED_UNREADABLE = "ORACLE_PAUSED_UNREADABLE"
RESULT_VERIFICATION_BLOCK_REORG = "VERIFICATION_BLOCK_REORG"


def _safe_rpc_label(url: str) -> str:
    """Strip credentials / query strings; return hostname only."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return parsed.hostname or "unknown"


def _rpc(client: httpx.Client, method: str, params: list) -> Any:
    r = client.post(RPC_URL, json={"jsonrpc": "2.0", "id": 1,
                                   "method": method, "params": params})
    r.raise_for_status()
    body = r.json()
    if body.get("error"):
        raise RuntimeError(f"RPC error: {body['error']}")
    return body.get("result")


def _hex_to_int(raw: str) -> int | None:
    if not raw or raw == "0x":
        return None
    try:
        return int(raw.removeprefix("0x"), 16)
    except ValueError:
        return None


def _decode_abi_string(raw_hex: str) -> str:
    clean = raw_hex.removeprefix("0x")
    if len(clean) < 128:
        return ""
    length = int(clean[64:128], 16)
    if length == 0:
        return ""
    data = bytes.fromhex(clean[128:128 + length * 2])
    return data.decode("utf-8", errors="replace")


def _decode_int256(hex_word: str) -> int:
    """Two's-complement signed int256 decoding."""
    value = int(hex_word, 16)
    if value >= 2 ** 255:
        value -= 2 ** 256
    return value


def _call_at_block(client: httpx.Client, to: str, data: str,
                   block_tag: str) -> str | None:
    try:
        raw = _rpc(client, "eth_call",
                   [{"to": to, "data": data}, block_tag])
        return raw if raw and raw != "0x" else None
    except Exception:
        return None


def _call_uint_at(client: httpx.Client, to: str, data: str,
                  block_tag: str) -> int | None:
    raw = _call_at_block(client, to, data, block_tag)
    if raw is None or len(raw.removeprefix("0x")) < 64:
        return None
    return int(raw.removeprefix("0x"), 16)


def main() -> int:
    candidates = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))

    with httpx.Client(timeout=15.0) as client:
        # ── Chain identity ────────────────────────────────────────────────
        chain_hex = _rpc(client, "eth_chainId", [])
        chain_id = _hex_to_int(chain_hex)
        if chain_id != CHAIN_ID:
            print(json.dumps({"error": "CHAIN_ID_MISMATCH",
                              "got": chain_id, "expected": CHAIN_ID}))
            return 2

        # ── Pin one block for the entire run ──────────────────────────────
        latest_block_hex = _rpc(client, "eth_getBlockByNumber", ["latest", False])
        pinned_block_number = _hex_to_int(latest_block_hex.get("number", "0x0"))
        pinned_block_hash = latest_block_hex.get("hash", "") if isinstance(
            latest_block_hex, dict) else ""
        pinned_block_ts = _hex_to_int(latest_block_hex.get("timestamp", "0x0"))

        block_tag = hex(pinned_block_number)
        print(json.dumps({"step": "pinned_block",
                          "block_number": pinned_block_number,
                          "block_hash_prefix": pinned_block_hash[:18]}))

        results = []
        for candidate in candidates["candidates"]:
            sym = candidate["symbol"]
            proxy = candidate["candidate_feed_proxy"]
            token = candidate["token_contract"]
            expected_pair = candidate["candidate_pair"]
            row: dict[str, Any] = {
                "symbol": sym,
                "canonical_id": candidate["canonical_id"],
                "token_contract": token,
                "candidate_feed_proxy": proxy,
                "expected_pair": expected_pair,
                "pinned_block": pinned_block_number,
            }

            # eth_getCode at pinned block
            proxy_code = _rpc(client, "eth_getCode", [proxy, block_tag])
            deployed = bool(proxy_code and proxy_code != "0x")
            row["proxy_deployed"] = deployed
            if not deployed:
                row["verification_result"] = RESULT_NOT_DEPLOYED
                results.append(row)
                continue

            # description() at pinned block
            desc_raw = _call_at_block(client, proxy, SEL_DESCRIPTION, block_tag)
            description = _decode_abi_string(desc_raw) if desc_raw else ""
            row["description"] = description

            # Exact description check: must contain the expected pair
            expected_pair_upper = expected_pair.upper()
            if expected_pair_upper not in description.upper():
                row["verification_result"] = RESULT_DESCRIPTION_MISMATCH
                row["expected_pair_in_description"] = False
                results.append(row)
                continue

            # decimals() at pinned block
            decimals_raw = _call_uint_at(
                client, proxy, SEL_DECIMALS, block_tag)
            decimals_valid = decimals_raw is not None and 0 <= decimals_raw <= 77
            row["decimals"] = decimals_raw
            if not decimals_valid:
                row["verification_result"] = RESULT_DECIMALS_INVALID
                results.append(row)
                continue

            # latestRoundData() at pinned block
            round_raw = _call_at_block(
                client, proxy, SEL_LATEST_ROUND, block_tag)
            if round_raw is None:
                row["verification_result"] = RESULT_ROUND_INVALID
                results.append(row)
                continue
            clean = round_raw.removeprefix("0x")
            words = [clean[i:i+64] for i in range(0, len(clean), 64)]
            if len(words) < 5:
                row["verification_result"] = RESULT_ROUND_INVALID
                results.append(row)
                continue

            round_id = int(words[0], 16)
            answer_raw_hex = words[1]
            answer_signed = _decode_int256(answer_raw_hex)
            started_at = int(words[2], 16)
            updated_at = int(words[3], 16)
            answered_in_round = int(words[4], 16)

            row["latest_round"] = {
                "roundId": round_id, "answer_signed": answer_signed,
                "updatedAt": updated_at,
                "answeredInRound": answered_in_round}

            if round_id <= 0 or answer_signed <= 0 or updated_at <= 0:
                row["verification_result"] = RESULT_ROUND_INVALID
                row["round_issue"] = "non-positive roundId/answer/updatedAt"
                results.append(row)
                continue
            if answered_in_round < round_id:
                row["verification_result"] = RESULT_ROUND_INVALID
                row["round_issue"] = "answeredInRound < roundId"
                results.append(row)
                continue

            # oraclePaused() on the Stock Token at pinned block
            paused_raw = _call_uint_at(client, token, SEL_ORACLE_PAUSED, block_tag)
            if paused_raw is None:
                row["verification_result"] = RESULT_ORACLE_PAUSED_UNREADABLE
                results.append(row)
                continue
            row["oracle_paused"] = bool(paused_raw)

            row["verification_result"] = RESULT_ONCHAIN_VERIFIED
            results.append(row)

        # ── Re-read pinned block to detect reorg ──────────────────────────
        recheck = _rpc(client, "eth_getBlockByNumber", [block_tag, False])
        recheck_hash = recheck.get("hash", "") if isinstance(recheck, dict) else ""
        reorg = recheck_hash != pinned_block_hash

    # ── Output sanitized artifact (no RPC credentials) ────────────────────
    output = {
        "rpc_authority": _safe_rpc_label(RPC_URL),
        "chain_id": CHAIN_ID,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "pinned_block_number": pinned_block_number,
        "pinned_block_hash_prefix": pinned_block_hash[:18],
        "reorg_detected": reorg,
        "total": len(results),
        "onchain_verified": sum(1 for r in results
                                if r["verification_result"] == RESULT_ONCHAIN_VERIFIED),
        "not_deployed": sum(1 for r in results
                            if r["verification_result"] == RESULT_NOT_DEPLOYED),
        "results": results,
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
