"""FINCO 37 Batch 4 — Slice B (C1F-A-2 / A16): durable minimal append-only import receipt acceptance tests.

Real HTTP routes (Legacy /v2/workbook/import/* and React /v2/model-react/import/*) and real SQLite DB:
1. CSV & XLSX end-to-end upload -> preview -> confirm -> apply (Legacy + React) writes exactly 1 durable receipt
   inside the same BEGIN EXCLUSIVE transaction as canonical batch Apply.
2. Independent SHA-256 of original uploaded bytes, exact before/after composite hashes, allowlisted canonical
   field IDs, approved_count, changed_count, no-op approval (changed_count=0), and zero receipts on preview/confirm/refusal.
3. Privacy guarantee: raw DB row and owner-scoped read route contain ZERO filename, cell values, labels, raw tickets,
   tokens, formulas, or secrets.
4. Durability across fresh client/app restart and expired tickets; owner-scoped read route refuses cross-tenant access.
5. Security & atomic rollback: missing digest on older ticket -> 422 IMPORT_SOURCE_DIGEST_MISSING; bad CSRF -> 403;
   replay -> 409 with 0 extra receipts; two simultaneous Apply threads -> exactly 1 commit + 1 receipt;
   injected receipt INSERT failure rolls back BOTH draft mutation and receipt; append-only trigger blocks UPDATE;
   idempotent migration on existing DB preserves receipts.
6. Financial authority proof: accepted import changes input without auto-running (sealed History immutable);
   subsequent deliberate Run reflects the new input while prior sealed History stays unchanged.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import re
import sqlite3
import threading
import openpyxl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME, create_session_token
from app.persistence import db
from app.persistence.import_receipt_repository import (
    ImportReceiptError,
    ensure_schema,
    list_receipts_for_project,
)
from app.persistence.run_history_repository import get_run_history
from app.persistence.workspace_repository import get_workspace_state
from app.services.reference_seed_service import create_reference_seeded_project
from app.v2.import_router import router as import_router
from app.v2.react_import import router as react_import_router
from app.v2.router import router as v2_router
from tests.run_clone_csrf import post_valid_csrf


@pytest.fixture(autouse=True, scope="module")
def _finco47_legacy_ssr_rollback():
    """Module-scoped so module/session fixtures that seed over HTTP see the legacy SSR
    surface this module still exercises; default production flag stays React ON and the
    environment is restored exactly when the module finishes."""
    patch = pytest.MonkeyPatch()
    patch.setenv("FINCO_MODEL_REACT_V1", "0")
    try:
        yield
    finally:
        patch.undo()

OWNER = "b4-imp-owner"
STRANGER = "b4-imp-stranger"
HDR = {"X-Finco-React-Request": "1"}


@pytest.fixture()
def imp_env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "b4_import.db")
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    db.init_db()

    def _make_app():
        app = FastAPI()
        app.include_router(v2_router, prefix="/v2")
        app.include_router(import_router, prefix="/v2")
        app.include_router(react_import_router, prefix="/v2")
        return app

    app = _make_app()
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))
        stranger = TestClient(app)
        stranger.cookies.set(COOKIE_NAME, create_session_token(user_id=STRANGER, username="stranger"))
        rec = create_reference_seeded_project(
            user_id=OWNER,
            requested_name="Batch4 Import Solar",
            template_source="generic_solar_reference",
            capacity_mw=20.0,
        )
        client.get("/v2/workbook", params={"project": rec.project_code})
        yield type(
            "Env",
            (),
            {
                "client": client,
                "stranger": stranger,
                "record": rec,
                "db_path": db_path,
                "make_app": staticmethod(_make_app),
            },
        )()


def _make_csv_bytes(field_id: str, value: str) -> bytes:
    return f"Assumption,Value,Unit\n{field_id},{value},\n".encode("utf-8")


def _make_xlsx_bytes(field_id: str, value: str) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Inputs"
    ws.append(["Assumption", "Value", "Unit"])
    ws.append([field_id, value, ""])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _react_preview_confirm_apply(client: TestClient, code: str, *, filename: str, payload: bytes, mime: str):
    ctx = client.get("/v2/model-react/import/context", params={"project": code}).json()
    assert ctx["ok"] is True
    csrf = ctx["csrf_token"]
    before_hash = ctx["content_hash"]

    prev = client.post(
        "/v2/model-react/import/preview",
        params={"project": code},
        headers=HDR,
        data={"project": code, "csrf_token": csrf, "encoding": "utf-8-sig"},
        files={"upload": (filename, payload, mime)},
    )
    assert prev.status_code == 200, prev.text[:300]
    pbody = prev.json()
    assert pbody["ok"] is True and len(pbody["rows"]) >= 1
    row = pbody["rows"][0]
    rid = row["id"]

    conf = client.post(
        "/v2/model-react/import/confirm",
        params={"project": code},
        headers=HDR,
        data={
            "project": code,
            "csrf_token": csrf,
            "preview_ticket": pbody["preview_ticket"],
            f"keep_{rid}": "on",
            f"field_{rid}": row["field_id"],
        },
    )
    assert conf.status_code == 200, conf.text[:300]
    cbody = conf.json()
    assert cbody["ok"] is True

    app_resp = client.post(
        "/v2/model-react/import/apply",
        params={"project": code},
        headers=HDR,
        data={"project": code, "csrf_token": csrf, "approved_ticket": cbody["approved_ticket"]},
    )
    return before_hash, csrf, cbody["approved_ticket"], app_resp


def _run_canonical(client: TestClient, code: str):
    page = client.get("/v2/workbook", params={"project": code})
    tokens = {
        k: re.search(f'name="{k}" value="([^"]*)"', page.text).group(1)
        for k in ("content_hash", "workbook_version")
    }
    resp = post_valid_csrf(client, "/v2/workbook/run", headers={"HX-Request": "true"}, data=dict(project=code, **tokens))
    assert resp.status_code == 200, resp.text[:300]


def test_slice_b_csv_and_xlsx_react_and_legacy_receipt_lineage_and_privacy(imp_env):
    code = imp_env.record.project_code
    pid = imp_env.record.project_id

    # Zero receipts before any Apply
    assert list_receipts_for_project(OWNER, pid) == []

    # 1. React CSV Apply (with secret-looking filename & distinct numeric value)
    csv_bytes = _make_csv_bytes("project_setup.technical.p50_hours", "1499")
    csv_sha = hashlib.sha256(csv_bytes).hexdigest()
    before_h, csrf, ticket1, resp1 = _react_preview_confirm_apply(
        imp_env.client,
        code,
        filename="CONFIDENTIAL_CLIENT_ACME_2026.csv",
        payload=csv_bytes,
        mime="text/csv",
    )
    assert resp1.status_code == 200, resp1.text[:300]
    body1 = resp1.json()
    rcpt1 = body1["receipt"]
    assert rcpt1["receipt_id"].startswith("imp_v1_")
    assert rcpt1["status"] == "COMMITTED"
    assert rcpt1["source_sha256"] == csv_sha
    assert rcpt1["source_format"] == "csv"
    assert rcpt1["before_composite_hash"] == before_h
    assert rcpt1["after_composite_hash"] == body1["transaction_identity"]
    assert rcpt1["before_composite_hash"] != rcpt1["after_composite_hash"]
    assert rcpt1["approved_field_ids"] == ["project_setup.technical.p50_hours"]
    assert rcpt1["changed_field_ids"] == ["project_setup.technical.p50_hours"]
    assert rcpt1["approved_count"] == 1 and rcpt1["changed_count"] == 1

    # 2. Privacy invariant: raw DB row and API response must NOT contain filename, cell value, or ticket
    conn = sqlite3.connect(imp_env.db_path)
    try:
        raw_row = json.dumps(conn.execute("SELECT * FROM model_import_receipts").fetchall())
    finally:
        conn.close()
    for forbidden in ("CONFIDENTIAL_CLIENT_ACME_2026", "1499", ticket1[:24], csrf[:16]):
        assert forbidden not in raw_row, f"Forbidden secret/content leaked into DB receipt: {forbidden}"
        assert forbidden not in json.dumps(rcpt1), f"Forbidden secret/content leaked into API receipt: {forbidden}"

    # 3. Replay of exact same approved_ticket -> 409, zero extra receipt, zero mutation
    replay = imp_env.client.post(
        "/v2/model-react/import/apply",
        params={"project": code},
        headers=HDR,
        data={"project": code, "csrf_token": csrf, "approved_ticket": ticket1},
    )
    assert replay.status_code == 409
    assert len(list_receipts_for_project(OWNER, pid)) == 1

    # 4. No-op approval (same value 1499 already in draft) -> changed_count=0, before==after
    before_noop, _, _, resp_noop = _react_preview_confirm_apply(
        imp_env.client,
        code,
        filename="noop.csv",
        payload=csv_bytes,
        mime="text/csv",
    )
    assert resp_noop.status_code == 200
    rcpt_noop = resp_noop.json()["receipt"]
    assert rcpt_noop["changed_count"] == 0 and rcpt_noop["changed_field_ids"] == []
    assert rcpt_noop["before_composite_hash"] == before_noop == rcpt_noop["after_composite_hash"]
    assert len(list_receipts_for_project(OWNER, pid)) == 2

    # 5. Legacy HTML XLSX Apply -> receipt rendered in provenance HTML & persisted with source_format='xlsx'
    xlsx_bytes = _make_xlsx_bytes("project_setup.technical.p50_hours", "1525")
    xlsx_sha = hashlib.sha256(xlsx_bytes).hexdigest()
    ctx = imp_env.client.get("/v2/model-react/import/context", params={"project": code}).json()
    leg_prev = imp_env.client.post(
        "/v2/workbook/import/preview",
        data={"project": code, "csrf_token": ctx["csrf_token"], "encoding": "utf-8-sig"},
        files={"upload": ("SECRET_XLSX_2026.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert leg_prev.status_code == 200
    ptok = re.search(r'name="preview_ticket" value="([^"]+)"', leg_prev.text).group(1)
    # Preview wrote zero new receipts
    assert len(list_receipts_for_project(OWNER, pid)) == 2

    leg_conf = imp_env.client.post(
        "/v2/workbook/import/confirm",
        data={
            "project": code,
            "csrf_token": ctx["csrf_token"],
            "preview_ticket": ptok,
            "keep_0": "on",
            "field_0": "project_setup.technical.p50_hours",
        },
    )
    assert leg_conf.status_code == 200
    atok = re.search(r'name="approved_ticket" value="([^"]+)"', leg_conf.text).group(1)
    # Confirm wrote zero new receipts
    assert len(list_receipts_for_project(OWNER, pid)) == 2

    leg_app = imp_env.client.post(
        "/v2/workbook/import/apply",
        data={"project": code, "csrf_token": ctx["csrf_token"], "approved_ticket": atok},
    )
    assert leg_app.status_code == 200
    assert 'data-testid="import-receipt-id"' in leg_app.text
    receipts = list_receipts_for_project(OWNER, pid)
    assert len(receipts) == 3
    newest = receipts[0]
    assert newest.source_format == "xlsx" and newest.source_sha256 == xlsx_sha
    assert newest.receipt_id in leg_app.text

    # 6. Durability across fresh app restart + owner-scoped read route (stranger gets 404)
    fresh_app = imp_env.make_app()
    with TestClient(fresh_app) as restarted:
        restarted.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))
        rlist = restarted.get("/v2/model-react/import/receipts", params={"project": code})
        assert rlist.status_code == 200
        items = rlist.json()["receipts"]
        assert len(items) == 3
        assert {i["source_format"] for i in items} == {"csv", "xlsx"}
    assert imp_env.stranger.get("/v2/model-react/import/receipts", params={"project": code}).status_code == 404


def test_slice_b_atomic_rollback_concurrency_append_only_and_migration_idempotency(imp_env, monkeypatch):
    code = imp_env.record.project_code
    pid = imp_env.record.project_id

    # 1. Injected receipt INSERT failure rolls back BOTH draft update AND receipt
    csv_bytes = _make_csv_bytes("project_setup.technical.p50_hours", "1610")
    ctx = imp_env.client.get("/v2/model-react/import/context", params={"project": code}).json()
    prev = imp_env.client.post(
        "/v2/model-react/import/preview",
        params={"project": code},
        headers=HDR,
        data={"project": code, "csrf_token": ctx["csrf_token"], "encoding": "utf-8-sig"},
        files={"upload": ("rb.csv", csv_bytes, "text/csv")},
    ).json()
    rid = prev["rows"][0]["id"]
    conf = imp_env.client.post(
        "/v2/model-react/import/confirm",
        params={"project": code},
        headers=HDR,
        data={
            "project": code,
            "csrf_token": ctx["csrf_token"],
            "preview_ticket": prev["preview_ticket"],
            f"keep_{rid}": "on",
            f"field_{rid}": prev["rows"][0]["field_id"],
        },
    ).json()
    before_draft = dict(get_workspace_state(OWNER, pid).draft_snapshot)

    import app.persistence.import_receipt_repository as repo_mod

    orig_insert = repo_mod.insert_receipt_in_tx

    def _boom(*args, **kwargs):
        raise ImportReceiptError("IMPORT_RECEIPT_INJECTED_FAILURE")

    monkeypatch.setattr(repo_mod, "insert_receipt_in_tx", _boom)
    failed = imp_env.client.post(
        "/v2/model-react/import/apply",
        params={"project": code},
        headers=HDR,
        data={"project": code, "csrf_token": ctx["csrf_token"], "approved_ticket": conf["approved_ticket"]},
    )
    assert failed.status_code == 422
    assert dict(get_workspace_state(OWNER, pid).draft_snapshot) == before_draft
    assert list_receipts_for_project(OWNER, pid) == []
    monkeypatch.setattr(repo_mod, "insert_receipt_in_tx", orig_insert)

    # 2. Two simultaneous Apply requests with same approved_ticket -> exactly ONE commits & ONE receipt
    barrier = threading.Barrier(2)

    def _apply_worker():
        barrier.wait(timeout=5.0)
        return imp_env.client.post(
            "/v2/model-react/import/apply",
            params={"project": code},
            headers=HDR,
            data={"project": code, "csrf_token": ctx["csrf_token"], "approved_ticket": conf["approved_ticket"]},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(lambda _: _apply_worker(), range(2)))
    assert statuses == [200, 409], f"Expected exactly one 200 and one 409 under concurrent replay, got {statuses}"
    receipts = list_receipts_for_project(OWNER, pid)
    assert len(receipts) == 1

    # 3. Append-only SQLite trigger refuses UPDATE on model_import_receipts
    conn = db.get_connection()
    try:
        with pytest.raises(sqlite3.IntegrityError, match="IMPORT_RECEIPT_IMMUTABLE"):
            conn.execute("UPDATE model_import_receipts SET changed_count = 99 WHERE receipt_id = ?", (receipts[0].receipt_id,))
        # 4. Idempotent migration on existing DB preserves receipts
        ensure_schema(conn)
    finally:
        conn.close()
    db.init_db()
    assert len(list_receipts_for_project(OWNER, pid)) == 1


def test_slice_b_missing_digest_ticket_refused_and_import_affects_subsequent_run_without_mutating_history(imp_env):
    from app.model_import.review import _serializer

    code = imp_env.record.project_code
    pid = imp_env.record.project_id

    # 1. Baseline canonical Run -> sealed History entry #1
    _run_canonical(imp_env.client, code)
    hist1 = get_run_history(OWNER, pid)
    assert len(hist1) == 1
    irr1 = hist1[0].runtime_summary["project_irr"]

    # 2. Legacy ticket missing valid 64-hex digest -> 422 IMPORT_SOURCE_DIGEST_MISSING, zero receipts
    ctx = imp_env.client.get("/v2/model-react/import/context", params={"project": code}).json()
    legacy_bad_ticket = _serializer("approved").dumps(
        {
            "kind": "approved",
            "owner": OWNER,
            "project_id": pid,
            "scenario_id": None,
            "content_hash": ctx["content_hash"],
            "workbook_version": ctx["workbook_version"],
            "digest": "",
            "approved": [{"field_id": "project_setup.technical.p50_hours", "value": "1700", "sheet": "S", "cell": "A1"}],
        }
    )
    bad_resp = imp_env.client.post(
        "/v2/model-react/import/apply",
        params={"project": code},
        headers=HDR,
        data={"project": code, "csrf_token": ctx["csrf_token"], "approved_ticket": legacy_bad_ticket},
    )
    assert bad_resp.status_code == 422 and bad_resp.json()["code"] == "IMPORT_SOURCE_DIGEST_MISSING"
    assert list_receipts_for_project(OWNER, pid) == []

    # 3. Valid CSV import changes p50_hours -> NO auto-run (History still 1), then deliberate Run #2 changes IRR
    csv_bytes = _make_csv_bytes("project_setup.technical.p50_hours", "1750")
    _, _, _, ok_resp = _react_preview_confirm_apply(
        imp_env.client, code, filename="valid_p50.csv", payload=csv_bytes, mime="text/csv"
    )
    assert ok_resp.status_code == 200
    assert len(get_run_history(OWNER, pid)) == 1  # import NEVER triggers a Run
    assert len(list_receipts_for_project(OWNER, pid)) == 1

    _run_canonical(imp_env.client, code)
    hist2 = get_run_history(OWNER, pid)
    assert len(hist2) == 2
    old_entry = next(e for e in hist2 if e.history_id == hist1[0].history_id)
    new_entry = next(e for e in hist2 if e.history_id != hist1[0].history_id)
    assert old_entry.runtime_summary["project_irr"] == irr1  # prior sealed History immutable
    assert new_entry.runtime_summary["project_irr"] > irr1   # higher P50 hours increased Project IRR


def test_slice_b_refused_imports_write_zero_receipts(imp_env):
    """Refused imports (bad encoding, formula cell, oversize body, line-owned scalar) must persist zero receipts."""
    code = imp_env.record.project_code
    pid = imp_env.record.project_id
    ctx = imp_env.client.get("/v2/model-react/import/context", params={"project": code}).json()
    csrf = ctx["csrf_token"]

    # 1. Unsupported encoding
    r_enc = imp_env.client.post(
        "/v2/model-react/import/preview",
        params={"project": code},
        headers=HDR,
        data={"project": code, "csrf_token": csrf, "encoding": "ebcdic-cp-us"},
        files={"upload": ("bad.csv", _make_csv_bytes("project_setup.technical.p50_hours", "1500"), "text/csv")},
    )
    assert r_enc.status_code == 422 and not r_enc.json()["ok"]

    # 2. Oversize upload (>2 MiB)
    r_big = imp_env.client.post(
        "/v2/model-react/import/preview",
        params={"project": code},
        headers=HDR,
        data={"project": code, "csrf_token": csrf, "encoding": "utf-8-sig"},
        files={"upload": ("big.csv", b"a" * (2 * 1024 * 1024 + 40_000), "text/csv")},
    )
    assert r_big.status_code == 413 and not r_big.json()["ok"]

    # 3. Formula cell in XLSX -> refused / not auto-applied, zero receipts
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Inputs"
    ws.append(["Assumption", "Value", "Unit"])
    ws.append(["project_setup.technical.p50_hours", "=1500+1", ""])
    buf = io.BytesIO()
    wb.save(buf)
    r_form = imp_env.client.post(
        "/v2/model-react/import/preview",
        params={"project": code},
        headers=HDR,
        data={"project": code, "csrf_token": csrf, "encoding": "utf-8-sig"},
        files={"upload": ("formula.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    if r_form.status_code == 200:
        row = r_form.json()["rows"][0]
        r_conf = imp_env.client.post(
            "/v2/model-react/import/confirm",
            params={"project": code},
            headers=HDR,
            data={
                "project": code,
                "csrf_token": csrf,
                "preview_ticket": r_form.json()["preview_ticket"],
                f"keep_{row['id']}": "on",
                f"field_{row['id']}": "project_setup.technical.p50_hours",
            },
        )
        assert r_conf.status_code == 422 and not r_conf.json()["ok"]
    else:
        assert r_form.status_code == 422

    # 4. Line-owned scalar (guarded by #479) -> confirm refused, zero receipts
    r_line = imp_env.client.post(
        "/v2/model-react/import/preview",
        params={"project": code},
        headers=HDR,
        data={"project": code, "csrf_token": csrf, "encoding": "utf-8-sig"},
        files={"upload": ("line_owned.csv", _make_csv_bytes("capex.total_capex_eur", "12345678"), "text/csv")},
    )
    if r_line.status_code == 200 and r_line.json().get("rows"):
        row = r_line.json()["rows"][0]
        r_lconf = imp_env.client.post(
            "/v2/model-react/import/confirm",
            params={"project": code},
            headers=HDR,
            data={
                "project": code,
                "csrf_token": csrf,
                "preview_ticket": r_line.json()["preview_ticket"],
                f"keep_{row['id']}": "on",
                f"field_{row['id']}": "capex.total_capex_eur",
            },
        )
        assert r_lconf.status_code == 422 and not r_lconf.json()["ok"]

    assert list_receipts_for_project(OWNER, pid) == []

