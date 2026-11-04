"""R18 — every canonical reference clone/create is atomic: seed lines and the COMPLETE flag land together or not at all.

Synthetic disposable data only.  The unkeyed entry points (library clone, legacy /projects/create) used to leave a live,
Run-eligible, partially seeded project when the seed was interrupted.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.persistence import db
from app.persistence.project_lifecycle_repository import LifecycleError, require_write_cursor
from app.persistence.projects_repository import list_project_records
from app.services import project_library_service as pls
from app.services import reference_seed_service as seed

U = "r18-user"
VERTICALS = ["generic_solar_reference", "generic_wind_reference", "generic_data_center_reference", "generic_ev_charging_reference"]


class Injected(RuntimeError):
    pass


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "r18.db"))
    db.init_db()
    pls.ensure_reference_models()
    return None


def _counts(pid):
    c = sqlite3.connect(db.DB_PATH)
    try:
        cx = c.execute("SELECT COUNT(*), COALESCE(SUM(amount_keur),0) FROM capex_sub_lines WHERE project_id=?", (pid,)).fetchone()
        ox = c.execute("SELECT COUNT(*), COALESCE(SUM(amount_keur),0) FROM opex_sub_lines WHERE project_id=?", (pid,)).fetchone()
        return cx[0], round(cx[1], 6), ox[0], round(ox[1], 6)
    finally:
        c.close()


def _mine():
    return [p for p in list_project_records(user_id=U, include_archived=True)]


def _state(p):
    return ((p.replay_metadata or {}).get("create_request") or {}).get("state")


def _writable(p):
    c = db.get_connection()
    try:
        require_write_cursor(c.cursor(), U, p.project_id)
        return True
    except LifecycleError:
        return False
    finally:
        c.close()


def _fail_on(monkeypatch, which, nth):
    real = getattr(seed, which)
    calls = {"n": 0}

    def flaky(cur, **kw):
        calls["n"] += 1
        if calls["n"] == nth:
            raise Injected(f"{which} #{nth}")
        return real(cur, **kw)

    monkeypatch.setattr(seed, which, flaky)
    return calls


def _total_calls(monkeypatch, which, template):
    """How many lines the success path inserts (probe on a throwaway user)."""
    real = getattr(seed, which)
    n = {"c": 0}

    def counting(cur, **kw):
        n["c"] += 1
        return real(cur, **kw)

    monkeypatch.setattr(seed, which, counting)
    seed.create_reference_seeded_project(user_id="r18-probe", template_source=template, requested_name="Probe", capacity_mw=20.0)
    monkeypatch.setattr(seed, which, real)
    return n["c"]


@pytest.mark.parametrize("template", VERTICALS)
@pytest.mark.parametrize("which, position", [("create_capex_line", "first"), ("create_capex_line", "middle"),
                                              ("create_opex_line", "first"), ("create_opex_line", "last")])
def test_an_interrupted_unkeyed_seed_leaves_no_live_partial_project(world, monkeypatch, template, which, position):
    total = _total_calls(monkeypatch, which, template)
    nth = {"first": 1, "middle": max(2, total // 2), "last": total}[position]
    _fail_on(monkeypatch, which, nth)
    with pytest.raises(Injected):
        seed.create_reference_seeded_project(user_id=U, template_source=template, requested_name="Interrupted", capacity_mw=20.0)
    projects = _mine()
    for p in projects:
        assert _state(p) == "CREATING"          # never COMPLETE
        assert not _writable(p)                 # not Run/edit-eligible
        assert _counts(p.project_id)[::2] == (0, 0)   # seed lines rolled back with the flag
        assert (p.replay_metadata or {}).get("create_request", {}).get("request_id", "").startswith("server-")


@pytest.mark.parametrize("template", VERTICALS)
def test_the_unkeyed_success_path_is_complete_and_equals_the_keyed_economics(world, template):
    a = seed.create_reference_seeded_project(user_id=U, template_source=template, requested_name="Unkeyed", capacity_mw=20.0)
    b, outcome = seed.create_reference_seeded_project_once(user_id=U, template_source=template, requested_name="Keyed",
                                                           capacity_mw=20.0, create_request_id="k" * 32, purpose="r18")
    assert outcome == "created"
    # a finished UNKEYED create carries no create_request marker (byte-for-byte the legacy shape: no replay key to collide on a row copy);
    # a finished KEYED create keeps its COMPLETE marker
    assert "create_request" not in (a.replay_metadata or {}) and _state(b) == "COMPLETE" and _writable(a) and _writable(b)
    assert _counts(a.project_id) == _counts(b.project_id) and _counts(a.project_id)[0] > 0 and _counts(a.project_id)[2] > 0
    assert (a.baseline_snapshot or {}).get("opex_y1_keur") == (b.baseline_snapshot or {}).get("opex_y1_keur")
    assert (a.baseline_snapshot or {}).get("total_capex_keur") == (b.baseline_snapshot or {}).get("total_capex_keur")


def _client():
    import main_web
    from app.auth import COOKIE_NAME, create_session_token
    c = TestClient(main_web.app, raise_server_exceptions=False)
    c.cookies.set(COOKIE_NAME, create_session_token(user_id=U, username="admin"))
    return c


@pytest.mark.parametrize("template", VERTICALS)
def test_the_library_clone_route_is_atomic(world, monkeypatch, template):
    from app.persistence.projects_repository import get_reference_by_template_source
    from tests.run_clone_csrf import post_valid_csrf
    ref = get_reference_by_template_source(template)
    _fail_on(monkeypatch, "create_opex_line", 3)
    r = post_valid_csrf(_client(), f"/library/clone/{ref.project_id}", data={"requested_name": "R18 clone"}, follow_redirects=False)
    assert r.status_code >= 400, r.status_code           # no misleading success
    for p in _mine():
        assert _state(p) == "CREATING" and not _writable(p) and _counts(p.project_id)[::2] == (0, 0)


@pytest.mark.parametrize("template", VERTICALS)
def test_the_legacy_projects_create_route_is_atomic(world, monkeypatch, template):
    _fail_on(monkeypatch, "create_opex_line", 3)
    r = _client().post("/projects/create", data={
        "project_name": "R18 legacy", "project_type": template.replace("generic_", "").replace("_reference", ""),
        "template_source": template, "capacity_mw": "20"}, follow_redirects=False)
    assert r.status_code >= 400 or not [p for p in _mine() if _state(p) == "COMPLETE"], r.status_code
    for p in _mine():
        assert _state(p) in ("CREATING", None)
        if _state(p) == "CREATING":
            assert not _writable(p) and _counts(p.project_id)[::2] == (0, 0)


# ── full canonical engine Run on a completely seeded control Working Copy: the unkeyed (atomic) path equals the keyed path ──
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: E402,F401  (fixtures of the canonical Run harness)


@pytest.mark.parametrize("template", VERTICALS)
def test_a_full_canonical_run_on_the_unkeyed_atomic_clone_equals_the_keyed_clone(env, template):
    from tests.test_model_financing_f2 import run
    a = seed.create_reference_seeded_project(user_id="decision-user", requested_name="Parity unkeyed", template_source=template, capacity_mw=16)
    b, outcome = seed.create_reference_seeded_project_once(user_id="decision-user", requested_name="Parity keyed", template_source=template,
                                                           capacity_mw=16, create_request_id="p" * 32, purpose="r18-parity")
    assert outcome == "created"
    _, ra = run(env, a)
    _, rb = run(env, b)
    numbers = lambda result: {k: v for k, v in dict(result.runtime_summary).items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    na, nb = numbers(ra), numbers(rb)
    assert na and na == nb, {k: (na.get(k), nb.get(k)) for k in set(na) | set(nb) if na.get(k) != nb.get(k)}      # exact: same inputs, same deterministic engine
    assert {"total_capex_keur", "total_opex_keur", "total_revenue_keur"} <= set(na)
