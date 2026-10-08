"""Staging Acceptance Correction A — scenario Last Run authority + Compare routing.

Real canonical runs through the V2 HTTP surface (no mocks of the engine).
"""
from __future__ import annotations

import re

import pytest


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    from app.persistence import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "staging-a.db"))
    db.init_db()
    yield


def _client_for(user_id="u-staging-a", template="generic_solar_reference",
                capacity=64.0, name="Staging A Project"):
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project
    from fastapi.testclient import TestClient
    import main_web

    record = create_reference_seeded_project(
        user_id=user_id, template_source=template,
        requested_name=name, capacity_mw=capacity)
    cookies = {COOKIE_NAME: create_session_token(user_id=user_id, username="admin")}
    return TestClient(main_web.app, raise_server_exceptions=True), cookies, record


def _tokens(client, cookies, code):
    page = client.get(f"/v2/workbook?project={code}", cookies=cookies)
    h = re.search(r'name="content_hash" value="([^"]+)"', page.text).group(1)
    v = re.search(r'name="workbook_version" value="([^"]+)"', page.text).group(1)
    return page, h, v


def _run(client, cookies, code):
    _, h, v = _tokens(client, cookies, code)
    r = client.post("/v2/workbook/run",
                    data={"project": code, "content_hash": h, "workbook_version": v},
                    cookies=cookies, headers={"HX-Request": "true"})
    assert r.status_code == 200
    return r


def _state(client, cookies, code) -> str:
    page = client.get(f"/v2/workbook?project={code}", cookies=cookies).text
    return re.search(r'data-testid="toolbar-runtime-state"[^>]*>([^<]+)<', page).group(1).strip()


def _edit_p50(client, cookies, code, value):
    _, h, v = _tokens(client, cookies, code)
    r = client.post("/v2/workbook/inputs-slice1/update",
                    data={"field_id": "project_setup.technical.p50_hours",
                          "value": str(value), "project": code,
                          "workbook_version": v, "content_hash": h},
                    cookies=cookies, headers={"HX-Request": "true"})
    assert r.status_code == 200


def _scenarios(user_id, project_id):
    from app.persistence.scenarios_repository import list_scenarios
    return {s.scenario_name: s for s in list_scenarios(user_id=user_id, project_id=project_id)}


def _select(client, cookies, code, scenario_id):
    r = client.post("/v2/workbook/scenarios/select",
                    data={"project": code, "scenario_id": scenario_id},
                    cookies=cookies, headers={"HX-Request": "true"})
    assert r.status_code == 200


def _base_id(user_id, project_id):
    return next(s.scenario_id for s in _scenarios(user_id, project_id).values()
                if s.is_base_case)


def _history_count(user_id, project_id):
    from app.persistence.run_history_repository import get_run_history
    return len(get_run_history(user_id, project_id))


