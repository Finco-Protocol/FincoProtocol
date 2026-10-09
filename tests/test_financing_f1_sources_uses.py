"""F1 presentation, authorization and real Solar/Wind persisted-Run acceptance.

No financial baselines are changed. Tests compare directly to canonical persisted
RuntimeResult and verify unavailable evidence is never replaced by a zero plug.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.v2.financing_sources_uses_projection import (
    NA, FinancingEvidenceInvalid, amount, build_sources_uses_projection,
)


def _rr(**kwargs):
    return SimpleNamespace(
        runtime_summary=kwargs.get("runtime_summary", {"senior_debt_keur": 0.0,
                                                        "actual_gearing_pct": .65}),
        debt_schedule=kwargs.get("debt_schedule", {"summary": {
            "target_dscr": 1.3, "actual_min_dscr": 1.16, "min_llcr": None}}),
        sponsor_schedule=kwargs.get("sponsor_schedule", {"summary": {
            "total_shl_cash_contributed_keur": 300.0}}),
    )


@pytest.mark.parametrize("value", [None, True, False, "0", "10,000", float("inf"), float("nan")])
def test_not_a_number_remains_unavailable(value):
    m = amount("Funding", value, "RuntimeResult.test")
    assert not m.available and m.display == NA


def test_real_zero_kept_not_as_missing():
    m = amount("Senior", 0.0, "RuntimeResult.runtime_summary.senior_debt_keur")
    assert m.available and m.display == "0.00"


def test_persisted_senior_and_shl_are_separate_not_total_sources():
    v = build_sources_uses_projection(runtime_result=_rr(), freshness="CURRENT")
    assert v["sources"][0].value == 0.0
    assert v["sources"][3].value == 300.0
    assert not v["total_sources"].available
    assert not v["total_uses"].available
    assert not v["residual"].available
    assert all(not use.available for use in v["uses"])
    assert v["integrity"] == "UNAVAILABLE"


def test_working_and_last_run_are_economically_disjoint():
    fin = SimpleNamespace(share_capital_keur=12.0, share_premium_keur=8.0,
                          shl_amount_keur=1500.0, senior_debt_amount_keur=120.0,
                          gearing_ratio=.7)
    r = _rr(runtime_summary={"senior_debt_keur": 555.0})
    cur = build_sources_uses_projection(
        runtime_result=r, working_financing=fin, freshness="CURRENT")
    stale = build_sources_uses_projection(
        runtime_result=r, working_financing=fin, freshness="STALE")
    assert cur["sources"] == stale["sources"]
    assert stale["sources"][0].value == 555
    assert next(m for m in stale["working"] if m.label.startswith("Share capital")).value == 12
    assert stale["total_sources"].value is None
    historic = build_sources_uses_projection(
        runtime_result=r, working_financing=fin, freshness="STALE",
        run_kind="HISTORICAL_RUN")
    assert historic["working"] == ()
    assert historic["sources"][0].value == 555
    assert historic["freshness"] == "HISTORICAL"


def test_missing_and_malformed_runtime_evidence_fail_closed():
    no_run = build_sources_uses_projection()
    assert not no_run["has_run"] and no_run["sources"][0].value is None
    for r in (_rr(runtime_summary=[]), _rr(debt_schedule={"summary": "bad"}),
              _rr(sponsor_schedule="malformed")):
        with pytest.raises(FinancingEvidenceInvalid):
            build_sources_uses_projection(runtime_result=r)
    with pytest.raises(FinancingEvidenceInvalid):
        build_sources_uses_projection(runtime_result=_rr(),
                                      integrity_evidence={"checks": "fake", "overall": "PASS"})


def test_run_integrity_cannot_infer_funding_balance():
    evidence = {"overall": "PASS", "checks": [{"status": "PASS", "reason_code": "X"}]}
    v = build_sources_uses_projection(runtime_result=_rr(), integrity_evidence=evidence)
    assert v["integrity"] == "PASS"
    assert not v["residual"].available
    bad = build_sources_uses_projection(integrity_evidence={"overall": "PASS"})
    assert bad["integrity"] == "UNAVAILABLE"


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    from app.persistence import db
    from app.services.reference_seed_service import create_reference_seeded_project
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "f1.db"))
    db.init_db()
    records = {}
    for kind, mw in (("solar", 64.0), ("wind", 48.0)):
        records[kind] = create_reference_seeded_project(
            user_id="f1-owner", requested_name="F1 " + kind,
            template_source="generic_" + kind + "_reference", capacity_mw=mw)
    return records


@pytest.fixture()
def client(seeded):
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    from main_web import app
    with TestClient(app) as test_client:
        test_client.cookies.set(
            COOKIE_NAME, create_session_token(user_id="f1-owner", username="admin"))
        yield test_client


def _run(client, record):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    from app.workbook.workbook_identity import assemble_consistent_for_get
    ws = get_workspace_state("f1-owner", record.project_id)
    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    h = assemble_consistent_for_get(
        "f1-owner", record.project_id, pis.workbook_version).composite_hash
    response = client.post("/v2/workbook/run",
                           data={"project": record.project_code,
                                 "content_hash": h, "workbook_version": pis.workbook_version},
                           headers={"HX-Request": "true"})
    assert response.status_code == 200, response.text[:500]


def test_no_auth_no_cross_owner_no_unscoped_historical(client, seeded):
    from app.auth import COOKIE_NAME, create_session_token
    record = seeded["solar"]
    good = client.get("/v2/financing/sources-uses", params={"project": record.project_code})
    assert good.status_code == 200
    assert 'data-testid="su-page"' in good.text
    assert good.headers["Cache-Control"] == "private, no-store"
    assert client.get("/v2/financing/sources-uses",
                      params={"project": record.project_code, "history_id": "foreign"}).status_code == 404
    client.cookies.clear()
    response = client.get("/v2/financing/sources-uses",
                          params={"project": record.project_code}, follow_redirects=False)
    assert response.status_code == 302
    client.cookies.set(COOKIE_NAME, create_session_token(
        user_id="f1-intruder", username="admin"))
    assert client.get("/v2/financing/sources-uses",
                      params={"project": record.project_code}).status_code == 404


def test_f1_get_is_read_only_and_no_engine_execution(client, seeded):
    from app.persistence.workspace_repository import get_workspace_state
    record = seeded["solar"]
    before = get_workspace_state("f1-owner", record.project_id)
    with patch("app.services.production_financial_authority.run_clean_production",
               side_effect=AssertionError("F1 GET must not execute engine")):
        response = client.get("/v2/financing/sources-uses",
                              params={"project": record.project_code})
    assert response.status_code == 200
    assert "Apply not enabled" in response.text
    assert get_workspace_state("f1-owner", record.project_id) == before


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_real_solar_wind_last_run_and_immutable_history(client, seeded, kind):
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.run_history_repository import get_run_history
    from app.workbook.service import WorkbookService
    record = seeded[kind]
    # Initialize the draft using the same GET path as the existing Model V2 tests.
    assert client.get("/v2/workbook", params={"project": record.project_code}).status_code == 200
    _run(client, record)
    before = get_workspace_state("f1-owner", record.project_id)
    rr = WorkbookService.get_runtime_result(before)
    assert rr is not None
    proj = build_sources_uses_projection(
        runtime_result=rr, integrity_evidence=before.last_integrity_evidence)
    assert proj["sources"][0].value == rr.runtime_summary.get("senior_debt_keur")
    assert proj["bankability"][0].value == rr.runtime_summary.get("actual_gearing_pct")
    assert proj["total_uses"].value is None
    page = client.get("/v2/financing/sources-uses", params={"project": record.project_code})
    assert page.status_code == 200
    assert 'data-testid="su-sources"' in page.text
    assert "Full canonical" not in page.text or "unavailable" in page.text.lower()
    entries = get_run_history("f1-owner", record.project_id, limit=1)
    assert entries
    historical = client.get("/v2/financing/sources-uses",
                            params={"project": record.project_code,
                                    "history_id": entries[0].history_id})
    assert historical.status_code == 200
    assert 'data-run-kind="HISTORICAL_RUN"' in historical.text
    assert 'data-testid="su-working"' not in historical.text
    assert get_workspace_state("f1-owner", record.project_id) == before


def test_protected_reference_cannot_expose_apply_route(client, seeded):
    page = client.get("/v2/financing/sources-uses",
                      params={"project": seeded["solar"].project_code})
    assert page.status_code == 200
    assert "<form" not in page.text.lower().split('data-testid="su-balance"')[-1].split("</section>")[0]
    assert "Apply not enabled" in page.text


def test_no_frozen_imports_in_projection_or_write_controls():
    import inspect
    import app.v2.financing_sources_uses_projection as projection
    import app.v2.financing_sources_uses_router as routing
    src = inspect.getsource(projection) + inspect.getsource(routing)
    for forbidden in ("run_project_financing_model(", "compute_project_uses(",
                      "WorkbookUpdateService.apply_draft_update(", "get_connection("):
        assert forbidden not in src
