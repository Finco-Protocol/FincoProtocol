"""F4 — user-safe Run failure reason carried by the typed JSON outcome (``app/services/run_intent_service.py``).

Separately governed: this module is byte-pinned in its own exact-source cohort together with the one protected source it covers.  What is proven:

* the reason is the route's reviewed wording for a typed engine refusal, a plain code-level reason for timeout / busy / conflict / save refusal,
  and a generic sentence for anything else; no traceback, SQL, path, credential or raw exception text ever reaches the browser;
* the D-029 lifecycle is unchanged: HTTP status, typed outcome, ledger state, replay semantics, immutable history and idempotency;
* the reason is disclosed only to the request that produced it (never to another user, another request or a replay), once, from a bounded cache;
* concurrent failures never mix their reasons; unknown failures fail closed to the generic sentence.
"""
from __future__ import annotations

import json
import re
import threading
import uuid

import pytest

from tests.test_pr394_staging_corrections_v1 import env, history, run_json   # noqa: F401  (fixture re-export)

LEAK_PROBES = ("Traceback", "/opt/", "/root/", "secret", "hunter2", "password", "sqlite", "SELECT ", "31956", "period_index",
               "SHL_MATURITY", "PR8_CLEAN", "ModelWorkerError", "CleanProductionRunUnavailable")


def _fail_engine(monkeypatch, exc_factory):
    import app.runtime.model_execution as me

    async def failing(*args, **kwargs):
        raise exc_factory(me)

    monkeypatch.setattr(me, "run_model_process", failing)


def _worker_error(error_type, message):
    return lambda me: me.ModelWorkerError(error_type, message, None, None)


def test_typed_engine_refusal_gets_the_reviewed_reason_a_code_and_a_log_reference(env, monkeypatch, caplog):
    record = env.create("solar")
    _fail_engine(monkeypatch, _worker_error(
        "CleanProductionRunUnavailable",
        "PR8_CLEAN_ENGINE_FAIL_CLOSED: ValueError: SHL_MATURITY_RESIDUAL_FAILS_CLOSED: closing balance 31956.03 kEUR remains "
        "at maturity period_index=57 /opt/finco_protocol/secret/path Traceback (most recent call last)"))
    response = run_json(env, record)
    body = response.json()
    assert response.status_code == 409 and body["outcome"] == "FAILED" and body["ok"] is False
    assert "shareholder loan" in body["message"].lower(), body["message"]
    assert body["error_code"] == "ENGINE_FAILED"
    assert re.fullmatch(r"[0-9a-f]{8}", body["reference"] or ""), body
    assert any(f"reference={body['reference']}" in r.getMessage() and "ENGINE_FAILED" in r.getMessage() for r in caplog.records)
    blob = json.dumps(body)
    for probe in LEAK_PROBES:
        assert probe not in blob, probe
    assert history(env, record) == [], "a failed Run commits nothing"
    from app.services import run_intent_service as ri
    assert ri._FAILURE_REASONS == {}, "the reason is consumed by the response that owns it"


@pytest.mark.parametrize("raw", [
    "boom at /root/private/db.sqlite password=hunter2",
    "sqlite3.OperationalError: no such table: users; SELECT * FROM users WHERE token='secret'",
    "Traceback (most recent call last): File \"/opt/finco_protocol/app/x.py\", line 1",
    "AWS_SECRET_ACCESS_KEY=abc123 /etc/finco/.env",
])
def test_an_unknown_failure_fails_closed_to_a_generic_sentence_and_never_echoes_its_text(env, monkeypatch, caplog, raw):
    record = env.create("solar")
    _fail_engine(monkeypatch, _worker_error("RuntimeError", raw))
    body = run_json(env, record).json()
    assert body["outcome"] == "FAILED" and body["error_code"] == "ENGINE_FAILED" and body["message"]
    assert "nothing was saved" in body["message"].lower()
    for probe in LEAK_PROBES + ("boom", "abc123", ".env", "users"):
        assert probe not in json.dumps(body), probe
    assert history(env, record) == []


