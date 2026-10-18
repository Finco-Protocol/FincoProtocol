"""RC-7B Workstream C: quarterly Run admission and institutional workspace.

Default state is release-closed: no Working Copy can save 3/3, no product Run
can execute it, no generic selector is rendered. Tests that open the gate do so
explicitly with monkeypatch as acceptance evidence only; they never change the
committed ``ACTIVATION_ENABLED = False``.
"""
from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace

import pytest

from app.workbook import quarterly_frequency_config as cfg
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401

OWNER = "decision-user"


def _solar():
    from app.project_factories import create_generic_solar_reference
    return create_generic_solar_reference()


def _quarterly(pi):
    from finco_core.engine.calendar_policy import quarterly_candidate_policy
    from finco_core.inputs import PeriodFrequency
    from finco_core.inputs._models import QuarterlyProjectInfo
    values = {f.name: getattr(pi.info, f.name) for f in dataclasses.fields(pi.info)}
    values["period_frequency"] = PeriodFrequency.QUARTERLY
    return dataclasses.replace(pi, info=QuarterlyProjectInfo(**values, operating_calendar_policy=quarterly_candidate_policy()))


# ── committed state is closed ────────────────────────────────────────────────

def test_activation_is_committed_closed():
    assert cfg.ACTIVATION_ENABLED is False
    from app.workbook.registry import WORKBOOK
    spec = WORKBOOK.field(cfg.FIELD_ID)
    assert spec.snapshot_key == cfg.SNAPSHOT_KEY and spec.engine_path == "info.operating_calendar_policy"


def test_strict_versioned_selection_contract():
    raw = cfg.candidate_config_json()
    assert cfg.canonical_json(raw) == raw and cfg.frequency_label(raw) == "3/3"
    assert cfg.parse_config("") is None and cfg.parse_config(None) is None and cfg.frequency_label("") == "6/6"
    good = json.loads(raw)
    for bad in ({**good, "operating_months": 6}, {**good, "debt_service_months": 6},
                {**good, "sponsor_funding_mode": "SHARE_CAPITAL_THEN_SHL"}, {**good, "reserve_support_mode": "CASH_DSRA"},
                {**good, "authority": "x"}, {**good, "version": 2}, {k: v for k, v in good.items() if k != "authority"},
                {**good, "extra": 1}, {**good, "operating_calendar_policy": {**good["operating_calendar_policy"], "stub": "ROLL"}}):
        with pytest.raises(ValueError, match="QUARTERLY_"):
            cfg.parse_config(json.dumps(bad))
    with pytest.raises(ValueError, match="QUARTERLY_CONFIG_DUPLICATE_KEY"):
        cfg.parse_config('{"version":1,"version":1}')
    with pytest.raises(ValueError, match="QUARTERLY_CONFIG_BOUNDED_JSON_REQUIRED"):
        cfg.parse_config("x" * (cfg.MAX_BYTES + 1))


def test_default_six_month_working_copy_is_the_same_object():
    pi = _solar()
    assert cfg.apply_config(pi, None, "Solar") is pi
    assert cfg.apply_config(pi, "", "Solar") is pi
    assert cfg.run_evidence(pi) == {}


def test_closed_gate_refuses_every_quarterly_application():
    with pytest.raises(ValueError, match="QUARTERLY_ADMISSION_CLOSED"):
        cfg.apply_config(_solar(), cfg.candidate_config_json(), "Solar")
    from app.services.production_financial_authority import (
        CleanProductionRunUnavailable, classify_production_authority, run_clean_production,
    )
    decision = classify_production_authority(_quarterly(_solar()))
    assert not decision.promoted and decision.reason_code == "QUARTERLY_ADMISSION_CLOSED"
    with pytest.raises(CleanProductionRunUnavailable, match="QUARTERLY_ADMISSION_CLOSED"):
        run_clean_production(_quarterly(_solar()))


