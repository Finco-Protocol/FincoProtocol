"""Opt-in, offline Radar V1 performance observation (NOT a CI timing gate).

Examples:
  python -m tools.bench_radar_v1_closeout --underlyings 10 --rows 64
  python -m tools.bench_radar_v1_closeout --underlyings 60 --rows 256

All observations are generated into a TEMPORARY test-only store. Nothing
acquires a provider, deploys, trades, or writes to an operator database.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from time import perf_counter

from finco_radar.venues.intelligence import build_tokenized_intelligence, _entry_identity
from finco_radar.venues.models import RegistryStatus
from finco_radar.venues.observations import MarketObservation, FreshnessState, ObservationStatus
from finco_radar.venues.registry import VenueRegistry
from finco_radar.venues.relative_value import (
    build_dislocation_monitor, compute_basis_distribution,
    compute_dislocation_persistence,
)
from finco_radar.venues.store import VenueMarketStore
from app.crypto_terminal.tokenized_signal_lifecycle import (
    MAX_FEED_EVENTS, build_tokenized_signal_lifecycle,
)
from app.crypto_terminal.deepstate_composition import build_deepstate_historical_context
from tools.radar_tokenized_closeout_audit import run_audit

NOW = datetime(2026, 10, 16, 9, tzinfo=timezone.utc)


class MeasuredStore(VenueMarketStore):
    """Count executed SQL statements through SQLite's own trace callback."""
    def __init__(self, path):
        self.query_counts = Counter()
        super().__init__(path)

    def _connect(self):
        conn = super()._connect()
        def count(statement):
            if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                self.query_counts["read_statements"] += 1
        conn.set_trace_callback(count)
        return conn


def _active_bindings(registry: VenueRegistry, cap: int):
    selected = []
    for symbol in sorted(registry._underlyings):
        entries = registry.representations_for_underlying(symbol)
        active = [x.entry for x in entries if x.status is RegistryStatus.ACTIVE]
        if not active:
            continue
        entry = active[0]
        venue, instrument = _entry_identity(entry)
        selected.append((symbol, venue, instrument, entry.instrument_type))
        if len(selected) >= cap:
            break
    return selected


def _seed(store, bindings, observations_per_rep):
    start = NOW - timedelta(minutes=observations_per_rep * 5 + 1)
    rows = []
    for symbol, venue, instrument, kind in bindings:
        for i in range(observations_per_rep):
            ts = start + timedelta(minutes=i * 5)
            rows.append(MarketObservation(
                ts=ts.isoformat(),
                collected_at=(ts + timedelta(seconds=5)).isoformat(),
                canonical_asset_id=symbol, venue_id=venue,
                instrument_id=instrument, instrument_type=kind,
                price="101", reference_price="100",
                source="SYNTHETIC_OFFLINE_BENCHMARK_ONLY",
                freshness_state=FreshnessState.AVAILABLE,
                observation_status=ObservationStatus.OK,
                payload={"reference_state": "AVAILABLE",
                         "reference_observed_at": ts.isoformat()},
            ))
    store.append_many_batched(rows)
    return len(rows)


def _probe(label, fn, store, repeats):
    durations = []
    reads = []
    outcome = None
    for _ in range(repeats):
        before = store.query_counts["read_statements"]
        t0 = perf_counter()
        outcome = fn()
        durations.append(round((perf_counter() - t0) * 1000, 3))
        reads.append(store.query_counts["read_statements"] - before)
    return {
        "operation": label, "runs": repeats,
        "wall_ms": durations,
        "min_ms": min(durations), "max_ms": max(durations),
        "spread_ms": round(max(durations) - min(durations), 3),
        "sqlite_read_statements": reads,
        "result_type": type(outcome).__name__,
    }


def run_bench(*, requested_underlyings=10, rows_per_representation=64, repeats=3):
    if not 1 <= requested_underlyings <= 60:
        raise ValueError("underlyings must be 1..60")
    if not 1 <= rows_per_representation <= 256:
        raise ValueError("rows must be 1..256")
    if not 1 <= repeats <= 5:
        raise ValueError("repeats must be 1..5")
    registry = VenueRegistry.load()
    bindings = _active_bindings(registry, requested_underlyings)
    if not bindings:
        raise RuntimeError("No canonical ACTIVE test fixture bindings in committed registry")
    with tempfile.TemporaryDirectory(prefix="finco-radar-perf-synthetic-") as directory:
        db = Path(directory) / "benchmark.db"
        store = MeasuredStore(db)
        nrows = _seed(store, bindings, rows_per_representation)
        symbol = bindings[0][0]
        def intelligence():
            return build_tokenized_intelligence(
                symbol, registry=registry, store=store,
                as_of=NOW, include_points=True)
        def history_projection():
            intel = intelligence()
            return [(compute_basis_distribution(h, now=NOW),
                     compute_dislocation_persistence(h, now=NOW))
                    for h in intel.representations]
        def lifecycle():
            return build_tokenized_signal_lifecycle(
                symbol, registry=registry, store=store,
                as_of=NOW, max_events=MAX_FEED_EVENTS)
        probes = [
            _probe("tokenized_monitor_60_cap", lambda: build_dislocation_monitor(
                registry=registry, store=store, now=NOW,
                symbols=[x[0] for x in bindings], limit=60), store, repeats),
            _probe("single_asset_relative_value", intelligence, store, repeats),
            _probe("historical_distribution_and_persistence", history_projection, store, repeats),
            _probe("signal_lifecycle_max_60", lifecycle, store, repeats),
            _probe("deepstate_historical_context", lambda:
                   build_deepstate_historical_context(
                       "NVDA", registry=registry, store=store, as_of=NOW), store, repeats),
        ]
        # This operation internally opens its own ephemeral snapshot and is
        # intentionally reported without a fabricated SQL query count.
        durations = []
        for _ in range(repeats):
            t0 = perf_counter()
            run_audit(db, as_of=NOW, max_assets=requested_underlyings)
            durations.append(round((perf_counter() - t0) * 1000, 3))
        probes.append({
            "operation": "read_only_closeout_audit",
            "runs": repeats, "wall_ms": durations,
            "min_ms": min(durations), "max_ms": max(durations),
            "spread_ms": round(max(durations) - min(durations), 3),
            "sqlite_read_statements": None,
            "result_type": "dict",
        })
        return {
            "contract": "RADAR_V1_OFFLINE_PERFORMANCE_PROBE_V1",
            "dataset_origin": "SYNTHETIC_TEMPORARY_ONLY_NOT_MARKET_EVIDENCE",
            "as_of": NOW.isoformat(),
            "requested_underlyings": requested_underlyings,
            "actual_bound_underlyings": len(bindings),
            "observations_per_representation": rows_per_representation,
            "total_synthetic_rows": nrows,
            "signal_representation_cap": 20, "signal_event_cap": 60,
            "deepstate_output_cap": 120,
            "performance_acceptance_budget": "NOT_YET_APPROVED",
            "probes": probes,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--underlyings", type=int, default=10)
    parser.add_argument("--rows", type=int, default=64)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(run_bench(
        requested_underlyings=args.underlyings,
        rows_per_representation=args.rows,
        repeats=args.repeats), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
