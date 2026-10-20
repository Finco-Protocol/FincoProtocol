"""Real canonical financial calls across every executor width, also in Linux CI."""
import multiprocessing as mp

import pytest

from financial_engine.financing import speculative as sp
from tools.v9_joint_acceptance import run_case


@pytest.mark.parametrize("name", ["reference-solar", "reference-wind",
                                   "reference-data_center", "reference-ev_charging",
                                   "quarterly-solar", "quarterly-wind"])
def test_full_financial_and_integrity_bits_at_all_worker_widths(monkeypatch, name):
    monkeypatch.setenv("FINCO_WEB_WORKERS", "1")
    monkeypatch.setenv("FINCO_MODEL_EXECUTION_CONCURRENCY", "1")
    # This isolates the execution primitive at all widths even on a two-CPU CI
    # runner. Independent resource-guard tests prove production refuses that load.
    monkeypatch.setattr(sp, "effective_cpus", lambda: 8)
    before = {p.pid for p in mp.active_children()}
    rows = []
    try:
        for workers in (0, 1, 2, 3):
            monkeypatch.setenv("FINCO_G2A_WORKERS", str(workers))
            row = run_case(name, "canonical", False)
            rows.append(row)
            assert row["status"] == "FEASIBLE", (name, row.get("evidence"))
            if workers:
                assert sp._POOL is not None
                assert not sp._POOL.broken, sp._POOL.last_failure
                assert sp._POOL.metrics["accepted"] > 0
        assert len({row["input_digest"] for row in rows}) == 1
        assert len({row["digest"] for row in rows}) == 1
        assert all(row["evidence"] == rows[0]["evidence"] for row in rows)
    finally:
        sp.shutdown_helpers()
    assert {p.pid for p in mp.active_children()} == before


def test_unavailable_cpu_executes_real_finance_without_starting_helpers(monkeypatch):
    sp.shutdown_helpers()
    monkeypatch.setenv("FINCO_G2A_WORKERS", "3")
    monkeypatch.setattr(sp, "effective_cpus", lambda: 1)
    result = run_case("reference-solar", "canonical", False)
    assert result["status"] == "FEASIBLE"
    assert sp._POOL is None


def test_actual_application_run_worker_preserves_results_and_joins_its_helpers(monkeypatch):
    from app import project_factories
    from app.runtime.model_execution import ModelExecutor, ModelExecutionConfig
    from tests.test_v9p1_speculative import process_alive
    from tools.v9p1_worker_benchmark import financial_return_digest, runtime_call
    monkeypatch.setenv("FINCO_WEB_WORKERS", "1")
    monkeypatch.setenv("FINCO_MODEL_EXECUTION_CONCURRENCY", "1")
    pi = project_factories.create_generic_solar_reference()
    digests = []
    for requested in (0, 1):
        monkeypatch.setenv("FINCO_G2A_WORKERS", str(requested))
        executor = ModelExecutor(ModelExecutionConfig(1, "process", 180))
        returned = None
        try:
            returned = executor.run_process_sync(runtime_call, "Solar", pi)
            digests.append(financial_return_digest(returned["result"]))
            assert not returned["broken_pool"]
            assert returned["configured_helpers"] == sp.configured_workers()
            if returned["configured_helpers"]:
                assert returned["helper_metrics"]["accepted"] > 0
                assert returned["helper_pids"]
        finally:
            assert executor.shutdown_and_join() == []
        assert all(not process_alive(pid) for pid in returned["helper_pids"])
    assert digests[0] == digests[1]
