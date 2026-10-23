"""Dormant authoritative shadow in the REAL production ModelExecutor (process mode, spawned workers).

The canonical value returned to the caller is identical with the shadow OFF and ON; the shadow records
MATCH for a feasible Run and for a rejected (exception) Run with native execution proven in the shadow
worker; timeout, backpressure, cancellation and a deliberately altered value are handled; the shadow
evaluates exactly the immutable input snapshot taken before the canonical submission, and inputs
mutated while the canonical Run was in flight are reported INPUT_MUTATED, never compared."""
from __future__ import annotations

import asyncio
import copy

import pytest

from app.runtime import native_shadow as ns
from app.runtime.model_execution import ModelExecutionConfig, ModelExecutor

pytestmark = pytest.mark.usefixtures("native_artifacts")


@pytest.fixture
def executor(monkeypatch):
    for name in (ns.ENV_SHADOW, ns.ENV_LOG, ns.ENV_QUEUE, ns.ENV_TIMEOUT, ns.ENV_MAX_INPUT_BYTES):
        monkeypatch.delenv(name, raising=False)
    ex = ModelExecutor(ModelExecutionConfig(mode="process", concurrency=1))
    yield ex
    assert ex.shutdown_and_join() == []


def _solar_override():
    from app import project_factories as pf
    return pf.create_generic_solar_reference()


def _rejected_override():
    from tools import v9p2a_odr_acceptance as acc
    return acc.cases()["W25-tenor18"][0]()


def _run(ex, override, project_type="Solar"):
    from app.api.project_runner import run_project
    try:
        return "return", asyncio.run(ex.run_process(run_project, project_type, "Base",
                                                    project_inputs_override=override))
    except Exception as exc:  # noqa: BLE001
        return "raise", exc


def test_shadow_on_returns_the_identical_canonical_value_and_records_match(executor, monkeypatch):
    kind_off, off = _run(executor, _solar_override())
    assert kind_off == "return"
    monkeypatch.setenv(ns.ENV_SHADOW, "stage2")
    kind_on, on = _run(executor, _solar_override())
    observer = executor.native_shadow_observer()
    assert observer is not None and observer.drain(900)
    assert kind_on == "return" and ns.fingerprint(value=on) == ns.fingerprint(value=off)
    (record,) = observer.records()
    assert record["outcome"] == "MATCH" and record["canonical"]["kind"] == "return"
    assert record["native"]["native_solves"] > 0 and record["native"]["stage2_native_calls"] > 0
    assert record["worker_status"] == "OK"


def test_shadow_matches_a_rejected_run_exception(executor, monkeypatch):
    monkeypatch.setenv(ns.ENV_SHADOW, "stage1")
    kind, err = _run(executor, _rejected_override(), project_type="Wind")
    assert kind == "raise"
    observer = executor.native_shadow_observer()
    assert observer.drain(900)
    (record,) = observer.records()
    assert record["outcome"] == "MATCH" and record["canonical"]["kind"] == "raise"


def test_candidate_timeout_is_contained(executor, monkeypatch):
    monkeypatch.setenv(ns.ENV_SHADOW, "stage2")
    monkeypatch.setenv(ns.ENV_TIMEOUT, "1")
    kind, value = _run(executor, _solar_override())
    observer = executor.native_shadow_observer()
    assert observer.drain(120)
    assert kind == "return"
    (record,) = observer.records()
    assert record["outcome"] == "CANDIDATE_TIMEOUT"
    assert observer.stats().get("worker_not_reaped", 0) == 0


def test_backpressure_drops_and_counts(executor, monkeypatch):
    from app.api.project_runner import run_project

    monkeypatch.setenv(ns.ENV_SHADOW, "stage1")
    monkeypatch.setenv(ns.ENV_QUEUE, "1")
    observer = executor._native_shadow_reconcile("stage1")
    override = _solar_override()
    kwargs = {"project_inputs_override": override}
    snap = observer.snapshot(run_project, ("Solar", "Base"), kwargs)
    for _ in range(3):
        observer.observe(snap, ("Solar", "Base"), kwargs, value={"canonical": 1.0})
    assert observer.drain(900)
    stats = observer.stats()
    assert stats["dropped_backpressure"] >= 1 and stats["enqueued"] + stats["dropped_backpressure"] == 3


