"""SC-01: committed distribution-account evidence, not unrestricted cash or new financial policy."""
from __future__ import annotations

import copy
from decimal import Decimal

import pytest

from app.v2.diagnostics_dx_checks import Facts, evaluate_advanced_checks
from tests.test_model_decision_workspace_v2 import env  # noqa: F401
from tests.test_model_diagnostics_v2 import _base_state, _period, _results, _row, _ws


def _retained_state():
    state = _base_state()
    retained = Decimal("37.123456789")
    current = Decimal("286.234567891")
    paid = retained + current
    for i, inflow, dividend, closing, locked in (
        (2, retained, Decimal(0), retained, True),
        (3, current, paid, Decimal(0), False),
    ):
        _row(state, "pf", i).update(fcf_for_distribution_keur=round(float(inflow), 2),
                                  net_dividends_keur=round(float(dividend), 2))
        state["evidence"]["balance_sheet"][i]["distribution_account"] = float(closing)
        state["evidence"]["sponsor"]["periods"][i]["legal_equity_distribution"] = float(dividend)
        state["dist"]["periods"][i].update(lockup_active=locked, distribution_keur=round(float(dividend), 2))
    return state, retained, current, paid


def test_retained_account_release_passes_with_full_precision_balances_and_independent_arithmetic():
    state, retained, current, paid = _retained_state()
    before = copy.deepcopy(state)
    result = _results(state)["DX-DIST-001"]
    assert paid - current == retained
    assert _period(result, 2)["status"] == _period(result, 3)["status"] == "PASS"
    release = _period(result, 3)["components"]
    assert release["opening_distribution_account"]["value"] == float(retained)
    assert release["closing_distribution_account"]["value"] == 0
    assert release["sponsor_legal_equity_distribution"]["value"] == float(paid)
    assert abs(Decimal(str(release["distribution_account_release"]["value"])) - paid) < Decimal("0.005")
    assert release["distribution_account_release"]["basis"] == "PERSISTED_2DP"
    assert state == before


def test_actual_overdistribution_still_fails_even_with_opening_retained_funds():
    state, _, _, paid = _retained_state()
    _row(state, "pf", 3)["net_dividends_keur"] = round(float(paid + Decimal("3.25")), 2)
    state["evidence"]["sponsor"]["periods"][3]["legal_equity_distribution"] = float(paid + Decimal("3.25"))
    row = _period(_results(state)["DX-DIST-001"], 3)
    assert row["status"] == "FAIL" and "DISTRIBUTION_EXCEEDS_CASH_AVAILABLE" in row["reason"]
    assert row["residual"] > 3.24


def test_unrestricted_cash_is_never_distribution_release_authority():
    state = _base_state()
    state["evidence"]["balance_sheet"][2]["unrestricted_cash"] = 100000.0
    _row(state, "pf", 3)["net_dividends_keur"] = 100.0
    state["evidence"]["sponsor"]["periods"][3]["legal_equity_distribution"] = 100.0
    assert _period(_results(state)["DX-DIST-001"], 3)["status"] == "FAIL"


def test_locked_account_cannot_release_and_open_account_must_reconcile():
    state, _, _, _ = _retained_state()
    state["dist"]["periods"][3]["lockup_active"] = True
    row = _period(_results(state)["DX-DIST-001"], 3)
    assert row["status"] == "FAIL" and "DISTRIBUTION_PAID_IN_COMMITTED_LOCKUP_PERIOD" in row["reason"]
    assert "DISTRIBUTION_ACCOUNT_MOVEMENT_DISAGREES_WITH_COMMITTED_GATE" in row["reason"]
    state, _, _, _ = _retained_state()
    state["evidence"]["balance_sheet"][2]["distribution_account"] += 1
    row = _period(_results(state)["DX-DIST-001"], 2)
    assert row["status"] == "FAIL" and row["residual"] == pytest.approx(1, abs=.005)
    assert row["residual"] == row["observed"] - row["expected"]
    assert abs(row["residual"]) > row["tolerance"]


def test_full_precision_lock_violation_reports_its_actual_tolerance_and_amount():
    state = _base_state()
    _row(state, "pf", 3).update(net_dividends_keur=0.0, fcf_for_distribution_keur=0.0)
    state["dist"]["periods"][3]["lockup_active"] = True
    state["evidence"]["sponsor"]["periods"][3]["legal_equity_distribution"] = 0.000002
    row = _period(_results(state)["DX-DIST-001"], 3)
    assert row["status"] == "FAIL"
    assert row["reason"] == "DISTRIBUTION_PAID_IN_COMMITTED_LOCKUP_PERIOD"
    assert row["observed"] == row["residual"] == 0.000002
    assert row["expected"] == 0.0 and row["tolerance"] == 0.000001


def test_rounded_zero_inflow_can_retain_a_small_real_amount_without_false_failure():
    state = _base_state()
    _row(state, "pf", 3).update(net_dividends_keur=0.0, fcf_for_distribution_keur=0.0)
    state["dist"]["periods"][3]["lockup_active"] = True
    state["evidence"]["balance_sheet"][3]["distribution_account"] = 0.004
    state["evidence"]["sponsor"]["periods"][3]["legal_equity_distribution"] = 0.0
    assert _period(_results(state)["DX-DIST-001"], 3)["status"] == "PASS"
    state["evidence"]["balance_sheet"][3]["distribution_account"] = 0.006
    row = _period(_results(state)["DX-DIST-001"], 3)
    assert row["status"] == "FAIL" and row["residual"] == 0.006
    assert row["tolerance"] == pytest.approx(0.005001)


