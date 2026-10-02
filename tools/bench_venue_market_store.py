"""Scale sanity benchmark for the venue market-observation store (PR 3a).

Synthetic TEST data only — benchmark rows are written to a throwaway
temporary database and never become product data.

Measures:
  - append throughput (sequential, one transaction-free insert per row,
    which is the honest worst case for the collector);
  - latest-by-instrument read;
  - bounded window reads (24h / 7d).

Scenario: tens of instruments (60) at 5-minute spot cadence over ~90 days.
"""
from __future__ import annotations

import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys = __import__("sys")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from finco_radar.venues.observations import (
    FreshnessState,
    MarketObservation,
    ObservationStatus,
)
from finco_radar.venues.store import VenueMarketStore

INSTRUMENTS = 60
CADENCE = timedelta(minutes=5)
DAYS = 90


def _row(instrument_index: int, moment: datetime, price: str) -> MarketObservation:
    ts = moment.isoformat()
    collected = (moment + timedelta(seconds=7)).isoformat()
    return MarketObservation(
        ts=ts,
        collected_at=collected,
        canonical_asset_id=f"SYM{instrument_index:03d}",
        venue_id="benchmark-venue",
        instrument_id=f"0x{instrument_index:064x}"[:42],
        instrument_type="tokenized-equity",
        price=price,
        source="benchmark",
        freshness_state=FreshnessState.AVAILABLE,
        observation_status=ObservationStatus.OK,
        payload={"i": instrument_index},
    )


def main() -> int:
    rows_per_instrument = (DAYS * 24 * 60) // 5  # 90 days at 5-minute cadence
    total = INSTRUMENTS * rows_per_instrument
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    print(f"scenario: {INSTRUMENTS} instruments x {rows_per_instrument} rows "
          f"= {total} observations (~{DAYS} days at 5m)")

    with tempfile.TemporaryDirectory() as tmp:
        store = VenueMarketStore(Path(tmp) / "bench.db")

        t0 = time.perf_counter()
        chunk: list[MarketObservation] = []
        for index in range(INSTRUMENTS):
            moment = start
            step = index * 7 % 13  # deterministic price walk seed
            for i in range(rows_per_instrument):
                price = f"{100 + (step + i) % 900 / 4:.2f}"
                chunk.append(_row(index, moment, price))
                moment += CADENCE
                if len(chunk) >= 2000:
                    store.append_many_batched(chunk)
                    chunk = []
        if chunk:
            store.append_many_batched(chunk)
        append_seconds = time.perf_counter() - t0

        sample_instrument = store.list_latest_by_venue("benchmark-venue")[0].instrument_id

        t1 = time.perf_counter()
        for _ in range(200):
            store.get_latest_for_instrument(sample_instrument)
        latest_ms = (time.perf_counter() - t1) / 200 * 1000

        since24 = start + timedelta(days=DAYS - 1)
        t2 = time.perf_counter()
        for _ in range(100):
            rows24 = store.get_window_for_instrument(
                sample_instrument, since=since24)
        window24_ms = (time.perf_counter() - t2) / 100 * 1000

        since7 = start + timedelta(days=DAYS - 7)
        t3 = time.perf_counter()
        for _ in range(50):
            rows7 = store.get_window_for_underlying(
                "SYM000", since=since7)
        window7_ms = (time.perf_counter() - t3) / 50 * 1000

    print(f"stored rows        : {store.count()}")
    print(f"append throughput  : {total / append_seconds:8.0f} rows/s "
          f"({append_seconds:.1f}s total)")
    print(f"latest-by-instr    : {latest_ms:8.2f} ms/read")
    print(f"24h window read    : {window24_ms:8.2f} ms ({len(rows24)} rows)")
    print(f"7d  window read    : {window7_ms:8.2f} ms ({len(rows7)} rows)")
    print("verdict: raw indexed reads are sufficient at this scale "
          "(no rollups needed)" if window24_ms < 50 and window7_ms < 100 else
          "verdict: window reads exceed budget — reconsider rollups")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
