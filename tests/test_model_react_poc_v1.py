"""UX-01 Full-React Architecture PoC — contract tests for the isolated React surface.

Synthetic data only.  The PoC adds NO authority: the page shell and bootstrap are
read-only presentations of the SAME canonical evidence the legacy workbook uses
(``PostRunRequestContext`` + statement services + composite CAS identity), and the
single editable input saves exclusively through the existing canonical
``POST /v2/workbook/grid/save``.  These tests pin:

* flag OFF → legacy experience unchanged and an explicit fallback (no React mount);
* flag ON → same-origin bundle served, direct refresh works, canonical contracts hold
  (session, foreign-project denial, protected reference read-only, CSRF, stale CAS,
  no automatic Run), the persisted P&L projection matches the canonical output
  workspace evidence, and unavailable values are never converted into zeros;
* input freshness and Run integrity remain independent dimensions.
"""
from __future__ import annotations

from tests.model_mutation_csrf import post_valid_mutation

from tests.run_clone_csrf import post_valid_csrf

import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.persistence import db
from app.persistence.workspace_repository import get_workspace_state

OWNER = "react-poc-owner"
STRANGER = "react-poc-stranger"

REACT_PAGE = "/v2/model-react"
CIT = "tax.assumptions.cit_rate_pct"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "react_poc.db"))
    db.init_db()
    from app.auth import COOKIE_NAME, create_session_token
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.services.reference_seed_service import create_reference_seeded_project
    from fastapi import FastAPI
    from app._asset_paths import resolve_static_dir
    from app.v2.grid_router import router as grid_router
    from app.v2.react_poc_router import router as react_router
    from app.v2.router import router as v2_router
    from fastapi.staticfiles import StaticFiles

    monkeypatch.delenv("FINCO_MODEL_REACT_V1", raising=False)
    monkeypatch.delenv("FINCO_WORKBOOK_V2", raising=False)
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    app.include_router(grid_router, prefix="/v2")
    app.include_router(react_router, prefix="/v2")
    static_dir = resolve_static_dir("")
    if static_dir:
        app.mount("/static", StaticFiles(directory=static_dir), name="static")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))
        stranger = TestClient(app)
        stranger.cookies.set(COOKIE_NAME, create_session_token(user_id=STRANGER, username="stranger"))
        anonymous = TestClient(app)

        def create(kind="solar", user=OWNER, name=None):
            return create_reference_seeded_project(
                user_id=user, requested_name=name or f"React {kind}",
                template_source=f"generic_{kind}_reference", capacity_mw=16)

        yield SimpleNamespace(client=client, stranger=stranger, anonymous=anonymous,
                              create=create, app=app)
    reset_model_executor_for_tests()


def flag_on(monkeypatch):
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")


def bootstrap(env, code: str):
    response = env.client.get("/v2/model-react/bootstrap", params={"project": code})
    assert response.status_code == 200, response.text[:600]
    return response.json()


def save_cit(env, body: dict, value: str):
    body = dict(body)
    body["cells"] = [{"field_id": CIT, "value": value}]
    return post_valid_mutation(env.client, "/v2/workbook/grid/save", json=body)


def grid_tokens(page_text: str) -> dict:
    match = re.search(
        r'data-csrf="([^"]+)"[^>]*data-content-hash="([0-9a-f]+)"[^>]*data-workbook-version="([^"]+)"',
        page_text, re.S)
    assert match, "legacy workbook page must expose grid identity tokens"
    return {"csrf_token": match.group(1), "content_hash": match.group(2),
            "workbook_version": match.group(3), "scenario_id": None}


# ───────────────────────────── flag OFF: legacy preservation ─────────────────────────────

def test_flag_off_leaves_legacy_experience_unchanged_with_explicit_fallback(env):
    c = env.client
    record = env.create()
    legacy = c.get("/v2/workbook", params={"project": record.project_code})
    assert legacy.status_code == 200 and 'id="v2-hybrid-bar"' in legacy.text

    page = c.get(f"{REACT_PAGE}/{record.project_code}")
    assert page.status_code == 200
    assert "React preview unavailable" in page.text
    assert "finco-react.js" not in page.text, "flag OFF must not mount the React bundle"
    assert f'href="/v2/workbook?project={record.project_code}"' in page.text

    boot = c.get("/v2/model-react/bootstrap", params={"project": record.project_code})
    assert boot.status_code == 404 and boot.json()["code"] == "REACT_POC_DISABLED"


