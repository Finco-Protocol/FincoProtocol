"""FINCO45B (B1, OD-TIME-01 promotion: P1-REV-05, E2E-05/06/07/09, F2-NEW-02, OD-TIME-01).

New ordinary Solar/Wind projects are created under ``OD-TIME-01/v1`` (explicit, persisted snapshot version) with NO
flag set; existing projects, clones, references, Data Center / EV Charging / BESS / quarterly keep their stored or
released contract; ``FINCO_NEW_PROJECT_DATE_AUTHORITY=legacy`` rolls back NEW creations only.

The dated economics are checked through the real HTTP stack (authenticated create -> canonical writer edits of COD /
construction / horizon -> explicit Run -> Run History P&L -> institutional XLSX) against an independent day-by-day
Fraction oracle for OPEX (no engine code shared) and an exact day count of the operating life. Synthetic data only.
"""
from __future__ import annotations

import io
import uuid
from datetime import date, timedelta
from decimal import Decimal

import openpyxl
import pytest

from app.persistence.workspace_repository import get_workspace_state
from app.services import new_project_calendar as npc
from tests.test_finco45a_slice_b_opex_preview import _daily_dated_opex_oracle
from tests.test_model_react_wf2_projections_v1 import OWNER, env  # noqa: F401  (shared real-app fixture)

DATED = "OD-TIME-01/v1"


@pytest.fixture(autouse=True)
def _thread_executor(monkeypatch):
    from app.runtime.model_execution import ModelExecutionConfig, ModelExecutor, reset_model_executor_for_tests
    monkeypatch.delenv(npc.ENV, raising=False)                    # prove the DEFAULT, never a monkeypatched ON
    monkeypatch.setenv("FINCO_MODEL_EXECUTION_MODE", "thread")
    reset_model_executor_for_tests(ModelExecutor(ModelExecutionConfig(mode="thread")))


def _version(record):
    return get_workspace_state(OWNER, record.project_id).draft_snapshot.get("date_authority_version")


def _edit(env, record, **fields):
    from app.workbook.registry import WORKBOOK
    from app.workbook.update_service import WorkbookUpdateService
    ws = get_workspace_state(OWNER, record.project_id)
    projection = env.client.get("/v2/model-react/fields/project_setup", params={"project": record.project_code}).json()
    updates = [(f"project_setup.technical.{k}", str(v)) for k, v in fields.items()]
    WorkbookUpdateService.apply_batch_draft_update(
        ws=ws, updates=updates, content_hash=projection["save"]["content_hash"], workbook_version=WORKBOOK.version,
        expected_scenario_id=ws.active_scenario_id, project_record=record, actor_user_id=record.user_id)


def _run(env, record):
    shell = env.client.get("/v2/model-react/workspace", params={"project": record.project_code}).json()
    meta = env.client.get("/v2/model-react/runs", params={"project": record.project_code}).json()
    response = env.client.post("/v2/workbook/run", headers={"Accept": "application/json"}, data={
        "project": record.project_code, "csrf_token": meta["run_contract"]["csrf_token"],
        "content_hash": shell["workbook"]["composite_hash"], "workbook_version": shell["workbook"]["version"],
        "run_intent_id": str(uuid.uuid4())})
    return response, meta


# ── creation semantics ────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind,expected", [("solar", DATED), ("wind", DATED), ("data_center", None),
                                           ("ev_charging", None)])
def test_new_project_creation_default(env, kind, expected):
    record = env.create(kind)
    assert _version(record) == expected
    from app.persistence.projects_repository import get_project_by_code
    assert (get_project_by_code(OWNER, record.project_code).baseline_snapshot or {}).get("date_authority_version") == expected


def test_react_http_create_persists_the_dated_version(tmp_path, monkeypatch):
    from tests.test_model_react_rcm_new_project_v1 import BASE, env as rcm_env_fixture  # noqa: F401
    from app.persistence import db
    from app.persistence.projects_repository import list_project_records
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    from app.v2.react_poc_router import router as poc_router
    from app.v2.react_workspace_router import router as workspace_router
    from app.v2.router import router as v2_router

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "b1_http.db"))
    db.init_db()
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    app = FastAPI()
    for r in (v2_router, workspace_router, poc_router):
        app.include_router(r, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id="b1-owner", username="admin"))
        for tech in ("solar", "wind"):
            opts = client.get(f"{BASE}/options").json()
            body = {"request_id": opts["request_id"], "csrf_token": opts["csrf_token"], "name": f"B1 {tech}",
                    "technology": tech, "country": "XA", "capacity_mw": 20.0, "acknowledge_preview": False}
            created = client.post(f"{BASE}/create", json=body)
            assert created.status_code == 200 and created.json()["ok"], created.text[:300]
        records = list_project_records(user_id="b1-owner")
        assert len(records) == 2
        for rec in records:
            assert get_workspace_state("b1-owner", rec.project_id).draft_snapshot["date_authority_version"] == DATED


