"""RC-M — atomic, request-keyed project creation through the canonical creator (single-process view).

The request identity is committed by the SAME INSERT that creates the project row and is unique per user in the database; the project
is COMPLETE only inside the transaction that writes its seed lines.  Crashes are simulated at each step by failing the next write, so
what remains in the database is exactly what a dying worker would leave.  The cross-process proof is in
``tests/test_model_react_rcm_new_project_multiprocess_v1.py``.  Synthetic data only; no Run is started.
"""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from app.persistence import db
from app.persistence.projects_repository import find_project_by_create_request, list_project_records
from app.services import project_library_service as pls
from app.services import reference_seed_service as seed
from tests.test_model_react_rcm_new_project_v1 import BASE, OWNER, STRANGER, env  # noqa: F401  (fixture reuse)

RID, OTHER = "a" * 32, "b" * 32
KW = dict(template_source="generic_solar_reference", requested_name="Atomic One", capacity_mw=20.0, country_market="XA")


def _once(user=OWNER, rid=RID, **over):
    return seed.create_reference_seeded_project_once(user_id=user, create_request_id=rid, purpose="t", **{**KW, **over})


def _lines(project_id: str) -> tuple[int, int]:
    conn = sqlite3.connect(db.DB_PATH)
    try:
        return tuple(conn.execute(f"SELECT COUNT(*) FROM {t} WHERE project_id=?", (project_id,)).fetchone()[0]
                     for t in ("capex_sub_lines", "opex_sub_lines"))
    finally:
        conn.close()


def _boom(*_a, **_k):
    raise RuntimeError("worker died")


def _die_for(module, attr, user):
    """Fail ``module.attr`` only for ``user`` (shared reference reconciliation keeps working), as a dying worker would."""
    real = getattr(module, attr)

    def wrapper(*args, **kwargs):
        if user in [*map(str, args), *map(str, kwargs.values())]:
            raise RuntimeError("worker died")
        return real(*args, **kwargs)
    return wrapper


# ── identity ───────────────────────────────────────────────────────────────

def test_the_database_refuses_a_second_project_for_one_user_and_request(env):
    record, outcome = _once()
    assert outcome == "created" and record.replay_metadata["create_request"]["state"] == "COMPLETE"
    conn = sqlite3.connect(db.DB_PATH)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO projects (project_id, user_id, project_code, project_name, source_project_template, governance_state_json, "
                         "last_run_summary_json, replay_metadata_json, created_at, updated_at) VALUES ('x', ?, 'dup-code', 'd', 't', '{}', '{}', ?, 'n', 'n')",
                         (OWNER, '{"create_request": {"request_id": "%s"}}' % RID))
        conn.execute("INSERT INTO projects (project_id, user_id, project_code, project_name, source_project_template, governance_state_json, "
                     "last_run_summary_json, replay_metadata_json, created_at, updated_at) VALUES ('y', ?, 'ok-code', 'd', 't', '{}', '{}', ?, 'n', 'n')",
                     (STRANGER, '{"create_request": {"request_id": "%s"}}' % RID))      # another user: independent
        conn.execute("INSERT INTO projects (project_id, user_id, project_code, project_name, source_project_template, governance_state_json, "
                     "last_run_summary_json, replay_metadata_json, created_at, updated_at) VALUES ('z', ?, 'bad-json', 'd', 't', '{}', '{}', 'not json', 'n', 'n')",
                     (OWNER,))                                                              # malformed legacy metadata never breaks the index
        conn.commit()
    finally:
        conn.close()


def test_two_workers_that_both_saw_no_request_still_create_exactly_one_project(env, monkeypatch):
    """The window between "no request yet" and the INSERT is closed by the database, not by the check."""
    import threading

    pls.ensure_reference_models()
    real = pls._observe_create_request
    gate = threading.Barrier(2, timeout=30)
    first_look = threading.local()

    def blind_first_look(user_id, create_request):
        if not getattr(first_look, "done", False):
            first_look.done = True
            gate.wait()                                   # both workers have now looked and found nothing
            return None
        return real(user_id, create_request)

    monkeypatch.setattr(pls, "_observe_create_request", blind_first_look)
    real_name = pls._unique_project_name
    counter = iter(range(2, 100))

    def distinct_codes(user_id, base_name):               # the two workers pick DIFFERENT codes: only the request identity can fence them
        n = next(counter)
        return f"{base_name} {n}", f"atomic-one-{n}"

    monkeypatch.setattr(pls, "_unique_project_name", distinct_codes)
    results, errors = [], []

    def worker():
        try:
            results.append(_once())
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    [t.start() for t in threads]
    [t.join(60) for t in threads]
    assert not errors, errors
    assert sorted(outcome for _r, outcome in results) in (["created", "in_progress"], ["created", "replayed"])
    assert len({r.project_id for r, _o in results}) == 1
    assert len(list_project_records(user_id=OWNER, include_archived=True)) == 1