def test_a_deliberately_altered_canonical_value_is_a_mismatch(executor, monkeypatch):
    from app.api.project_runner import run_project

    monkeypatch.setenv(ns.ENV_SHADOW, "stage1")
    kind, value = _run(executor, _solar_override())
    observer = executor.native_shadow_observer()
    assert observer.drain(900) and observer.records()[-1]["outcome"] == "MATCH"
    tampered = copy.deepcopy(value)
    k0 = next(k for k, v in tampered["kpis"].items() if isinstance(v, float))
    tampered["kpis"][k0] += 1e-9
    kwargs = {"project_inputs_override": _solar_override()}
    snap = observer.snapshot(run_project, ("Solar", "Base"), kwargs)
    observer.observe(snap, ("Solar", "Base"), kwargs, value=tampered)
    assert observer.drain(900)
    assert observer.records()[-1]["outcome"] == "MISMATCH"


def test_inputs_mutated_during_the_canonical_run_are_never_compared(executor, monkeypatch):
    from app.api.project_runner import run_project

    monkeypatch.setenv(ns.ENV_SHADOW, "stage1")
    observer = executor._native_shadow_reconcile("stage1")
    override = _solar_override()
    kwargs = {"project_inputs_override": override}
    snap = observer.snapshot(run_project, ("Solar", "Base"), kwargs)
    payload_before = snap.payload
    assert ns.inputs_unchanged(snap, ("Solar", "Base"), {"project_inputs_override": copy.deepcopy(override)})
    kwargs["project_inputs_override"] = "replaced after submission"     # the caller's dict mutated late
    observer.observe(snap, ("Solar", "Base"), kwargs, value={"anything": 1})
    assert observer.drain(60)
    assert snap.payload == payload_before                     # the snapshot is independently owned bytes
    (record,) = observer.records()
    assert record["outcome"] == "INPUT_MUTATED" and record["input_sha256"] == snap.sha256
    assert observer.stats().get("enqueued", 0) == 0          # no candidate was evaluated


def test_candidate_refuses_a_snapshot_whose_bytes_do_not_match_its_digest(executor, monkeypatch):
    from app.api.project_runner import run_project

    monkeypatch.setenv(ns.ENV_SHADOW, "stage1")
    observer = executor._native_shadow_reconcile("stage1")
    kwargs = {"project_inputs_override": _solar_override()}
    snap = observer.snapshot(run_project, ("Solar", "Base"), kwargs)
    forged = ns.InputSnapshot(snap.fn_module, snap.fn_name, snap.payload + b"\x00", snap.sha256)
    monkeypatch.setattr(ns, "inputs_unchanged", lambda *_a, **_k: True)
    observer.observe(forged, ("Solar", "Base"), kwargs, value={"x": 1})
    assert observer.drain(300)
    record = observer.records()[-1]
    assert record["outcome"] == "CANDIDATE_EXCEPTION"
    assert "SHADOW_SNAPSHOT_DIGEST_MISMATCH" in record["candidate_error"]


def test_snapshot_is_bounded_and_unshadowed_calls_are_ignored(executor, monkeypatch):
    from app.api.project_runner import run_project

    monkeypatch.setenv(ns.ENV_SHADOW, "stage1")
    monkeypatch.setenv(ns.ENV_MAX_INPUT_BYTES, "64")
    observer = executor._native_shadow_reconcile("stage1")
    assert observer.snapshot(run_project, ("Solar", "Base"), {"project_inputs_override": _solar_override()}) is None
    assert observer.stats()["dropped_snapshot_too_large"] == 1
    assert observer.snapshot(len, ((1, 2),), {}) is None


def test_a_cancelled_canonical_call_is_never_shadowed(monkeypatch):
    from tests.native_v10_support import sleep_for

    monkeypatch.setenv(ns.ENV_SHADOW, "stage1")
    monkeypatch.setattr(ns, "SHADOWED", ns.SHADOWED | {("tests.native_v10_support", "sleep_for")})
    ex = ModelExecutor(ModelExecutionConfig(mode="thread", concurrency=1))

    async def cancel_soon():
        task = asyncio.ensure_future(ex.run_process(sleep_for, 0.5))
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(cancel_soon())
        observer = ex.native_shadow_observer()
        assert observer is not None and observer.records() == [] and observer.stats().get("enqueued", 0) == 0
    finally:
        assert ex.shutdown_and_join() == []