def test_rollback_affects_new_creations_only(env, monkeypatch):
    dated = env.create("solar")
    monkeypatch.setenv(npc.ENV, "legacy")
    legacy = env.create("solar")
    assert _version(legacy) is None and _version(dated) == DATED       # the older dated project is not reinterpreted
    monkeypatch.delenv(npc.ENV)
    assert _version(legacy) is None                                    # nor the legacy one by a later default


@pytest.mark.parametrize("value,enabled", [("", True), ("OD-TIME-01/v1", True), ("on", True), ("legacy", False),
                                           ("0", False), ("off", False), ("garbage", False)])
def test_rollback_switch_parsing(monkeypatch, value, enabled):
    monkeypatch.setenv(npc.ENV, value)
    assert npc.dated_default_enabled() is enabled


def test_stamp_never_overrides_and_never_admits_unsupported(monkeypatch):
    explicit = {"date_authority_version": "LEGACY_CALENDAR/v0"}
    assert npc.stamp_new_project_date_authority(explicit, template_source="generic_solar_reference") == explicit
    for source in ("generic_data_center_reference", "generic_ev_charging_reference", "generic_storage_reference"):
        assert "date_authority_version" not in npc.stamp_new_project_date_authority({}, template_source=source)
    for kind in ("Data Center", "EV Charging", "Storage"):
        assert "date_authority_version" not in npc.stamp_new_project_date_authority({}, project_type=kind)
    from app.workbook.quarterly_frequency_config import SNAPSHOT_KEY as Q_KEY
    assert "date_authority_version" not in npc.stamp_new_project_date_authority(
        {Q_KEY: '{"frequency":"3/3"}'}, template_source="generic_wind_reference")
    assert "date_authority_version" not in npc.stamp_new_project_date_authority(
        {"bess_enabled": True}, project_type="Solar")


@pytest.mark.parametrize("kind", ["data_center", "ev_charging"])
def test_explicit_dated_request_on_unsupported_verticals_keeps_its_typed_refusal(env, kind):
    from app.input_adapter import SnapshotInputError, build_projectinputs_from_snapshot
    record = env.create(kind)
    snap = dict(get_workspace_state(OWNER, record.project_id).draft_snapshot)
    assert "date_authority_version" not in snap
    snap["date_authority_version"] = DATED
    with pytest.raises(SnapshotInputError, match="DATE_AUTHORITY_TECHNOLOGY_UNSUPPORTED"):
        build_projectinputs_from_snapshot(snap)


def test_protected_reference_templates_stay_unversioned(env):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services.project_library_service import ensure_reference_models
    ensure_reference_models()
    env.create("solar")
    for source in ("generic_solar_reference", "generic_wind_reference"):
        ref = get_reference_by_template_source(source)
        assert "date_authority_version" not in (ref.baseline_snapshot or {})


def test_legacy_project_is_never_migrated_by_read_edit_or_run(env, monkeypatch):
    monkeypatch.setenv(npc.ENV, "legacy")
    record = env.create("solar")
    monkeypatch.delenv(npc.ENV)
    env.client.get("/v2/model-react/workspace", params={"project": record.project_code})
    env.client.get("/v2/model-react/opex-projection", params={"project": record.project_code})
    _edit(env, record, horizon_years=24)
    response, _ = _run(env, record)
    assert response.status_code == 200 and response.json()["outcome"] == "COMMITTED"
    assert _version(record) is None
    from app.persistence.run_history_repository import get_latest_history_entry
    op = env.client.get("/v2/model-react/opex-projection", params={"project": record.project_code}).json()
    assert op["operating_preview"]["date_authority_version"] == "LEGACY_CALENDAR/v0"
    assert get_latest_history_entry(OWNER, record.project_id) is not None


# ── dated economics through the real HTTP stack ───────────────────────────────────────────────────────────────

