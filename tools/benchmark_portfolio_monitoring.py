"""Opt-in local portfolio GET benchmark; disposable storage, real canonical commits.

Run --prepare once in an empty evidence directory, then measure the SAME 20/100
project databases before/after. No staging, provider data or engine timing is
included in the GET measurements. No benchmark fixture enters Git.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import statistics
import sqlite3
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    from app.v2.router import router
    app = FastAPI()
    app.include_router(router, prefix="/v2")
    result = TestClient(app)
    result.cookies.set(COOKIE_NAME, create_session_token(user_id="decision-user", username="admin"))
    return result


def prepare(directory):
    from app.persistence import db
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.persistence.run_history_repository import get_latest_history_entry
    from tests.test_model_financing_f2 import run
    from types import SimpleNamespace
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.glob("portfolio-*.db*")):
        raise ValueError("Refusing to overwrite existing benchmark evidence")
    db.DB_PATH = str(directory / "portfolio-100.db")
    db.init_db()
    with client() as http:
        for index in range(100):
            kind = ("solar", "wind", "data_center", "ev_charging")[index % 4]
            record = create_reference_seeded_project(user_id="decision-user", requested_name=f"Portfolio {index:03d}",
                template_source=f"generic_{kind}_reference", capacity_mw=16)
            run(SimpleNamespace(client=http), record)
            assert get_latest_history_entry("decision-user", record.project_id) is not None
            if index == 19:
                with sqlite3.connect(db.DB_PATH) as source, sqlite3.connect(directory / "portfolio-20.db") as target:
                    source.backup(target)
            print("PREPARED", index + 1, kind, flush=True)


def measure(database, repetitions):
    from app.persistence import db, run_history_repository as history
    from app.workbook import workbook_identity as identity
    db.DB_PATH = str(database)
    before = data_digest(database)
    samples = []
    original = db.get_connection
    with client() as http:
        first_at = time.perf_counter()
        first = http.get("/v2/portfolio")
        first_s = time.perf_counter() - first_at
        assert first.status_code == 200
        for _ in range(repetitions):
            counts = Counter()
            def trace(sql):
                verb = sql.lstrip().split(None, 1)[0].upper()
                counts[verb] += 1
                if verb in {"SELECT", "WITH"}:
                    for table in ("model_run_history", "workspace_states", "capex_sub_lines", "opex_sub_lines", "scenarios", "projects"):
                        if table in sql:
                            counts["reads_" + table] += 1
            def connection():
                counts["connections"] += 1
                value = original()
                value.set_trace_callback(trace)
                return value
            with ExitStack() as stack:
                stack.enter_context(patch.object(db, "get_connection", connection))
                latest = stack.enter_context(patch.object(history, "get_latest_history_entry", wraps=history.get_latest_history_entry))
                assembly = stack.enter_context(patch.object(identity, "assemble_transactional", wraps=identity.assemble_transactional))
                started = time.perf_counter()
                response = http.get("/v2/portfolio")
                elapsed = time.perf_counter() - started
                assert response.status_code == 200
                samples.append({"wall_s": elapsed, "bytes": len(response.content), "sql": dict(counts),
                                "latest_history_calls": latest.call_count, "identity_assemblies": assembly.call_count})
    times = sorted(s["wall_s"] for s in samples)
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as conn:
        projects = conn.execute("SELECT COUNT(*) FROM projects WHERE user_id='decision-user' AND archived=0").fetchone()[0]
        runs = conn.execute("SELECT COUNT(*) FROM model_run_history WHERE user_id='decision-user'").fetchone()[0]
    after = data_digest(database)
    assert before == after, "Portfolio GET changed persisted evidence"
    assert response.text.count('data-project="') == projects
    return {"projects": projects, "committed_runs": runs, "first_get_s": first_s,
            "median_s": statistics.median(times), "p95_s": times[max(0, int(len(times) * .95 + .999) - 1)],
            "samples": samples, "data_before_sha256": before, "data_after_sha256": after}


def data_digest(database):
    """Outside timed GETs: detect any project, Workspace or history mutation."""
    digest = hashlib.sha256()
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as conn:
        for table, key in (("projects", "project_id"), ("workspace_states", "workspace_id"), ("model_run_history", "history_id")):
            digest.update(table.encode())
            for row in conn.execute(f"SELECT * FROM {table} ORDER BY {key}"):
                digest.update(json.dumps(tuple(row), separators=(",", ":"), ensure_ascii=True).encode())
    return digest.hexdigest()


def main():
    import os
    os.environ.setdefault("FINCO_MODEL_EXECUTION_MODE", "thread")
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    try:
        if args.prepare:
            prepare(args.fixtures)
        if args.output:
            result = {"head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "python": sys.version, "fixtures": "100 real canonical commits across four synthetic verticals",
                "sources": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in (
                    "app/v2/portfolio_reads.py", "app/v2/portfolio_projection.py", "app/templates/portfolio_monitoring.html")},
                "results": {str(n): measure(args.fixtures / f"portfolio-{n}.db", args.repetitions) for n in (20, 100)}}
            args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result, indent=2), flush=True)
    finally:
        from app.runtime.model_execution import reset_model_executor_for_tests
        assert not reset_model_executor_for_tests(None)


if __name__ == "__main__":
    main()
