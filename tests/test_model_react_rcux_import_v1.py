"""RC-UX A3 (Audit A GAP-R10) — React Excel/CSV import adapter over the REAL Workflow C authority.

The adapter calls the Legacy handlers unchanged: preview and confirm write nothing; apply is the canonical C0 batch writer (composite-hash
CAS, one transaction) and never runs the model; every Legacy refusal (CSRF, ownership, size, stale preview, forged targets) is preserved.
"""
from __future__ import annotations

import io
import sqlite3

import pytest

from tests.test_model_decision_workspace_v2 import env  # noqa: F401  (fixture)

CONTEXT = "/v2/model-react/import/context"
PREVIEW = "/v2/model-react/import/preview"
CONFIRM = "/v2/model-react/import/confirm"
APPLY = "/v2/model-react/import/apply"
HDR = {"X-Finco-React-Request": "1"}
FIELD = "project_setup.technical.p50_hours"


@pytest.fixture
def imp(env, monkeypatch):  # noqa: F811
    from app.v2.react_import import router
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    env.client.app.include_router(router, prefix="/v2")
    return env


def tsv(*rows):
    return ("\n".join("\t".join(r) for r in (("Assumption", "Value", "Unit"),) + rows) + "\n").encode("utf-8")


def context(env, record):
    response = env.client.get(CONTEXT, params={"project": record.project_code})
    assert response.status_code == 200, response.text[:300]
    return response.json()


def preview(env, record, data, *, name="plan.csv", token=None, headers=HDR, project=None):
    ctx = context(env, record)
    return env.client.post(PREVIEW, params={"project": record.project_code}, headers=headers,
                           data={"project": project or record.project_code, "csrf_token": token or ctx["csrf_token"], "encoding": "utf-8-sig"},
                           files={"upload": (name, io.BytesIO(data), "text/csv")})


def confirm(env, record, ticket, ctx, *, keep=(), extra=None):
    form = {"project": record.project_code, "csrf_token": ctx["csrf_token"], "preview_ticket": ticket}
    for row_id, field in keep:
        form[f"keep_{row_id}"] = "on"
        form[f"field_{row_id}"] = field
    form.update(extra or {})
    return env.client.post(CONFIRM, params={"project": record.project_code}, headers=HDR, data=form)


def apply(env, record, ticket, ctx):
    return env.client.post(APPLY, params={"project": record.project_code}, headers=HDR,
                           data={"project": record.project_code, "csrf_token": ctx["csrf_token"], "approved_ticket": ticket})


def db_dump():
    from app.persistence import db
    with sqlite3.connect(db.DB_PATH) as conn:
        return "\n".join(conn.iterdump())


def draft_value(record, owner="decision-user"):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.input_set import ProjectInputSet
    from app.workbook.registry import WORKBOOK
    ws = get_workspace_state(owner, record.project_id)
    return ProjectInputSet.from_snapshot(ws.draft_snapshot, workbook=WORKBOOK).get(FIELD)


def test_router_is_mounted_before_the_project_catch_all():
    from app.v2.router import router
    paths = [getattr(route, "path", "") for route in router.routes]
    for path in ("/model-react/import/context", "/model-react/import/preview", "/model-react/import/confirm", "/model-react/import/apply"):
        assert paths.count(path) == 1 and paths.index(path) < paths.index("/model-react/{project_code}")


def test_context_is_flagged_authenticated_and_scoped(imp, monkeypatch):
    record = imp.create("solar")
    data = context(imp, record)
    assert data["csrf_token"] and data["content_hash"] and data["limits"]["max_upload_bytes"] == 2 * 1024 * 1024
    assert any(f["id"] == FIELD for f in data["fields"]) and data["semantics"]["file_is_stored"] is False
    assert imp.client.get(CONTEXT, params={"project": "nope"}).status_code == 404
    monkeypatch.delenv("FINCO_MODEL_REACT_V1")
    assert imp.client.get(CONTEXT, params={"project": record.project_code}).status_code == 404


def test_a_protected_template_cannot_import(imp):
    from app.persistence.db import get_connection
    record = imp.create("solar")
    with get_connection() as connection:
        connection.execute("UPDATE projects SET project_role='reference', is_protected=1 WHERE project_id=?", (record.project_id,))
        connection.commit()
    assert imp.client.get(CONTEXT, params={"project": record.project_code}).status_code == 403


