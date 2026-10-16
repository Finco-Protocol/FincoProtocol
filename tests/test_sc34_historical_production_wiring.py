"""PR #292 Correction A: the historical Statements route and Run History link, proven against the REAL application.

Every test drives ``main_web.app`` with its standard router registration (nothing here calls ``include_router``).
Runs are committed through the product's own Run route; evidence corruption is applied directly to the stored row only to
prove the route fails closed without echoing it.
"""
from __future__ import annotations

import json
import re

import pytest

from tests import wfa_support as S

URL = "/v2/workbook/run-history/statements"
SENTINEL = "SECRET-PAYLOAD-SENTINEL-7f3a"


@pytest.fixture(scope="module")
def lab(tmp_path_factory):
    lab = S.make_lab(tmp_path_factory, "sc34prod")
    yield lab
    lab.patch.undo()


@pytest.fixture(scope="module")
def solar(lab):
    record = S.project("solar", "sc34")
    S.commit_run(lab, record)
    return record


def entries(record, user=S.USER):
    from app.persistence.run_history_repository import get_run_history
    return sorted(get_run_history(user, record.project_id), key=lambda h: h.created_at)


def get(client, record, history_id, **extra):
    return client.get(URL, params={"project": record.project_code, "history_id": history_id, **extra})


def other_client(user):
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    from main_web import app
    client = TestClient(app)
    client.cookies.set(COOKIE_NAME, create_session_token(user_id=user, username="admin"))
    return client


def raw_update(history_id, **columns):
    from app.persistence.db import get_cursor
    sets = ", ".join(f"{k} = ?" for k in columns)
    with get_cursor() as cur:
        cur.execute(f"UPDATE model_run_history SET {sets} WHERE history_id = ?", (*columns.values(), history_id))


def raw_row(history_id):
    from app.persistence.db import get_cursor
    with get_cursor() as cur:
        cur.execute("SELECT * FROM model_run_history WHERE history_id = ?", (history_id,))
        return dict(cur.fetchone())


# ───────────────────────────── production availability ─────────────────────────────
def test_route_is_registered_in_the_real_application():
    from main_web import app
    paths = {getattr(r, "path", "") for r in app.routes}
    assert URL in paths                                              # /v2 prefix + the isolated router, registered by router.py


def test_authenticated_owner_gets_the_exact_run(lab, solar):
    entry = entries(solar)[0]
    r = get(lab.client, solar, entry.history_id)
    assert r.status_code == 200
    assert f'data-history-id="{entry.history_id}"' in r.text
    assert f'data-out-snapshot="{entry.runtime_snapshot_id}"' in r.text           # exact immutable identity
    assert 'id="v2-run-statements"' in r.text and 'id="v2-sheet-outputs"' not in r.text   # never the Outputs sheet's id
    assert r.text.count('id="v2-run-statements"') == 1


def test_unauthenticated_request_is_refused(solar):
    from fastapi.testclient import TestClient
    from main_web import app
    entry = entries(solar)[0]
    r = TestClient(app).get(URL, params={"project": solar.project_code, "history_id": entry.history_id}, follow_redirects=False)
    assert r.status_code in (401, 302, 303, 307, 404)               # a stranger never reaches the Run (the app answers 404/401)
    assert "v2-run-statements" not in r.text and entry.runtime_snapshot_id not in r.text


def test_foreign_owner_cannot_read_the_run(solar):
    entry = entries(solar)[0]
    r = get(other_client("someone-else"), solar, entry.history_id)
    assert r.status_code == 404 and "v2-run-statements" not in r.text and entry.runtime_snapshot_id not in r.text


def test_run_of_another_project_is_not_reachable_through_this_project(lab, solar):
    other = S.project("wind", "sc34-other")
    S.commit_run(lab, other)
    foreign_id = entries(other)[0].history_id
    r = get(lab.client, solar, foreign_id)
    assert r.status_code == 404


@pytest.mark.parametrize("params,status", [
    ({"project": "", "history_id": "x"}, 400), ({"project": "p"}, 400), ({"history_id": "x"}, 400),
    ({"project": "no-such-project", "history_id": "x"}, 404), ({"project": "p" * 200, "history_id": "x"}, 400),
])
def test_bad_requests_are_controlled_errors(lab, params, status):
    r = lab.client.get(URL, params=params)
    assert r.status_code == status


def test_missing_history_id_is_a_controlled_404(lab, solar):
    r = get(lab.client, solar, "does-not-exist")
    assert r.status_code == 404 and "does-not-exist" not in r.text


