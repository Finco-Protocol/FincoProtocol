"""Exact canonical parity, adversarial evidence and no second financial authority."""
import copy
from pathlib import Path

import pytest

import test_model_quality_q1 as q1
from test_model_insight_q3 import fake_ws
from app.model_quality import evaluate_model_quality
from app.model_quality.evidence import evidence_from_workspace, terms_from_project_inputs
from app.run_integrity import evidence_digest, run_integrity_checks
from app.v2.diagnostics_projection import PERIOD_VALIDATORS
from app.v2.insight_quality_projection import build_quality_insight

runs = q1.runs


def diagnostics(pi, payload, state="CURRENT", **over):
    ws = fake_ws(payload, last_financial_statements=payload.get("financial_statements", {}), **over)
    quality = build_quality_insight(ws, run_state=state, project_inputs=pi,
        scenario_name="Base Case", active_scenario_id=ws.active_scenario_id, include_diagnostics=True)
    return ws, quality, quality["diagnostics"]


@pytest.mark.parametrize("vertical", list(q1.VERTICALS))
def test_exact_authority_parity_and_no_mutation(runs, vertical):
    pi, payload = runs[vertical]
    original = copy.deepcopy(payload)
    ws, quality, d = diagnostics(pi, payload)
    canonical = evaluate_model_quality(evidence_from_workspace(ws, freshness="CURRENT",
        terms=terms_from_project_inputs(pi), scenario_known=True))
    assert len(d["checks"]) == 30
    assert d["score"] == quality["score"]
    assert d["score"]["score"] == canonical.summary.score
    assert d["integrity"] == run_integrity_checks(ws.last_integrity_evidence).to_dict()
    for row in d["checks"]:
        c = canonical.check(row["check_id"])
        for key, value in c.to_dict().items():
            assert row[key] == value
        if row["status"] == "FAIL" and row["check_id"] in PERIOD_VALIDATORS:
            assert any(p["status"] == "FAIL" for p in row["periods"]) or row["global_component"]["status"] == "FAIL"
        for p in row["periods"]:
            assert p["run_identity"] == canonical.run_identity
            if row["check_id"] not in PERIOD_VALIDATORS:
                assert p["status"] in ("AGGREGATE_ONLY", "UNAVAILABLE", "NOT_PERIODIC")
    assert payload == original  # no schedule/input/numerical changes


def row(d, check):
    return next(c for c in d["checks"] if c["check_id"] == check)


def corrupt(payload, mutate, reseal=True):
    payload = copy.deepcopy(payload)
    mutate(payload["integrity_evidence"])
    if reseal:
        payload["integrity_evidence"]["digest"] = evidence_digest(payload["integrity_evidence"])
    return payload


@pytest.mark.parametrize("check,mutate", [
    ("QM-SU-001", lambda e: e["sources_uses"]["construction_periods"][0].update(sources=-123.0)),
    ("QM-ACC-001", lambda e: next(r for r in e["balance_sheet"] if r.get("retained_earnings") is not None).update(retained_earnings=123456.0)),
    ("QM-SD-001", lambda e: e["senior_debt"]["periods"][2].update(closing=123456.0)),
    ("QM-SD-002", lambda e: e["senior_debt"]["periods"][2].update(interest=123456.0)),
    ("QM-SD-003", lambda e: e["senior_debt"]["periods"][2].update(reported_dscr=123456.0)),
    ("QM-CASH-001", lambda e: e["cash"][2].update(cash_after_senior_before_reserves=-123.0)),
    ("QM-SD-004", lambda e: e["senior_debt"]["diagnostics"].update(is_authoritative=False)),
])
def test_real_failure_has_proven_period_or_explicit_boundary(runs, check, mutate):
    pi, payload = runs["solar"]
    _, _, d = diagnostics(pi, corrupt(payload, mutate))
    r = row(d, check)
    assert r["status"] == "FAIL"
    assert any(p["status"] == "FAIL" for p in r["periods"]) or r["global_component"]["status"] == "FAIL"
    failed = [p for p in r["periods"] if p["status"] == "FAIL"]
    assert all(p["reason"] and p["scope"] and p["snapshot_id"] for p in failed)