def test_a_plain_exception_not_from_the_worker_is_also_generic(env, monkeypatch):
    record = env.create("solar")
    _fail_engine(monkeypatch, lambda me: ValueError("internal: /opt/finco_protocol/app/secret.py line 9 token=zzz"))
    body = run_json(env, record).json()
    assert body["outcome"] == "FAILED" and body["message"]
    for probe in ("/opt/", "secret", "token=zzz", "internal:"):
        assert probe not in json.dumps(body), probe


def test_timeout_and_busy_have_their_own_plain_reasons_and_unchanged_status(env, monkeypatch):
    from app.runtime.model_execution import ModelExecutionBusy, ModelExecutionTimeout
    record = env.create("solar")
    for factory, code, needle in ((ModelExecutionTimeout, "ENGINE_TIMEOUT", "too long"), (ModelExecutionBusy, "ADMISSION_REFUSED", "busy")):
        _fail_engine(monkeypatch, lambda me, _f=factory: _f())
        response = run_json(env, record)
        body = response.json()
        assert response.status_code == 409 and body["outcome"] == "FAILED" and body["error_code"] == code and needle in body["message"].lower(), body
        assert history(env, record) == []


def test_replaying_a_failed_intent_returns_the_ledger_message_not_the_recorded_reason(env, monkeypatch):
    record = env.create("solar")
    key = str(uuid.uuid4())
    _fail_engine(monkeypatch, _worker_error("CleanProductionRunUnavailable", "SHL_MATURITY_RESIDUAL_FAILS_CLOSED x"))
    first = run_json(env, record, key).json()
    assert first["outcome"] == "FAILED" and "shareholder loan" in first["message"].lower()
    again = run_json(env, record, key)
    second = again.json()
    assert again.status_code == 409 and second["outcome"] == "FAILED"
    assert "cannot be reused" in second["message"], "D-029: a failed intent is terminal; a replay never re-discloses the first reason"
    assert second["error_code"] != "ENGINE_FAILED" or "shareholder" not in second["message"].lower()
    assert history(env, record) == []


def test_the_reason_is_never_disclosed_to_another_user_or_intent(env, monkeypatch):
    from app.services import run_intent_service as ri
    from app.persistence.run_intent_repository import SubmittedIntent
    record = env.create("solar")
    _fail_engine(monkeypatch, _worker_error("CleanProductionRunUnavailable", "SHL_MATURITY_RESIDUAL_FAILS_CLOSED"))
    first = run_json(env, record).json()
    assert first["message"]
    # a decision built for a DIFFERENT actor / project / key finds no recorded reason and keeps the released (empty) payload
    other = SubmittedIntent(actor_id="someone-else", project_id=record.project_id, run_intent_id=str(uuid.uuid4()),
                            workbook_version="2.3.0", content_hash="0" * 64)
    released = ri.payload(ri.Decision("NEW", other), "FAILED")
    assert released["message"] == "" and released["error_code"] is None and "reference" not in released
    assert ri._FAILURE_REASONS == {}


def test_payload_is_unchanged_for_every_non_failed_outcome():
    from app.services import run_intent_service as ri
    from app.persistence.run_intent_repository import SubmittedIntent
    intent = SubmittedIntent(actor_id="a", project_id="p", run_intent_id=str(uuid.uuid4()), workbook_version="2.3.0", content_hash="0" * 64)
    for kind in ("COMMITTED", "REPLAYED", "IN_PROGRESS", "CONFLICT", "EXPIRED", "UNAVAILABLE"):
        body = ri.payload(ri.Decision(kind, intent, history_id="h" if kind in ("COMMITTED", "REPLAYED") else None,
                                      snapshot_id="s" if kind in ("COMMITTED", "REPLAYED") else None, message="m"))
        assert set(body) == {"ok", "outcome", "run_intent_id", "history_id", "runtime_snapshot_id", "error_code", "message"}, kind
        assert body["message"] == "m" and body["outcome"] == kind
    assert ri.STATUS["FAILED"] == 409 and ri.STATUS["COMMITTED"] == 200 and ri.STATUS["UNAVAILABLE"] == 503