CASES = [
    # kind, COD, construction months, horizon years  (construction where the seeded CAPEX timing admits it)
    ("solar", "2031-01-01", 12, 20),
    ("solar", "2031-05-15", 18, 25),          # mid-month COD -> short first and final stubs
    ("wind", "2028-02-29", 48, 30),           # leap COD reachable from a leap close (2024-02-29 + 48 months)
    ("wind", "2031-05-15", 24, 25),
    ("solar", "2032-07-01", 36, 25),
    ("wind", "2032-03-01", 24, 25),           # first operating year inside a leap calendar year (366 days)
]


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_six_month_construction_keeps_its_typed_engine_refusal_on_both_calendars(env, monkeypatch, kind):
    """Not admitted (pre-existing, identical on LEGACY and dated): the seeded CAPEX timing / SHL maturity grid
    refuse a 6-month construction with a typed fail-closed Run outcome, never a silent dated admission or a 5xx."""
    for authority in ("legacy", ""):
        monkeypatch.setenv(npc.ENV, authority) if authority else monkeypatch.delenv(npc.ENV, raising=False)
        record = env.create(kind)
        monkeypatch.delenv(npc.ENV, raising=False)
        _edit(env, record, cod_date="2031-05-15", construction_months=6, horizon_years=25)
        response, _ = _run(env, record)
        assert response.status_code == 409 and response.json()["error_code"] == "ENGINE_FAILED"


@pytest.mark.parametrize("cod,months", [("2032-02-29", 24), ("2031-05-31", 3), ("2031-03-30", 13)])
def test_unreachable_cod_is_refused_at_save_not_500_on_read(env, cod, months):
    from app.workbook.update_service import FieldValidationError
    record = env.create("wind")
    with pytest.raises(FieldValidationError, match="COD_CONSTRUCTION_AXIS_UNREACHABLE"):
        _edit(env, record, cod_date=cod, construction_months=months)
    shell = env.client.get("/v2/model-react/workspace", params={"project": record.project_code})
    assert shell.status_code == 200                                    # nothing was saved; reads stay healthy


@pytest.mark.parametrize("kind,cod,construction,horizon", CASES)
def test_dated_project_save_run_history_xlsx_match_the_independent_oracle(env, kind, cod, construction, horizon):
    record = env.create(kind)
    assert _version(record) == DATED
    _edit(env, record, cod_date=cod, construction_months=construction, horizon_years=horizon)
    assert _version(record) == DATED                                   # canonical writer keeps the persisted version
    snap = get_workspace_state(OWNER, record.project_id).draft_snapshot
    assert str(snap["cod_date"]) == cod and int(float(snap["horizon_years"])) == horizon

    op = env.client.get("/v2/model-react/opex-projection", params={"project": record.project_code}).json()["operating_preview"]
    assert op["status"] == "OK" and op["date_authority_version"] == DATED
    cod_d = date.fromisoformat(cod)
    ops = [p for p in op["periods"] if p["is_operation"]]
    # exact operating life: [COD, COD + horizon years) with a Feb-29 clamp, covered once by the half-open rows
    end_y = cod_d.year + horizon
    end_excl = date(end_y, 2, 28) if (cod_d.month, cod_d.day) == (2, 29) and not (end_y % 4 == 0 and (end_y % 100 or end_y % 400 == 0)) else cod_d.replace(year=end_y)
    assert date.fromisoformat(ops[0]["period_start"]) <= cod_d
    assert date.fromisoformat(ops[-1]["period_end"]) + timedelta(days=1) >= end_excl

    # independent OPEX oracle (y1 budget and per-line inflation read from the persisted canonical lines)
    from app.persistence.opex_sub_lines import get_active_sub_lines_for_project
    from collections import defaultdict
    lines = get_active_sub_lines_for_project(record.project_id)
    rates = defaultdict(Decimal)
    for line in lines:
        rates[Decimal(str(line.inflation_pct or 0)) / 100] += Decimal(str(line.amount_keur))
    contingency_free = len(rates) >= 1
    assert contingency_free
    expected = {}
    for rate, y1 in rates.items():
        for idx, value in _daily_dated_opex_oracle(op["periods"], cod=cod_d, horizon_years=horizon, y1_budget=y1,
                                                   inflation=rate).items():
            expected[idx] = expected.get(idx, 0) + value

    response, meta = _run(env, record)
    assert response.status_code == 200, response.text[:400]
    assert response.json()["outcome"] == "COMMITTED"
    from app.persistence.run_history_repository import get_latest_history_entry
    entry = get_latest_history_entry(OWNER, record.project_id)
    hist = {i: p for i, p in enumerate(entry.financial_statements["pnl"]["periods"])}
    by_index = {p["period_index"]: p for p in op["periods"]}
    total_preview = Decimal(0)
    total_oracle = Decimal(0)
    for idx, value in expected.items():
        oracle = Decimal(value.numerator) / Decimal(value.denominator)
        total_oracle += oracle
        total_preview += Decimal(repr(by_index[idx]["operating_expenses_keur"]))
    # The preview carries every derived OPEX (incl. B.13 contingency where seeded) on the same dated clock: the
    # oracle covers the line budgets, so compare the ratio of totals (contingency is a fixed % of the base).
    ratio = total_preview / total_oracle
    assert Decimal(1) <= ratio < Decimal("1.25"), ratio              # only the seeded % contingency on top
    for idx, value in expected.items():
        oracle = Decimal(value.numerator) / Decimal(value.denominator) * ratio
        assert abs(Decimal(repr(by_index[idx]["operating_expenses_keur"])) - oracle) <= Decimal("1e-9"), (idx, cod)
    # committed Run evidence equals the preview (2 dp persisted)
    assert len(hist) == len(op["periods"])
    for i, p in enumerate(op["periods"]):
        assert round(p["operating_expenses_keur"], 2) == pytest.approx(float(hist[i]["operating_expenses_keur"]), abs=1e-9)

    after = env.client.get("/v2/model-react/opex-projection", params={"project": record.project_code}).json()
    assert after["operating_preview"]["freshness"]["state"] == "CURRENT"
    g10 = env.client.get("/v2/model-react/opex-run-projection", params={"project": record.project_code}).json()
    assert g10["status"] == "OK" and g10["freshness"]["state"] == "CURRENT"

    xlsx = env.client.post("/v2/workbook/export", data={"project": record.project_code,
                                                         "csrf_token": meta["exports"]["last_run"]["csrf_token"]})
    assert xlsx.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(xlsx.content))
    formulas = sum(1 for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.data_type == "f")
    assert formulas == 0                                               # institutional export carries values only

    _edit(env, record, horizon_years=horizon - 1)                     # horizon edit after the Run: STALE, still dated
    assert _version(record) == DATED
    stale = env.client.get("/v2/model-react/opex-run-projection", params={"project": record.project_code}).json()
    assert stale["freshness"]["state"] == "STALE" and stale["run"]["history_id"] == entry.history_id