# ───────────────────────────── read-only and no-engine ─────────────────────────────
def test_get_never_runs_saves_or_changes_history(lab, solar, monkeypatch):
    from app.persistence.workspace_repository import get_workspace_state
    from app.services import production_financial_authority as P
    entry = entries(solar)[0]
    before_row = raw_row(entry.history_id)
    before_ws = json.dumps(get_workspace_state(S.USER, solar.project_id).last_runtime_summary, sort_keys=True, default=str)
    count = len(entries(solar))
    monkeypatch.setattr(P, "run_clean_production", lambda *a, **k: pytest.fail("engine executed on GET"))
    for _ in range(2):
        assert get(lab.client, solar, entry.history_id).status_code == 200
    assert raw_row(entry.history_id) == before_row and len(entries(solar)) == count
    assert json.dumps(get_workspace_state(S.USER, solar.project_id).last_runtime_summary, sort_keys=True, default=str) == before_ws


def test_working_copy_edits_do_not_change_historical_values(lab):
    record = S.project("solar", "sc34-edit")
    first = S.commit_run(lab, record)
    from app.persistence.workspace_repository import get_workspace_state
    snap = get_workspace_state(S.USER, record.project_id).draft_snapshot
    tariff = float(snap.get("rev_ppa_base_tariff") or snap["tariff_eur_mwh"])
    S.update_field(lab, record, "revenue.ppa.base_tariff", tariff * 1.4, "revenue")
    second = S.commit_run(lab, record)
    assert first.history_id != second.history_id
    expected = [p["revenues_keur"] for p in first.financial_statements["pnl"]["periods"]]
    assert expected != [p["revenues_keur"] for p in second.financial_statements["pnl"]["periods"]]
    html = get(lab.client, record, first.history_id).text
    model = re.search(r'data-st-tree="pnl" data-st-basis="model".*?</table>', html, re.S).group(0)
    row = re.search(r'data-st-key="revenues_keur".*?</tr>', model, re.S).group(0)
    shown = [float(v) for v in re.findall(r'data-raw="([^"]+)"', row)]
    assert shown == pytest.approx(expected, abs=1e-9)


# ───────────────────────────── fail-closed on malformed evidence, no echo ─────────────────────────────
def fresh_run(lab, label):
    record = S.project("solar", label)
    return record, S.commit_run(lab, record)


def test_malformed_stored_json_fails_closed_without_echoing_it(lab):
    record, entry = fresh_run(lab, "sc34-bad-json")
    raw_update(entry.history_id, financial_statements_json='{"pnl": ' + SENTINEL)
    r = get(lab.client, record, entry.history_id)
    assert r.status_code == 422
    assert SENTINEL not in r.text and "RUN_HISTORY_PAYLOAD_MALFORMED" not in r.text and "Traceback" not in r.text
    assert "<script" not in r.text.lower()


def test_wrong_shape_evidence_fails_closed_or_renders_nothing_estimated(lab):
    record, entry = fresh_run(lab, "sc34-bad-shape")
    raw_update(entry.history_id, financial_statements_json=json.dumps({"pnl": SENTINEL, "balance_sheet": [SENTINEL]}))
    r = get(lab.client, record, entry.history_id)
    assert r.status_code in (200, 422)
    if r.status_code == 422:
        assert SENTINEL not in r.text                     # an error never echoes the stored payload
    else:
        # rendered instead: statements are unavailable, never estimated, and the stored text is not shown as a value
        assert 'role="treegrid"' not in r.text or "data-raw=\"\"" in r.text
        assert "This Run did not persist statements" in r.text or SENTINEL not in re.sub(r"<[^>]+>", "", r.text)


def test_identifiers_are_html_escaped(lab):
    record, entry = fresh_run(lab, "sc34-escape")
    raw_update(entry.history_id, runtime_snapshot_id='"><script>alert(1)</script>')
    r = get(lab.client, record, entry.history_id)
    if r.status_code == 200:
        assert "<script>alert(1)</script>" not in r.text and "&lt;script&gt;" in r.text
    else:
        assert "<script>alert(1)" not in r.text


# ───────────────────────────── engine identity, integrity, input freshness ─────────────────────────────
def dims(html):
    return {m[0]: m[1] for m in re.findall(r'data-testid="outputs-dim-(\w+)" data-state="([^"]*)"', html)}