class TestScenarioLastRunAuthority:
    def test_scenario_switch_restores_each_scenarios_own_last_run(self, seeded_db):
        from app.persistence.workspace_repository import get_workspace_state

        client, cookies, record = _client_for()
        code, uid, pid = record.project_code, record.user_id, record.project_id

        _run(client, cookies, code)                                   # Base: Run A
        assert _state(client, cookies, code) == "Current"
        base_snapshot_id = get_workspace_state(uid, pid).last_runtime_snapshot_id
        assert base_snapshot_id

        client.post("/v2/workbook/scenarios/create",
                    data={"project": code, "scenario_name": "Scenario X"},
                    cookies=cookies, headers={"HX-Request": "true"})
        x_id = _scenarios(uid, pid)["Scenario X"].scenario_id
        base_id = _base_id(uid, pid)
        assert get_workspace_state(uid, pid).active_scenario_id == x_id
        assert _state(client, cookies, code) == "Not run"             # X never run
        _run(client, cookies, code)                                   # Scenario X: Run B
        x_snapshot_id = get_workspace_state(uid, pid).last_runtime_snapshot_id
        assert x_snapshot_id != base_snapshot_id
        history_before = _history_count(uid, pid)
        assert history_before == 2

        _select(client, cookies, code, base_id)                       # back to Base
        ws = get_workspace_state(uid, pid)
        assert ws.last_runtime_snapshot_id == base_snapshot_id       # Run A, not B
        # provenance is the immutable history row's (pre-scenario Base == None)
        assert ws.last_runtime_scenario_id is None
        assert _state(client, cookies, code) == "Current"
        page = client.get(f"/v2/workbook?project={code}", cookies=cookies).text
        assert "Never run" not in page

        _select(client, cookies, code, x_id)                          # back to X
        assert get_workspace_state(uid, pid).last_runtime_snapshot_id == x_snapshot_id
        assert _state(client, cookies, code) == "Current"

        # selection never mutates Run History
        assert _history_count(uid, pid) == history_before

    def test_working_copy_edit_is_stale_and_restore_never_fakes_current(self, seeded_db):
        from app.persistence.workspace_repository import get_workspace_state

        client, cookies, record = _client_for(user_id="u-staging-a2")
        code, uid, pid = record.project_code, record.user_id, record.project_id
        _run(client, cookies, code)
        client.post("/v2/workbook/scenarios/create",
                    data={"project": code, "scenario_name": "Scenario X"},
                    cookies=cookies, headers={"HX-Request": "true"})
        x_id = _scenarios(uid, pid)["Scenario X"].scenario_id
        base_id = _base_id(uid, pid)
        _run(client, cookies, code)
        assert _state(client, cookies, code) == "Current"

        _select(client, cookies, code, base_id)
        _edit_p50(client, cookies, code, 2300)                        # edit Base, no Run
        assert _state(client, cookies, code) == "Stale"

        _select(client, cookies, code, x_id)
        # Scenario X is an overlay on the shared Working Copy: its recorded run
        # no longer matches the current composite identity => STALE, never CURRENT
        # (and never NOT RUN: its own evidence is still restored).
        assert _state(client, cookies, code) == "Stale"
        assert get_workspace_state(uid, pid).last_runtime_snapshot_id is not None
        _select(client, cookies, code, base_id)
        assert _state(client, cookies, code) == "Stale"

    def test_scenario_without_run_is_not_run_and_other_evidence_is_not_copied(self, seeded_db):
        from app.persistence.workspace_repository import get_workspace_state

        client, cookies, record = _client_for(user_id="u-staging-a3")
        code, uid, pid = record.project_code, record.user_id, record.project_id
        _run(client, cookies, code)
        client.post("/v2/workbook/scenarios/create",
                    data={"project": code, "scenario_name": "Never Run"},
                    cookies=cookies, headers={"HX-Request": "true"})
        ws = get_workspace_state(uid, pid)
        assert ws.last_runtime_snapshot_id is None          # Base's run not copied
        assert _state(client, cookies, code) == "Not run"


class TestCompareRouting:
    def test_form_posts_to_canonical_route_and_never_raw_json(self, seeded_db):
        client, cookies, record = _client_for(user_id="u-staging-a4")
        page = client.get("/v2/compare-projects", cookies=cookies)
        assert page.status_code == 200
        assert 'action="/v2/compare-projects"' in page.text
        assert 'action="/compare-projects"' not in page.text
        # picker lists the user's accessible project
        assert f'data-testid="ds-pick-{record.project_code}"' in page.text

    def test_two_selected_projects_render_the_matrix_via_picker(self, seeded_db):
        client, cookies, r1 = _client_for(user_id="u-staging-a5", name="Alpha")
        from app.services.reference_seed_service import create_reference_seeded_project
        r2 = create_reference_seeded_project(
            user_id="u-staging-a5", template_source="generic_wind_reference",
            requested_name="Beta", capacity_mw=50.0)
        _run(client, cookies, r1.project_code)
        resp = client.get(
            f"/v2/compare-projects?pick={r1.project_code}&pick={r2.project_code}",
            cookies=cookies)
        assert resp.status_code == 200
        assert 'data-testid="ds-cross-table"' in resp.text
        assert f'data-testid="ds-col-{r1.project_code}"' in resp.text
        assert f'data-testid="ds-col-{r2.project_code}"' in resp.text
        assert "NO CANONICAL RUN" in resp.text      # r2 never run: unavailable

    def test_unknown_project_is_a_friendly_page_not_json(self, seeded_db):
        client, cookies, _ = _client_for(user_id="u-staging-a6")
        resp = client.get("/v2/compare-projects?projects=does-not-exist", cookies=cookies)
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert '{"detail"' not in resp.text
        assert 'data-testid="ds-unresolved"' in resp.text
        assert "does-not-exist" in resp.text


# ── Correction A: transactional + fail-closed restore authority ──────────────

