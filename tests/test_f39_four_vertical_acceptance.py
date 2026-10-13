"""F3.9 four-vertical acceptance: independent reconciliation of REAL committed Runs.

Solar, Wind, Data Center and EV Charging, each as legacy single-Senior, F3 two-Senior and the test-only
Senior+Junior configuration (the controlled synthetic path; production activation stays disabled), plus signed
Revenue V2 contract runs.  Everything is read from the immutable Run History entry; the application is never changed.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.persistence.run_history_repository import get_latest_history_entry, get_run_history
from tests.test_financing_f37_instrument_su import _junior_run, _two_senior_run
from tests.test_model_decision_workspace_v2 import env  # noqa: F401  (fixture)
from tests.test_model_financing_f2 import run
from tools.numerical_validation import coverage
from tools.numerical_validation.identities import reconcile_bundle
from tools.numerical_validation.periodic import reports
from tools.numerical_validation.source import bundle_from_history_entry, source_sha256, verify_source_binding

KINDS = ["solar", "wind", "data_center", "ev_charging"]
MODES = ["legacy", "two", "junior"]
USER = "decision-user"
ROOT = Path(__file__).resolve().parents[1]


def _make(env, monkeypatch, kind, mode):
    if mode == "legacy":
        record = env.create(kind)
        run(env, record)
    elif mode == "two":
        record, _, _ = _two_senior_run(env, monkeypatch, kind)
    else:
        record, _, _ = _junior_run(env, monkeypatch, kind)
    return record


def _entry(record):
    return get_latest_history_entry(USER, record.project_id)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("mode", MODES)
def test_real_run_reconciles_with_no_failure_and_is_bound_to_the_run(env, monkeypatch, kind, mode):
    record = _make(env, monkeypatch, kind, mode)
    entry = _entry(record)
    bundle = bundle_from_history_entry(entry)
    result = reconcile_bundle(bundle)

    assert result["counts"]["FAIL"] == 0 and result["first_divergence"] is None, result["first_divergence"]
    assert result["counts"]["PASS"] > 300
    ident = result["identity"]
    assert ident["run_key"] == entry.history_id and ident["composite_hash"] == entry.composite_hash
    assert ident["snapshot_id"] == entry.runtime_snapshot_id and ident["engine_version"] == entry.engine_version
    assert ident["project_key"] == entry.project_code and len(ident["configuration_sha256"]) == 64
    assert verify_source_binding(bundle, entry) == []

    verdict = {r["identity"]: r for r in result["by_identity"]}
    for key in ("AXIS-INTEGRITY", "UNIT-CONSISTENCY", "REV-TOTAL", "REV-STATEMENT", "EBITDA-SUMMARY"):
        assert verdict[key]["verdict"] == "VERIFIED", (key, verdict[key])
    # nothing is silently promoted: facility attribution of tax and NPV remain disclosed, not invented
    assert {u["capability"] for u in bundle["unsupported"]} >= {"facility_tax_attribution", "npv"}
    if mode == "legacy":
        assert verdict["FAC-DEBT-ROLLFORWARD"]["verdict"] in ("UNAVAILABLE", "NOT_COMPARABLE") \
            if "FAC-DEBT-ROLLFORWARD" in verdict else True
    else:
        facility_rows = [r for r in result["by_identity"] if r["identity"].startswith("FAC-")]
        assert any(r["counts"]["PASS"] for r in facility_rows)


@pytest.mark.parametrize("kind", KINDS)
def test_reconciliation_is_deterministic_and_does_not_touch_the_immutable_run(env, kind):
    record = env.create(kind)
    run(env, record)
    before = get_run_history(USER, record.project_id, limit=50)
    snapshot = [json.dumps(dataclasses.asdict(h), sort_keys=True, default=str) for h in before]
    first = reports(reconcile_bundle(bundle_from_history_entry(_entry(record))))
    second = reports(reconcile_bundle(bundle_from_history_entry(_entry(record))))
    assert first == second
    after = get_run_history(USER, record.project_id, limit=50)
    assert [json.dumps(dataclasses.asdict(h), sort_keys=True, default=str) for h in after] == snapshot


def test_current_stale_and_last_run_immutability(env, monkeypatch):
    from app.workbook import multisenior_config as config
    from app.workbook.input_set import ProjectInputSet
    from app.persistence.workspace_repository import get_workspace_state
    from tests.test_model_financing_f2 import save
    from tests.test_model_financing_f3_workspace import collection_for_inputs, state

    record, ws, rr = _two_senior_run(env, monkeypatch, "solar")
    first = get_run_history(USER, record.project_id, limit=1)[0]
    bundle_one = bundle_from_history_entry(first)
    result_one = reconcile_bundle(bundle_one)

    # change an input: the working copy is now STALE relative to the Last Run
    new = json.loads(state(active=True, collection=collection_for_inputs(
        ProjectInputSet.from_snapshot(get_workspace_state(USER, record.project_id).draft_snapshot).to_projectinputs())))
    new["scopes"]["base"]["proposal"]["instruments"][0]["interest"]["fixed_rate"] = .07
    new["scopes"]["base"]["activation"]["proposal_digest"] = "BIND_ON_SAVE"
    assert "field-error" not in save(env, record, json.dumps(new), field=config.FIELD_ID).text

    # the committed Run is untouched by the edit: same evidence, same digest, same result
    again = get_run_history(USER, record.project_id, limit=1)[0]
    assert again.history_id == first.history_id and source_sha256(again) == source_sha256(first)
    assert reports(reconcile_bundle(bundle_from_history_entry(again))) == reports(result_one)

    # a new Run is a NEW immutable record with a different configuration, still reconciled with no FAIL
    run(env, record)
    latest = _entry(record)
    assert latest.history_id != first.history_id and latest.composite_hash != first.composite_hash
    result_two = reconcile_bundle(bundle_from_history_entry(latest))
    assert result_two["counts"]["FAIL"] == 0
    assert result_two["identity"]["configuration_sha256"] != result_one["identity"]["configuration_sha256"]
    # and the earlier Run still reconciles to exactly its original result
    old = next(h for h in get_run_history(USER, record.project_id, limit=10) if h.history_id == first.history_id)
    assert reports(reconcile_bundle(bundle_from_history_entry(old))) == reports(result_one)


# ── negatives, derived from a REAL Run ───────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def real(env):
    record = env.create("solar")
    run(env, record)
    entry = _entry(record)
    return entry, reconcile_bundle(bundle_from_history_entry(entry))


def _mutated(entry, **changes):
    return dataclasses.replace(entry, **{k: v for k, v in changes.items()})


def _pnl_rows(statements):
    return statements["pnl"]["periods"]


def test_negative_residual_in_a_statement_is_caught_at_the_earliest_stage(real):
    entry, clean = real
    statements = copy.deepcopy(dict(entry.financial_statements))
    row = next(r for r in _pnl_rows(statements) if r.get("revenues_keur"))
    row["revenues_keur"] = row["revenues_keur"] - 50.0
    result = reconcile_bundle(bundle_from_history_entry(_mutated(entry, financial_statements=statements)))
    assert result["counts"]["FAIL"] > 0 and clean["counts"]["FAIL"] == 0
    first = result["first_divergence"]
    assert first["period"] and first["classification"] in ("CALCULATION_MISMATCH", "INPUT_MISMATCH")
    failed = next(o for o in result["outcomes"] if o["status"] == "FAIL" and o["identity"] == first["identity"])
    assert failed["residual_observed_minus_expected"].startswith("-") or failed["residual_observed_minus_expected"].startswith("5")
    stages = {o["stage"] for o in result["outcomes"] if o["status"] == "FAIL"}
    assert first["stage"] in stages


def test_duplicate_period_is_not_comparable_not_silently_merged(real):
    entry, clean = real
    statements = copy.deepcopy(dict(entry.financial_statements))
    rows = _pnl_rows(statements)
    rows.append(copy.deepcopy(rows[-1]))
    result = reconcile_bundle(bundle_from_history_entry(_mutated(entry, financial_statements=statements)))
    axis = next(r for r in result["by_identity"] if r["identity"] == "AXIS-INTEGRITY")
    assert axis["counts"]["NOT_COMPARABLE"] >= 1 and axis["verdict"] != "VERIFIED"
    assert "DUPLICATE_PERIOD" in axis["reasons"]


def test_missing_period_is_never_read_as_zero(real):
    entry, clean = real
    debt = copy.deepcopy(dict(entry.debt_schedule))
    removed = debt["periods"].pop(len(debt["periods"]) // 2)
    result = reconcile_bundle(bundle_from_history_entry(_mutated(entry, debt_schedule=debt)))
    assert removed
    weaker = result["counts"]["UNAVAILABLE"] + result["counts"]["NOT_COMPARABLE"] + result["counts"]["FAIL"]
    base = clean["counts"]["UNAVAILABLE"] + clean["counts"]["NOT_COMPARABLE"] + clean["counts"]["FAIL"]
    assert weaker > base, "a missing period must reduce coverage or fail, never pass as zero"
    assert result["counts"]["PASS"] < clean["counts"]["PASS"]


def test_unit_mismatch_is_withheld_and_reported(real):
    entry, _ = real
    bundle = bundle_from_history_entry(entry)
    bundle = copy.deepcopy(bundle)
    bundle["series"]["ev.senior.interest"]["unit"] = "EUR"
    result = reconcile_bundle(bundle)
    unit = next(r for r in result["by_identity"] if r["identity"] == "UNIT-CONSISTENCY")
    assert unit["counts"]["NOT_COMPARABLE"] == 1 and unit["reasons"] == ["UNIT_MISMATCH_EUR_EXPECTED_kEUR"]
    # the EUR-labelled series is not compared against kEUR values
    assert result["counts"]["FAIL"] == 0


def test_tampered_source_is_detected_by_the_bound_digest(real):
    entry, _ = real
    bundle = bundle_from_history_entry(entry)
    assert verify_source_binding(bundle, entry) == []
    statements = copy.deepcopy(dict(entry.financial_statements))
    _pnl_rows(statements)[0]["revenues_keur"] = 12345.0
    assert "SOURCE_HASH_MISMATCH" in verify_source_binding(bundle, _mutated(entry, financial_statements=statements))
    other = _mutated(entry, composite_hash="0" * 64)
    assert "IDENTITY_MISMATCH_composite_hash" in verify_source_binding(bundle, other)


def test_identity_is_required(real):
    from tools.numerical_validation.evidence import build_bundle
    from tools.numerical_validation.reconcile import ReconciliationInputError

    entry, _ = real
    with pytest.raises(ReconciliationInputError):
        build_bundle({"runtime_summary": entry.runtime_summary}, {"project_key": "p"})


# ── signed Revenue V2 contract runs (Solar and Wind) ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("strike", [100, 40])
def test_contract_revenue_reconciles_including_negative_signed_settlement(env, kind, strike):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    from tests.test_wf07_revenue_multistream import contracts
    from tests.test_wf07_revenue_workspace import contract_tokens

    record = env.create(kind)
    project = {"project": record.project_code}
    inputs = WorkbookService.build_draft_input_set_from_workspace(get_workspace_state(USER, record.project_id)).to_projectinputs()
    payload = contracts(inputs, kind, price=95, merchant_price=90, strike=strike, index=.02)
    page = env.client.get("/v2/workbook", params=project)
    response = env.client.post("/v2/workbook/revenue/contracts", headers={"HX-Request": "true"},
                               data={**project, **contract_tokens(page.text), "contracts": json.dumps(payload)})
    assert response.status_code == 200
    run(env, record)
    bundle = bundle_from_history_entry(_entry(record))
    result = reconcile_bundle(bundle)
    assert result["counts"]["FAIL"] == 0
    rows = {r["identity"]: r for r in result["by_identity"]}
    for key in ("RV2-ENERGY-REVENUE", "RV2-CFD-SETTLEMENT", "RV2-NET-REVENUE", "RV2-NET-VS-REVENUE-PERIOD",
                "RV2-GENERATION-ALLOCATION"):
        assert rows[key]["verdict"] == "VERIFIED" and rows[key]["counts"]["PASS"] > 0, key
    settlements = [float(v) for v in bundle["series"]["rv2.settlement"]["values"].values() if v is not None]
    assert settlements and (min(settlements) < 0 if strike == 40 else max(settlements) > 0)


@pytest.mark.parametrize("kind", ["data_center", "ev_charging"])
def test_revenue_v2_is_disclosed_unsupported_for_data_center_and_ev(env, kind):
    record = env.create(kind)
    run(env, record)
    result = reconcile_bundle(bundle_from_history_entry(_entry(record)))
    assert not [r for r in result["by_identity"] if r["identity"].startswith("RV2-") and r["counts"]["PASS"]]


# ── four-vertical matrix and CLI ────────────────────────────────────────────────────────────────────────────────
def test_four_vertical_coverage_matrix_has_no_failure_and_discloses_gaps(env, monkeypatch, tmp_path):
    results = {}
    for kind in KINDS:
        record = env.create(kind)
        run(env, record)
        results[f"{kind}/legacy"] = reconcile_bundle(bundle_from_history_entry(_entry(record)))
    matrix = coverage.build_matrix(results)
    assert matrix["configurations_with_fail"] == [] and len(matrix["configurations"]) == 4
    rendered = coverage.render(results)
    assert rendered == coverage.render(results)
    text = rendered["coverage.md"].decode()
    assert "Unsupported capabilities" in text and "external_workbook_parity" in text
    cells = matrix["identities"]["FAC-DEBT-ROLLFORWARD"]["cells"] if "FAC-DEBT-ROLLFORWARD" in matrix["identities"] else {}
    assert all(c["verdict"] in ("NOT_APPLICABLE", "UNAVAILABLE", "NOT_COMPARABLE") for c in cells.values())


def test_cli_exit_codes_and_private_output(env, tmp_path):
    record = env.create("wind")
    run(env, record)
    bundle = bundle_from_history_entry(_entry(record))
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    out = tmp_path / "artifacts" / "f39"
    proc = subprocess.run([sys.executable, "-m", "tools.numerical_validation.verify", "--bundle", str(path),
                           "--output", str(out)], cwd=ROOT, capture_output=True, text=True)
    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    assert summary["counts"]["FAIL"] == 0 and summary["first_divergence"] is None
    # legacy runs leave non-persisted identities UNAVAILABLE: a verdict (2), not a crash and not a silent pass
    assert proc.returncode == 2, proc.stderr
    assert {p.name for p in out.iterdir()} == {"report.json", "report.csv", "report.md"}
    bad = subprocess.run([sys.executable, "-m", "tools.numerical_validation.verify", "--bundle", str(tmp_path / "nope.json"),
                          "--output", str(out)], cwd=ROOT, capture_output=True, text=True)
    assert bad.returncode == 3 and "RECONCILIATION_BLOCKED" in bad.stderr