def test_legacy_grid_routes_still_function_with_flag_on(env, monkeypatch):
    flag_on(monkeypatch)
    c = env.client
    record = env.create()
    page = c.get("/v2/workbook", params={"project": record.project_code})
    assert page.status_code == 200 and 'id="v2-hybrid-bar"' in page.text
    for sheet in ("capex", "opex", "tax", "project_setup", "revenue"):
        assert c.get("/v2/workbook/grid/sheet",
                     params={"project": record.project_code, "sheet": sheet}).status_code == 200


# ───────────────────────────── flag ON: shell, assets, authorization ─────────────────────────────

def test_flag_on_serves_same_origin_bundle_and_direct_refresh_works(env, monkeypatch):
    flag_on(monkeypatch)
    c = env.client
    record = env.create()
    for _ in (1, 2):  # second GET models a direct browser refresh
        page = c.get(f"{REACT_PAGE}/{record.project_code}")
        assert page.status_code == 200
        assert 'id="finco-react-root"' in page.text
        assert f'data-project="{record.project_code}"' in page.text
        assert 'data-save-url="/v2/workbook/grid/save"' in page.text
        assert 'src="/static/react/finco-react.js?v=' in page.text
        assert 'href="/static/react/finco-react.css?v=' in page.text
        assert "<script" in page.text and "http://" not in page.text  # same-origin assets only
    bundle = c.get("/static/react/finco-react.js")
    assert bundle.status_code == 200 and "javascript" in bundle.headers["content-type"]
    stylesheet = c.get("/static/react/finco-react.css")
    assert stylesheet.status_code == 200


def test_bundle_contains_no_runtime_cdn_dependency():
    from pathlib import Path

    import app._asset_paths as asset_paths

    static_dir = Path(asset_paths.resolve_static_dir(""))
    bundle = (static_dir / "react" / "finco-react.js").read_text(encoding="utf-8")
    urls = set(re.findall(r"https?://[^\s\"'`\\)]+", bundle))
    # Concept B NON-MODEL integration V1 (additive, narrowly scoped): the
    # approved Concept B design renders read-only source-documentation anchors
    # pointing at this repository's GitHub blobs (frontend/src/nonmodel/
    # _shared/fixtures.ts, byte-identical to the handoff).  They are
    # click-through navigation destinations, never runtime fetches — the
    # NON-MODEL tree contains no fetch/XHR/WebSocket usage (enforced by
    # tests/test_nonmodel_concept_b_v1.py).
    allowed = {u for u in urls if u.startswith("http://www.w3.org/")
               or u.startswith("https://reactjs.org/docs/error-decoder")
               or u.startswith("https://github.com/Finco-Protocol/FincoProtocol/blob/main/")}
    assert urls == allowed, f"unexpected non-same-origin URLs in bundle: {sorted(urls - allowed)}"


