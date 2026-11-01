"""ON-08 OD-1(A): the two generic-SHL period indices follow the EFFECTIVE geometry on a qualifying Working Copy.

Real authenticated HTTP (save-all, workbook run), real engine, real SQLite, real Run intent / CAS / run history.  Only the
Run-route hook is new: every other input, the repayment method and the Last Run semantics are asserted unchanged.
"""
from __future__ import annotations

import csv
import dataclasses
import re
import uuid
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.persistence import db
from app.services import on08_shl_index_authority as on08

ROOT = Path(__file__).resolve().parent.parent
OWNER, STRANGER = "on08-owner", "on08-stranger"
H, C = "project_setup.technical.horizon_years", "project_setup.technical.construction_months"


# ── pure helper ──────────────────────────────────────────────────────────────────────────────────────────

def test_geometry_formula_semestrial_and_annual():
    assert on08.geometry_indices(construction_months=20, horizon_years=25, senior_tenor_years=15, period_frequency="Semestrial") == (53, 34)
    assert on08.geometry_indices(construction_months=18, horizon_years=25, senior_tenor_years=12, period_frequency="Semestrial") == (52, 27)
    assert on08.geometry_indices(construction_months=20, horizon_years=25, senior_tenor_years=15, period_frequency="Annual") == (1 + 25 - 1 + 1, 2 + 15)
    # ceil on months: 13 months = 3 semestrial periods
    assert on08.geometry_indices(construction_months=13, horizon_years=10, senior_tenor_years=5, period_frequency="Semestrial") == (3 + 20 - 1, 3 + 10)


@pytest.mark.parametrize("frequency", ["Quarterly", "Monthly", "", "semestrial", None])
def test_unknown_frequency_is_refused_never_defaulted(frequency):
    with pytest.raises(on08.On08ShlIndexRefusal) as caught:
        on08.geometry_indices(construction_months=18, horizon_years=25, senior_tenor_years=12, period_frequency=frequency)
    assert caught.value.code == "ON08_SHL_UNSUPPORTED_FREQUENCY"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 12.5, True, "12", None])
def test_non_finite_or_non_integral_terms_are_refused(bad):
    with pytest.raises(on08.On08ShlIndexRefusal) as caught:
        on08.geometry_indices(construction_months=18, horizon_years=bad, senior_tenor_years=12, period_frequency="Semestrial")
    assert caught.value.code == "ON08_SHL_NON_INTEGRAL_TERM"


# ── real HTTP environment ────────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "on08.db"))
    db.init_db()
    for key, value in (("FINCO_MODEL_REACT_V1", "1"), ("FINCO_MODEL_EXECUTION_MODE", "thread"),
                       ("FINCO_NATIVE_V10_RUN", "off"), ("FINCO_NATIVE_V11_RUN", "off")):
        monkeypatch.setenv(key, value)
    from app.auth import COOKIE_NAME, create_session_token
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.v2.grid_router import router as grid_router
    from app.v2.react_workspace_router import router as workspace_router
    from app.v2.router import router as v2_router
    from app.workbook.financing_csrf import issue_token

    app = FastAPI()
    for router in (v2_router, grid_router, workspace_router):
        app.include_router(router, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))

        def create(kind, name=None):
            return create_reference_seeded_project(user_id=OWNER, requested_name=name or f"ON08 {kind} {uuid.uuid4().hex[:5]}",
                                                   template_source=f"generic_{kind}_reference", capacity_mw=40, country_market="XA")

        def tokens(record):
            page = client.get("/v2/workbook", params={"project": record.project_code})
            return {k: re.search(f'name="{k}" value="([^"]*)"', page.text).group(1) for k in ("content_hash", "workbook_version")}

        def purpose_token(record, purpose):
            return issue_token(SimpleNamespace(cookies=client.cookies, state=SimpleNamespace()), record.project_code, purpose=purpose)

        def save(record, cells):
            t = tokens(record)
            body = {"project": record.project_code, "csrf_token": purpose_token(record, "model-save-all-v1"), **t,
                    "request_id": "r-" + uuid.uuid4().hex[:16], "cells": [{"field_id": f, "value": v} for f, v in cells]}
            response = client.post("/v2/workbook/save-all", json=body)
            assert response.status_code == 200, response.text[:300]

        def run(record, intent=None):
            data = {"project": record.project_code, **tokens(record), "csrf_token": purpose_token(record, "workbook-run-v1"),
                    "run_intent_id": intent or str(uuid.uuid4())}
            return client.post("/v2/workbook/run", data=data, headers={"Accept": "application/json"}, follow_redirects=False)

        def history(record):
            return client.get("/v2/model-react/runs", params={"project": record.project_code}).json()["runs"]

        yield SimpleNamespace(client=client, create=create, save=save, run=run, history=history, tokens=tokens, purpose_token=purpose_token)
    reset_model_executor_for_tests()


