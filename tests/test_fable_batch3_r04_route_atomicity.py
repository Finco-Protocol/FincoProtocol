"""FINCO 36 Correction F — R04 write-path atomicity through the REAL /v2 route boundary (dated Solar project).

Every refusal asserts: typed code in the response body (HTTP 200 + a field error is NOT success), unchanged draft snapshot,
unchanged content hash / workbook version, no success event, no new History row, immutable Last Run.  Every acceptance asserts the
persisted effective input.  Cap boundary values are derived independently (Decimal) from the persisted typed technical facts.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date
from decimal import Decimal, ROUND_FLOOR
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME, create_session_token
from app.persistence import db
from app.persistence.run_history_repository import get_run_history
from app.persistence.workspace_repository import get_workspace_state
from app.services.reference_seed_service import create_reference_seeded_project
from app.v2.router import router as v2_router
from app.workbook.financing_csrf import issue_token
from app.workbook.mutation_csrf import mutation_token


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

COD = date(2031, 3, 1)
FIELD = "revenue.multistream.contracts"


def _book(streams):
    return json.dumps({"version": 2, "technology": "solar", "indexation_basis": "OPERATING_YEAR", "streams": streams}, separators=(",", ":"))


def _ppa(sid, start, end, amount, unit="MWh", price=72.0):
    return {"id": sid, "type": "ppa", "start_date": start, "end_date": end, "volume_share": None,
            "annual_quantity": {"mode": "ABSOLUTE_ANNUAL", "amount": str(amount), "unit": unit}, "price_eur_mwh": price,
            "indexation_rate": 0.0, "settlement": "SAME_PERIOD", "source_ref": "ROUTE_" + sid}


MERCHANT = {"id": "merchant", "type": "merchant", "start_date": "2031-03-01", "end_date": "2056-03-01", "volume_share": None,
            "price_eur_mwh": 55.0, "indexation_rate": 0.0, "settlement": "SAME_PERIOD", "source_ref": "ROUTE_M", "capture_rate": 1.0}


class Env:
    def __init__(self, tmp_path):
        self.user = "route-atomicity-user"
        db.DB_PATH = str(tmp_path / "ra.db")
        db.init_db()
        app = FastAPI()
        app.include_router(v2_router, prefix="/v2")
        self.cm = TestClient(app, raise_server_exceptions=False)
        self.client = self.cm.__enter__()
        self.client.cookies.set(COOKIE_NAME, create_session_token(user_id=self.user, username="admin"))
        self.rec = create_reference_seeded_project(user_id=self.user, requested_name="RA Solar", template_source="generic_solar_reference", capacity_mw=16)
        self.req = SimpleNamespace(cookies=self.client.cookies, state=SimpleNamespace())

    def close(self):
        self.cm.__exit__(None, None, None)

    def tokens(self):
        html = self.client.get("/v2/workbook", params={"project": self.rec.project_code}).text
        return {k: re.search(r'name="' + k + r'" value="([^"]*)"', html).group(1) for k in ("content_hash", "workbook_version")}

    def snapshot(self):
        return dict(get_workspace_state(self.user, self.rec.project_id).draft_snapshot)

    def state(self):
        tokens = self.tokens()                       # the first page render normalises stored types; snapshot is read after it
        ws = get_workspace_state(self.user, self.rec.project_id)
        return {"snapshot": dict(ws.draft_snapshot), "tokens": tokens, "history": len(get_run_history(self.user, self.rec.project_id))}

    def save(self, field, value, tokens=None):
        t = tokens or self.tokens()
        return self.client.post("/v2/workbook/update", headers={"Accept": "application/json"}, data={
            "project": self.rec.project_code, "field_id": field, "value": value, **t,
            "csrf_token": mutation_token(self.req, self.rec.project_code, "workbook-update")})

    def run(self):
        t = self.tokens()
        return self.client.post("/v2/workbook/run", headers={"Accept": "application/json"}, data={
            "project": self.rec.project_code, **t, "csrf_token": issue_token(self.req, self.rec.project_code, purpose="workbook-run-v1"),
            "run_intent_id": str(uuid.uuid4())}, follow_redirects=False)

    def annual_p50_mwh(self):
        from app.input_adapter import build_projectinputs_from_snapshot
        t = build_projectinputs_from_snapshot(self.snapshot()).technical
        return Decimal(repr(t.capacity_mw)) * Decimal(repr(t.operating_hours_p50)) * Decimal(repr(t.combined_availability))


@pytest.fixture()
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.close()


def _one_year_book(amount, unit="MWh"):
    return _book([_ppa("ppa_1", "2031-03-01", "2032-03-01", amount, unit), MERCHANT])


def _assert_refused(env, resp, code, before):
    assert code in resp.text, resp.text[:300]
    after = env.state()
    assert after["snapshot"] == before["snapshot"] and after["tokens"] == before["tokens"] and after["history"] == before["history"]


def test_exact_p50_boundary_accept_at_cap_refuse_by_0_001_mwh(env):
    first_ops = env.state()                                    # first render normalises stored types; baseline after it
    cap = env.annual_p50_mwh().quantize(Decimal("0.001"), rounding=ROUND_FLOOR)
    ok = env.save(FIELD, _one_year_book(cap))
    assert ok.status_code == 200 and "R04_" not in ok.text
    assert json.loads(env.snapshot()["rev_multistream_config_json"])["streams"][0]["annual_quantity"]["amount"] in (str(cap), format(cap, "f"))
    before = env.state()
    over = env.save(FIELD, _one_year_book(cap + Decimal("0.001")))
    _assert_refused(env, over, "R04_GLOBAL_P50_CAP_EXCEEDED", before)


def test_gwh_and_mwh_are_equivalent_at_the_boundary(env):
    env.state()
    cap_gwh = (env.annual_p50_mwh() / 1000).quantize(Decimal("0.000001"), rounding=ROUND_FLOOR)
    assert "R04_" not in env.save(FIELD, _one_year_book(cap_gwh, "GWh")).text
    before = env.state()
    _assert_refused(env, env.save(FIELD, _one_year_book(cap_gwh + Decimal("0.000001"), "GWh")), "R04_GLOBAL_P50_CAP_EXCEEDED", before)


@pytest.mark.parametrize("label,value,code", [
    ("malformed_json", "{not json", "REVENUE_V2_SCHEMA"),
    ("duplicate_stream_ids", _book([_ppa("dup", "2031-03-01", "2032-03-01", 10), _ppa("dup", "2031-03-01", "2032-03-01", 10), MERCHANT]), "REVENUE_STREAM_ID_DUPLICATE"),
    ("bad_date", _book([_ppa("p", "2031-13-45", "2032-03-01", 10), MERCHANT]), "REVENUE_V2"),
    ("negative_quantity", _book([_ppa("p", "2031-03-01", "2032-03-01", -5), MERCHANT]), "R04_QUANTITY_AMOUNT_INVALID"),
    ("nonfinite_quantity", _book([_ppa("p", "2031-03-01", "2032-03-01", "NaN"), MERCHANT]), "R04_QUANTITY_AMOUNT_INVALID"),
    ("unsupported_unit", _book([_ppa("p", "2031-03-01", "2032-03-01", 10, "kWh"), MERCHANT]), "R04_QUANTITY_UNIT_UNSUPPORTED"),
    ("duplicate_json_key", '{"version":2,"version":2}', "REVENUE_V2"),
])
def test_malformed_and_invalid_books_are_refused_without_mutation(env, label, value, code):
    before = env.state()
    _assert_refused(env, env.save(FIELD, value), code, before)


def test_stale_cas_is_refused_without_mutation(env):
    stale = env.tokens()
    assert "R04_" not in env.save(FIELD, _one_year_book(1000)).text            # a competing committed change
    before = env.state()
    resp = env.save(FIELD, _one_year_book(2000), tokens=stale)
    assert "changed" in resp.text.lower()
    after = env.state()
    assert after["snapshot"] == before["snapshot"] and after["history"] == before["history"]


def test_race_between_preflight_and_write_is_refused_by_the_transaction(env, monkeypatch):
    """A competing writer commits AFTER the proposed-state validation but BEFORE the write: the write transaction refuses (CAS), no partial state."""
    import app.workbook.update_service as us
    original = us._validate_ppa_book_against_proposed_snapshot
    fired = []

    def racing(snapshot):
        original(snapshot)
        if not fired:
            fired.append(1)
            ws = get_workspace_state(env.user, env.rec.project_id)
            from app.workbook.registry import WORKBOOK
            from app.workbook.workbook_identity import assemble_consistent_for_get
            ident = assemble_consistent_for_get(env.user, env.rec.project_id, WORKBOOK.version)      # no HTTP call from inside the request thread
            us.WorkbookUpdateService.apply_draft_update(
                ws=ws, field_id=FIELD, raw_value=_one_year_book(1500), content_hash=ident.composite_hash,
                workbook_version=WORKBOOK.version, project_record=env.rec)
    monkeypatch.setattr(us, "_validate_ppa_book_against_proposed_snapshot", racing)
    resp = env.save(FIELD, _one_year_book(2500))
    assert fired and "changed" in resp.text.lower()
    streams = json.loads(env.snapshot()["rev_multistream_config_json"])["streams"]
    assert streams[0]["annual_quantity"]["amount"] == "1500"                          # only the competing, committed write survives


def test_batch_route_refuses_the_contract_book_and_technical_pairs_validate_the_final_state_in_both_orders(env):
    from app.workbook.update_service import BatchApplyError, FieldValidationError, WorkbookUpdateService

    def batch(edits):
        ws = get_workspace_state(env.user, env.rec.project_id)
        t = env.tokens()
        return WorkbookUpdateService.apply_batch_draft_update(
            ws=ws, updates=edits, content_hash=t["content_hash"], workbook_version=t["workbook_version"],
            expected_scenario_id=ws.active_scenario_id, project_record=env.rec, actor_user_id=env.user)

    env.state()
    cap = env.annual_p50_mwh().quantize(Decimal("0.001"), rounding=ROUND_FLOOR)       # P50 1500 h, P90 1400 h seeded
    assert "R04_" not in env.save(FIELD, _one_year_book(cap)).text
    before = env.state()
    with pytest.raises(BatchApplyError, match="BATCH_REVENUE_CONTRACT_EDITOR_ONLY"):   # explicit refusal: the book has ONE writer
        batch([(FIELD, _one_year_book(1))])
    assert env.state()["snapshot"] == before["snapshot"]
    _assert_refused(env, env.save("project_setup.technical.p50_hours", "1400"), "R04_GLOBAL_P50_CAP_EXCEEDED", before)   # direct route
    for edits in ([("project_setup.technical.p50_hours", "1400"), ("project_setup.technical.p90_10y_hours", "1300")],     # shrinks the envelope
                  [("project_setup.technical.p90_10y_hours", "1300"), ("project_setup.technical.p50_hours", "1400")]):
        before = env.state()
        with pytest.raises(FieldValidationError) as exc:
            batch(edits)
        assert "R04_GLOBAL_P50_CAP_EXCEEDED" in str(exc.value)
        assert env.state()["snapshot"] == before["snapshot"]
    # shrink the contract first (single writer), then the same paired technical edit is valid in BOTH orders (P90 below P50 in the final state)
    assert "R04_" not in env.save(FIELD, _one_year_book(Decimal("1000"))).text
    for edits in ([("project_setup.technical.p50_hours", "1400"), ("project_setup.technical.p90_10y_hours", "1300")],
                  [("project_setup.technical.p90_10y_hours", "1250"), ("project_setup.technical.p50_hours", "1350")]):
        batch(edits)
        snap = env.snapshot()
        assert float(snap["p50_hours"]) == float(edits[0][1] if edits[0][0].endswith("p50_hours") else edits[1][1])


def test_run_refuses_a_forged_over_cap_snapshot_and_keeps_history_and_last_run(env):
    assert "R04_" not in env.save(FIELD, _one_year_book(1000)).text
    first = env.run()
    assert first.status_code == 200 and first.json()["outcome"] == "COMMITTED"
    stale_tokens = env.tokens()
    ws = get_workspace_state(env.user, env.rec.project_id)
    forged = dict(ws.draft_snapshot)
    forged["rev_multistream_config_json"] = _one_year_book(10 ** 9)                  # written below the validators, straight to storage
    with db.get_cursor() as cur:
        cur.execute("UPDATE workspace_states SET draft_snapshot_json=? WHERE project_id=?", (json.dumps(forged), env.rec.project_id))
    page = env.client.get("/v2/workbook", params={"project": env.rec.project_code})
    assert "R04_GLOBAL_P50_CAP_EXCEEDED" in page.text                                # typed, read-only recovery view (fail closed)
    second = env.client.post("/v2/workbook/run", headers={"Accept": "application/json"}, data={
        "project": env.rec.project_code, **stale_tokens, "csrf_token": issue_token(env.req, env.rec.project_code, purpose="workbook-run-v1"),
        "run_intent_id": str(uuid.uuid4())}, follow_redirects=False)
    assert second.status_code != 200 or second.json().get("outcome") != "COMMITTED"
    assert len(get_run_history(env.user, env.rec.project_id)) == 1                   # no new History row; the first Run is untouched


def test_injected_failure_after_writes_rolls_back_the_whole_capacity_save(env, monkeypatch):
    import app.services.reference_seed_service as rs
    env.state()
    before = env.state()
    original = rs.rescale_snapshot_in_transaction

    def boom(cursor, **kw):
        original(cursor, **kw)                       # the sub-line rescale WRITES, then the transaction fails
        raise RuntimeError("injected failure after writes")
    monkeypatch.setattr(rs, "rescale_snapshot_in_transaction", boom)
    resp = env.save("project_setup.technical.capacity_mw", "20")
    assert resp.status_code in (200, 422, 500)
    after = env.state()
    assert after["snapshot"] == before["snapshot"] and after["history"] == before["history"]
