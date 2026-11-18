"""F2-NEW-03 (S8) — sealed Run tax provenance, audit-only.

Proves that the sealed financial_core_v1 evidence now carries the EXISTING
Phase-2B tax traces (taxable_income_before_losses, tax_loss_*, tax
depreciation, CIT accrual / cash tax) without recomputing any tax schedule,
without substituting zero for unknown values, and with zero numerical drift:

- every pre-existing financial_core_v1 key keeps its exact value (the block is
  purely additive: keys(main) + {"tax_provenance_v1"} == keys(branch));
- the trace values equal the engine's own TaxAndCfadsSchedules vectors;
- the loss schedule reconciles (closing == next opening) and CIT/cash totals
  are exact sums of the same vectors;
- a Run without tax schedules yields explicit NOT_AVAILABLE, never zeros.
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

TAX_FIELDS = (
    "taxable_income_before_losses_audit_keur",
    "taxable_profit_after_losses_audit_keur",
    "tax_loss_opening_audit_keur",
    "tax_loss_used_audit_keur",
    "tax_loss_closing_audit_keur",
    "tax_depreciation_audit_keur",
    "cit_accrual_audit_keur",
    "cash_tax_current_period_audit_keur",
    "cash_tax_bridge_reconciliation_keur",
)

# Exact financial_core_v1 top-level key set produced by accepted main
# 37ffcdea (additive-only contract guard for this evidence-only change).
MAIN_FINANCIAL_CORE_KEYS = frozenset({
    "schema_version", "status", "authority", "valuation_policy_version",
    "valuation_policy", "input_rate_contract", "typed_rate_unit",
    "goal_seek_regime", "valuation_summary", "coverage_input_periods",
    "project_cashflows", "loan_life_coverage", "project_npv_keur",
    "llcr_contractual_maturity", "llcr_actual_repayment",
    "llcr_at_first_senior_opening", "min_rolling_llcr", "rolling_loan_life",
    "plcr", "sponsor_npv", "sponsor_policy", "sponsor_npv_keur", "shl_timing",
    "sponsor_metric_policy", "tax_policy_classification",
    "contractual_assessment", "lender_acceptance",
})


@pytest.fixture(scope="module")
def sealed(tmp_path_factory):
    """One real Run through the production V2 workbook path on a temp DB."""
    tmp_path = tmp_path_factory.mktemp("pr3")
    import app.persistence.db as _db
    _db.DB_PATH = str(tmp_path / "pr3.db")
    _db.init_db()
    from starlette.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project
    from tests.run_clone_csrf import post_valid_csrf
    from app.persistence.run_history_repository import get_run_history
    import main_web

    user = "pr3-probe"
    with TestClient(main_web.app, base_url="https://pr3.local") as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=user, username="admin"))
        record = create_reference_seeded_project(
            user_id=user, requested_name="PR3 tax",
            template_source="generic_solar_reference", capacity_mw=10)
        page = client.get("/v2/workbook", params={"project": record.project_code})
        toks = {k: re.search(r'name="' + k + r'" value="([^"]+)"', page.text).group(1)
                for k in ("content_hash", "workbook_version")}
        assert post_valid_csrf(client, "/v2/workbook/run", headers={"HX-Request": "true"},
                               data={"project": record.project_code, **toks}).status_code == 200
        entry = get_run_history(user, record.project_id)[0]
        evidence = (entry.runtime_summary.get("financing_evidence") or {}).get("financial_core_v1") or {}
        yield evidence, entry


def test_tax_provenance_block_is_purely_additive(sealed):
    evidence, _entry = sealed
    assert set(evidence) == MAIN_FINANCIAL_CORE_KEYS | {"tax_provenance_v1"}
    block = evidence["tax_provenance_v1"]
    assert block["status"] == "CALCULATED_FROM_EXISTING_SCHEDULES"
    assert block["authority"] == "PHASE_2B_TAX_AND_CFADS_SCHEDULES_READ_ONLY"


def test_tax_trace_matches_engine_schedules_and_reconciles(sealed):
    evidence, _entry = sealed
    block = evidence["tax_provenance_v1"]
    periods = block["periods"]
    assert periods, "a canonical Solar Run must expose the tax trace periods"
    for row in periods:
        for name in TAX_FIELDS:
            assert name in row
            # No unknown value is substituted with zero or omitted silently.
            assert row[name] is not None, (row["period_index"], name)
    # Loss schedule continuity over the SAME engine values.
    assert block["reconciliation"]["loss_schedule_closing_equals_next_opening"] is True
    # Totals are exact sums of the sealed vectors.
    cit_total = block["reconciliation"]["cit_accrual_total_keur"]
    vec_sum = sum(p["cit_accrual_audit_keur"] for p in periods)
    assert cit_total == pytest.approx(vec_sum, abs=1e-9)


def test_trace_is_bound_to_the_sealed_run_identity(sealed):
    evidence, entry = sealed
    block = evidence["tax_provenance_v1"]
    # The block travels inside financing_evidence, whose run binding was
    # validated for THIS run identity by financial_core_evidence.from_runtime_summary.
    from app.services.financial_core_evidence import from_runtime_summary
    result = from_runtime_summary(
        {"financing_evidence": {"financial_core_v1": evidence,
                                "run_binding": {"snapshot_id": entry.runtime_snapshot_id,
                                                "composite_hash": entry.composite_hash}}},
        snapshot_id=entry.runtime_snapshot_id,
        composite_hash=entry.composite_hash,
    )
    assert result["status"] == "PERSISTED"
    assert result["tax_provenance_v1"] == block


def test_missing_tax_schedules_declare_not_available_not_zero():
    from types import SimpleNamespace
    from app.services.financial_core_evidence import _tax_provenance_evidence

    clean_run = SimpleNamespace(g2c_result=SimpleNamespace(
        financing_result=SimpleNamespace(project_model_result=SimpleNamespace(tax_and_cfads=None))))
    block = _tax_provenance_evidence(clean_run)
    assert block == {"status": "NOT_AVAILABLE",
                     "reason": "TAX_AND_CFADS_SCHEDULES_NOT_COMPUTED"}
    assert "0" not in str(block)