@pytest.fixture()
def spy(monkeypatch):
    """Records the exact ProjectInputs override handed to the engine and the one the D-029 fingerprint was taken over."""
    import app.api.project_runner as runner
    from app.services import run_intent_service as ri
    seen = SimpleNamespace(engine=[], fingerprint=[])
    original_run, original_identity = runner.run_project, ri.effective_identity

    def run_project(*args, **kwargs):
        seen.engine.append(kwargs.get("project_inputs_override"))
        return original_run(*args, **kwargs)

    def effective_identity(override, **kwargs):
        seen.fingerprint.append(override)
        return original_identity(override, **kwargs)

    monkeypatch.setattr(runner, "run_project", run_project)
    monkeypatch.setattr(ri, "effective_identity", effective_identity)
    return seen


def indices(inputs):
    f = inputs.financing
    return f.shl_maturity_period_index, f.shl_principal_eligibility_start_period


def only_two_indices_differ(a, b):
    da, db_ = dataclasses.asdict(a), dataclasses.asdict(b)
    changed = {k for k in da["financing"] if da["financing"][k] != db_["financing"][k]}
    rest = {k for k in da if k != "financing" and da[k] != db_[k]}
    return changed, rest


# ── positives (authenticated V2 route) ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind,cells,expected", [
    ("wind", [(H, "25")], (53, 34)),                       # stale off-grid maturity (57) was refused before
    ("wind", [(H, "29")], (61, 34)),                       # stale in-grid maturity (57) silently committed before
    ("wind", [(C, "18"), (H, "25")], (52, 33)),
    ("solar", [(H, "23")], (48, 33)),
    ("solar", [(C, "24"), (H, "26")], (55, 34)),           # stale eligibility with an apparently in-grid maturity
])
def test_run_uses_geometry_indices_and_changes_nothing_else(env, spy, kind, cells, expected):
    record = env.create(kind)
    env.save(record, cells)
    before = len(env.history(record))
    response = env.run(record)
    assert response.status_code == 200 and response.headers["X-Finco-Run-Outcome"] == "COMMITTED", response.text[:300]
    assert len(env.history(record)) == before + 1
    engine_inputs, fingerprint_inputs = spy.engine[-1], spy.fingerprint[-1]
    assert indices(engine_inputs) == expected
    assert indices(fingerprint_inputs) == expected, "the D-029 fingerprint must be taken over the CORRECTED effective inputs"
    assert engine_inputs is fingerprint_inputs or dataclasses.asdict(engine_inputs) == dataclasses.asdict(fingerprint_inputs)
    assert engine_inputs.financing.clean_shl_repayment_method.value == "cash_sweep"   # method preserved, never re-set


def test_default_geometry_is_byte_for_byte_unchanged(env, spy):
    record = env.create("wind")
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    stale = WorkbookService.to_projectinputs(WorkbookService.build_draft_input_set_from_workspace(get_workspace_state(OWNER, record.project_id)))
    assert env.run(record).status_code == 200
    assert indices(spy.engine[-1]) == indices(stale) == (57, 34)


def test_only_the_two_indices_differ_from_the_uncorrected_materialisation(env, spy):
    record = env.create("wind")
    env.save(record, [(C, "18"), (H, "25")])
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    stale = WorkbookService.to_projectinputs(WorkbookService.build_draft_input_set_from_workspace(get_workspace_state(OWNER, record.project_id)))
    assert env.run(record).status_code == 200
    financing_changed, rest = only_two_indices_differ(spy.engine[-1], stale)
    assert financing_changed == {"shl_maturity_period_index", "shl_principal_eligibility_start_period"}
    for part in ("info", "technical", "revenue", "tax"):
        assert dataclasses.asdict(spy.engine[-1])[part] == dataclasses.asdict(stale)[part], part


