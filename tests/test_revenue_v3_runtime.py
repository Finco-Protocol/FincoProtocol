"""Candidate products flow through the existing production financial authorities."""
import copy
import json
from dataclasses import replace

import pytest

from tests.test_revenue_v3_products import candidate
from tests.revenue_v3_cases import book
from app.workbook.revenue_multistream import apply_config


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("multi_senior", [False, True])
def test_canonical_products_financing_tax_statements_and_returns(candidate, kind, multi_senior, record_property):
    from app import project_factories
    from tests.test_financing_f3_multisenior import case
    from app.services.production_financial_authority import run_clean_production
    from app.run_integrity import build_run_integrity_evidence, run_integrity_checks
    pi = case(kind)[0] if multi_senior else getattr(project_factories, "create_generic_" + kind + "_reference")()
    pi = replace(pi, revenue=replace(pi.revenue, co2_enabled=False))
    payload, _ = book(pi, kind)
    old = copy.deepcopy(payload)
    old.update(version=2)
    del old["products"], old["environmental_rights"]
    def execute(raw):
        return run_clean_production(apply_config(pi, json.dumps(raw), project_type=kind), "Base", project_type=kind)
    before, after = execute(old), execute(payload)
    fin = after.g2c_result.financing_result
    previous = before.g2c_result.financing_result.project_model_result
    result = fin.project_model_result
    integrity = run_integrity_checks(build_run_integrity_evidence(after)).to_dict()
    assert integrity["overall"] == "PASS", integrity
    assert sum(result.operating_schedules.revenue_keur) > sum(previous.operating_schedules.revenue_keur)
    assert sum(result.operating_schedules.ebitda_keur) > sum(previous.operating_schedules.ebitda_keur)
    assert result.tax_and_cfads.cfads_keur != previous.tax_and_cfads.cfads_keur
    assert result.tax_and_cfads.corporate_tax_cash_keur != previous.tax_and_cfads.corporate_tax_cash_keur
    assert after.g2c_result.total_sponsor_xirr != before.g2c_result.total_sponsor_xirr
    assert after.g2c_result.return_summary.project.project_xirr != before.g2c_result.return_summary.project.project_xirr
    if multi_senior:
        assert len(fin.facility_schedules) == 2
        assert fin.facility_schedules == before.g2c_result.financing_result.facility_schedules
        assert result.senior_debt.base_dscr != previous.senior_debt.base_dscr
    else:
        assert result.senior_debt.debt_size_keur != previous.senior_debt.debt_size_keur
    for row in after.financial_statements_result.income_statement_periods:
        if not row.is_construction:
            assert row.ebitda_keur == pytest.approx(row.revenue_keur - row.opex_keur, abs=1e-9)
    evidence = next(e for e in result.provenance.derivation_evidence if e.output_path == "operating_schedules.revenue_keur")
    assert evidence.notes and any("products" in str(note) for note in evidence.notes)
    record_property("before_revenue_keur", sum(previous.operating_schedules.revenue_keur))
    record_property("after_revenue_keur", sum(result.operating_schedules.revenue_keur))
    record_property("before_senior_keur", previous.senior_debt.debt_size_keur)
    record_property("after_senior_keur", result.senior_debt.debt_size_keur)
    record_property("before_sponsor_xirr", before.g2c_result.total_sponsor_xirr)
    record_property("after_sponsor_xirr", after.g2c_result.total_sponsor_xirr)