def test_a_second_call_replays_and_the_same_id_with_other_inputs_conflicts(env):
    first, _ = _once()
    again, outcome = _once()
    assert outcome == "replayed" and again.project_id == first.project_id
    with pytest.raises(pls.CreateRequestConflict):
        _once(requested_name="Another name")
    with pytest.raises(pls.CreateRequestConflict):
        _once(capacity_mw=21.0)
    assert len([r for r in list_project_records(user_id=OWNER, include_archived=True)]) == 1


def test_users_are_independent_for_the_same_request_id(env):
    mine, _ = _once(user=OWNER)
    theirs, outcome = _once(user=STRANGER)
    assert outcome == "created" and mine.project_id != theirs.project_id
    assert find_project_by_create_request(OWNER, RID).project_id == mine.project_id
    assert find_project_by_create_request("nobody", RID) is None


def test_the_legacy_unkeyed_path_is_unchanged_and_twin_seeds_are_identical(env):
    from app.persistence.workspace_repository import get_workspace_state

    plain = seed.create_reference_seeded_project(user_id=OWNER, **KW)
    keyed, _ = _once(user=STRANGER)
    assert "create_request" not in (plain.replay_metadata or {}) and keyed.replay_metadata["create_request"]["state"] == "COMPLETE"
    a = get_workspace_state(OWNER, plain.project_id).draft_snapshot
    b = get_workspace_state(STRANGER, keyed.project_id).draft_snapshot
    volatile = {"project_name", "active_project", "_reference_seed_profile"}
    assert {k: v for k, v in a.items() if k not in volatile} == {k: v for k, v in b.items() if k not in volatile}
    assert _lines(plain.project_id) == _lines(keyed.project_id) and all(_lines(keyed.project_id))


def test_creation_never_runs_the_model(env):
    from app.persistence.workspace_repository import get_workspace_state

    record, _ = _once()
    ws = get_workspace_state(OWNER, record.project_id)
    assert not ws.last_runtime_snapshot_id and not ws.last_runtime_summary


# ── crash simulation: what a dying worker leaves, and what a retry may do ──

@pytest.mark.parametrize("target,attr", [
    ("pls", "save_workspace_state"),           # row inserted, no workspace yet
    ("pls", "get_or_create_base_case_scenario"),
    ("seed", "update_project_record"),         # workspace and scenario exist, seed snapshot not written
    ("seed", "save_workspace_state"),
    ("seed", "create_capex_line"),             # inside the seed-lines transaction
    ("seed", "create_opex_line"),
])
def test_a_worker_dying_at_any_step_leaves_one_creating_project_that_a_retry_never_duplicates(env, monkeypatch, target, attr):
    pls.ensure_reference_models()                                       # the shared references exist before the worker "dies"
    with pytest.MonkeyPatch.context() as crash:                         # a local patch: the env fixture's own patches stay in force
        module = pls if target == "pls" else seed
        crash.setattr(module, attr, _boom if attr.endswith("_line") else _die_for(module, attr, OWNER))
        with pytest.raises(RuntimeError):
            _once()
    rows = list_project_records(user_id=OWNER, include_archived=True)
    assert len(rows) == 1 and rows[0].replay_metadata["create_request"]["state"] == "CREATING"
    assert _lines(rows[0].project_id) == (0, 0)                                  # the seed lines are all-or-nothing: none landed
    retry, outcome = _once()
    assert outcome == "in_progress" and retry.project_id == rows[0].project_id
    assert len(list_project_records(user_id=OWNER, include_archived=True)) == 1          # a retry within the lease writes nothing


def test_an_interrupted_create_is_archived_after_the_lease_and_its_id_stays_consumed(env, monkeypatch):
    with pytest.MonkeyPatch.context() as crash:
        crash.setattr(seed, "create_opex_line", _boom)
        with pytest.raises(RuntimeError):
            _once()
    monkeypatch.setattr(pls, "CREATE_INCOMPLETE_LEASE_SECONDS", 0)
    record, outcome = _once()
    assert outcome == "abandoned" and record.archived is True and record.replay_metadata["create_request"]["state"] == "ABANDONED"
    again, outcome = _once()
    assert outcome == "abandoned" and again.project_id == record.project_id
    assert len(list_project_records(user_id=OWNER, include_archived=True)) == 1          # the id never produces a second project
    fresh, outcome = _once(rid=OTHER)
    assert outcome == "created" and fresh.project_id != record.project_id                 # a NEW id is a deliberate new create


def test_a_complete_project_cannot_be_abandoned(env, monkeypatch):
    first, _ = _once()
    monkeypatch.setattr(pls, "CREATE_INCOMPLETE_LEASE_SECONDS", 0)
    again, outcome = _once()
    assert outcome == "replayed" and again.archived is False


