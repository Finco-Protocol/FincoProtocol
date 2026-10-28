"""PR #394 staging corrections F1–F10 — contract and regression tests.

Synthetic data only; the real canonical routes, engine and SQLite are used (thread executor, native kernels off).  What is pinned:

* F1  the React cost-line wire format (decimal STRINGS) is accepted by the canonical batch writer for every vertical, decimals are
      preserved, Save never runs the model, and the server contract is NOT weakened (numbers, invalid amounts, stale CAS and a bad CSRF
      token are still refused);
* F3  the Last Run export names its real refusal, never claims "no committed Run" when one exists, and offers the immutable record of
      that very Run (its historical export is the same committed evidence);
* F4  lives in tests/test_pr394_f4_run_failure_reason_v1.py (separately governed: it covers the D-029 service);
* F8  Compare Projects shows the market and the MOIC a Run published, and still shows nothing for what it did not publish;
* the React-side pure helpers (F1 payload builder, F2 reserve gate, F5 reconciliation, F7 facility state, F10 identity checks) run
  through the real TypeScript sources when node and the frontend dev dependencies are present.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.persistence import db

ROOT = Path(__file__).resolve().parent.parent
OWNER = "pr394-corr-owner"
KINDS = ("solar", "wind", "data_center", "ev_charging")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "pr394_corr.db"))
    db.init_db()
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    monkeypatch.setenv("FINCO_MODEL_EXECUTION_MODE", "thread")
    monkeypatch.setenv("FINCO_NATIVE_V10_RUN", "off")
    monkeypatch.setenv("FINCO_NATIVE_V11_RUN", "off")
    from app.auth import COOKIE_NAME, create_session_token
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.v2.grid_router import router as grid_router
    from app.v2.react_compare_projects import router as compare_router
    from app.v2.react_poc_router import router as poc_router
    from app.v2.react_workspace_router import router as workspace_router
    from app.v2.router import router as v2_router

    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    app.include_router(grid_router, prefix="/v2")
    app.include_router(compare_router, prefix="/v2")
    app.include_router(workspace_router, prefix="/v2")      # before the PoC catch-all, as in main_web
    app.include_router(poc_router, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))

        def create(kind="solar", name=None, country=None):
            return create_reference_seeded_project(
                user_id=OWNER, requested_name=name or f"PR394 {kind}", template_source=f"generic_{kind}_reference",
                capacity_mw=16, country_market=country)

        yield SimpleNamespace(client=client, create=create)
    reset_model_executor_for_tests()


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────────────

def costlines(env, record, sheet):
    response = env.client.get("/v2/model-react/costlines", params={"sheet": sheet, "project": record.project_code})
    assert response.status_code == 200, response.text[:300]
    return response.json()


def save_batch(env, record, payload, edits, *, csrf=None, content_hash=None, sheet="capex"):
    save = payload["save"]
    return env.client.post(save["url"], data={
        "project": record.project_code, "csrf_token": save["csrf_token"] if csrf is None else csrf,
        "workbook_version": save["workbook_version"], "content_hash": content_hash or save["content_hash"],
        "sheet": sheet, "payload": json.dumps(edits)}, follow_redirects=False)


def first_line(payload):
    return next(line for line in payload["lines"] if line["active"] and float(line["amount_keur"] or 0) > 0)


def wire_edit(sheet, line, amount, inflation=None):
    """The exact shape frontend/src/app/costLinePayload.ts produces: decimal STRINGS."""
    edit = {"kind": sheet, "sub_line_id": line["sub_line_id"], "label": line["label"], "amount_keur": amount,
            "row_version": line["row_version"], "notes": line["notes"] or ""}
    if inflation is not None:
        edit["inflation_pct"] = inflation
    return edit


def history(env, record):
    return env.client.get("/v2/model-react/runs", params={"project": record.project_code}).json()["runs"]


def run_json(env, record, intent=None):
    from app.workbook.financing_csrf import issue_token
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    tokens = {k: re.search(f'name="{k}" value="([^"]*)"', page.text).group(1) for k in ("content_hash", "workbook_version")}
    req = SimpleNamespace(cookies=env.client.cookies, state=SimpleNamespace())
    data = {"project": record.project_code, **tokens, "csrf_token": issue_token(req, record.project_code, purpose="workbook-run-v1"),
            "run_intent_id": intent or str(uuid.uuid4())}
    return env.client.post("/v2/workbook/run", data=data, headers={"Accept": "application/json"}, follow_redirects=False)


# ── F1 ───────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", KINDS)
def test_f1_string_wire_batch_saves_capex_and_opex_for_every_vertical_without_running(env, kind):
    record = env.create(kind)
    for sheet, amount, inflation in (("capex", "1234.5678", None), ("opex", "87.125", "3.25")):
        payload = costlines(env, record, sheet)
        line = first_line(payload)
        response = save_batch(env, record, payload, [wire_edit(sheet, line, amount, inflation)], sheet=sheet)
        assert response.status_code == 200, (kind, sheet, response.text[:300])
        assert response.headers.get("X-Cost-Batch-Saved") == "1"
        after = {l["sub_line_id"]: l for l in costlines(env, record, sheet)["lines"]}[line["sub_line_id"]]
        assert float(after["amount_keur"]) == float(amount), "decimal precision must survive the save"
        if inflation is not None:
            assert float(after["inflation_pct"]) == float(inflation)
        assert after["row_version"] != line["row_version"]
    assert history(env, record) == [], "Save must never run the model"


def test_f1_batch_of_several_lines_is_atomic_and_all_saved(env):
    record = env.create("solar")
    payload = costlines(env, record, "capex")
    lines = [l for l in payload["lines"] if l["active"] and float(l["amount_keur"] or 0) > 0][:3]
    assert len(lines) == 3
    edits = [wire_edit("capex", l, f"{float(l['amount_keur']) + 10:.3f}") for l in lines]
    response = save_batch(env, record, payload, edits)
    assert response.status_code == 200 and response.headers.get("X-Cost-Batch-Saved") == "3"


def test_f1_the_server_contract_is_not_weakened(env):
    record = env.create("solar")
    payload = costlines(env, record, "capex")
    line = first_line(payload)
    before = {l["sub_line_id"]: l["amount_keur"] for l in payload["lines"]}

    numeric = wire_edit("capex", line, 1600)                                   # the old client bug: a JSON number
    refused = save_batch(env, record, payload, [numeric])
    assert refused.status_code == 422 and refused.json()["code"] == "COST_BATCH_INVALID"

    for bad in ("abc", "", "1,5", "NaN", "inf"):
        response = save_batch(env, record, payload, [wire_edit("capex", line, bad)])
        assert response.status_code == 422, (bad, response.status_code, response.text[:200])

    stale = save_batch(env, record, payload, [wire_edit("capex", line, "1")], content_hash="0" * 64)
    assert stale.status_code in (409, 422) and stale.status_code != 200
    wrong_row = dict(wire_edit("capex", line, "1"), row_version="1999-01-01T00:00:00+00:00")
    assert save_batch(env, record, payload, [wrong_row]).status_code == 409
    assert save_batch(env, record, payload, [wire_edit("capex", line, "1")], csrf="forged").status_code == 403

    again = {l["sub_line_id"]: l["amount_keur"] for l in costlines(env, record, "capex")["lines"]}
    assert again == before, "no refused save may change a stored amount"


# ── F3 ───────────────────────────────────────────────────────────────────────────────────────────────────

def _save_front_loaded_profile(record):
    from app.capex_profiles.runtime import leaves_for
    from app.capex_profiles.service import save_profiles
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
    from app.workbook.registry import WORKBOOK
    from app.workbook.service import WorkbookService
    from app.workbook.workbook_identity import assemble_consistent_for_get

    ws = get_workspace_state(record.user_id, record.project_id)
    pi = WorkbookService.to_projectinputs(WorkbookService.build_draft_input_set_from_workspace(ws))
    capex = apply_user_sub_lines_replacing_base(pi.capex, project_id=record.project_id)
    leaves = [leaf for leaf in leaves_for(capex, record.project_id) if leaf.amount_keur > 0]
    document = json.dumps({"version": 1, "profiles": [{"item_key": leaf.item_key, "shape": "FRONT_LOADED", "explicit_percent": [],
                                                      "milestone_month": None} for leaf in leaves]})
    identity = assemble_consistent_for_get(record.user_id, record.project_id, WORKBOOK.version).composite_hash
    save_profiles(owner=record.user_id, project_id=record.project_id, expected_hash=identity,
                  expected_scenario_id=ws.active_scenario_id or "", raw=document)


def test_f3_export_reasons_are_truthful_and_the_immutable_record_is_offered(env):
    record = env.create("solar")
    runs = lambda: env.client.get("/v2/model-react/runs", params={"project": record.project_code}).json()
    never_run = runs()["exports"]["last_run"]
    assert never_run["available"] is False and never_run["unavailable_code"] == "NO_COMMITTED_RUN"
    assert never_run["historical_fallback"] is None

    assert run_json(env, record).json()["outcome"] == "COMMITTED"
    plain = runs()["exports"]["last_run"]
    assert plain["available"] is True and plain["unavailable_code"] is None and plain["historical_fallback"] is None

    _save_front_loaded_profile(record)
    assert run_json(env, record).json()["outcome"] == "COMMITTED"
    payload = runs()
    closed = payload["exports"]["last_run"]
    assert closed["available"] is False and closed["unavailable_code"] == "CAPEX_PROFILE_RUN"
    assert "no committed run" not in closed["unavailable_reason"].lower(), "a committed Run exists: the reason must not say otherwise"
    fallback = closed["historical_fallback"]
    assert fallback and fallback["history_id"] == payload["runs"][0]["history_id"], "the fallback IS the committed Last Run"
    export = env.client.get(fallback["url"], params={"project": record.project_code, "history_id": fallback["history_id"]})
    assert export.status_code == 200 and export.content[:2] == b"PK", "an XLSX of the immutable Run record"
    assert len(export.content) > 10_000


# ── F8 ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_f8_compare_projects_shows_market_and_published_moic_but_nothing_invented(env):
    ran = env.create("solar", name="PR394 cmp ran", country="DE")
    idle = env.create("wind", name="PR394 cmp idle", country="FR")
    assert run_json(env, ran).json()["outcome"] == "COMMITTED"
    data = env.client.get("/v2/model-react/compare-projects", params=[("code", ran.project_code), ("code", idle.project_code)]).json()
    cols = {c["code"]: c for c in data["columns"]}
    assert cols[ran.project_code]["country"] == "Germany" and cols[idle.project_code]["country"] == "France"
    moic = cols[ran.project_code]["metrics"]["pure_equity_moic"]
    assert moic not in ("—", "", None) and str(moic).endswith("x"), moic
    assert cols[idle.project_code]["run_state"] == "NOT_RUN"
    assert cols[idle.project_code]["metrics"].get("pure_equity_moic") in ("—", "", None), "a project without a Run stays unavailable, never zero"


# ── pure React helpers through the real TypeScript sources ───────────────────────────────────────────────────

ESBUILD = ROOT / "frontend/node_modules/.bin/esbuild"
needs_node = pytest.mark.skipif(shutil.which("node") is None or not ESBUILD.exists(),
                                reason="needs node and the frontend dev dependencies (esbuild)")


def _node(tmp_path, entry_source, program):
    entry = tmp_path / "entry.ts"
    entry.write_text(entry_source, encoding="utf-8")
    bundle = tmp_path / "bundle.mjs"
    subprocess.run([str(ESBUILD), str(entry), "--bundle", "--format=esm", "--platform=node", f"--outfile={bundle}", "--log-level=error"],
                   check=True, cwd=ROOT / "frontend")
    script = tmp_path / "run.mjs"
    script.write_text(f"import * as M from {json.dumps(bundle.as_uri())};\n{program}", encoding="utf-8")
    out = subprocess.run(["node", str(script)], check=True, capture_output=True, text=True, cwd=ROOT / "frontend").stdout
    return json.loads(out)


APP = ROOT / "frontend/src/app"


@needs_node
def test_f1_payload_builder_emits_strings_preserves_text_and_stops_on_invalid(tmp_path):
    out = _node(tmp_path, f"export * from {json.dumps(str(APP / 'costLinePayload.ts'))};", """
