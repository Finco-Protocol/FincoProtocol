"""RC-7A compatibility proofs; no quarterly production admission is granted."""
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal, localcontext
import ast
import json
from pathlib import Path
import subprocess

import pytest

from tools.quarterly_research import ACTIVATION_ENABLED
from tools.quarterly_research.calendar import QuarterlyCandidateAxis, RenewableTechnology
from tools.quarterly_research.runtime import (
    QuarterlyDebtStudy, build_operating_candidate, evaluate_quarterly_candidate,
)
from test_rc7_quarterly_calendar import candidate_calendar
from test_rc7_quarterly_financial_candidate import study
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
BASE = "78e4c0edcc1bdb5013df79f11b3ba7b9c2151013"
D = Decimal


def _git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def test_review_inventory_is_not_release_authorization_and_matches_git_bytes():
    manifest = json.loads((ROOT / "docs/model_v2/RC7_QUARTERLY_CANDIDATE_BLOB_MANIFEST.json").read_text())
    assert manifest["release_approved"] is False
    assert manifest["activation_enabled"] is False and ACTIVATION_ENABLED is False
    assert manifest["research_only"] is True and manifest["not_a_project_run"] is True
    blobs = manifest["research_git_blobs"]
    assert len(blobs) == 4
    for path, expected in blobs.items():
        assert path.startswith("tools/quarterly_research/")
        assert _git("hash-object", "--path=" + path, path) == expected
    assert not (ROOT / "docs/rc3/QUARTERLY_FINANCIAL_ACCEPTANCE.json").exists()


def _authority_maps(source):
    result = {}
    for node in ast.parse(source).body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        for target in targets:
            if isinstance(target, ast.Name) and target.id.endswith("_AUTHORITIES"):
                result[target.id] = ast.literal_eval(node.value)
    return result


def test_historical_authority_maps_remain_exactly_the_rc7a_maps():
    path = "tests/model_v2_governance.py"
    original = _authority_maps(_git("show", BASE + ":" + path))
    assert original, "a missing authority inventory is not proof of preservation"
    assert _authority_maps((ROOT / path).read_text(encoding="utf-8")) == original


def test_all_historical_m7_and_ppa_bytes_are_preserved_without_successors():
    # The current-byte assertions remain blocking until an independently
    # accepted financial successor exists. Historical proof below is separate.
    from tests.m7_rc3_candidate_successor import M7_RC3_CANDIDATE_AUTHORITIES
    from tests.ppa01_candidate_authority import PPA01_CANDIDATE_AUTHORITIES
    assert len(M7_RC3_CANDIDATE_AUTHORITIES) == 11 and len(PPA01_CANDIDATE_AUTHORITIES) == 3
    # RC-7B Gate R: the HISTORICAL bytes (at BASE) are always asserted unchanged. The CURRENT bytes of the two shared M7 paths are the superseding
    # candidate blob only while a complete, authentic Gate R is active; otherwise (and for every other path) they must still be the M7 pin.
    from quarterly_candidate_recognition import current_expected_blob
    for path, blob in M7_RC3_CANDIDATE_AUTHORITIES.items():
        assert _git("rev-parse", BASE + ":" + path) == blob
        assert _git("hash-object", "--path=" + path, path) == current_expected_blob(path, blob, repo=ROOT)
    for path, blob in PPA01_CANDIDATE_AUTHORITIES.items():
        assert _git("rev-parse", BASE + ":" + path) == blob == _git("hash-object", "--path=" + path, path)