def test_adjacent_continuity_and_initial_commitment_are_not_lost(runs):
    pi, payload = runs["solar"]
    def mutation(e):
        r = e["senior_debt"]["periods"][2]
        r["opening"] += 5; r["closing"] += 5  # local arithmetic still balances
    _, _, d = diagnostics(pi, corrupt(payload, mutation))
    r = row(d, "QM-SD-001")
    assert r["status"] == "FAIL"
    assert any(p["status"] == "FAIL" and p["scope"] == "CUMULATIVE_THROUGH_PERIOD" for p in r["periods"])


def test_global_sources_failure_not_presented_as_period_residual(runs):
    pi, payload = runs["solar"]
    _, _, d = diagnostics(pi, corrupt(payload, lambda e: e["sources_uses"]["summary"].update(total_sources_keur=-1.)))
    r = row(d, "QM-SU-001")
    assert r["global_component"]["status"] == "FAIL"
    assert all(p["scope"] in ("PERIOD_AND_GLOBAL_SOURCES_USES", "UNAVAILABLE") for p in r["periods"])


def test_digest_corruption_blocks_all_period_proof(runs):
    pi, payload = runs["solar"]
    _, _, d = diagnostics(pi, corrupt(payload, lambda e: e["cash"][2].update(cash_after_senior_before_reserves=-9), False))
    assert row(d, "QM-PRV-001")["status"] == "FAIL"
    for c in d["checks"]:
        if c["check_id"] in PERIOD_VALIDATORS:
            assert all(p["status"] == "UNAVAILABLE" and p["reason"] == "EVIDENCE_DIGEST_NOT_INTACT" for p in c["periods"])


def test_missing_period_not_green_missing_covenant_not_threshold(runs):
    pi, payload = runs["solar"]
    removed_index = payload["integrity_evidence"]["senior_debt"]["periods"][2]["period_index"]
    _, _, d = diagnostics(pi, corrupt(payload, lambda e: e["senior_debt"]["periods"].pop(2)))
    p = next(p for p in row(d, "QM-SD-002")["periods"] if p["period_index"] == removed_index)
    assert p["status"] == "UNAVAILABLE"
    assert row(d, "QM-COV-001")["status"] == "UNAVAILABLE"
    assert row(d, "QM-COV-001")["threshold_value"] is None


def test_aggregate_pass_does_not_paint_periods_green(runs):
    pi, payload = runs["solar"]
    _, _, d = diagnostics(pi, payload)
    r = row(d, "QM-ACC-003")
    assert r["status"] == "PASS"
    assert all(p["status"] == "AGGREGATE_ONLY" for p in r["periods"])


@pytest.mark.parametrize("state", ["CURRENT", "STALE"])
def test_last_run_identity_and_stale_threshold_scope(runs, state):
    pi, payload = runs["solar"]
    _, q, d = diagnostics(pi, payload, state, active_scenario_id="different-scenario")
    assert d["state"] == state and d["identity"]["snapshot_id"] == q1.SNAP
    assert row(d, "QM-PRV-005")["status"] == "WARNING"
    if state == "STALE":
        assert not q["terms_bound"]
        assert row(d, "QM-COV-002")["threshold_value"] is None


def test_not_run_has_no_invented_checks_or_score(runs):
    pi, payload = runs["solar"]
    _, _, d = diagnostics(pi, payload, "NOT_RUN")
    assert d == {"state": "NOT_RUN", "available": False}


def test_diagnostic_code_has_no_execution_persistence_or_scorer():
    import ast
    root = Path(__file__).resolve().parents[1]
    source = (root / "app/v2/diagnostics_projection.py").read_text()
    tree = ast.parse(source)
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(m and m.startswith(("financial_engine", "finco_core", "app.persistence")) for m in imports)
    assert "evaluate_model_quality(" not in source and "score_checks(" not in source


@pytest.mark.parametrize("vertical", list(q1.VERTICALS))
def test_period_residuals_reconcile_exactly_to_full_validator(runs, vertical):
    pi, payload = runs[vertical]
    _, _, d = diagnostics(pi, payload)
    for cid in PERIOD_VALIDATORS:
        r = row(d, cid)
        residuals = [p["residual"] for p in r["periods"] if p["residual"] is not None]
        if residuals and r["measured_value"] is not None:
            assert max(residuals) == r["measured_value"], cid
        if r["status"] == "PASS":
            assert not any(p["status"] == "FAIL" for p in r["periods"])