def test_snapshot_carrying_a_selection_fails_closed_at_the_adapter(env):
    from app.input_adapter import SnapshotInputError, build_projectinputs_from_snapshot
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create("solar")
    snapshot = dict(get_workspace_state(OWNER, record.project_id).draft_snapshot)
    assert cfg.SNAPSHOT_KEY not in snapshot  # every existing Working Copy is 6/6 by absence
    assert build_projectinputs_from_snapshot(snapshot).info.period_frequency.name == "SEMESTRIAL"
    with pytest.raises(SnapshotInputError, match="QUARTERLY_ADMISSION_CLOSED"):
        build_projectinputs_from_snapshot({**snapshot, cfg.SNAPSHOT_KEY: cfg.candidate_config_json()})


@pytest.mark.parametrize("project_type", ["Data Center", "Ev Charging", "Storage"])
def test_open_gate_still_refuses_unsupported_technologies(monkeypatch, project_type):
    monkeypatch.setattr(cfg, "ACTIVATION_ENABLED", True)
    with pytest.raises(ValueError, match="QUARTERLY_TECHNOLOGY_UNSUPPORTED"):
        cfg.apply_config(_solar(), cfg.candidate_config_json(), project_type)


def test_open_gate_binds_recorded_structure_and_refuses_existing_reserves(monkeypatch):
    from finco_core.inputs import DebtServiceReserveSupportMode, SponsorFundingMode
    from finco_core.inputs._models import QuarterlyProjectInfo
    monkeypatch.setattr(cfg, "ACTIVATION_ENABLED", True)
    applied = cfg.apply_config(_solar(), cfg.candidate_config_json(), "Solar")
    assert isinstance(applied.info, QuarterlyProjectInfo)
    assert applied.financing.sponsor_funding_mode is SponsorFundingMode.EQUITY_ONLY
    assert applied.financing.dsra_months == 0 and applied.financing.shl_amount_keur == 0.0
    evidence = cfg.run_evidence(applied)
    assert evidence["operating_frequency"] == "3/3" and evidence["period_months"] == 3
    assert evidence["sponsor_returns_status"] == "PENDING_D08_DISTRIBUTION_ELIGIBILITY"
    assert evidence["financing_structure_binding"]["shareholder_loan"] == "EXCLUDED_BY_3_3_SELECTION"
    reserved = dataclasses.replace(_solar(), financing=dataclasses.replace(
        _solar().financing, dsra_support_mode=DebtServiceReserveSupportMode.CASH_DSRA))
    with pytest.raises(ValueError, match="QUARTERLY_RESERVE_POLICY_PENDING_D09"):
        cfg.apply_config(reserved, cfg.candidate_config_json(), "Solar")


# ── product surfaces while closed ────────────────────────────────────────────

def test_closed_endpoint_generic_field_and_writer_refuse_and_nothing_is_rendered(env):
    from app.auth import generate_csrf_token
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.revenue_contracts_service import save_contracts
    record = env.create("solar")
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    assert page.status_code == 200
    assert cfg.FIELD_ID not in page.text and cfg.SNAPSHOT_KEY not in page.text  # no selector exposed
    before = get_workspace_state(OWNER, record.project_id)
    response = env.client.post("/v2/workbook/calendar/operating-frequency", data={
        "project": record.project_code, "csrf_token": generate_csrf_token(), "frequency": "3/3", "financing_structure": "EQUITY_ONLY_NO_RESERVE", **tokens(page.text)})
    assert response.status_code == 404 and response.json()["error"] == "QUARTERLY_ADMISSION_CLOSED"
    generic = env.client.post("/v2/workbook/update", data={
        "project": record.project_code, "sheet_id": "project_setup", "field_id": cfg.FIELD_ID,
        "value": cfg.candidate_config_json(), **tokens(page.text)})
    assert generic.status_code == 409 and "QUARTERLY_GENERIC_FIELD_WRITE_REFUSED" in generic.text
    # The security-critical typed contract writer is unchanged and never authorizes this field.
    with pytest.raises(ValueError, match="TYPED_CONTRACT_FIELD_NOT_AUTHORIZED"):
        save_contracts(owner=OWNER, project_id=record.project_id, expected_hash=tokens(page.text)["content_hash"],
                       raw=cfg.candidate_config_json(), field_id=cfg.FIELD_ID)
    # Every canonical write path (single field or batch) refuses at validation.
    from app.workbook.update_service import NonEditableFieldError, WorkbookUpdateService
    with pytest.raises(NonEditableFieldError, match="QUARTERLY_ADMISSION_CLOSED"):
        WorkbookUpdateService.validate_field_update(cfg.FIELD_ID, cfg.candidate_config_json())
    with pytest.raises(NonEditableFieldError, match="QUARTERLY_ADMISSION_CLOSED"):
        WorkbookUpdateService.apply_draft_update(ws=before, field_id=cfg.FIELD_ID, raw_value=cfg.candidate_config_json(),
                                                 content_hash=tokens(page.text)["content_hash"],
                                                 workbook_version=tokens(page.text)["workbook_version"], project_record=record)
    assert get_workspace_state(OWNER, record.project_id) == before


