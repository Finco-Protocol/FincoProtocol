"""RC-M Lane A — the durable request-id fence of the React New Project create (single-process view).

The cross-process proof (separate OS processes, simultaneous POSTs, a crash before the claim is finished) is in
``tests/test_model_react_rcm_new_project_multiprocess_v1.py``.  Here: the claim ledger's own contract and the handler's
reaction to every claim state.  Synthetic users only; no engine Run is started.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app.v2 import react_request_claims as claims
from tests.test_model_react_rcm_new_project_v1 import BASE, OWNER, STRANGER, env  # noqa: F401  (fixture reuse)

PURPOSE = "react-new-project-v1"
RID = "a" * 32


@pytest.fixture()
def counted(monkeypatch):
    """Counts calls of the canonical creator while still delegating to it."""
    import app.services.reference_seed_service as seed

    real, calls = seed.create_reference_seeded_project, []

    def wrapper(**kw):
        calls.append(kw)
        return real(**kw)

    monkeypatch.setattr(seed, "create_reference_seeded_project", wrapper)
    return calls


# ── ledger contract ────────────────────────────────────────────────────────

def test_exactly_one_of_many_concurrent_claims_wins(env):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: claims.claim(OWNER, RID, PURPOSE), range(16)))
    assert sum(r.won for r in results) == 1 and {r.state for r in results} == {claims.CLAIMED}


def test_a_claim_is_scoped_to_user_request_and_purpose(env):
    assert claims.claim(OWNER, RID, PURPOSE).won
    assert claims.claim(STRANGER, RID, PURPOSE).won                 # another user's identical id is independent
    assert claims.claim(OWNER, RID, "another-purpose").won          # so is another purpose
    assert not claims.claim(OWNER, RID, PURPOSE).won
    assert claims.lookup("nobody", RID, PURPOSE) is None


def test_a_terminal_claim_is_never_rewritten_or_reclaimed(env):
    assert claims.claim(OWNER, RID, PURPOSE).won
    assert claims.finish(OWNER, RID, PURPOSE, "P-1") is True
    assert claims.finish(OWNER, RID, PURPOSE, "P-2") is False and claims.fail(OWNER, RID, PURPOSE, "X") is False
    again = claims.claim(OWNER, RID, PURPOSE)
    assert not again.won and again.state == claims.DONE and again.project_code == "P-1"
    other = "b" * 32
    assert claims.claim(OWNER, other, PURPOSE).won and claims.fail(OWNER, other, PURPOSE, "CREATE_REFUSED")
    assert claims.finish(OWNER, other, PURPOSE, "P-3") is False
    assert claims.lookup(OWNER, other, PURPOSE).state == claims.FAILED


def test_an_abandoned_claim_stays_claimed_for_ever(env):
    assert claims.claim(OWNER, RID, PURPOSE, now=1.0).won                   # the claimant "crashes": never finished
    later = claims.claim(OWNER, RID, PURPOSE, now=10_000_000.0)
    assert not later.won and later.state == claims.CLAIMED                  # no expiry, no takeover


def test_the_durable_budget_is_atomic_and_rolls_with_the_window(env):
    budget = (3, 3600)
    won = [claims.claim("demo-x", f"{i:032x}", PURPOSE, rate_limit=budget, now=1000.0 + i).won for i in range(5)]
    assert won == [True, True, True, False, False]
    blocked = claims.claim("demo-x", "f" * 32, PURPOSE, rate_limit=budget, now=1100.0)
    assert blocked.rate_limited and 0 < blocked.retry_after <= 3600
    assert claims.claim("demo-x", "e" * 32, PURPOSE, rate_limit=budget, now=1000.0 + 3600 + 5).won      # window passed
    assert claims.claim("demo-y", "d" * 32, PURPOSE, rate_limit=budget, now=1100.0).won                  # per user


# ── handler reaction to each claim state ───────────────────────────────────

def _post(env, opts, **over):
    return env.client.post(f"{BASE}/create", json=env.body(opts, **over))


def test_a_crashed_claim_reports_unknown_and_creates_nothing(env, counted):
    opts = env.options()
    assert claims.claim(OWNER, opts["request_id"], PURPOSE).won            # another worker claimed, then died
    response = _post(env, opts)
    assert response.status_code == 503 and response.json()["code"] == "CREATE_IN_FLIGHT_OR_UNKNOWN"
    assert counted == [] and env.mine() == []
    status = env.client.get(f"{BASE}/status", params={"request_id": opts["request_id"]}).json()
    assert status == {"ok": True, "created": False, "conclusive": False, "state": "IN_FLIGHT_OR_UNKNOWN"}
    assert claims.lookup(OWNER, opts["request_id"], PURPOSE).state == claims.CLAIMED      # not overwritten


def test_a_replay_of_a_finished_request_returns_the_project_without_a_write(env, counted):
    opts = env.options()
    first = _post(env, opts).json()
    assert first["ok"] and first["idempotency_recorded"] is True and first["stamp_recorded"] is True and len(counted) == 1
    replay = _post(env, opts, name="Changed after a lost response", capacity_mw=999.0).json()
    assert replay["replayed"] is True and replay["project"]["code"] == first["project"]["code"] and len(counted) == 1
    assert len(env.mine()) == 1


def test_a_failed_request_id_is_consumed_and_never_retried(env, monkeypatch):
    import app.services.reference_seed_service as seed

    calls = []

    def boom(**kw):
        calls.append(kw)
        raise RuntimeError("partial write")

    monkeypatch.setattr(seed, "create_reference_seeded_project", boom)
    opts = env.options()
    assert _post(env, opts).status_code == 500
    again = _post(env, opts)
    assert again.status_code == 503 and again.json()["code"] == "REQUEST_ID_CONSUMED" and len(calls) == 1


def test_a_lost_finish_still_blocks_a_duplicate(env, counted, monkeypatch):
    """The project was created but the claim could not be finished: replays stay unknown, never a second project."""
    monkeypatch.setattr(claims, "finish", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db gone")))
    opts = env.options()
    first = _post(env, opts).json()
    assert first["ok"] and first["idempotency_recorded"] is False and len(counted) == 1
    replay = _post(env, opts)
    assert replay.status_code == 200 and replay.json()["replayed"] is True       # the stamp reconciles it
    assert len(counted) == 1 and len(env.mine()) == 1


def test_an_unreadable_fence_fails_closed_before_any_write(env, counted, monkeypatch):
    monkeypatch.setattr(claims, "lookup", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db gone")))
    response = _post(env, env.options())
    assert response.status_code == 503 and response.json()["code"] == "CREATE_UNAVAILABLE" and counted == []


def test_an_unclaimable_fence_fails_closed_before_any_write(env, counted, monkeypatch):
    monkeypatch.setattr(claims, "claim", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db gone")))
    response = _post(env, env.options())
    assert response.status_code == 503 and response.json()["code"] == "CREATE_UNAVAILABLE" and counted == [] and env.mine() == []


def test_a_refusal_before_the_claim_does_not_consume_the_request_id(env, counted):
    opts = env.options()
    bad = _post(env, opts, capacity_mw=-1)
    assert bad.status_code == 422 and claims.lookup(OWNER, opts["request_id"], PURPOSE) is None
    assert _post(env, opts).json()["ok"] and len(counted) == 1


def test_another_user_cannot_replay_or_observe_a_request(env, counted):
    opts = env.options()
    created = _post(env, opts).json()
    stolen = env.stranger.post(f"{BASE}/create", json=env.body(opts))              # owner's token is bound to the owner's session
    assert stolen.status_code == 403 and stolen.json()["code"] == "CSRF_INVALID"
    status = env.stranger.get(f"{BASE}/status", params={"request_id": opts["request_id"]}).json()
    assert status["created"] is False and "project" not in status and status["state"] == "NONE"
    assert created["ok"] and len(counted) == 1 and env.mine(STRANGER) == []


# ── demo budget ────────────────────────────────────────────────────────────

def _as_demo(monkeypatch, user_id="demo-fence-user"):
    import app.v2.react_new_project as np

    monkeypatch.setattr(np, "resolve_request_session",
                        lambda request: SimpleNamespace(user_id=user_id, username="demo", is_demo=True))


def test_the_demo_project_budget_is_enforced_inside_the_fence(env, counted, monkeypatch):
    import app.auth as auth

    _as_demo(monkeypatch)
    monkeypatch.setitem(auth.DEMO_RATE_LIMITS, "project_create", (2, 3600))
    monkeypatch.setattr(auth, "check_demo_rate_limit", lambda *a, **k: (True, 0))       # the in-process limiter is not the proof here
    import app.v2.react_new_project as np
    monkeypatch.setattr(np, "check_demo_rate_limit", lambda *a, **k: (True, 0))
    results = [_post(env, env.options()) for _ in range(3)]
    assert [r.status_code for r in results] == [200, 200, 429] and results[2].json()["code"] == "RATE_LIMITED"
    assert len(counted) == 2 and results[2].json()["retry_after"] > 0


def test_the_canonical_demo_limiter_still_applies_and_a_replay_costs_nothing(env, counted, monkeypatch):
    import app.v2.react_new_project as np

    _as_demo(monkeypatch)
    seen = []

    def limiter(user_id, op):
        seen.append((user_id, op))
        return (len(seen) <= 1), 30

    monkeypatch.setattr(np, "check_demo_rate_limit", limiter)
    opts = env.options()
    assert _post(env, opts).status_code == 200
    assert _post(env, opts).json()["replayed"] is True and len(seen) == 1            # replay never reaches the limiter
    blocked = _post(env, env.options())
    assert blocked.status_code == 429 and blocked.json() == {"ok": False, "code": "RATE_LIMITED", "retry_after": 30}
    assert len(counted) == 1


# ── reference and release-closed protection ────────────────────────────────

def test_release_closed_and_unknown_technologies_never_claim(env, counted):
    for technology in ("storage", "unknown"):
        opts = env.options()
        response = _post(env, opts, technology=technology)
        assert response.status_code == 422 and claims.lookup(OWNER, opts["request_id"], PURPOSE) is None
    assert counted == [] and env.mine() == []


def test_a_protected_reference_is_never_the_target_of_a_create(env, counted):
    from app.ui.protected_reference_service import is_protected_reference

    created = _post(env, env.options()).json()["project"]
    record = next(r for r in env.mine() if r.project_code == created["code"])
    assert not is_protected_reference(record)