def test_m7_ppa_original_bytes_and_ancestry_at_the_immutable_research_checkpoint():
    from tests.m7_rc3_candidate_successor import M7_RC3_CANDIDATE_AUTHORITIES
    from tests.ppa01_candidate_authority import PPA01_CANDIDATE_AUTHORITIES
    checkpoint = "5be8c4b149712dd39b38b54c6fabcf3fcf47ef0d"
    _git("merge-base", "--is-ancestor", BASE, checkpoint)
    _git("merge-base", "--is-ancestor", checkpoint, "HEAD")
    for inventory in (M7_RC3_CANDIDATE_AUTHORITIES, PPA01_CANDIDATE_AUTHORITIES):
        for path, original in inventory.items():
            assert _git("rev-parse", BASE + ":" + path) == original
            assert _git("rev-parse", checkpoint + ":" + path) == original


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_monthly_funding_and_idc_survive_real_committed_run_without_quarter_recasting(env, monkeypatch, kind):
    from app.services import production_financial_authority as authority
    from app.persistence.run_history_repository import get_run_history
    from tests.test_model_rc7_capex_profile_run import _base_leaves, _save, _row, _run, _latest, OWNER

    project = env.create(kind)
    assert _run(env, project).status_code == 200
    historical = _latest(project).to_dict()
    _save(project, [_row(leaf.item_key, "FRONT_LOADED") for leaf in _base_leaves(project)])
    captured = []
    real = authority.run_clean_production

    def observe(*args, **kwargs):
        result = real(*args, **kwargs)
        captured.append(result)
        return result

    monkeypatch.setattr(authority, "run_clean_production", observe)
    assert _run(env, project).status_code == 200
    assert len(captured) == 1, "observe the real Run, never execute a second financial calculation"
    clean = captured[0]
    finance = clean.g2c_result.financing_result
    c = finance.construction_financing
    funding = finance.construction_funding
    typed = clean.project_inputs.financing.construction_financing
    assert c is not None and typed is not None
    assert len(c.period_start_dates) == clean.project_inputs.info.construction_months
    assert typed.idc_balance_basis == "OPENING_DRAWN"
    assert typed.senior_pricing.mode.value == "flat_all_in"
    denominator = {"ACT_360": D(360), "ACT_365": D(365)}[typed.senior_pricing.day_count.value.upper()]
    rate = D(str(typed.senior_pricing.flat_all_in_rate))
    maximum_idc_residual = D(0)
    with localcontext() as ctx:
        ctx.prec = 50
        opening = D(0)
        for i, (start, end, draw, idc) in enumerate(zip(c.period_start_dates, c.period_end_dates,
                                                       c.senior_draws_keur, c.senior_idc_accrual_keur)):
            assert (start, end) == (typed.periods[i].start_date, typed.periods[i].end_date)
            if i:
                assert start == c.period_end_dates[i - 1] + timedelta(days=1)
            expected = opening * rate * D((end - start).days + 1) / denominator
            residual = abs(D(str(idc)) - expected)
            maximum_idc_residual = max(maximum_idc_residual, residual)
            assert residual < D("1e-6")
            opening += D(str(draw))
            assert opening <= D(str(finance.final_senior_commitment_keur)) + D("1e-6")
        non_construction = funding.non_construction_fc_use
        outside_construction = D(str(non_construction.senior_draw_keur)) if non_construction else D(0)
        cod_funded_senior = opening + outside_construction
        assert abs(cod_funded_senior - D(str(finance.final_senior_commitment_keur))) < D("1e-6")
        first_operating_opening = finance.project_model_result.senior_debt.senior_debt_opening_keur[0]
        assert abs(D(str(first_operating_opening)) - cod_funded_senior) < D("1e-6")
        assert abs(D(str(funding.total_audit_sources_keur)) - D(str(funding.total_audit_uses_keur))) < D("1e-6")
    assert c.period_end_dates[-1] + timedelta(days=1) == clean.project_inputs.info.cod_date
    committed = _latest(project)
    persisted = committed.runtime_summary["financing_evidence"]
    rows = persisted["construction_funding"]["periods"]
    assert len(rows) == len(funding.periods) == len(c.period_start_dates)
    for i, (actual, row) in enumerate(zip(funding.periods, rows)):
        assert row["period_start"] == actual.period_start.isoformat()
        assert row["period_end"] == actual.period_end.isoformat()
        assert actual.period_start == c.period_start_dates[i]
        assert actual.period_end == c.period_end_dates[i]
        # The current construction DTO can omit a distinct settlement date.
        # Preserve that absence; never fabricate one for quarterly eligibility.
        assert row["cashflow_date"] == (actual.cashflow_date.isoformat() if actual.cashflow_date else None)
        assert row["senior_draw_keur"] == actual.senior_draw_keur
        assert abs(row["total_sources_keur"] - row["project_cash_uses_keur"]) < 1e-6
        assert abs(row["cumulative_sources_uses_difference_keur"]) < 1e-6
    su = persisted["sources_uses"]
    assert abs(su["total_sources_keur"] - su["total_uses_keur"]) < 1e-6
    assert su["capitalized_idc_keur"] == pytest.approx(sum(c.senior_idc_capitalized_uses_keur), abs=1e-6)
    assert get_run_history(OWNER, project.project_id)[1].to_dict() == historical
    print(json.dumps({"technology": kind, "monthly_periods": len(rows),
        "construction_senior_keur": str(opening), "non_construction_senior_keur": str(outside_construction),
        "cod_funded_senior_keur": str(cod_funded_senior), "idc_keur": su["capitalized_idc_keur"],
        "sources_keur": su["total_sources_keur"], "uses_keur": su["total_uses_keur"],
        "maximum_idc_residual_keur": str(maximum_idc_residual),
        "missing_separate_cashflow_dates": sum(r["cashflow_date"] is None for r in rows)}))

    # The current research contract refuses a real positive COD opening balance.
    # Funding commitment is NOT permission to fabricate a quarter-ready project.
    candidate = study(RenewableTechnology(kind.upper()))
    with pytest.raises(ValueError, match="QUARTERLY_DEBT_POLICY_UNSUPPORTED"):
        QuarterlyDebtStudy(replace(candidate.inputs, senior_debt_inputs=replace(
            candidate.inputs.senior_debt_inputs, opening_debt_balance_keur=float(cod_funded_senior))), candidate.contractual_maturity)
    with pytest.raises(ValueError, match="monthly_funding_to_quarterly_statement_bridge"):
        evaluate_quarterly_candidate(candidate).require_complete_project_run()


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_real_revenue_contracts_keep_six_month_physical_authority_and_are_refused_by_candidate(kind):
    from tests.test_rc7_revenue_ppa_v3_economics import _pi, _operating, _payload, _row, _merchant, _decompose
    pi = _pi(kind)
    op = _operating(pi)
    payload = _payload(kind, [_row(op, "ppa", "ppa", share=.3, price=60),
                              _merchant(op), _row(op, "cfd", "cfd", share=.2, price=65, reference_stream_id="market")])
    active, values = _decompose(pi, payload, kind)
    for p in op:
        streams = {s["id"]: s for s in values[p.index]["multistream_evidence"]["streams"]}
        gen = D(str(values[p.index]["generation_mwh"]))
        assert abs(D(str(streams["ppa"]["quantity_mwh"])) + D(str(streams["market"]["quantity_mwh"])) - gen) < D("1e-7")
        assert streams["cfd"]["quantity_mwh"] > 0
    from financial_engine.adapters.project_inputs import from_project_inputs
    from tools.quarterly_research.calendar import QuarterlyCandidateCalendar
    from test_rc7_quarterly_calendar import explicit_policy
    from dataclasses import fields
    from financial_engine.inputs import CalendarInput
    base = from_project_inputs(active)
    cal = QuarterlyCandidateCalendar(**{f.name: getattr(base.calendar, f.name) for f in fields(CalendarInput)}, policy=explicit_policy())
    with pytest.raises(ValueError, match="QUARTERLY_REVENUE_CONTRACT_HANDOFF_REQUIRED"):
        build_operating_candidate(base, cal, RenewableTechnology(kind.upper()))


def test_credit_period_end_is_not_sufficient_cross_frequency_interval_identity():
    axis = QuarterlyCandidateAxis.build(candidate_calendar(date(2028, 12, 31)))
    q2 = axis.rows[2]
    assert q2.end_date == date(2029, 6, 30)
    semiannual_start = date(2028, 12, 31)
    assert q2.start_date != semiannual_start
    assert (q2.end_date - q2.start_date).days == 91
    assert (q2.end_date - semiannual_start).days == 181
    with pytest.raises(ValueError, match="production_save_run_history_and_export_admission"):
        evaluate_quarterly_candidate(study()).require_complete_project_run()


def test_d02_day_fraction_policy_difference_is_explicit_not_a_tolerance_issue():
    axis = QuarterlyCandidateAxis.build(candidate_calendar(date(2027, 12, 31)))
    row = axis.rows[1]
    assert row.days_in_period == 91
    end_year_fraction = D(91) / D(366)
    split_calendar_fraction = D(1) / D(365) + D(90) / D(366)
    assert row.day_fraction == float(end_year_fraction)
    assert split_calendar_fraction > end_year_fraction
    assert abs((split_calendar_fraction - end_year_fraction) * D(20000) - D("0.149711804775806571")) < D("1e-15")