# ── negatives: no rewrite (persisted lineage / terms decide, never form fields or the snapshot) ──────────────

def _update(sql, params):
    with db.get_cursor() as cur:
        cur.execute(sql, params)


@pytest.mark.parametrize("label,sql", [
    ("missing lineage", "UPDATE projects SET source_project_id=NULL WHERE project_id=?"),
    ("ordinary-project role", "UPDATE projects SET project_role='user_project' WHERE project_id=?"),
    ("not user-created", "UPDATE projects SET project_origin='imported' WHERE project_id=?"),
    ("lineage points at a user project", "UPDATE projects SET source_project_id=(SELECT project_id FROM projects WHERE user_id!='__reference__' LIMIT 1) WHERE project_id=?"),
])
def test_no_rewrite_without_proven_lineage(env, spy, label, sql):
    record = env.create("wind")
    env.save(record, [(H, "25")])
    _update(sql, (record.project_id,))
    before = len(env.history(record))
    response = env.run(record)
    assert indices(spy.engine[-1] if spy.engine else spy.fingerprint[-1]) == (57, 34), label
    assert response.headers["X-Finco-Run-Outcome"] == "FAILED" and len(env.history(record)) == before, label


def test_forged_seed_profile_in_snapshot_cannot_grant_eligibility(env, spy):
    record = env.create("wind")
    env.save(record, [(H, "25")])
    _update("UPDATE projects SET source_project_id=NULL WHERE project_id=?", (record.project_id,))
    from app.persistence.workspace_repository import get_workspace_state
    ws = get_workspace_state(OWNER, record.project_id)
    assert "_reference_seed_profile" in ws.draft_snapshot       # present and (here) authentic, but only the persisted row counts
    env.run(record)
    assert indices(spy.fingerprint[-1]) == (57, 34)


def test_custom_shl_terms_are_never_rewritten(env, spy, monkeypatch):
    from app.workbook.service import WorkbookService
    original = WorkbookService.to_projectinputs

    def custom(pis):
        inputs = original(pis)
        return dataclasses.replace(inputs, financing=dataclasses.replace(inputs.financing, shl_rate=0.095))

    monkeypatch.setattr(WorkbookService, "to_projectinputs", staticmethod(custom))
    record = env.create("wind")
    env.save(record, [(H, "25")])
    env.run(record)
    assert indices(spy.fingerprint[-1]) == (57, 34)


def test_custom_stored_maturity_is_never_overwritten(env, spy, monkeypatch):
    from app.workbook.service import WorkbookService
    original = WorkbookService.to_projectinputs

    def custom(pis):
        inputs = original(pis)
        return dataclasses.replace(inputs, financing=dataclasses.replace(inputs.financing, shl_maturity_period_index=50))

    monkeypatch.setattr(WorkbookService, "to_projectinputs", staticmethod(custom))
    record = env.create("wind")
    env.save(record, [(H, "25")])
    env.run(record)
    assert indices(spy.fingerprint[-1]) == (50, 34)


def test_foreign_owner_cannot_run_or_trigger_a_rewrite(env, spy):
    record = env.create("wind")
    env.save(record, [(H, "25")])
    from app.auth import COOKIE_NAME, create_session_token
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id=STRANGER, username="admin"))
    data = {"project": record.project_code, "content_hash": "x", "workbook_version": "x", "csrf_token": "x"}
    assert env.client.post("/v2/workbook/run", data=data, headers={"Accept": "application/json"}, follow_redirects=False).status_code in (403, 404)
    assert not spy.engine and not spy.fingerprint


def test_archived_project_is_refused_before_any_rewrite(env, spy):
    record = env.create("wind")
    env.save(record, [(H, "25")])
    from tests.wf03_fixture_seams import archive_through_lifecycle
    data = {"project": record.project_code, **env.tokens(record), "csrf_token": env.purpose_token(record, "workbook-run-v1"),
            "run_intent_id": str(uuid.uuid4())}                 # a client that loaded the page BEFORE the project was archived
    archive_through_lifecycle(OWNER, record.project_code)        # the REAL ARCHIVE transition, as a user would
    response = env.client.post("/v2/workbook/run", data=data, headers={"Accept": "application/json"}, follow_redirects=False)
    assert response.status_code in (404, 409) and not spy.fingerprint and not spy.engine