@pytest.mark.parametrize("dates", [["2027-01-31", "2027-02-28"], ["2027-03-31", "2027-06-30"],
                                  ["2027-06-30", "2027-12-31"], ["2027-12-31", "2028-12-31"]])
def test_axis_uses_persisted_dates_not_annual_or_working_copy_assumptions(runs, dates):
    pi, payload = runs["solar"]
    _, _, d = diagnostics(pi, payload, last_runtime_at="2026-10-10T00:00:00+00:00")
    from app.v2.diagnostics_projection import _axis
    ws = fake_ws(payload, last_financial_statements={"pnl": {"periods": [
        {"period": i, "date": date} for i, date in enumerate(dates)]}})
    columns, _ = _axis(ws, {})
    assert [c["date"] for c in columns] == dates


# Frozen pre-extension full-run control from main 153d7044958bb94d01ff07325c09c6b354aa32fa.
# TEST ONLY: no legacy validator or alternative authority is introduced at runtime.
_PRE_EXTENSION_SENIOR_VALIDATOR = "def check_senior_rollforward(evidence: Mapping[str, Any]) -> IntegrityCheck:\n    cid, title = \"SENIOR_DEBT_ROLLFORWARD\", \"Opening + draws - principal = closing\"\n    rows = _debt_rows(evidence)\n    su = _section(evidence, \"sources_uses\", \"summary\")\n    if rows is None or not isinstance(su, Mapping) or not _complete(su, \"senior_debt_keur\"):\n        return _unavailable(cid, title, \"SENIOR_DEBT_EVIDENCE_MISSING\")\n    if not rows:\n        if abs(su[\"senior_debt_keur\"]) <= TOL_KEUR:\n            return IntegrityCheck(cid, title, CheckStatus.NOT_APPLICABLE, \"NO_SENIOR_DEBT\")\n        return IntegrityCheck(cid, title, CheckStatus.FAIL, \"SENIOR_DEBT_SCHEDULE_MISSING\",\n                              detail=\"senior debt is committed but the schedule is empty\")\n    if not all(_complete(r, \"opening\", \"principal\", \"closing\") for r in rows):\n        return _unavailable(cid, title, \"SENIOR_DEBT_EVIDENCE_MISSING\")\n    deviations = []\n    for row in rows:  # operating periods draw nothing: draws are committed before COD\n        deviations.append(abs(row[\"opening\"] - row[\"principal\"] - row[\"closing\"]))\n        if row[\"principal\"] < -TOL_KEUR or row[\"closing\"] < -TOL_KEUR:\n            deviations.append(abs(min(row[\"principal\"], row[\"closing\"])))\n    for previous, current in zip(rows, rows[1:]):\n        deviations.append(abs(current[\"opening\"] - previous[\"closing\"]))\n    deviations.append(abs(rows[0][\"opening\"] - su[\"senior_debt_keur\"]))  # draws sum to the commitment\n    result = _verdict(cid, title, deviations, TOL_KEUR, \"SENIOR_ROLLFORWARD_BREAK\", evaluated=len(rows),\n                      detail=\"period roll-forward, opening-to-closing chain, and first opening = committed senior debt\")\n    if result.status is CheckStatus.PASS and not _section(evidence, \"senior_debt\", \"permit_terminal_balloon\"):\n        if rows[-1][\"closing\"] > TOL_KEUR:\n            return IntegrityCheck(cid, title, CheckStatus.FAIL, \"SENIOR_TERMINAL_BALANCE_UNREPAID\",\n                                  len(rows), rows[-1][\"closing\"], TOL_KEUR)\n    return result\n"


