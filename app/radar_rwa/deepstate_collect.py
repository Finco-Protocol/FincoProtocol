"""One-shot Deepstate NVDA/USDG live collector (V1 vertical slice).

Canonical Router logs -> initial block canonicality -> exact decode in memory
-> FINAL block-hash recheck -> ONE append-only batch persistence -> operational
checkpoint advance.

The operational scan checkpoint is mutable and separate from market evidence.
It advances only after a complete bounded range passes acquisition, decode,
final canonicality and atomic observation persistence. Market observations
remain append-only and are never used to infer scan completeness.

Every subsequent run re-scans a small deterministic overlap before the
checkpoint. This is operational shallow-reorg safety only; it is NOT a chain
finality claim. The explicit reviewed bootstrap remains the hard lower bound.

Environment:
    FINCO_DEEPSTATE_START_BLOCK   explicit reviewed bootstrap (always required)
    FINCO_DEEPSTATE_RESCAN_BLOCKS overlap size (default 16; operational only)

No deploy/scheduler is configured here.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import sys
import urllib.request as _urllib_request

from finco_radar.venues.store import VenueMarketStore

from app.radar_rwa.deepstate_chain import ensure_chain, eth_block_number
from finco_radar.venues.deepstate_live import (
    DEEPSTATE_BOOK_ID,
    DEEPSTATE_CHAIN_ID,
    decode_match_log,
    fetch_match_logs,
    match_to_observations,
)

_CHECKPOINT_KEY = "DEEPSTATE_NVDA_USDG_V1"
_DEFAULT_RESCAN_BLOCKS = 16
_CHECKPOINT_SCHEMA = """
CREATE TABLE IF NOT EXISTS collector_checkpoints (
    collector_key      TEXT PRIMARY KEY,
    last_scanned_block INTEGER NOT NULL,
    updated_at         TEXT NOT NULL
)
"""


def _checkpoint_block(store: VenueMarketStore) -> int | None:
    conn = store._connect()
    try:
        conn.execute(_CHECKPOINT_SCHEMA)
        row = conn.execute(
            "SELECT last_scanned_block FROM collector_checkpoints "
            "WHERE collector_key=?", (_CHECKPOINT_KEY,)).fetchone()
        conn.commit()
        return int(row[0]) if row is not None else None
    finally:
        conn.close()


def _advance_checkpoint(store: VenueMarketStore, block_number: int) -> None:
    """Advance mutable operational state monotonically; never market evidence."""
    conn = store._connect()
    try:
        conn.execute(_CHECKPOINT_SCHEMA)
        conn.execute(
            "INSERT INTO collector_checkpoints "
            "(collector_key,last_scanned_block,updated_at) VALUES (?,?,?) "
            "ON CONFLICT(collector_key) DO UPDATE SET "
            "last_scanned_block=excluded.last_scanned_block, "
            "updated_at=excluded.updated_at "
            "WHERE excluded.last_scanned_block > collector_checkpoints.last_scanned_block",
            (_CHECKPOINT_KEY, int(block_number), datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally:
        conn.close()


def _chunked_logs(rpc_url: str, from_block: int, to_block: int,
                  max_blocks: int, max_requests: int) -> tuple[list[dict], int, bool]:
    """Bounded chunked getLogs. Returns (logs, requests, lag_remaining)."""
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
    """Hash-by-number canonicality plus timestamp from the SAME block."""
    payload = json.dumps({"jsonrpc": "2.0", "id": 1,
                          "method": "eth_getBlockByNumber",
                          "params": [hex(block_number), False]}).encode()
    request = _urllib_request.Request(
        rpc_url, data=payload, headers={"Content-Type": "application/json"})
    with _urllib_request.urlopen(request, timeout=timeout) as response:
        body = json.load(response)
    block = body.get("result") or {}
    if block.get("hash") != expected_hash:
        return False, None
    ts = int(block["timestamp"], 16) if block.get("timestamp") else None
    return (ts is not None), ts


def _reorg_report(reason: str, rejected_logs: int = 0) -> int:
    print(json.dumps({"state": "REORG_DETECTED", "reason": reason,
                      "rejected_logs": rejected_logs, "exit_code": 6}), flush=True)
    return 6


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
    rescan_blocks = int(os.getenv("FINCO_DEEPSTATE_RESCAN_BLOCKS")
                        or _DEFAULT_RESCAN_BLOCKS)
    bootstrap = int(os.getenv("FINCO_DEEPSTATE_START_BLOCK") or "0")
    if not bootstrap:
        print(json.dumps({
            "state": "BOOTSTRAP_REQUIRED",
            "reason": ("set FINCO_DEEPSTATE_START_BLOCK to an explicit "
                       "reviewed start block; there is no genesis fallback"),
            "exit_code": 4}), flush=True)
        return 4
    scan_capacity = max_blocks * max_requests
    if (max_blocks <= 0 or max_requests <= 0 or rescan_blocks <= 0
            or rescan_blocks >= scan_capacity):
        print(json.dumps({
            "state": "CONFIG_ERROR",
            "reason": ("positive scan bounds required and "
                       "FINCO_DEEPSTATE_RESCAN_BLOCKS must be smaller "
                       "than per-run scan capacity"),
            "exit_code": 4}), flush=True)
        return 4

    collected_at = datetime.now(timezone.utc)
    store = VenueMarketStore(path=db_path)
    checkpoint = _checkpoint_block(store)
    if checkpoint is None:
        from_block = bootstrap
    else:
        # Operational shallow-reorg safety. Re-read the checkpoint tail so a
        # replacement of a previously empty block can surface new match logs.
        from_block = max(bootstrap, checkpoint - rescan_blocks + 1)

    current_head = eth_block_number(rpc_url)
    if from_block > current_head:
        report = {
            "schema": "FINCO_DEEPSTATE_LIVE_INTELLIGENCE_V1",
            "state": "OK", "book": DEEPSTATE_BOOK_ID,
            "chain_id": DEEPSTATE_CHAIN_ID, "from_block": from_block,
            "to_block": current_head, "current_head": current_head,
            "getlogs_requests": 0, "lag_blocks_remaining": 0,
            "lag_truthfully_reported": False, "logs_seen": 0,
            "observations_persisted": 0, "duplicates_skipped": 0,
            "operational_checkpoint_block": checkpoint,
            "reviewed_bootstrap_start": bootstrap,
            "rescan_blocks": rescan_blocks,
            "market_observations_total": _total(store), "exit_code": 0,
        }
        print(json.dumps(report), flush=True)
        return 0

    to_block = min(current_head, from_block + scan_capacity - 1)
    logs, requests, _ = _chunked_logs(
        rpc_url, from_block, to_block, max_blocks, max_requests)

    # Initial canonicality. Every log in a block must identify one block hash.
    validated_blocks: dict[int, dict[str, int | str]] = {}
    for log in logs:
        try:
            block_number = int(log["blockNumber"], 16)
            expected_hash = str(log["blockHash"])
        except (KeyError, TypeError, ValueError):
            return _reorg_report("malformed canonical log identity", 1)
        previous = validated_blocks.get(block_number)
        if previous is not None and previous["hash"] != expected_hash:
            return _reorg_report("conflicting block hashes inside acquired range", 1)
        if previous is None:
            ok, timestamp = _canonical_block(rpc_url, block_number, expected_hash)
            if not ok or timestamp is None:
                return _reorg_report("block hash no longer canonical", 1)
            validated_blocks[block_number] = {
                "hash": expected_hash, "timestamp": timestamp}

    # Decode all observations in memory using only timestamps from validated blocks.
    observations = []
    for log in logs:
        decoded = decode_match_log(log)
        if decoded is None:
            continue
        block = validated_blocks.get(decoded["block_number"])
        if block is None:
            return _reorg_report("validated block timestamp unavailable", 1)
        observations.extend(match_to_observations(
            decoded, collected_at=collected_at,
            block_timestamp=int(block["timestamp"])))

    # FINAL canonicality immediately before persistence. A changed block
    # invalidates the entire run; ZERO observations are persisted.
    for block_number in sorted(validated_blocks):
        block = validated_blocks[block_number]
        ok, timestamp = _canonical_block(
            rpc_url, block_number, str(block["hash"]))
        if not ok or timestamp != block["timestamp"]:
            return _reorg_report("final block canonicality changed", len(logs))

    # One atomic evidence batch. Only after success may operational state advance.
    # A crash after commit but before checkpoint causes a safe retry/dedupe.
    created = store.append_many_batched(observations)
    persisted = sum(1 for _digest, was_created in created if was_created)
    duplicates = len(created) - persisted
    _advance_checkpoint(store, to_block)

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
        "operational_checkpoint_block": _checkpoint_block(store),
        "reviewed_bootstrap_start": bootstrap,
        "rescan_blocks": rescan_blocks,
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