def test_preview_reads_the_file_in_memory_and_writes_nothing(imp):
    record = imp.create("solar")
    before = db_dump()
    response = preview(imp, record, tsv((FIELD, "1850", ""), ("Totally unknown label", "5", "")))
    assert response.status_code == 200, response.text[:400]
    body = response.json()
    assert body["detected"] == 2 and body["preview_ticket"] and body["semantics"]["nothing_written"] is True
    mapped = next(r for r in body["rows"] if r["field_id"] == FIELD)
    assert mapped["status"] in ("ready", "needs_review", "unchanged") and mapped["mapping_method"] == "exact_field_id"
    unknown = next(r for r in body["rows"] if r["label"] == "Totally unknown label")
    assert unknown["field_id"] is None and unknown["status"] in ("unsupported", "invalid", "unsupported_for_apply")
    assert db_dump() == before


@pytest.mark.parametrize("case", ["header", "csrf", "format", "empty", "mismatch"])
def test_preview_refusals_keep_the_legacy_contract(imp, case):
    record = imp.create("solar")
    before = db_dump()
    data = tsv((FIELD, "1850", ""))
    if case == "header":
        response = preview(imp, record, data, headers={})
        assert response.status_code == 400 and response.json()["code"] == "REQUEST_HEADER_REQUIRED"
    elif case == "csrf":
        response = preview(imp, record, data, token="forged")
        assert response.status_code == 403 and response.json()["code"] == "IMPORT_CSRF_INVALID"
    elif case == "format":
        response = preview(imp, record, data, name="plan.txt")
        assert response.status_code == 422 and response.json()["code"] == "IMPORT_FORMAT_UNSUPPORTED"
    elif case == "empty":
        response = preview(imp, record, b"", name="plan.csv")
        assert response.status_code in (411, 422) and not response.json()["ok"]
    else:
        response = preview(imp, record, data, project="someone-elses")
        assert response.status_code == 400 and response.json()["code"] == "BODY_INVALID"
    assert db_dump() == before


def test_an_oversize_body_is_refused_before_parsing(imp):
    record = imp.create("solar")
    response = preview(imp, record, b"a" * (2 * 1024 * 1024 + 40_000))
    assert response.status_code == 413 and response.json()["code"] == "IMPORT_BODY_SIZE_INVALID"


def test_confirm_needs_a_selection_and_rejects_forged_targets_without_writing(imp):
    record = imp.create("solar")
    ctx = context(imp, record)
    body = preview(imp, record, tsv((FIELD, "1850", ""))).json()
    row = next(r for r in body["rows"] if r["field_id"] == FIELD)
    before = db_dump()
    none = confirm(imp, record, body["preview_ticket"], ctx)
    assert none.status_code == 422 and none.json()["code"] == "IMPORT_APPROVED_FIELD_COUNT_INVALID"
    forged = confirm(imp, record, body["preview_ticket"], ctx, keep=[(row["id"], "project_setup.not_a_real_field")])
    assert forged.status_code == 422 and not forged.json()["ok"]
    assert confirm(imp, record, "forged-ticket", ctx, keep=[(row["id"], FIELD)]).status_code == 422
    assert db_dump() == before


def test_apply_is_the_canonical_batch_writer_marks_results_stale_and_never_runs(imp):
    from app.persistence.run_history_repository import get_run_history
    record = imp.create("solar")
    runs_before = len(get_run_history("decision-user", record.project_id))
    ctx = context(imp, record)
    body = preview(imp, record, tsv((FIELD, "1850", ""))).json()
    row = next(r for r in body["rows"] if r["field_id"] == FIELD)
    approved = confirm(imp, record, body["preview_ticket"], ctx, keep=[(row["id"], FIELD)])
    assert approved.status_code == 200, approved.text[:400]
    a = approved.json()
    assert a["approved_count"] == 1 and a["approved"][0]["field_id"] == FIELD and a["semantics"]["nothing_written"] is True
    assert float(draft_value(record)) != 1850.0, "confirm wrote nothing"
    applied = apply(imp, record, a["approved_ticket"], ctx)
    assert applied.status_code == 200, applied.text[:400]
    r = applied.json()
    assert r["applied_count"] == 1 and r["semantics"]["model_was_run"] is False and r["saved"][0]["field_id"] == FIELD
    assert float(draft_value(record)) == 1850.0
    assert len(get_run_history("decision-user", record.project_id)) == runs_before, "apply never runs the model"
    # the same approval cannot be replayed: the project identity has changed
    replay = apply(imp, record, a["approved_ticket"], ctx)
    assert replay.status_code == 409 and not replay.json()["ok"]
    assert float(draft_value(record)) == 1850.0


def test_another_users_project_is_not_reachable(imp):
    record = imp.create("solar")
    from app.auth import COOKIE_NAME, create_session_token
    imp.client.cookies.set(COOKIE_NAME, create_session_token(user_id="intruder", username="admin"))
    assert imp.client.get(CONTEXT, params={"project": record.project_code}).status_code == 404
    assert preview(imp, record, tsv((FIELD, "1", ""))).status_code in (401, 404)