def test_engine_identity_is_independent_and_fails_closed(lab):
    record, entry = fresh_run(lab, "sc34-engine")
    ident = dict(entry.last_runtime_identity or {})
    base = dims(get(lab.client, record, entry.history_id).text)
    assert base["engine"] == "CURRENT_ENGINE" and base["inputs"] == "CURRENT" and base["context"] == "HISTORICAL_RUN"
    # proven superseded: every committed identity agrees on an older version
    older = dict(ident, engine_version="clean_senior_debt_older")
    raw_update(entry.history_id, engine_version="clean_senior_debt_older", last_runtime_identity_json=json.dumps(older),
               replay_metadata_json=json.dumps({"engine_version": "clean_senior_debt_older"}))
    d = dims(get(lab.client, record, entry.history_id).text)
    assert d["engine"] == "ENGINE_SUPERSEDED" and d["inputs"] == "CURRENT"
    html = get(lab.client, record, entry.history_id).text
    assert 'data-superseded-treatment="EVIDENCE_ONLY_D2_PENDING"' in html and "ENGINE SUPERSEDED" not in html   # D2 stays off
    # missing everywhere -> unknown
    raw_update(entry.history_id, engine_version=None, last_runtime_identity_json=json.dumps({k: v for k, v in ident.items() if k != "engine_version"}),
               replay_metadata_json=json.dumps({}))
    assert dims(get(lab.client, record, entry.history_id).text)["engine"] == "ENGINE_IDENTITY_UNKNOWN"
    # conflicting committed values -> unknown (never picks one)
    raw_update(entry.history_id, engine_version="clean_senior_debt_older", last_runtime_identity_json=json.dumps(dict(ident, engine_version="clean_senior_debt_v0")))
    assert dims(get(lab.client, record, entry.history_id).text)["engine"] == "ENGINE_IDENTITY_UNKNOWN"


def test_integrity_fail_is_independent_of_engine_and_inputs(lab, monkeypatch):
    from types import SimpleNamespace
    import app.run_integrity as RI
    record, entry = fresh_run(lab, "sc34-integrity")
    report = SimpleNamespace(to_dict=lambda: {"overall": "FAIL", "counts": {"FAIL": 1}, "checks": [
        {"check_id": "X", "title": "Synthetic failure", "status": "FAIL", "reason_code": "R"}]})
    monkeypatch.setattr(RI, "run_integrity_checks", lambda evidence: report)
    html = get(lab.client, record, entry.history_id).text
    d = dims(html)
    assert (d["integrity"], d["inputs"], d["engine"]) == ("FAIL", "CURRENT", "CURRENT_ENGINE")
    assert 'data-testid="outputs-integrity-fail"' in html and "Synthetic failure" in html


def test_input_freshness_is_strictly_hash_equality_of_the_working_copy(lab):
    record, entry = fresh_run(lab, "sc34-fresh")
    assert dims(get(lab.client, record, entry.history_id).text)["inputs"] == "CURRENT"
    from app.persistence.workspace_repository import get_workspace_state
    snap = get_workspace_state(S.USER, record.project_id).draft_snapshot
    tariff = float(snap.get("rev_ppa_base_tariff") or snap["tariff_eur_mwh"])
    S.update_field(lab, record, "revenue.ppa.base_tariff", tariff * 1.2, "revenue")
    html = get(lab.client, record, entry.history_id).text
    assert dims(html)["inputs"] == "STALE" and dims(html)["engine"] == "CURRENT_ENGINE"
    assert "Historical Run. Links open the CURRENT Working Copy" in html


def test_scenario_identity_is_proven_or_unavailable_never_guessed(lab):
    record, entry = fresh_run(lab, "sc34-scenario")
    html = get(lab.client, record, entry.history_id).text
    label = re.search(r'data-out-scenario="([^"]+)"', html).group(1)
    assert label.startswith("Base Case") and label != "UNAVAILABLE"
    raw_update(entry.history_id, last_runtime_scenario_id="no-such-scenario")
    bad = get(lab.client, record, entry.history_id).text
    assert 'data-out-scenario="UNAVAILABLE"' in bad                       # an unprovable id is never shown as Base


# ───────────────────────────── Run History link ─────────────────────────────
def test_run_detail_exposes_the_link_only_for_the_mounted_route(lab, solar):
    entry = entries(solar)[0]
    r = lab.client.get("/v2/workbook/run-history/detail", params={"project": solar.project_code, "history_id": entry.history_id})
    assert r.status_code == 200
    assert 'data-testid="run-detail-open-statements"' in r.text
    assert f'data-history-id="{entry.history_id}"' in r.text and URL in r.text
    assert 'hx-target="#v2-run-detail"' in r.text


def test_registration_gate_reports_false_when_the_route_is_not_mounted(monkeypatch):
    import app.v2.router as R
    monkeypatch.setattr(R.router, "routes", [x for x in R.router.routes if getattr(x, "path", "") != "/workbook/run-history/statements"])
    assert R._statements_drilldown_registered() is False


def test_outputs_sheet_and_library_still_load(lab, solar):
    assert lab.client.get("/v2/workbook/outputs", params={"project": solar.project_code}).status_code == 200
    assert lab.client.get("/library").status_code in (200, 302)