def test_quarterly_selection_on_a_dated_project_is_a_typed_refusal(env):
    """The release-closed 3/3 frequency stays a LEGACY_CALENDAR/v0 feature: no silent dated/quarterly mix."""
    from app.input_adapter import SnapshotInputError, build_projectinputs_from_snapshot
    from app.workbook.quarterly_frequency_config import SNAPSHOT_KEY as Q_KEY
    from tests.test_rc7b_quarterly_production_acceptance import TIMELINE  # noqa: F401 - module import proves availability
    record = env.create("solar")
    snap = dict(get_workspace_state(OWNER, record.project_id).draft_snapshot)
    assert snap["date_authority_version"] == DATED
    snap[Q_KEY] = '{"version": 1}'
    with pytest.raises(SnapshotInputError, match="DATE_AUTHORITY_FREQUENCY_UNSUPPORTED|QUARTERLY"):
        build_projectinputs_from_snapshot(snap)



@pytest.mark.parametrize("name", ["EV Charging Hub Solar", "Data Center Rooftop PV", "ev_charging site"])
def test_names_the_engine_admission_refuses_are_not_stamped(env, name):
    """Review finding: finco_core's dated admission refuses projects whose name/code carries a DC/EV token; such a
    new Solar project stays on the released legacy contract instead of being created into a refusal."""
    from app.services.reference_seed_service import create_reference_seeded_project
    record = create_reference_seeded_project(user_id=OWNER, requested_name=name,
                                             template_source="generic_solar_reference", capacity_mw=16)
    assert _version(record) is None
    assert npc.stamp_new_project_date_authority({"bess_native_config_json": "{}"}, project_type="Solar") == \
        {"bess_native_config_json": "{}"}


def test_legacy_run_route_refuses_a_dated_project_before_any_write(env):
    """Review finding: the legacy POST /run engine path ignores the persisted date authority; it now refuses an
    OD-TIME-01/v1 project with a typed 409 and writes nothing (the workbook Run is the supported path)."""
    import asyncio
    from types import SimpleNamespace
    from app.services import run_service
    from app.persistence.run_history_repository import get_run_history
    record = env.create("solar")
    ws = get_workspace_state(OWNER, record.project_id)
    deps = SimpleNamespace(collect_form_snapshot=lambda form: {"active_project": record.project_code},
                           project_workspace_from_snapshot=lambda user, snap: (record, ws))
    outcome = asyncio.run(run_service.execute_run_route(
        request=None, user=SimpleNamespace(user_id=OWNER, is_demo=False), form={}, deps=deps))
    assert outcome.status_code == 409 and "LEGACY_RUN_DATED_UNSUPPORTED" in outcome.context["errors"][0]
    assert get_run_history(OWNER, record.project_id) == []
    assert get_workspace_state(OWNER, record.project_id).draft_snapshot == ws.draft_snapshot