def test_bootstrap_reports_canonical_project_name_distinct_from_code(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create(name="Alpha Wind Portfolio 7")
    assert record.project_name != record.project_code, "fixture must produce a name/code divergence"
    payload = bootstrap(env, record.project_code)
    assert payload["project"]["name"] == record.project_name
    assert payload["project"]["code"] == record.project_code


def test_bootstrap_identity_matches_the_legacy_workbook_identity(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    legacy = env.client.get("/v2/workbook", params={"project": record.project_code})
    payload = bootstrap(env, record.project_code)
    assert payload["workbook"]["version"]
    assert payload["workbook"]["composite_hash"] == grid_tokens(legacy.text)["content_hash"], \
        "React bootstrap must read the SAME composite CAS identity as the legacy grid"
    assert payload["field"]["field_id"] == CIT
    assert payload["field"]["editable"] is True
    assert payload["csrf_token"]


def test_bootstrap_requires_session_and_denies_foreign_projects(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    anonymous = env.anonymous.get("/v2/model-react/bootstrap", params={"project": record.project_code})
    assert anonymous.status_code in (401, 404)
    foreign = env.stranger.get("/v2/model-react/bootstrap", params={"project": record.project_code})
    assert foreign.status_code == 404 and foreign.json()["code"] == "PROJECT_NOT_FOUND"


def test_protected_reference_stays_read_only(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    from app.persistence.db import get_connection

    with get_connection() as conn:
        conn.execute("UPDATE projects SET is_protected=1, is_readonly=1, project_role='reference' "
                     "WHERE project_id=?", (record.project_id,))
    payload = bootstrap(env, record.project_code)
    assert payload["field"]["editable"] is False
    assert payload["project"]["protected_reference"] is True
    legacy = env.client.get("/v2/workbook", params={"project": record.project_code})
    body = dict(grid_tokens(legacy.text))
    body["project"] = record.project_code
    response = save_cit(env, body, "22.5")
    assert response.status_code == 403, "canonical authority must keep protected references read-only"


# ───────────────────────────── the one real Save through canonical authority ─────────────────────────────

def test_forged_or_missing_csrf_is_rejected(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    legacy = env.client.get("/v2/workbook", params={"project": record.project_code})
    tokens = grid_tokens(legacy.text)
    # Every forged case is guaranteed to differ from the original token: flipping
    # the first character always changes the decoded payload (the historical
    # `[:-1] + "x"` mutation could alias to the original through noncanonical
    # base64url trailing bits — see the canonical-encoding unit tests below).
    original = tokens["csrf_token"]
    first_char_flipped = ("x" if original[0] != "x" else "y") + original[1:]
    assert first_char_flipped != original
    for forged in ("", "forged-token", first_char_flipped):
        body = dict(project=record.project_code, csrf_token=forged,
                    content_hash=tokens["content_hash"], workbook_version=tokens["workbook_version"],
                    scenario_id=None, cells=[{"field_id": CIT, "value": "22.5"}])
        response = env.client.post("/v2/workbook/grid/save", json=body)
        assert response.status_code == 403 and response.json()["code"] == "CSRF_INVALID"


def test_valid_save_updates_working_copy_and_returns_new_authoritative_identity(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    payload = bootstrap(env, record.project_code)
    before = get_workspace_state(OWNER, record.project_id)
    assert payload["freshness"]["state"] == "NOT_RUN"

    body = dict(project=record.project_code, csrf_token=payload["csrf_token"],
                content_hash=payload["workbook"]["composite_hash"],
                workbook_version=payload["workbook"]["version"],
                scenario_id=payload["workbook"]["scenario_id"])
    response = save_cit(env, body, "22.5")
    assert response.status_code == 200, response.text[:600]
    out = response.json()
    assert out["ok"] is True and out["model_executed"] is False
    assert out["content_hash"] != payload["workbook"]["composite_hash"], \
        "Save must return the NEW authoritative composite hash"
    assert out["workbook_version"] == payload["workbook"]["version"]
    assert out["run_state"] == "NOT_RUN", "a Save never runs the model"
    saved = next(s for s in out["saved"] if s["field_id"] == CIT)
    assert saved["value"].startswith("22.5")

    after = get_workspace_state(OWNER, record.project_id)
    assert float(after.draft_snapshot["tax_corporate_rate_pct"]) == pytest.approx(22.5)
    assert after.last_runtime_snapshot_id == before.last_runtime_snapshot_id
    assert after.last_runtime_summary == before.last_runtime_summary, \
        "a Save must not alter the persisted Last Run"

    refreshed = bootstrap(env, record.project_code)
    assert refreshed["workbook"]["composite_hash"] == out["content_hash"]
    assert refreshed["field"]["value"].startswith("22.5")


def test_invalid_value_rejected_without_mutation_and_typed_value_preserved_client_side(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    payload = bootstrap(env, record.project_code)
    before = get_workspace_state(OWNER, record.project_id).draft_snapshot
    body = dict(project=record.project_code, csrf_token=payload["csrf_token"],
                content_hash=payload["workbook"]["composite_hash"],
                workbook_version=payload["workbook"]["version"], scenario_id=None)
    for bad in ("abc", "150", "-3"):
        response = save_cit(env, body, bad)
        assert response.status_code == 422, (bad, response.text[:300])
        assert response.json()["ok"] is False
        assert get_workspace_state(OWNER, record.project_id).draft_snapshot == before, \
            "a rejected value must mutate nothing"


def test_stale_cas_conflict_returns_reload_without_retry(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    payload = bootstrap(env, record.project_code)
    body = dict(project=record.project_code, csrf_token=payload["csrf_token"],
                content_hash=payload["workbook"]["composite_hash"],
                workbook_version=payload["workbook"]["version"], scenario_id=None)
    assert save_cit(env, body, "21.0").status_code == 200
    replay = save_cit(env, body, "23.0")  # same stale identity: a blind retry
    assert replay.status_code == 409 and replay.json()["reload"] is True
    assert float(get_workspace_state(OWNER, record.project_id).draft_snapshot["tax_corporate_rate_pct"]) == pytest.approx(21.0)


def test_save_after_run_classifies_last_run_stale_and_never_recomputes(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    run_response = post_valid_csrf(env.client, "/v2/workbook/run", headers={"HX-Request": "true"},
                                   data=dict(project=record.project_code, **grid_tokens(page.text)))
    assert run_response.status_code == 200, run_response.text[:600]
    from app.workbook.service import WorkbookService
    ws0 = get_workspace_state(OWNER, record.project_id)
    rr0 = WorkbookService.get_runtime_result(ws0)
    payload = bootstrap(env, record.project_code)
    assert payload["freshness"]["state"] == "CURRENT"

    body = dict(project=record.project_code, csrf_token=payload["csrf_token"],
                content_hash=payload["workbook"]["composite_hash"],
                workbook_version=payload["workbook"]["version"],
                scenario_id=payload["workbook"]["scenario_id"])
    response = save_cit(env, body, "24.0")
    assert response.status_code == 200 and response.json()["run_state"] == "STALE"
    ws1 = get_workspace_state(OWNER, record.project_id)
    rr1 = WorkbookService.get_runtime_result(ws1)
    assert ws1.last_runtime_snapshot_id == ws0.last_runtime_snapshot_id
    assert rr1.snapshot_id == rr0.snapshot_id, "the persisted Last Run is immutable under a Save"
    refreshed = bootstrap(env, record.project_code)
    assert refreshed["freshness"]["state"] == "STALE"
    assert refreshed["outputs"]["state"] == "STALE"
    assert refreshed["outputs"]["banner"], "STALE must be communicated, not hidden"


# ───────────────────────────── persisted P&L projection parity ─────────────────────────────

def _persisted_pnl(rr):
    from app.workbook.runtime_projection import thaw_runtime_payload
    return thaw_runtime_payload(rr.financial_statements)["pnl"]["periods"]


def test_pnl_projection_matches_canonical_persisted_evidence(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    run_response = post_valid_csrf(env.client, "/v2/workbook/run", headers={"HX-Request": "true"},
                                   data=dict(project=record.project_code, **grid_tokens(page.text)))
    assert run_response.status_code == 200, run_response.text[:600]
    from app.workbook.service import WorkbookService
    rr = WorkbookService.get_runtime_result(get_workspace_state(OWNER, record.project_id))
    payload = bootstrap(env, record.project_code)

    assert payload["outputs"]["state"] == "CURRENT"
    identity = payload["outputs"]["identity"]
    assert identity["snapshot_id"] == rr.snapshot_id
    assert identity["composite_hash"] == get_workspace_state(OWNER, record.project_id).last_runtime_composite_hash
    assert identity["scenario_proven"] is True

    pnl = payload["outputs"]["pnl"]
    assert pnl and pnl["available"] and pnl["id"] == "pnl"
    persisted = _persisted_pnl(rr)
    keys = ["revenues_keur", "ebitda_keur", "net_income_keur"]
    for row in pnl["rows"]:
        if row["key"] not in keys:
            continue
        expected = [p.get(row["key"]) for p in persisted]
        assert len(row["cells"]) == len(expected)
        for cell, value in zip(row["cells"], expected):
            if value is None:
                assert cell["v"] is None and cell["text"] == "—", \
                    "an unavailable value must never be converted into a zero"
            else:
                assert cell["v"] == pytest.approx(float(value), abs=1e-9)
    columns = pnl["columns"]
    assert [c["label"] for c in columns] and all(c["label"] and c["label"] != "None" for c in columns)


def test_unavailable_values_are_never_zeros_and_period_labels_survive(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    run_response = post_valid_csrf(env.client, "/v2/workbook/run", headers={"HX-Request": "true"},
                                   data=dict(project=record.project_code, **grid_tokens(page.text)))
    assert run_response.status_code == 200, run_response.text[:600]
    payload = bootstrap(env, record.project_code)
    pnl = payload["outputs"]["pnl"]
    zeros_for_unavailable = [
        row["key"] for row in pnl["rows"]
        for cell in row["cells"]
        if cell["v"] is None and (cell["text"] == "0" or cell["text"] == "0.00")
    ]
    assert zeros_for_unavailable == [], zeros_for_unavailable
    for column in pnl["columns"]:
        assert column["date"] and column["label"]


def test_input_freshness_and_run_integrity_remain_independent(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    run_response = post_valid_csrf(env.client, "/v2/workbook/run", headers={"HX-Request": "true"},
                                   data=dict(project=record.project_code, **grid_tokens(page.text)))
    assert run_response.status_code == 200, run_response.text[:600]
    payload = bootstrap(env, record.project_code)
    dimensions = payload["outputs"]["status_dimensions"]
    assert dimensions["run_context"] == "LAST_RUN"
    assert dimensions["input_freshness"] == "CURRENT"
    assert dimensions["integrity"] in ("PASS", "FAIL", "INCOMPLETE", "UNAVAILABLE")
    assert dimensions["engine_currency"] in ("CURRENT_ENGINE", "ENGINE_SUPERSEDED", "ENGINE_IDENTITY_UNKNOWN")

    # A Save moves input freshness to STALE while the committed Run's own Integrity
    # verdict is untouched: the two dimensions stay independent facts (SC-03).
    body = dict(project=record.project_code, csrf_token=payload["csrf_token"],
                content_hash=payload["workbook"]["composite_hash"],
                workbook_version=payload["workbook"]["version"],
                scenario_id=payload["workbook"]["scenario_id"])
    assert save_cit(env, body, "25.0").status_code == 200
    after = bootstrap(env, record.project_code)
    assert after["outputs"]["status_dimensions"]["input_freshness"] == "STALE"
    assert after["outputs"]["status_dimensions"]["integrity"] == dimensions["integrity"]
    assert after["freshness"]["state"] == "STALE"


def test_not_run_project_reports_no_run_and_no_statements(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    payload = bootstrap(env, record.project_code)
    assert payload["freshness"]["state"] == "NOT_RUN"
    assert payload["outputs"]["state"] == "NOT_RUN"
    assert payload["outputs"]["pnl"] is None
    assert payload["outputs"]["identity"] is None
    assert payload["outputs"]["integrity"]["status"] == "UNAVAILABLE"


# ───────────────────────── CSRF canonical-encoding hardening ────────────────
# itsdangerous accepts noncanonical base64url renderings (a final character with
# unused trailing bits decodes to the same bytes), so a textual mutation of a
# valid token could be accepted as itself.  The CSRF validator now requires the
# exact canonical encoding; these tests pin that behaviour deterministically.

def test_canonical_csrf_token_is_accepted_and_first_char_mutation_rejected():
    from app.auth import generate_csrf_token, validate_csrf_token
    for _ in range(50):
        token = generate_csrf_token()
        assert validate_csrf_token(token)
        flipped = ("x" if token[0] != "x" else "y") + token[1:]
        assert flipped != token and not validate_csrf_token(flipped)
        assert not validate_csrf_token("")
        assert not validate_csrf_token("not-a-token")


def test_noncanonical_base64url_alias_is_rejected():
    import base64
    from app.auth import generate_csrf_token, validate_csrf_token
    alias_alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    alias = None
    for _ in range(400):                     # ~6% of tokens admit an alias; bounded search
        token = generate_csrf_token()
        segments = token.split(".")
        last = segments[-1]
        decoded = base64.urlsafe_b64decode(last + "=" * (-len(last) % 4))
        for ch in alias_alphabet:
            candidate = last[:-1] + ch
            if candidate == last:
                continue
            recoded = base64.urlsafe_b64decode(candidate + "=" * (-len(candidate) % 4))
            if recoded == decoded and candidate != last:
                alias = ".".join(segments[:-1] + [candidate])
                break
        if alias:
            break
    if alias is None:                        # no alias admits for these tokens; nothing to pin
        pytest.skip("no base64url alias candidate among generated tokens")
    assert alias != token
    assert base64.urlsafe_b64decode(alias.split(".")[-1] + "=" * (-len(alias.split(".")[-1]) % 4)) == decoded
    assert not validate_csrf_token(alias), "a noncanonical textual alias must not validate"