const lines=[{sub_line_id:"a",label:"PV",amount_keur:1560,inflation_pct:2,notes:"n",row_version:"v1"},{sub_line_id:"b",label:"Mast",amount_keur:null,row_version:"v2"}];
const ok=M.buildCostLineEdits("opex",{a:{amount_keur:" 1600.50 ",inflation_pct:" 3.25 "}},lines);
const keep=M.buildCostLineEdits("opex",{a:{label:"PV2"}},lines);
const blankInfl=M.buildCostLineEdits("opex",{a:{amount_keur:"1",inflation_pct:" "}},lines);
const capex=M.buildCostLineEdits("capex",{a:{amount_keur:"7.125"},b:{notes:"x"}},lines);
const bad=M.buildCostLineEdits("capex",{a:{amount_keur:"abc"}},lines);
const bad2=M.buildCostLineEdits("opex",{a:{amount_keur:"1",inflation_pct:"1e3"}},lines);
console.log(JSON.stringify({ok,keep,blankInfl,capex,bad,bad2}));""")
    assert out["ok"]["edits"][0] == {"kind": "opex", "sub_line_id": "a", "label": "PV", "amount_keur": "1600.50",
                                     "row_version": "v1", "notes": "n", "inflation_pct": "3.25"}
    assert out["keep"]["edits"][0]["amount_keur"] == "1560" and "inflation_pct" not in out["keep"]["edits"][0]
    assert "inflation_pct" not in out["blankInfl"]["edits"][0], "blank inflation keeps the stored escalation (key omitted)"
    assert [e["amount_keur"] for e in out["capex"]["edits"]] == ["7.125", "0"] and all("inflation_pct" not in e for e in out["capex"]["edits"])
    assert out["bad"]["ok"] is False and "Nothing was saved" in out["bad"]["message"]
    assert out["bad2"]["ok"] is False
    assert all(isinstance(e["amount_keur"], str) for e in out["ok"]["edits"] + out["capex"]["edits"])


@needs_node
def test_f2_reserve_gate_blocks_new_unreleased_policies_and_preserves_stored_ones(tmp_path):
    out = _node(tmp_path, f"export * from {json.dumps(str(APP / 'financing/serializeBankability.ts'))};", """
