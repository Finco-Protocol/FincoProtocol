#!/usr/bin/env python3
"""V8-A SQLite-only paired benchmark; NOT a substitute for end-to-end HTTP Runs.

Usage: python tools/bench_model_v8a_sqlite.py --connections 60 --sessions 2

For each isolated test database, compare historical per-connection _init_schema
against the guarded get_connection path with identical SQLite PRAGMAs,
connection factory and schema. Alternates measurement order between sessions.
Never touches FINCO_DB_PATH or any production database.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.persistence import db  # noqa: E402


def percentile(values: list[float], proportion: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(proportion * len(ordered)) - 1)]


def measure(mode: str, connections: int) -> dict:
    original_gate = db._ensure_schema_ready
    original_connect = sqlite3.connect
    timings = []
    statements = []
    sql_by_connection = []
    try:
        if mode == "historical":
            db._ensure_schema_ready = lambda conn: db._init_schema(conn)
        elif mode != "guarded":
            raise ValueError("unknown mode")

        def connect(*args, **kwargs):
            connection = original_connect(*args, **kwargs)
            sql_for_this_connection = []
            sql_by_connection.append(sql_for_this_connection)
            connection.set_trace_callback(sql_for_this_connection.append)
            return connection

        sqlite3.connect = connect
        for _ in range(connections):
            before = time.perf_counter_ns()
            connection = db.get_connection()
            connection.close()
            timings.append((time.perf_counter_ns() - before) / 1e6)
        statements = [len(sql) for sql in sql_by_connection]
    finally:
        db._ensure_schema_ready = original_gate
        sqlite3.connect = original_connect
    return {
        "connections": len(timings),
        "connection_ms_median": round(statistics.median(timings), 3),
        "connection_ms_p95": round(percentile(timings, 0.95), 3),
        "connection_ms_max": round(max(timings), 3),
        "sql_statements_total": sum(statements),
        "sql_statements_per_connection_median": statistics.median(statements),
    }


def benchmark(sessions: int, connections: int) -> dict:
    result = []
    saved_path = db.DB_PATH
    try:
        for index in range(sessions):
            with tempfile.TemporaryDirectory(prefix="finco-v8a-dbbench-") as directory:
                db.DB_PATH = str(Path(directory) / "synthetic.sqlite")
                db.get_connection().close()  # Prepare the exact same schema once.
                # Warm the guarded path before measuring warm-connection overhead.
                for _ in range(3):
                    db.get_connection().close()
                modes = ("historical", "guarded") if index % 2 == 0 else ("guarded", "historical")
                trial = {mode: measure(mode, connections) for mode in modes}
                result.append({"session": index + 1, "trial": trial})
    finally:
        db.DB_PATH = saved_path
    return {"benchmark": "SQLite connection + schema overhead only",
            "financial_results_measured": False,
            "http_runs_measured": False,
            "sessions": result}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--connections", type=int, default=60)
    parser.add_argument("--sessions", type=int, default=2)
    args = parser.parse_args()
    if args.connections < 6 or args.sessions < 2:
        parser.error("at least six connections and two independent sessions required")
    print(json.dumps(benchmark(args.sessions, args.connections), indent=2, sort_keys=True))