@pytest.mark.parametrize("kind", ["data_center", "ev_charging"])
def test_open_gate_endpoint_refuses_non_renewable_projects(env, monkeypatch, kind):
    from app.auth import generate_csrf_token
    monkeypatch.setattr(cfg, "ACTIVATION_ENABLED", True)
    record = env.create(kind)
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    response = env.client.post("/v2/workbook/calendar/operating-frequency", data={
        "project": record.project_code, "csrf_token": generate_csrf_token(), "frequency": "3/3", "financing_structure": "EQUITY_ONLY_NO_RESERVE", **tokens(page.text)})
    assert response.status_code == 409 and "QUARTERLY_TECHNOLOGY_UNSUPPORTED" in response.json()["error"]


@pytest.mark.parametrize("frequency", ["3/6", "6/3", "1/1", ""])
def test_open_gate_endpoint_refuses_mixed_or_unknown_frequencies(env, monkeypatch, frequency):
    from app.auth import generate_csrf_token
    monkeypatch.setattr(cfg, "ACTIVATION_ENABLED", True)
    record = env.create("solar")
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    response = env.client.post("/v2/workbook/calendar/operating-frequency", data={
        "project": record.project_code, "csrf_token": generate_csrf_token(), "frequency": frequency, "financing_structure": "", **tokens(page.text)})
    assert response.status_code == 409 and "QUARTERLY_FREQUENCY_UNSUPPORTED" in response.json()["error"]


def test_open_gate_validation_rejects_malformed_selection(monkeypatch):
    from app.workbook.update_service import WorkbookUpdateService
    monkeypatch.setattr(cfg, "ACTIVATION_ENABLED", True)
    bad = WorkbookUpdateService.validate_field_update(cfg.FIELD_ID, '{"version":1}')
    assert not bad.is_valid and "QUARTERLY_CONFIG_KEYS_INVALID" in bad.error
    assert WorkbookUpdateService.validate_field_update(cfg.FIELD_ID, cfg.candidate_config_json()).is_valid
    assert WorkbookUpdateService.validate_field_update(cfg.FIELD_ID, "").is_valid  # 6/6


def test_open_gate_endpoint_requires_explicit_structure_consent(env, monkeypatch):
    from app.auth import generate_csrf_token
    from app.persistence.workspace_repository import get_workspace_state
    monkeypatch.setattr(cfg, "ACTIVATION_ENABLED", True)
    record = env.create("solar")
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    before = get_workspace_state(OWNER, record.project_id)
    for consent in ("", "EQUITY_ONLY", "SHARE_CAPITAL_THEN_SHL"):
        response = env.client.post("/v2/workbook/calendar/operating-frequency", data={
            "project": record.project_code, "csrf_token": generate_csrf_token(), "frequency": "3/3",
            "financing_structure": consent, **tokens(page.text)})
        assert response.status_code == 409
        assert "QUARTERLY_FINANCING_STRUCTURE_CONSENT_REQUIRED" in response.json()["error"]
    assert get_workspace_state(OWNER, record.project_id) == before