const view=(reserve)=>({available:true,config:reserve?{version:1,reserve}:{version:1},periods:[],scalar_target:1.2,fees:{},mode:"flat_dscr_sculpted"});
const stored={mode:"dsrf",months:0,requirement_keur:100,commitment_keur:150,fee_pct:0.5};
const vDsrf=view(stored), dDsrf=M.draftFromView(vDsrf);
const roundtrip=JSON.parse(M.serializeBankability(dDsrf)).reserve;
const edited=JSON.parse(M.serializeBankability({...dDsrf,sizingMode:"flat_dscr_sculpted"}));
const vNone=view(undefined), dNone=M.draftFromView(vNone);
const tryNew=(mode)=>M.advisoryProblems({...dNone,reserveMode:mode,requirement:"10",commitment:"20",feePct:"1",months:"6"},vNone);
const storedAuto={mode:"automatic_peak",months:9,requirement_keur:0,commitment_keur:0,fee_pct:0};
const rtAuto=JSON.parse(M.serializeBankability(M.draftFromView(view(storedAuto)))).reserve;
console.log(JSON.stringify({released:M.RELEASED_RESERVE_MODES,roundtrip,edited:edited.reserve,
  newDsrf:tryNew("dsrf"),newAuto:tryNew("automatic_peak"),newCash:tryNew("cash_fixed"),newNone:tryNew("none"),
  keepStoredDsrf:M.advisoryProblems(dDsrf,vDsrf),rtAuto,isRel:["inherit","none","cash_fixed","dsrf","automatic_peak"].map(m=>[m,M.isReleasedReserveMode(m)])}));""")
    assert out["released"] == ["inherit", "none", "cash_fixed"]
    assert out["roundtrip"] == {"mode": "dsrf", "months": 0, "requirement_keur": 100, "commitment_keur": 150, "fee_pct": 0.5}, \
        "a stored unreleased policy is written back exactly as stored — never reset, never rewritten to NONE"
    assert out["edited"] == out["roundtrip"], "editing another bankability field must not touch the stored reserve"
    assert any("not released" in p for p in out["newDsrf"]) and any("not released" in p for p in out["newAuto"])
    assert out["newCash"] == [] and out["newNone"] == []
    assert out["keepStoredDsrf"] == [], "keeping the stored policy is not a new selection"
    assert out["rtAuto"] == {"mode": "automatic_peak", "months": 9, "requirement_keur": 0, "commitment_keur": 0, "fee_pct": 0}
    assert dict(map(tuple, out["isRel"])) == {"inherit": True, "none": True, "cash_fixed": True, "dsrf": False, "automatic_peak": False}


@needs_node
def test_f5_reconciliation_classifies_lost_responses_from_canonical_state(tmp_path):
    out = _node(tmp_path, f"export * from {json.dumps(str(APP / 'gridReconcile.ts'))}; export * from {json.dumps(str(APP / 'costLinePayload.ts'))};", """
