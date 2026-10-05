"""One-shot Deepstate NVDA/USDG live collector (V1 vertical slice).

Runtime architecture (mirrors tokenized_collect):
canonical Deepstate router logs (read-only RPC) -> bounded exact decode
-> block canonicality validation -> MarketObservation -> append-only
VenueMarketStore.

Only canonical executed Deepstate matches on the reviewed NVDA/USDG book
become observations.  No quotes, no order-book midpoints, no wallet, no
signing, no scheduler in-process.  Environment:

    FINCO_DEEPSTATE_COLLECTOR_ENABLED   1 to allow a run (default off)
    ROBINHOOD_RPC_URL                   read-only chain RPC (required)
    FINCO_VENUE_DB_PATH                 VenueMarketStore path (required)
    FINCO_DEEPSTATE_START_BLOCK         explicit bootstrap block (required
                                        when the store is empty; there is
                                        NO silent genesis scan)
    FINCO_DEEPSTATE_MAX_BLOCKS_PER_REQ  getLogs chunk size (default 20000)
    FINCO_DEEPSTATE_MAX_REQUESTS        per-run request budget (default 40)

Exit codes: 0 OK (bounded run completed), 2 wrong chain, 4 DISABLED/
CONFIG_ERROR, 6 reorg/canonicality failure (fail closed).
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import sys

from finco_radar.venues.store import VenueMarketStore

from app.radar_rwa.deepstate_chain import ensure_chain, eth_block_number
from finco_radar.venues.deepstate_live import (
    DEEPSTATE_BOOK_ID,
    DEEPSTATE_CHAIN_ID,
    DEEPSTATE_VENUE,
    decode_match_log,
    fetch_block_timestamp,
    fetch_match_logs,
    match_to_observations,
)


def _latest_block_number(store: VenueMarketStore) -> int | None:
    latest = 0
    conn = store._connect()
    try:
        rows = conn.execute(
            "SELECT payload FROM market_observations WHERE venue_id=?",
            (DEEPSTATE_VENUE,)).fetchall()
    finally:
        conn.close()
    for (payload_text,) in rows:
        try:
            payload = json.loads(payload_text)
            latest = max(latest, int(payload.get("block_number") or 0))
        except Exception:
            continue
    return latest or None


def _chunked_logs(rpc_url: str, from_block: int, to_block: int,
                  max_blocks: int, max_requests: int) -> tuple[list[dict], int, bool]:
    """Bounded chunked getLogs.  Returns (logs, requests, lag_remaining)."""
    logs: list[dict] = []
    requests = 0
    start = from_block
    while start <= to_block and requests < max_requests:
        end = min(start + max_blocks - 1, to_block)
        logs.extend(fetch_match_logs(rpc_url, start, end))
        requests += 1
        start = end + 1
    return logs, requests, start <= to_block


def _canonical_block(rpc_url: str, block_number: int, expected_hash: str,
                     timeout: int = 25) -> tuple[bool, int | None]:
    """Prove the block is still canonical: hash-by-number == persisted hash.

    Returns (ok, block_timestamp_from_the_same_validated_block).
    """
    payload = json.dumps({"jsonrpc": "2.0", "id": 1,
                          "method": "eth_getBlockByNumber",
                          "params": [hex(block_number), False]}).encode()
    request = urllib_request.Request(
        rpc_url, data=payload, headers={"Content-Type": "application/json"})
    import urllib.request as _u
    with _u.urlopen(request, timeout=timeout) as response:
        body = json.load(response)
    block = body.get("result") or {}
    if block.get("hash") != expected_hash:
        return False, None
    ts = int(block["timestamp"], 16) if block.get("timestamp") else None
    return True, ts


import urllib.request as _urllib_request  # noqa: E402  (used above)


def main(argv: list[str] | None = None) -> int:
    del argv
    if os.getenv("FINCO_DEEPSTATE_COLLECTOR_ENABLED") != "1":
        print(json.dumps({"state": "DISABLED",
                          "reason": "FINCO_DEEPSTATE_COLLECTOR_ENABLED is not set",
                          "exit_code": 4}), flush=True)
        return 4
    rpc_url = os.getenv("ROBINHOOD_RPC_URL")
    db_path = os.getenv("FINCO_VENUE_DB_PATH")
    if not rpc_url or not db_path:
        print(json.dumps({"state": "CONFIG_ERROR", "exit_code": 4}), flush=True)
        return 4
    if not ensure_chain(rpc_url, expected_chain_id=DEEPSTATE_CHAIN_ID):
        print(json.dumps({"state": "WRONG_CHAIN", "exit_code": 2}), flush=True)
        return 2

    max_blocks = int(os.getenv("FINCO_DEEPSTATE_MAX_BLOCKS_PER_REQ") or 20000)
    max_requests = int(os.getenv("FINCO_DEEPSTATE_MAX_REQUESTS") or 40)
    collected_at = datetime.now(timezone.utc)
    store = VenueMarketStore(path=db_path)

    latest = _latest_block_number(store)
    if latest is None:
        bootstrap = int(os.getenv("FINCO_DEEPSTATE_START_BLOCK") or "0")
        if not bootstrap:
            print(json.dumps({
                "state": "BOOTSTRAP_REQUIRED",
                "reason": ("empty Deepstate store: set FINCO_DEEPSTATE_START_BLOCK "
                           "to an explicit reviewed start block (no genesis scan)"),
                "exit_code": 4}), flush=True)
            return 4
        from_block = bootstrap
    else:
        from_block = latest + 1
    current_head = eth_block_number(rpc_url)
    to_block = min(current_head, from_block + max_blocks * max_requests - 1)
    logs, requests, lag = _chunked_logs(rpc_url, from_block, to_block,
                                        max_blocks, max_requests)

    # block canonicality BEFORE persistence (fail closed on reorg)
    canonical_blocks: dict[int, int] = {}
    rejected_reorg = 0
    accepted_logs = []
    for log in logs:
        block_number = int(log["blockNumber"], 16)
        if block_number not in canonical_blocks:
            ok, _ = _canonical_block(rpc_url, block_number, log["blockHash"])
            canonical_blocks[block_number] = 1 if ok else 0
        if canonical_blocks[block_number]:
            canonical_blocks[block_number] = max(canonical_blocks[block_number], 1)
            accepted_logs.append(log)
        else:
            rejected_reorg += 1
    if canonical_blocks and 0 in canonical_blocks.values():
        print(json.dumps({"state": "REORG_DETECTED",
                          "reason": "block hash no longer canonical",
                          "rejected_logs": rejected_reorg,
                          "exit_code": 6}), flush=True)
        return 6

    observations = []
    for log in accepted_logs:
        decoded = decode_match_log(log)
        if decoded is None:
            continue
        block_ts = canonical_blocks.get(decoded["block_number"])
        ok, block_timestamp = _canonical_block(
            rpc_url, decoded["block_number"], log["blockHash"]) if block_timestamp is None \
            else (True, block_timestamp)
        observations.extend(match_to_observations(
            decoded, collected_at=collected_at, block_timestamp=block_timestamp))

    persisted = 0
    duplicates = 0
    for observation in observations:
        _, created = store.append_observation(observation)
        persisted += 1 if created else 0
        duplicates += 0 if created else 1

    remaining_lag = max(0, current_head - to_block)
    report = {
        "schema": "FINCO_DEEPSTATE_LIVE_INTELLIGENCE_V1",
        "state": "OK",
        "book": DEEPSTATE_BOOK_ID,
        "chain_id": DEEPSTATE_CHAIN_ID,
        "from_block": from_block,
        "to_block": to_block,
        "current_head": current_head,
        "getlogs_requests": requests,
        "lag_blocks_remaining": remaining_lag,
        "lag_truthfully_reported": remaining_lag > 0,
        "logs_seen": len(logs),
        "observations_persisted": persisted,
        "duplicates_skipped": duplicates,
        "market_observations_total": _total(store),
        "exit_code": 0,
    }
    print(json.dumps(report), flush=True)
    return 0


def _total(store: VenueMarketStore) -> int:
    conn = store._connect()
    try:
        return conn.execute("SELECT count(*) FROM market_observations").fetchone()[0]
    finally:
        conn.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