def test_the_complete_flag_is_refused_for_an_abandoned_project_and_its_seed_rolls_back(env, monkeypatch):
    """A slow worker finishing after another process abandoned the request must not complete an archived project."""
    from app.persistence import projects_repository as repo

    real = seed.create_opex_line

    def abandon_then_continue(cur, **kwargs):
        monkeypatch.setattr(pls, "CREATE_INCOMPLETE_LEASE_SECONDS", 0)
        conn = sqlite3.connect(db.DB_PATH, timeout=1)                        # a second connection: the abandon cannot see our open
        try:                                                                  # transaction and, with BEGIN IMMEDIATE, must wait or fail
            conn.execute("UPDATE projects SET archived=1, replay_metadata_json=json_set(replay_metadata_json,'$.create_request.state','ABANDONED') "
                         "WHERE json_extract(replay_metadata_json,'$.create_request.request_id')=?", (RID,))
            conn.commit()
            raise AssertionError("the abandon wrote while the seed transaction was open")
        except sqlite3.OperationalError:
            pass                                                              # locked out, as required
        finally:
            conn.close()
        return real(cur, **kwargs)

    monkeypatch.setattr(seed, "create_opex_line", abandon_then_continue)
    record, outcome = _once()
    assert outcome == "created" and record.replay_metadata["create_request"]["state"] == "COMPLETE"
    assert repo.find_project_by_create_request(OWNER, RID).archived is False


# ── adapter reaction to each outcome ───────────────────────────────────────

def _post(env, opts, **over):
    return env.client.post(f"{BASE}/create", json=env.body(opts, **over))


def test_the_adapter_maps_every_outcome_and_never_creates_on_a_retry(env, monkeypatch):
    opts = env.options()
    first = _post(env, opts).json()
    assert first["ok"] and first["replayed"] is False
    again = _post(env, opts).json()
    assert again["replayed"] is True and again["project"]["code"] == first["project"]["code"]
    status = env.client.get(f"{BASE}/status", params={"request_id": opts["request_id"]}).json()
    assert status["created"] is True and status["conclusive"] is True
    conflict = _post(env, opts, capacity_mw=33.0)
    assert conflict.status_code == 409 and conflict.json()["code"] == "REQUEST_ID_REUSED"
    assert len(env.mine()) == 1


def test_an_interrupted_request_is_unknown_then_consumed_in_the_adapter(env, monkeypatch):
    opts = env.options()
    with pytest.MonkeyPatch.context() as crash:
        crash.setattr(seed, "create_opex_line", _boom)
        assert _post(env, opts).status_code == 500
    pending = _post(env, opts)
    assert pending.status_code == 503 and pending.json()["code"] == "CREATE_IN_FLIGHT_OR_UNKNOWN"
    assert env.client.get(f"{BASE}/status", params={"request_id": opts["request_id"]}).json() == {
        "ok": True, "created": False, "conclusive": False, "state": "IN_FLIGHT_OR_UNKNOWN"}
    monkeypatch.setattr(pls, "CREATE_INCOMPLETE_LEASE_SECONDS", 0)
    consumed = _post(env, opts)
    assert consumed.status_code == 503 and consumed.json()["code"] == "REQUEST_ID_CONSUMED"
    assert env.client.get(f"{BASE}/status", params={"request_id": opts["request_id"]}).json()["state"] == "ABANDONED"
    assert len(env.mine()) == 1


def test_the_demo_budget_reads_durable_project_rows(env, monkeypatch):
    import app.v2.react_new_project as adapter
    from app.auth import DEMO_RATE_LIMITS

    monkeypatch.setattr(adapter, "resolve_request_session",
                        lambda request: SimpleNamespace(user_id="demo_atomic_budget", username="demo", is_demo=True))
    monkeypatch.setattr(adapter, "check_demo_rate_limit", lambda *a, **k: (True, 0))       # the in-process limiter is not the proof here
    limit = DEMO_RATE_LIMITS["project_create"][0]
    for n in range(limit):
        _once(user="demo_atomic_budget", rid=f"{n:032x}", requested_name=f"Demo {n}")
    blocked = _post(env, env.options())
    assert blocked.status_code == 429 and blocked.json()["code"] == "RATE_LIMITED" and blocked.json()["retry_after"] > 0
    replay = _post(env, {"request_id": f"{0:032x}", "csrf_token": env.options()["csrf_token"]})   # a bad token is refused before any budget
    assert replay.status_code == 403


def test_release_closed_and_unknown_technologies_commit_nothing(env):
    for technology in ("storage", "unknown"):
        opts = env.options()
        assert _post(env, opts, technology=technology).status_code == 422
        assert find_project_by_create_request(OWNER, opts["request_id"]) is None
    assert env.mine() == []