def _two_scenario_project(user_id):
    client, cookies, record = _client_for(user_id=user_id)
    code, uid, pid = record.project_code, record.user_id, record.project_id
    _run(client, cookies, code)                                   # pre-scenario Base run
    client.post("/v2/workbook/scenarios/create",
                data={"project": code, "scenario_name": "Scenario X"},
                cookies=cookies, headers={"HX-Request": "true"})
    x_id = _scenarios(uid, pid)["Scenario X"].scenario_id
    return client, cookies, record, x_id, _base_id(uid, pid)


def _history_rows(uid, pid, scenario_id):
    from app.persistence.db import get_cursor
    with get_cursor() as cur:
        cur.execute("SELECT history_id, runtime_snapshot_id FROM model_run_history "
                    "WHERE user_id=? AND project_id=? AND last_runtime_scenario_id=? "
                    "ORDER BY ran_at DESC, history_id DESC", (uid, pid, scenario_id))
        return [tuple(r) for r in cur.fetchall()]


class TestRestoreAuthorityHardening:
    def test_malformed_newest_history_row_never_falls_back_to_an_older_run(self, seeded_db):
        from app.persistence.db import get_cursor
        from app.persistence.workspace_repository import get_workspace_state

        client, cookies, record, x_id, base_id = _two_scenario_project("u-hard-d")
        code, uid, pid = record.project_code, record.user_id, record.project_id
        _run(client, cookies, code)                                # X: older valid run
        _run(client, cookies, code)                                # X: newest run
        rows = _history_rows(uid, pid, x_id)
        assert len(rows) == 2
        newest_id, _ = rows[0]
        _select(client, cookies, code, base_id)
        before = get_workspace_state(uid, pid)
        with get_cursor() as cur:                                  # corrupt ONLY the newest row
            cur.execute("UPDATE model_run_history SET runtime_summary_json='{not json' "
                        "WHERE history_id=?", (newest_id,))

        resp = client.post("/v2/workbook/scenarios/select",
                           data={"project": code, "scenario_id": x_id},
                           cookies=cookies, headers={"HX-Request": "true"})
        assert resp.status_code == 409
        assert 'data-testid="scenario-history-unreadable"' in resp.text
        assert '{"detail"' not in resp.text and "Traceback" not in resp.text
        after = get_workspace_state(uid, pid)
        # nothing written: still Base, and the older valid X run was NOT promoted
        assert after.active_scenario_id == base_id
        assert after.last_runtime_snapshot_id == before.last_runtime_snapshot_id
        assert after.last_runtime_snapshot_id != rows[1][1]
        assert after.updated_at == before.updated_at

    def test_restore_assembles_identity_inside_an_exclusive_transaction(
            self, seeded_db, monkeypatch):
        import sqlite3

        from app.persistence import db
        from app.persistence.scenarios_repository import select_scenario
        import app.workbook.workbook_identity as wi

        client, cookies, record, x_id, base_id = _two_scenario_project("u-hard-e")
        code, uid, pid = record.project_code, record.user_id, record.project_id
        _run(client, cookies, code)                                # X has a run to restore
        _select(client, cookies, code, base_id)

        real = wi.assemble_transactional
        probe = {"calls": 0, "writer_blocked": None}

        def spy(*args, **kwargs):
            probe["calls"] += 1
            other = sqlite3.connect(db.DB_PATH, timeout=0.2, isolation_level=None)
            try:
                other.execute("UPDATE workspace_states SET dirty=dirty")   # any writer
                probe["writer_blocked"] = False
            except sqlite3.OperationalError as exc:
                probe["writer_blocked"] = "locked" in str(exc).lower()
            finally:
                other.close()
            return real(*args, **kwargs)

        monkeypatch.setattr(wi, "assemble_transactional", spy)
        assert select_scenario(uid, pid, x_id) is True
        assert probe["calls"] >= 1
        assert probe["writer_blocked"] is True      # the lock was held while assembling

    def test_pre_transaction_state_is_never_authority(self, seeded_db, monkeypatch):
        import app.persistence.repository as repo
        import app.persistence.scenarios_repository as sr
        from app.persistence.workspace_repository import get_workspace_state

        client, cookies, record, x_id, base_id = _two_scenario_project("u-hard-e2")
        code, uid, pid = record.project_code, record.user_id, record.project_id
        _run(client, cookies, code)                                # X run (draft D1)
        _select(client, cookies, code, base_id)
        stale_view = get_workspace_state(uid, pid)                 # snapshot BEFORE the edit
        _edit_p50(client, cookies, code, 2300)                     # newer committed state

        def forbidden(*a, **k):
            raise AssertionError("pre-transaction read used as authority")

        with monkeypatch.context() as scoped:
            scoped.setattr(repo, "get_workspace_state", lambda *a, **k: stale_view)
            scoped.setattr(sr, "get_scenario", forbidden)
            assert sr.select_scenario(uid, pid, x_id) is True
        ws = get_workspace_state(uid, pid)
        # decided from the CURRENT (edited) draft inside the transaction: STALE
        assert ws.dirty is True
        assert ws.last_runtime_snapshot is None or ws.last_runtime_snapshot == {}
        assert _state(client, cookies, code) == "Stale"

    def test_select_rejects_foreign_or_archived_scenario_inside_the_transaction(
            self, seeded_db):
        from app.persistence.scenarios_repository import select_scenario

        client, cookies, record, x_id, base_id = _two_scenario_project("u-hard-e3")
        assert select_scenario("someone-else", record.project_id, x_id) is False
        assert select_scenario(record.user_id, "wrong-project", x_id) is False

    def test_pre_scenario_base_run_keeps_its_immutable_identity(self, seeded_db):
        import json

        from app.persistence.db import get_cursor
        from app.persistence.workspace_repository import get_workspace_state
        from app.ui.dirty_state import STALE_SCENARIO_LABEL

        client, cookies, record, x_id, base_id = _two_scenario_project("u-hard-f")
        code, uid, pid = record.project_code, record.user_id, record.project_id
        with get_cursor() as cur:
            cur.execute("SELECT last_runtime_scenario_id, composite_hash, "
                        "last_runtime_identity_json, runtime_snapshot_id "
                        "FROM model_run_history WHERE user_id=? AND project_id=?", (uid, pid))
            hist = cur.fetchone()
        assert hist["last_runtime_scenario_id"] is None        # pre-scenario Base(None)

        _run(client, cookies, code)                            # run X, then back to Base
        _select(client, cookies, code, base_id)
        ws = get_workspace_state(uid, pid)
        identity = ws.last_runtime_identity
        # outer provenance == immutable history == inner run-bound identity
        assert ws.last_runtime_scenario_id is None
        assert ws.last_runtime_composite_hash == hist["composite_hash"]
        assert ws.last_runtime_composite_hash == identity["composite_hash"]
        assert ws.last_runtime_snapshot_id == hist["runtime_snapshot_id"]
        assert identity == json.loads(hist["last_runtime_identity_json"])
        assert base_id not in json.dumps(identity)             # no invented scenario id
        # …yet presentation resolves CURRENT because equivalence is positively proven
        assert _state(client, cookies, code) == "Current"
        page = client.get(f"/v2/workbook?project={code}", cookies=cookies).text
        assert STALE_SCENARIO_LABEL not in page

    def test_base_equivalence_is_base_only_and_requires_proof(self, seeded_db):
        import json
        from types import SimpleNamespace

        from app.persistence.db import get_cursor
        from app.persistence.scenarios_repository import get_scenario
        from app.persistence.workspace_repository import get_workspace_state
        from app.workbook.runtime_authority import pre_scenario_base_equivalent

        client, cookies, record, x_id, base_id = _two_scenario_project("u-hard-f2")
        uid, pid = record.user_id, record.project_id
        ws = get_workspace_state(uid, pid)
        draft = json.dumps(ws.draft_snapshot)
        base, x = get_scenario(base_id, uid), get_scenario(x_id, uid)
        with get_cursor() as cur:
            cur.execute("SELECT composite_hash FROM model_run_history WHERE project_id=?", (pid,))
            run_hash = cur.fetchone()["composite_hash"]

            def probe(scenario, last_sid=None, last_hash=run_hash):
                return pre_scenario_base_equivalent(
                    cur, draft_snapshot_json=draft, project_id=pid, user_id=uid,
                    scenario=scenario, last_runtime_scenario_id=last_sid, last_hash=last_hash)

            assert probe(base) is True                                  # proven Base
            assert probe(x) is False                                    # never non-Base
            assert probe(SimpleNamespace(is_base_case=True, overrides={"k": "1"})) is False
            assert probe(base, last_sid=base_id) is False               # not pre-scenario
            assert probe(base, last_hash="0" * 64) is False             # hash not reproduced
            assert probe(None) is False