def test_open_gate_endpoint_requires_csrf_and_cas(env, monkeypatch):
    from app.auth import generate_csrf_token
    monkeypatch.setattr(cfg, "ACTIVATION_ENABLED", True)
    record = env.create("solar")
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    bad_csrf = env.client.post("/v2/workbook/calendar/operating-frequency", data={
        "project": record.project_code, "csrf_token": "forged", "frequency": "3/3", "financing_structure": "EQUITY_ONLY_NO_RESERVE", **tokens(page.text)})
    assert bad_csrf.status_code == 403
    stale = {**tokens(page.text), "content_hash": "0" * 64}
    bad_cas = env.client.post("/v2/workbook/calendar/operating-frequency", data={
        "project": record.project_code, "csrf_token": generate_csrf_token(), "frequency": "3/3", "financing_structure": "EQUITY_ONLY_NO_RESERVE", **stale})
    assert bad_cas.status_code == 409


# ── labels, comparison and Credit V4 eligibility ─────────────────────────────

def test_export_period_basis_declares_quarterly_only_from_persisted_metadata():
    from datetime import date
    from app.export.reporting_common import period_basis
    dates = [date(2031, 6, 30), date(2031, 9, 30), date(2031, 12, 31), date(2032, 3, 31)]
    declared = period_basis(dates, [("runtime_summary.financing_evidence", {"period_months": 3})])
    assert declared.declared_months == 3 and declared.label == "Quarterly" and not declared.warning
    semi = [date(2031, 6, 30), date(2031, 12, 31), date(2032, 6, 30)]
    mismatch = period_basis(semi, [("runtime_summary.financing_evidence", {"period_months": 3})])
    assert mismatch.warning.startswith("FREQUENCY_METADATA_MISMATCH")


def _entry(history_id, ran_at, frequency=None):
    evidence = {} if frequency is None else {"operating_frequency": frequency}
    return SimpleNamespace(history_id=history_id, ran_at=ran_at, runtime_snapshot_id=history_id, composite_hash="h",
                           last_runtime_scenario_id=None, active_scenario_name="Base", engine_version="v",
                           runtime_summary={"financing_evidence": evidence}, integrity_evidence={})


def test_run_compare_marks_cross_frequency_checks_not_comparable(monkeypatch):
    from app.v2 import diagnostics_run_compare as compare
    old, new = _entry("a", "2026-01-01"), _entry("b", "2026-01-02", "3/3")
    assert compare.operating_frequency(old) == "6/6" and compare.operating_frequency(new) == "3/3"
    codes = [q["code"] for q in compare.qualifications(old, new)]
    assert "OPERATING_FREQUENCY_DIFFERS" in codes
    monkeypatch.setattr("app.persistence.run_history_repository.get_run_history", lambda *a, **k: [new, old])
    rows = {"x": {"status": "PASS", "residual": 0.0, "family": "f"}}
    monkeypatch.setattr(compare, "evaluate_entry", lambda entry, q: rows)
    result = compare.build_run_comparison(SimpleNamespace(user_id=OWNER, project_id="p", last_runtime_snapshot_id="b"))
    row = result["candidates"][0]["rows"][0]
    assert row["classification"] == "NOT_COMPARABLE" and row["reason"] == "OPERATING_FREQUENCY_DIFFERS"
    assert row["residual_change"] is None
    assert compare.qualifications(old, _entry("c", "2026-01-03")) == []  # 6/6 vs 6/6 unchanged


def test_credit_v4_refuses_end_date_joins_across_frequencies():
    from app.v2.credit_v4_evidence import build_credit_v4
    timeline = {"available": True, "columns": [{"date": "2031-06-30", "index": 1}],
                "rows": [{"key": k, "cells": [1.0]} for k in ("dscr", "debt_service", "base_cfads", "closing")]}
    semi = {"identity": {"history_id": "a"}, "timeline": timeline}
    quarter = {"identity": {"history_id": "b"}, "timeline": timeline, "operating_frequency": "3/3"}
    refused = build_credit_v4([semi, quarter])["period_comparison"]
    assert refused["available"] is False and "different operating/debt frequencies" in refused["reason"]
    same = build_credit_v4([semi, {**semi, "identity": {"history_id": "c"}}])["period_comparison"]
    assert same["available"] is True
