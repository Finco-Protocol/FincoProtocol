"""One-shot Deepstate NVDA/USDG live collector (V1 vertical slice).

Runtime architecture (mirrors tokenized_collect):
canonical Deepstate router logs (read-only RPC) -> bounded exact decode
-> MarketObservation -> append-only VenueMarketStore.

Only canonical executed Deepstate matches on the reviewed NVDA/USDG book
become observations.  No quotes, no order-book midpoints, no wallet, no
signing, no scheduler in-process.  Environment:

    FINCO_DEEPSTATE_COLLECTOR_ENABLED   1 to allow a run (default off)
    ROBINHOOD_RPC_URL                   read-only chain RPC (required)
    FINCO_VENUE_DB_PATH                 VenueMarketStore path (required)

Exit codes: 0 OK (run allowed, cycle completed), 4 DISABLED/CONFIG_ERROR.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import sys

from finco_radar.venues.store import VenueMarketStore

from app.radar_rwa.deepstate_chain import ensure_chain
from finco_radar.venues.deepstate_live import (
    DEEPSTATE_BOOK_ID,
    DEEPSTATE_CHAIN_ID,
    decode_match_log,
    fetch_block_timestamp,
    fetch_match_logs,
    match_to_observation,
)


def _latest_block_number(store: VenueMarketStore) -> int | None:
    latest = 0
    conn = store._connect()
    try:
        rows = conn.execute(
            "SELECT payload FROM market_observations WHERE venue_id=?",
            ("DEEPSTATE",)).fetchall()
    finally:
        conn.close()
    for (payload_text,) in rows:
        try:
            payload = json.loads(payload_text)
            latest = max(latest, int(payload.get("block_number") or 0))
        except Exception:
            continue
    return latest or None


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

    collected_at = datetime.now(timezone.utc)
    store = VenueMarketStore(path=db_path)
    head = int(os.getenv("FINCO_DEEPSTATE_HEAD_BLOCK") or "0") or None
    latest = _latest_block_number(store)
    from_block = int(os.getenv("FINCO_DEEPSTATE_FROM_BLOCK") or "0") or (
        (latest + 1) if latest else head or 0)
    to_block = head or from_block
    logs = fetch_match_logs(rpc_url, from_block, to_block) if to_block >= from_block else []
    attempted = len(logs)
    accepted = 0
    duplicates = 0
    created_list = []
    for log in logs:
        decoded = decode_match_log(log)
        if decoded is None:
            continue
        block_ts = fetch_block_timestamp(rpc_url, decoded["block_number"])
        observation = match_to_observation(decoded, collected_at=collected_at,
                                           block_timestamp=block_ts)
        digest, created = store.append_observation(observation)
        accepted += 1
        duplicates += 0 if created else 1
        if created:
            created_list.append({"tx": decoded["transaction_hash"],
                                 "log_index": decoded["log_index"],
                                 "digest": digest})
    report = {
        "schema": "FINCO_DEEPSTATE_LIVE_INTELLIGENCE_V1",
        "state": "OK" if to_block >= from_block else "NO_WINDOW",
        "book": DEEPSTATE_BOOK_ID,
        "chain_id": DEEPSTATE_CHAIN_ID,
        "from_block": from_block,
        "to_block": to_block,
        "logs_seen": attempted,
        "observations_accepted": accepted,
        "duplicates_skipped": duplicates,
        "persisted": len(created_list),
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