@pytest.mark.parametrize("vertical", list(q1.VERTICALS))
@pytest.mark.parametrize("case", ["original", "arithmetic", "continuity", "terminal", "missing"])
def test_full_run_validator_matches_pre_extension_exactly(runs, vertical, case):
    from app.run_integrity import checks
    ev = copy.deepcopy(runs[vertical][1]["integrity_evidence"])
    debt = ev["senior_debt"]
    if case == "arithmetic":
        debt["periods"][2]["closing"] += 5
    elif case == "continuity":
        debt["periods"][2]["opening"] += 5
        debt["periods"][2]["closing"] += 5
    elif case == "terminal":
        debt["permit_terminal_balloon"] = False
        for r in debt["periods"]:
            r.update(opening=ev["sources_uses"]["summary"]["senior_debt_keur"], principal=0,
                     closing=ev["sources_uses"]["summary"]["senior_debt_keur"])
    elif case == "missing":
        debt["periods"][2].pop("opening")
    namespace = dict(vars(checks))
    exec(_PRE_EXTENSION_SENIOR_VALIDATOR, namespace)
    expected = namespace["check_senior_rollforward"](ev).to_dict()
    assert checks.check_senior_rollforward(ev).to_dict() == expected
    assert checks.check_senior_rollforward(ev, terminal_boundary_is_present=True).to_dict() == expected


def test_prefix_preserves_balloon_policy_and_terminal_failure_is_proven(runs):
    from app.v2.diagnostics_projection import _restricted
    pi, payload = runs["solar"]
    ev = copy.deepcopy(payload["integrity_evidence"])
    ev["senior_debt"]["permit_terminal_balloon"] = False
    rows = ev["senior_debt"]["periods"]
    for r in rows:
        r.update(opening=ev["sources_uses"]["summary"]["senior_debt_keur"], principal=0,
                 closing=ev["sources_uses"]["summary"]["senior_debt_keur"])
    payload = copy.deepcopy(payload)
    ev["digest"] = evidence_digest(ev)
    payload["integrity_evidence"] = ev
    _, _, d = diagnostics(pi, payload)
    c = row(d, "QM-SD-001")
    assert c["status"] == "FAIL" and c["reason_code"] == "SENIOR_TERMINAL_BALANCE_UNREPAID"
    first = next(p for p in c["periods"] if p["period_index"] == rows[0]["period_index"])
    final = next(p for p in c["periods"] if p["period_index"] == rows[-1]["period_index"])
    assert first["status"] == "PASS" and final["status"] == "FAIL"
    assert final["reason"] == "SENIOR_TERMINAL_BALANCE_UNREPAID"
    prefix, _ = _restricted("QM-SD-001", ev, rows[0]["period_index"])
    assert prefix["senior_debt"]["permit_terminal_balloon"] is False


def test_shl_inspector_copies_intact_sponsor_facts_only(runs):
    pi, payload = runs["solar"]
    _, _, d = diagnostics(pi, payload)
    for label, key in (("SHL interest", "shl_cash_interest"), ("SHL principal", "shl_principal")):
        line = next(r for r in d["waterfall"] if r["label"] == label)
        assert line["source"] == "Last Run.integrity_evidence.sponsor.periods." + key
        for col, value in zip(d["columns"], line["values"]):
            matching = [r for r in payload["integrity_evidence"]["sponsor"]["periods"]
                        if r["period"] == col["index"] and r["date"] == col["date"]]
            assert value == (matching[0].get(key) if len(matching) == 1 else None)
    bad = corrupt(payload, lambda e: e["sponsor"]["periods"][0].update(shl_cash_interest=99999), False)
    _, _, d = diagnostics(pi, bad)
    assert all(v is None for line in d["waterfall"] if line["label"].startswith("SHL") for v in line["values"])


def test_unrendered_boundary_failure_is_explicit_not_an_all_green_run(runs, monkeypatch):
    import app.v2.diagnostics_projection as projection
    pi, payload = runs["solar"]
    monkeypatch.setattr(projection, "MAX_RENDERED_PERIODS", 3)
    def failure(e):
        e["senior_debt"]["periods"][-1]["closing"] += 5
    _, _, d = diagnostics(pi, corrupt(payload, failure))
    c = row(d, "QM-SD-001")
    assert d["truncated"] and d["total_periods"] > len(d["columns"])
    assert c["status"] == "FAIL"
    assert not any(p["status"] == "FAIL" for p in c["periods"])
    assert c["global_component"]["status"] == "FAIL"
    assert c["global_component"]["scope"] == "AGGREGATE_OR_UNRENDERED_BOUNDARY"