def test_unserviceable_geometry_is_left_to_the_existing_refusal_and_explanation(env, spy):
    record = env.create("wind")
    env.save(record, [(H, "12")])                       # horizon 12 <= senior tenor 15
    before = len(env.history(record))
    response = env.run(record)
    assert response.headers["X-Finco-Run-Outcome"] == "FAILED" and len(env.history(record)) == before
    assert "ON08_" not in response.text, "the hook must not pre-empt the existing, more precise explanation"
    assert indices(spy.fingerprint[-1]) == (57, 34), "nothing is rewritten for an unserviceable geometry"


def _eligible_fixture():
    ref = SimpleNamespace(user_id="__reference__", project_role="reference", is_protected=True, archived=False,
                          template_source="generic_wind_reference", project_id="ref-1")
    record = SimpleNamespace(user_id="u", project_role="working_copy", project_origin="user_created", is_protected=False, archived=False,
                             is_readonly=False, project_type="Wind", template_source="generic_wind_reference", source_project_id="ref-1")
    from app.services.reference_seed_service import get_reference_inputs
    factory = get_reference_inputs("generic_wind_reference")
    return ref, record, factory


def _apply(inputs, ref, record, factory):
    return on08.apply_generic_shl_index_authority(
        inputs, project_record=record, actor_user_id="u", owner_user_id="u", runtime_project_key="Wind",
        canonical_reference=ref, factory_reference_inputs=factory, grid_last_provider=lambda _o: 99)


def test_eligible_lineage_with_an_unknown_frequency_is_refused_not_defaulted():
    ref, record, factory = _eligible_fixture()
    monthly = dataclasses.replace(factory, info=dataclasses.replace(factory.info, period_frequency="Monthly"))
    with pytest.raises(on08.On08ShlIndexRefusal) as caught:
        _apply(monthly, ref, record, factory)
    assert caught.value.code == "ON08_SHL_UNSUPPORTED_FREQUENCY"


def test_quarterly_is_handed_to_the_quarterly_authority_unchanged():
    """RC-7B/RC-7C interoperability: ON-08 owns no quarterly SHL geometry. The SAME object comes back, nothing is rewritten or refused, so the
    existing admission gate (QUARTERLY_ADMISSION_CLOSED), the 3/3 calendar and its typed refusals stay the only authority."""
    ref, record, factory = _eligible_fixture()
    freq_type = type(factory.info.period_frequency)
    stale = dataclasses.replace(
        factory, info=dataclasses.replace(factory.info, period_frequency=freq_type("Quarterly"), horizon_years=20),
        financing=dataclasses.replace(factory.financing))
    out, outcome = _apply(stale, ref, record, factory)
    assert out is stale and outcome.status == on08.NOT_ELIGIBLE and "quarterly" in outcome.reason.lower()
    assert indices(out) == indices(factory)


@pytest.mark.parametrize("frequency", ["Semestrial", "Annual"])
def test_annual_and_semestrial_are_still_rederived_for_an_eligible_project(frequency):
    ref, record, factory = _eligible_fixture()
    freq_type = type(factory.info.period_frequency)
    inputs = dataclasses.replace(factory, info=dataclasses.replace(factory.info, period_frequency=freq_type(frequency), horizon_years=20))
    out, outcome = _apply(inputs, ref, record, factory)
    expected = on08.geometry_indices(construction_months=inputs.info.construction_months, horizon_years=20,
                                     senior_tenor_years=inputs.financing.senior_tenor_years, period_frequency=frequency)
    assert outcome.status == on08.CORRECTED and indices(out) == expected
    assert out.financing.clean_shl_repayment_method == inputs.financing.clean_shl_repayment_method


# ── the economic residual stays a SEPARATE refusal (original WND-02, L1 removed, L2 remains) ─────────────────