const attempt={cells:[{field_id:"f.a",value:"22"},{field_id:"f.b",value:"3.50"}],baselineHash:"H0"};
const rows=(a,b)=>[{field_id:"f.a",value:a},{field_id:"f.b",value:b}];
const g=(hash,a,b)=>M.classifyAttempt(attempt,{save:{content_hash:hash},rows:rows(a,b)});
const edits=[{kind:"capex",sub_line_id:"x",label:"PV",amount_keur:"1600.0",row_version:"v1",notes:""},{kind:"opex",sub_line_id:"y",label:"O",amount_keur:"5",inflation_pct:"2",row_version:"v9",notes:""}];
const lines=(vx,ax,vy,ay,iy)=>[{sub_line_id:"x",label:"PV",amount_keur:ax,row_version:vx,notes:null},{sub_line_id:"y",label:"O",amount_keur:ay,inflation_pct:iy,row_version:vy,notes:""}];
console.log(JSON.stringify({
 notCommitted:g("H0","20","3.5"), committed:g("H1","22.0","3.5"), committedText:g("H1","22","3.50"), elsewhere:g("H2","21","3.5"), partial:g("H3","22","9"),
 batchNot:M.classifyBatchAttempt(edits,lines("v1",1560,"v9",5,2)), batchDone:M.classifyBatchAttempt(edits,lines("v2",1600,"v10",5,2)),
 batchElse:M.classifyBatchAttempt(edits,lines("v2",1601,"v10",5,2)), batchMissing:M.classifyBatchAttempt(edits,[]), same:[M.sameCellValue("22","22.0"),M.sameCellValue("","0"),M.sameCellValue(null,"")]}));""")
    assert out["notCommitted"] == "not_committed" and out["committed"] == "committed" and out["committedText"] == "committed"
    assert out["elsewhere"] == "changed_elsewhere" and out["partial"] == "changed_elsewhere"
    assert out["batchNot"] == "not_committed" and out["batchDone"] == "committed"
    assert out["batchElse"] == "changed_elsewhere" and out["batchMissing"] == "changed_elsewhere"
    assert out["same"] == [True, False, True]


@needs_node
def test_f7_f10_unconfigured_facility_and_identity_checks(tmp_path):
    out = _node(tmp_path, f"export * from {json.dumps(str(APP / 'financing/facilityState.ts'))}; export * from {json.dumps(str(APP / 'financing/serializeAgreement.ts'))};", """
console.log(JSON.stringify({
 draftZero:M.isUnconfiguredFacility({status:"DRAFT",commitment_keur:0,draws_total_keur:0}),
 draftReal:M.isUnconfiguredFacility({status:"DRAFT",commitment_keur:500,draws_total_keur:0}),
 activeZero:M.isUnconfiguredFacility({status:"ACTIVE",commitment_keur:0,draws_total_keur:0}),
 blank:M.identityProblems({agreementId:" ",investors:[{investorId:"",ownershipPct:"100",commitment:"1"}],contributions:[{investorId:"",cashDate:"2030-01-01",amount:"1"}]}),
 fine:M.identityProblems({agreementId:"AGR-1",investors:[{investorId:"A",ownershipPct:"100",commitment:"1"}],contributions:[]}),
 internal:M.friendlyAgreementError("F4 requires explicit, nonblank identities"), other:M.friendlyAgreementError("Ownership must total 100%"), none:M.friendlyAgreementError(undefined)}));""")
    assert out["draftZero"] is True and out["draftReal"] is False and out["activeZero"] is False
    assert len(out["blank"]) == 3 and out["fine"] == []
    assert "F4" not in out["internal"] and out["other"] == "Ownership must total 100%" and out["none"]
