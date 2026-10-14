"""Focused independent M6 numerical, provenance, and isolation acceptance."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace as NS
import copy
import math
import sqlite3

import pytest

from app.model_v2.acquisition.evidence import (
    AcquisitionEvidenceError, extract, bind, validate,
)
from app.model_v2.acquisition.economics import (
    ACTIVATION_ENABLED, STATUS, AcquisitionPolicyError, AcquisitionTerms,
    buyer_cashflows, evaluate, enterprise_equity_bridge,
)
from app.persistence.acquisition_repository import (
    AcquisitionCaseConflict, make_document, save_case, read_case,
)


BINDING = dict(owner_id="owner-A", project_id="project-A",
               snapshot_id="snapshot-123", composite_hash="c"*64, scenario_id=None)


def source():
    dates = (date(2027, 1, 1), date(2028, 1, 1), date(2029, 1, 1))
    rows = []
    for i, d in enumerate(dates):
        net = (0.0, 70.0, 70.0)[i]
        rows.append(NS(period_index=i, cashflow_date=d,
            gross_dividend_paid_keur=net, dividend_wht_keur=0.0,
            net_dividend_received_keur=net,
            shl_cash_interest_receipt_keur=(0.0, 9.0, 9.0)[i],
            actual_shl_principal_paid_keur=(0.0, 20.0, 20.0)[i],
            shl_cash_contribution_keur=0.0,
            share_capital_contribution_keur=0.0,
            share_premium_contribution_keur=0.0,
            other_committed_equity_contribution_keur=0.0,
            additional_equity_contribution_keur=0.0))
    project = NS(cashflows=(
        NS(cashflow_date=dates[0], net_unlevered_project_cashflow_keur=-100.0),
        NS(cashflow_date=dates[1], net_unlevered_project_cashflow_keur=100.0),
        NS(cashflow_date=dates[2], net_unlevered_project_cashflow_keur=100.0)),
        project_xirr_status=NS(value="OK"))
    return NS(waterfall_periods=rows, total_net_dividend_received_keur=140.0,
              return_summary=NS(project=project))


def evidence():
    return validate(bind(extract(source()), **BINDING), **BINDING)


def terms(**updates):
    d = dict(closing_date=date(2027, 1, 1),
             purchase_price_keur=100.0, transaction_costs_keur=10.0,
             buyer_discount_rate=0.10, target_buyer_irr=0.10,
             bid_lower_bound_keur=0.0, bid_upper_bound_keur=400.0)
    d.update(updates)
    return AcquisitionTerms(**d)


def test_extraction_exact_gross_wht_net_shl_separation():
    s = source()
    s.waterfall_periods[1].gross_dividend_paid_keur = 75.0
    s.waterfall_periods[1].dividend_wht_keur = 5.0
    e = extract(s)
    assert e["equity_periods"][1]["net_legal_dividend_keur"] == 70.0
    assert e["equity_periods"][1]["shl_principal_keur"] == 20.0
    assert e["equity_periods"][1]["shl_interest_keur"] == 9.0
    assert e["project_cashflows"][0]["net_unlevered_project_cashflow_keur"] == -100.0


def test_missing_and_corrupt_evidence_fail_closed():
    with pytest.raises(AcquisitionEvidenceError):
        validate(None, **BINDING)
    a = evidence()
    a["equity_periods"][1]["net_legal_dividend_keur"] = 70000.0
    with pytest.raises(AcquisitionEvidenceError, match="DIGEST"):
        validate(a, **BINDING)
    with pytest.raises(AcquisitionEvidenceError, match="BINDING"):
        validate(evidence(), **{**BINDING, "snapshot_id": "different"})


def test_source_bad_dates_nonfinite_and_gross_net_denied():
    s = source()
    s.waterfall_periods[1].cashflow_date = s.waterfall_periods[0].cashflow_date
    with pytest.raises(AcquisitionEvidenceError, match="DATE"):
        extract(s)
    s = source()
    s.waterfall_periods[1].gross_dividend_paid_keur = float("nan")
    with pytest.raises(AcquisitionEvidenceError, match="NON_FINITE"):
        extract(s)
    s = source()
    s.waterfall_periods[1].dividend_wht_keur = 1.0
    with pytest.raises(AcquisitionEvidenceError, match="RECONCILIATION"):
        extract(s)


def test_buyer_cashflow_uses_postclose_only_no_shl_rights_and_fees():
    rows = buyer_cashflows(evidence(), terms())
    assert rows[0]["amount_keur"] == -110.0
    assert [r["amount_keur"] for r in rows[1:]] == [70.0, 70.0]
    assert sum(r["amount_keur"] for r in rows) == 30.0
    assert all("SHL" not in c["component"] for r in rows for c in r["components"])


def test_buyer_irr_moic_npv_independent_identity():
    out = evaluate(evidence(), terms())
    assert out["status"] == STATUS and not ACTIVATION_ENABLED
    assert out["buyer_irr"] is not None
    assert out["buyer_moic"] == pytest.approx(140/110)
    # Independent ACT/365 candidate discount check.
    expected = -110 + 70/(1.1**1) + 70/(1.1**(731/365))
    assert out["buyer_npv_keur"] == pytest.approx(expected, abs=1e-8)
    assert out["buyer_irr"] > .10
    assert out["bid_ceiling_status"] == "ROOT_FOUND"
    assert out["bid_ceiling_keur"] == pytest.approx(expected + 100, abs=1e-6)


def test_future_equity_calls_included_but_not_historical_capital():
    e = evidence()
    e["equity_periods"][1]["legal_equity_contribution_keur"] = 20.0
    # Rebind after changing the full-precision source facts.
    fresh = bind({k: v for k, v in e.items() if k not in ("binding", "digest")}, **BINDING)
    e = validate(fresh, **BINDING)
    out = evaluate(e, terms())
    assert out["buyer_cashflows"][1]["amount_keur"] == 50.0
    # MOIC denominator includes new 20k equity calls, not historical contributions.
    assert out["buyer_moic"] == pytest.approx(140/130)


def test_zero_vs_unavailable_and_ambiguous_root_denial():
    e = evidence()
    for r in e["equity_periods"]:
        r["net_legal_dividend_keur"] = 0.0
        r["gross_legal_dividend_keur"] = 0.0
    v = bind({k: v for k, v in e.items() if k not in ("binding","digest")}, **BINDING)
    out = evaluate(validate(v, **BINDING), terms())
    assert out["buyer_irr"] is None
    assert out["buyer_irr_status"] == "NO_VALID_XIRR"
    assert out["buyer_moic"] == 0.0
    assert out["bid_ceiling_keur"] is None


def test_buyer_exit_dates_and_transactions_denied_when_unsupported():
    with pytest.raises(AcquisitionPolicyError, match="OWNERSHIP"):
        terms(ownership_fraction=0.5).check()
    with pytest.raises(AcquisitionPolicyError, match="STRUCTURE"):
        terms(transaction_type="ASSET_ACQUISITION").check()
    with pytest.raises(AcquisitionPolicyError, match="SHL"):
        terms(shl_policy="ACQUIRE_SHL_AUTOMATICALLY").check()
    with pytest.raises(AcquisitionPolicyError, match="EXIT"):
        terms(exit_date=date(2030,1,1)).check()
    with pytest.raises(AcquisitionPolicyError, match="BOUNDS"):
        terms(bid_lower_bound_keur=200, bid_upper_bound_keur=100).check()
    out = evaluate(evidence(), terms(exit_date=date(2028, 6, 1), exit_proceeds_keur=60))
    assert out["buyer_cashflows"][-1]["amount_keur"] == 60.0


def test_closing_event_order_and_source_horizon_fail_closed():
    e = evidence()
    with pytest.raises(AcquisitionPolicyError, match="HORIZON"):
        evaluate(e, terms(closing_date=date(2029, 1, 1)))
    with pytest.raises(AcquisitionPolicyError, match="HORIZON"):
        evaluate(e, terms(exit_date=date(2030, 1, 1), exit_proceeds_keur=10))
    with pytest.raises(AcquisitionPolicyError, match="ORDER_AMBIGUOUS"):
        evaluate(e, terms(closing_date=date(2028, 1, 1)))


def test_enterprise_equity_signs_and_restricted_reserve_excluded():
    a = enterprise_equity_bridge(enterprise_value_keur=1000,
        senior_debt_keur=400, unrestricted_cash_keur=50, shl_balance_keur=100,
        restricted_cash_keur=80, debt_like_keur=0,
        working_capital_adjustment_keur=20, transaction_adjustment_keur=0)
    assert a["equity_value_keur"] == 570.0
    assert a["restricted_cash_excluded_keur"] == 80.0
    with pytest.raises(AcquisitionPolicyError):
        enterprise_equity_bridge(enterprise_value_keur=1000,
            senior_debt_keur=None, unrestricted_cash_keur=50,
            shl_balance_keur=100, restricted_cash_keur=80)


def _db(tmp_path, monkeypatch):
    import app.persistence.acquisition_repository as repo
    path = str(tmp_path / "cases.db")
    def get():
        conn = sqlite3.connect(path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    monkeypatch.setattr(repo, "get_connection", get)
    with get() as c:
        c.execute("CREATE TABLE projects (project_id TEXT PRIMARY KEY,user_id TEXT,archived INTEGER,"
                  "is_protected INTEGER,is_readonly INTEGER)")
        c.execute("CREATE TABLE model_run_history (history_id TEXT PRIMARY KEY,user_id TEXT,"
                  "project_id TEXT,runtime_snapshot_id TEXT,composite_hash TEXT,last_runtime_scenario_id TEXT)")
        c.execute("INSERT INTO projects VALUES ('project-A','owner-A',0,0,0)")
        c.execute("INSERT INTO model_run_history VALUES ('h-1','owner-A','project-A','snapshot-123',?,NULL)",
                  ('c'*64,))
    return path


def test_case_revision_cas_owner_protection_and_failed_rollback(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    entry = NS(history_id="h-1", runtime_snapshot_id="snapshot-123",
               composite_hash="c"*64, last_runtime_scenario_id=None)
    doc = make_document(entry, terms())
    case, revision = save_case(owner_id="owner-A",project_id="project-A",document=doc)
    assert revision == 1
    assert read_case(owner_id="owner-A",project_id="project-A",case_id=case)["revision"] == 1
    assert read_case(owner_id="owner-B",project_id="project-A",case_id=case) is None
    with pytest.raises(AcquisitionCaseConflict, match="CAS"):
        save_case(owner_id="owner-A",project_id="project-A",document=doc,
                  case_id=case,expected_revision=0)
    # Immutable source/run binding cannot be swapped in a case edit.
    changed = copy.deepcopy(doc)
    changed["source"]["snapshot_id"] = "forged"
    with pytest.raises(AcquisitionCaseConflict, match="SOURCE"):
        save_case(owner_id="owner-A",project_id="project-A",document=changed,
                  case_id=case,expected_revision=1)
    assert read_case(owner_id="owner-A",project_id="project-A",case_id=case)["revision"] == 1
    with sqlite3.connect(str(tmp_path / "cases.db")) as c:
        # Successful and failed acquisitions never mutate immutable financial history.
        assert c.execute("SELECT COUNT(*) FROM model_run_history").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM model_m6_acquisition_revisions").fetchone()[0] == 1
        assert c.execute("SELECT runtime_snapshot_id FROM model_run_history").fetchone()[0] == "snapshot-123"
    with sqlite3.connect(str(tmp_path / "cases.db")) as c:
        c.execute("UPDATE projects SET is_protected=1 WHERE project_id='project-A'")
    with pytest.raises(AcquisitionCaseConflict, match="PROTECTED"):
        save_case(owner_id="owner-A",project_id="project-A",document=doc,
                  case_id=case,expected_revision=1)


def test_governance_no_secondary_project_run_and_explicit_csrf_boundary():
    import inspect
    from app.v2 import acquisition_router
    from app.model_v2.acquisition import economics
    code = inspect.getsource(acquisition_router.acquisition_save)
    assert "validate_csrf_token" in code
    assert "is_protected_reference" in code
    assert "save_case(" in code
    review = inspect.getsource(acquisition_router.acquisition_review_candidate)
    assert "_review_gate(request)" in review
    assert "validate_csrf_token" in review
    get = inspect.getsource(acquisition_router.acquisition_page)
    assert "evaluate(" not in get
    gate = inspect.getsource(acquisition_router._review_gate)
    assert "resolve_admin_session" in gate
    assert "FINCO_M6_CANDIDATE_REVIEW" in gate
    assert '("development", "internal")' in gate
    calc = inspect.getsource(economics)
    assert "run_project(" not in calc
    assert "financial_engine.orchestrator" not in calc
    assert "ACTIVATION_ENABLED = False" in calc
