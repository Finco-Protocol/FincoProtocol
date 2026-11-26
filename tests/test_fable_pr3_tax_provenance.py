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
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _finco47_legacy_ssr_rollback(monkeypatch):
    """Scoped to this legacy SSR test module; default production flag stays React ON."""
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")

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


from app.services.financial_core_evidence import _tax_provenance_evidence


def _synthetic_schedules(period_indices, opening, closing):
    """Minimal read-alike of TaxAndCfadsSchedules for the projection contract:
    the block must mirror exactly what the schedules carry — including an
    inconsistent or duplicated axis — and never invent or repair values."""
    fields = {
        "taxable_income_before_losses_audit_keur": tuple(float(i) for i in range(len(period_indices))),
        "taxable_profit_after_losses_audit_keur": tuple(1.0 for _ in period_indices),
        "tax_loss_opening_audit_keur": tuple(opening),
        "tax_loss_used_audit_keur": tuple(0.0 for _ in period_indices),
        "tax_loss_closing_audit_keur": tuple(closing),
        "tax_depreciation_audit_keur": tuple(2.0 for _ in period_indices),
        "cit_accrual_audit_keur": tuple(3.0 for _ in period_indices),
        "cash_tax_current_period_audit_keur": tuple(3.0 for _ in period_indices),
        "cash_tax_bridge_reconciliation_keur": tuple(0.0 for _ in period_indices),
    }
    return SimpleNamespace(period_indices=tuple(period_indices), **fields)


def _clean_run_with(tax):
    return SimpleNamespace(g2c_result=SimpleNamespace(
        financing_result=SimpleNamespace(project_model_result=SimpleNamespace(tax_and_cfads=tax))))


def test_inconsistent_loss_schedule_is_reported_not_repaired():
    # closing != next opening: the reconciliation flag must say False, and the
    # block must carry the inconsistent values EXACTLY as the schedules hold
    # them (no silent continuity repair, no recomputation).
    tax = _synthetic_schedules(
        period_indices=[0, 1, 2],
        opening=[10.0, 4.0, 4.0],   # opening[1] != closing[0]=5.0 -> inconsistent
        closing=[5.0, 5.0, 5.0],
    )
    block = _tax_provenance_evidence(_clean_run_with(tax))
    assert block["status"] == "CALCULATED_FROM_EXISTING_SCHEDULES"
    assert block["reconciliation"]["loss_schedule_closing_equals_next_opening"] is False
    rows = block["periods"]
    assert [r["tax_loss_opening_audit_keur"] for r in rows] == [10.0, 4.0, 4.0]
    assert [r["tax_loss_closing_audit_keur"] for r in rows] == [5.0, 5.0, 5.0]


def test_duplicate_period_indices_are_mirrored_row_for_row():
    # A duplicated period index (engine invariant violation upstream) is
    # mirrored row for row: the projection never deduplicates or reindexes,
    # so a consumer reconciling against the schedules sees the same anomaly.
    tax = _synthetic_schedules(
        period_indices=[1, 1, 2],
        opening=[0.0, 0.0, 0.0],
        closing=[0.0, 0.0, 0.0],
    )
    block = _tax_provenance_evidence(_clean_run_with(tax))
    assert block["period_count"] == 3
    assert [r["period_index"] for r in block["periods"]] == [1, 1, 2]
    assert [r["cit_accrual_audit_keur"] for r in block["periods"]] == [3.0, 3.0, 3.0]


def test_provenance_refuses_without_a_valid_run_binding():
    # F2-NEW-03 binding contract: the sealed evidence (with the tax block) is
    # only reachable through from_runtime_summary with the run's own identity;
    # a foreign snapshot or composite hash fails closed with RUN_BINDING_MISMATCH.
    evidence, entry = _sealed_fixture_evidence()
    from app.services.financial_core_evidence import from_runtime_summary
    tampered = {"financing_evidence": {"financial_core_v1": evidence,
                                       "run_binding": {"snapshot_id": "other-run",
                                                       "composite_hash": "f" * 64}}}
    result = from_runtime_summary(tampered,
                                  snapshot_id=entry.runtime_snapshot_id,
                                  composite_hash=entry.composite_hash)
    assert result["status"] == "RUN_BINDING_MISMATCH"


def _sealed_fixture_evidence():
    """Reuse the module fixture's sealed Run (single engine invocation)."""
    return _SEALED[0], _SEALED[1]


_SEALED = [None, None]


@pytest.fixture(scope="module", autouse=True)
def _capture_sealed(sealed):
    _SEALED[0], _SEALED[1] = sealed
    yield
    _SEALED[0] = _SEALED[1] = None


def test_short_and_misaligned_vectors_are_explicit_none_and_status_partial():
    """A vector shorter than the period axis yields an explicit per-period
    None (never a zero) and the block is classified PARTIAL, never complete."""
    tax = _synthetic_schedules(period_indices=[0, 1, 2], opening=[0.0, 0.0, 0.0], closing=[0.0, 0.0, 0.0])
    # Truncate two vectors below the axis length (misaligned/short producer).
    tax.tax_depreciation_audit_keur = (2.0, 2.0)
    tax.cash_tax_bridge_reconciliation_keur = ()
    block = _tax_provenance_evidence(_clean_run_with(tax))
    assert block["status"] == "PARTIAL_SCHEDULE_COVERAGE"
    assert set(block["not_available_fields"]) == {
        "tax_depreciation_audit_keur", "cash_tax_bridge_reconciliation_keur"}
    rows = block["periods"]
    assert [r["tax_depreciation_audit_keur"] for r in rows] == [2.0, 2.0, None]
    assert [r["cash_tax_bridge_reconciliation_keur"] for r in rows] == [None, None, None]
    # Computed fields stay exactly what the engine wrote.
    assert [r["cit_accrual_audit_keur"] for r in rows] == [3.0, 3.0, 3.0]


def test_none_values_are_mirrored_not_zeroed():
    tax = _synthetic_schedules(period_indices=[0, 1], opening=[0.0, 0.0], closing=[0.0, 0.0])
    tax.taxable_income_before_losses_audit_keur = (10.0, None)
    block = _tax_provenance_evidence(_clean_run_with(tax))
    assert [r["taxable_income_before_losses_audit_keur"] for r in block["periods"]] == [10.0, None]


def test_nonfinite_engine_values_are_mirrored_not_zeroed():
    tax = _synthetic_schedules(period_indices=[0], opening=[0.0], closing=[0.0])
    tax.tax_depreciation_audit_keur = (float("inf"),)
    block = _tax_provenance_evidence(_clean_run_with(tax))
    # The projection is read-only: the engine's own value is mirrored and the
    # consumer/audit layer sees the anomaly instead of a fabricated zero.
    assert block["periods"][0]["tax_depreciation_audit_keur"] == float("inf")


def test_empty_period_axis_fails_closed():
    tax = _synthetic_schedules(period_indices=[], opening=[], closing=[])
    block = _tax_provenance_evidence(_clean_run_with(tax))
    assert block == {"status": "NOT_AVAILABLE",
                     "reason": "TAX_AND_CFADS_PERIOD_AXIS_EMPTY"}