def test_rounded_zero_dividend_is_compared_to_full_legal_amount_with_representation_bound():
    state = _base_state()
    _row(state, "pf", 3)["net_dividends_keur"] = 0.0
    state["evidence"]["sponsor"]["periods"][3]["legal_equity_distribution"] = 0.004
    assert _period(_results(state)["DX-DIST-001"], 3)["status"] == "PASS"


@pytest.mark.parametrize("missing", ["opening", "closing", "source", "gate", "sponsor", "previous_period", "date"])
def test_missing_account_or_release_evidence_is_unavailable_not_zero_or_pass(missing):
    state, _, _, _ = _retained_state()
    if missing in ("opening", "closing"):
        state["evidence"]["balance_sheet"][2 if missing == "opening" else 3].pop("distribution_account")
    elif missing == "source":
        state["dist"]["periods"][3].pop("distribution_source")
    elif missing == "gate":
        state["dist"]["periods"][3].pop("lockup_active")
    elif missing == "sponsor":
        state["evidence"]["sponsor"]["periods"][3].pop("legal_equity_distribution")
    elif missing == "previous_period":
        state["statements"]["pf_cash_waterfall"]["periods"].pop(2)
    else:
        state["dist"]["periods"][3].pop("date")
    assert _period(_results(state)["DX-DIST-001"], 3)["status"] == "UNAVAILABLE"


@pytest.mark.parametrize("kind", ["reversed_dates", "date_mismatch", "unknown_source", "duplicate_balance", "bad_digest"])
def test_incoherent_or_untrusted_account_evidence_fails_closed(kind):
    state, _, _, _ = _retained_state()
    if kind == "reversed_dates":
        _row(state, "pf", 2)["date"] = "2040-01-01"
    elif kind == "date_mismatch":
        state["dist"]["periods"][3]["date"] = "2031-07-02"
    elif kind == "unknown_source":
        state["dist"]["periods"][3]["distribution_source"] = "unproven"
    elif kind == "duplicate_balance":
        state["evidence"]["balance_sheet"].append(copy.deepcopy(state["evidence"]["balance_sheet"][2]))
    assert _period(_results(state, digest_ok=kind != "bad_digest")["DX-DIST-001"], 3)["status"] == "UNAVAILABLE"


def test_reordered_storage_rows_join_by_period_not_list_position():
    state, _, _, _ = _retained_state()
    state["evidence"]["balance_sheet"].reverse()
    state["dist"]["periods"].reverse()
    assert _period(_results(state)["DX-DIST-001"], 3)["status"] == "PASS"


def test_shl_can_consume_release_before_legal_dividends_without_diagnostic_recalculation():
    state, _, _, paid = _retained_state()
    equity = paid - Decimal("19.75")
    _row(state, "pf", 3)["net_dividends_keur"] = round(float(equity), 2)
    state["evidence"]["sponsor"]["periods"][3].update(legal_equity_distribution=float(equity), shl_principal=19.75)
    assert _period(_results(state)["DX-DIST-001"], 3)["status"] == "PASS"


def test_evaluation_leaves_committed_evidence_and_other_diagnostics_unchanged():
    state, _, _, _ = _retained_state()
    ws = _ws(state)
    before = copy.deepcopy(vars(ws))
    first = evaluate_advanced_checks(Facts.from_workspace(ws, digest_ok=True))
    second = evaluate_advanced_checks(Facts.from_workspace(ws, digest_ok=True))
    assert first == second and vars(ws) == before


@pytest.mark.parametrize("mode", ["legacy", "two"])
def test_real_single_and_two_senior_evaluation_preserves_entire_run_and_history(env, monkeypatch, mode):
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.workspace_repository import get_workspace_state
    from app.run_integrity.evidence import evidence_digest
    from tests.test_model_diagnostics_v2_real_runs import _get, _make, USER

    record = _make(env, monkeypatch, "solar", mode)
    workspace = get_workspace_state(USER, record.project_id)
    history = copy.deepcopy(get_run_history(USER, record.project_id, limit=50))
    digest = evidence_digest(workspace.last_integrity_evidence)
    _, data = _get(env, record)
    check = next(c for c in data["v2"]["advanced_checks"] if c["check_id"] == "DX-DIST-001")
    assert check["status"] == "PASS" and check["coverage"]["evaluated_periods"] > 0
    missing = [p for p in check["periods"] if p["status"] == "UNAVAILABLE"]
    assert all(p["reason"] in {"ADJACENT_DISTRIBUTION_ACCOUNT_BALANCE_MISSING",
                               "SPONSOR_DISTRIBUTION_EVIDENCE_MISSING"} for p in missing), missing
    assert check["coverage"]["complete"] is (not missing)
    assert get_workspace_state(USER, record.project_id) == workspace
    assert get_run_history(USER, record.project_id, limit=50) == history
    assert evidence_digest(get_workspace_state(USER, record.project_id).last_integrity_evidence) == digest