FIXTURES = ROOT / "research/on07_correction_a/isolated_revised_copies/ON07_PROJECT_FIXTURES_REVISED.csv"


@pytest.mark.skipif(not FIXTURES.exists(), reason="ON-07 fixture CSV not present")
def test_original_wnd02_keeps_its_separate_economic_refusal(env, spy, caplog):
    from app.workbook.registry import WORKBOOK
    rows = [r for r in csv.DictReader(open(FIXTURES, newline="")) if r["fixture_id"] == "WND-02" and r["source_class"] == "EXPLICIT"]
    skip = {"project_type", "project_name", "country_market", "currency", "financial_close", "scenario", "period_frequency", "capacity_mw",
            "total_capex_keur", "opex_y1_keur", "operating_hours_p90_10y", "rev_merchant_price_curve_json"}
    cells = []
    for r in rows:
        if r["fixture_key"] in skip or not r["true_route_entry_mechanism"].startswith("SAVE_ALL_CELL"):
            continue
        try:
            spec = WORKBOOK.field(r["finco_field_id"])
        except Exception:
            continue
        if spec.editable:
            cells.append((r["finco_field_id"], r["intended_value"].strip()))
    record = env.create("wind")
    env.save(record, cells)
    # CAPEX/OPEX totals and the merchant curve through the same real save-all path used by the Save button
    for kind, target in (("capex", 52000), ("opex", 1150)):
        lines = env.client.get("/v2/model-react/costlines", params={"sheet": kind, "project": record.project_code}).json()["lines"]
        active = [l for l in lines if l["active"] and float(l["amount_keur"] or 0) > 0]
        total = sum(Decimal(str(l["amount_keur"])) for l in active)
        new = [(Decimal(str(l["amount_keur"])) * Decimal(target) / total).quantize(Decimal("0.000001"), ROUND_HALF_EVEN) for l in active]
        new[max(range(len(new)), key=new.__getitem__)] += Decimal(target) - sum(new)
        edits = [{"kind": kind, "sub_line_id": l["sub_line_id"], "label": l["label"], "amount_keur": str(n), "row_version": l["row_version"],
                  "notes": l.get("notes") or "", **({"inflation_pct": str(l["inflation_pct"])} if kind == "opex" and l.get("inflation_pct") is not None else {})}
                 for l, n in zip(active, new)]
        t = env.tokens(record)
        from app.workbook.financing_csrf import issue_token
        body = {"project": record.project_code, **t, "request_id": "c-" + uuid.uuid4().hex[:16], "cells": [], "cost_lines": edits,
                "csrf_token": issue_token(SimpleNamespace(cookies=env.client.cookies, state=SimpleNamespace()), record.project_code, purpose="model-save-all-v1")}
        assert env.client.post("/v2/workbook/save-all", json=body).status_code == 200
    from app.persistence.projects_repository import resolve_accessible_project
    from app.v2.save_all_commands import SaveAllInput, save_all
    from app.workbook.workbook_identity import assemble_consistent_for_get
    curve = next(r["intended_value"] for r in rows if r["fixture_key"] == "rev_merchant_price_curve_json")
    pr, _ = resolve_accessible_project(OWNER, record.project_code)
    save_all(project_record=pr, user_id=OWNER, data=SaveAllInput(
        request_id="mc-" + uuid.uuid4().hex[:12], workbook_version=WORKBOOK.version, scenario_id=None,
        content_hash=assemble_consistent_for_get(OWNER, record.project_id, WORKBOOK.version).composite_hash,
        cells=(("revenue.merchant.price_curve_json", curve),)))
    before = len(env.history(record))
    with caplog.at_level("ERROR"):
        response = env.run(record)
    assert indices(spy.engine[-1]) == (52, 27), "L1 removed: the corrected geometry reached the engine"
    assert response.headers["X-Finco-Run-Outcome"] == "FAILED" and len(env.history(record)) == before, "a refused Run is never committed"
    log = caplog.text
    assert "SHL_MATURITY_RESIDUAL_FAILS_CLOSED" in log and "SHL_MATURITY_NOT_ON_PERIOD_GRID_FAILS_CLOSED" not in log
    # Last Run preserved: nothing was committed by the refused attempt
    assert env.history(record) == []