def test_reason_mapping_is_a_pure_closed_set_of_reviewed_sentences():
    from app.services import run_intent_service as ri
    import app.runtime.model_execution as me
    typed = ri._safe_failure_reason("ENGINE_FAILED", me.ModelWorkerError("X", "F3_PERIOD_OVERFUNDING detail", None, None))
    assert "facility draw" in typed.lower() and "/opt" not in typed
    generic = ri._safe_failure_reason("ENGINE_FAILED", RuntimeError("anything /etc/passwd"))
    assert generic == ri._safe_failure_reason("ENGINE_FAILED", None) and "passwd" not in generic
    for code in ("ENGINE_TIMEOUT", "ADMISSION_REFUSED", "FINAL_CAS_CONFLICT", "FINANCIAL_REFUSED"):
        assert ri._safe_failure_reason(code, RuntimeError("leak /root")) == ri._CODE_REASONS[code] and "/root" not in ri._CODE_REASONS[code]


def test_concurrent_failures_never_mix_their_reasons_and_the_cache_stays_bounded(monkeypatch):
    from app.services import run_intent_service as ri
    from app.persistence.run_intent_repository import Reservation, RunIntentError
    import app.runtime.model_execution as me
    monkeypatch.setattr(ri, "_fail", lambda reservation, code: None)
    ri._FAILURE_REASONS.clear()
    errors = []

    def one(index):
        reservation = Reservation(f"res-{index:05d}", "RUNNING", 1, "n", "f", 0, None, None)
        exc = (me.ModelWorkerError("T", "SHL_MATURITY_RESIDUAL_FAILS_CLOSED " + "x" * 50, None, None) if index % 2 == 0
               else RuntimeError(f"leak-{index} /root/secret"))
        try:
            raise exc
        except Exception:
            ri.mark_failed(reservation, "ENGINE_FAILED")
        with ri._FAILURE_REASONS_LOCK:
            recorded = ri._FAILURE_REASONS.get(reservation.reservation_id)
        # either still cached (right reason for ITS parity) or already evicted by the bound; never another request's
        if recorded is not None:
            wants_shl = index % 2 == 0
            if ("shareholder loan" in recorded[1].lower()) != wants_shl or "leak-" in recorded[1]:
                errors.append((index, recorded))

    threads = [threading.Thread(target=lambda lo=lo: [one(i) for i in range(lo, lo + 100)]) for lo in range(0, 2400, 100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(ri._FAILURE_REASONS) <= ri._FAILURE_REASONS_MAX
    assert RunIntentError is not None
    ri._FAILURE_REASONS.clear()


def test_the_oldest_reason_is_evicted_first():
    from app.services import run_intent_service as ri
    from app.persistence.run_intent_repository import Reservation
    ri._FAILURE_REASONS.clear()
    original = ri._fail
    ri._fail = lambda reservation, code: None
    try:
        for i in range(ri._FAILURE_REASONS_MAX + 5):
            ri.mark_failed(Reservation(f"r{i}", "RUNNING", 1, "n", "f", 0, None, None), "ENGINE_TIMEOUT")
        assert len(ri._FAILURE_REASONS) == ri._FAILURE_REASONS_MAX
        assert "r0" not in ri._FAILURE_REASONS and f"r{ri._FAILURE_REASONS_MAX + 4}" in ri._FAILURE_REASONS
    finally:
        ri._fail = original
        ri._FAILURE_REASONS.clear()


def test_mark_failed_with_no_reservation_or_a_broken_reason_path_never_raises_into_the_response(monkeypatch):
    from app.services import run_intent_service as ri
    from app.persistence.run_intent_repository import Reservation
    assert ri.mark_failed(None, "ENGINE_FAILED") is None
    monkeypatch.setattr(ri, "_safe_failure_reason", lambda code, exc: (_ for _ in ()).throw(RuntimeError("reason path broke")))
    called = []
    monkeypatch.setattr(ri, "_fail", lambda reservation, code: called.append(code))
    ri.mark_failed(Reservation("x", "RUNNING", 1, "n", "f", 0, None, None), "ENGINE_FAILED")
    assert called == ["ENGINE_FAILED"], "the ledger transition still happens when the diagnostic path fails"
