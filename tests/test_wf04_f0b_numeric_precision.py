"""F0-B precision: one lending capacity authority; no debt extinguishment plug."""
from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from app import project_factories as factories
from app.run_integrity import build_run_integrity_evidence, run_integrity_checks
from app.services import production_financial_authority as authority


CASES = (
    ("solar", {}), ("wind", {}), ("data_center", {}), ("ev", {}),
    ("solar", {"gearing_ratio": .9, "target_dscr": 1.3}),
    ("solar", {"gearing_ratio": .9, "target_dscr": 1.4}),
    ("solar", {"gearing_ratio": .9, "target_dscr": 1.5}),
    ("wind", {"gearing_ratio": .9, "target_dscr": 1.5}),
    ("solar", {"senior_tenor_years": 10}),
)


def decimal(value):
    return Decimal.from_float(float(value))


@pytest.fixture(scope="module", params=CASES, ids=[
    "reference-solar", "reference-wind", "legacy-data-center", "legacy-ev",
    "SOLAR-23", "SOLAR-24", "SOLAR-25", "WIND-25", "SOLAR-27",
])
def canonical_run(request):
    kind, changes = request.param
    factory_kind = "ev_charging" if kind == "ev" else kind
    pi = getattr(factories, "create_generic_" + factory_kind + "_reference")()
    pi = replace(pi, financing=replace(pi.financing, **changes))
    return authority.run_clean_production(pi, "Base", project_type=factory_kind)


def test_final_debt_is_minimum_of_same_solve_capacity_and_project_uses(canonical_run):
    financing = canonical_run.g2c_result.financing_result
    senior = financing.project_model_result.senior_debt
    with localcontext() as ctx:
        ctx.prec = 50
        capacity = decimal(senior.diagnostics["dscr_debt_capacity_keur"])
        gearing = decimal(senior.diagnostics["gearing_debt_capacity_keur"])
        assert abs(decimal(senior.debt_size_keur) - min(capacity, gearing)) <= Decimal("1e-7")
    assert senior.diagnostics["is_authoritative"] is True


def test_actual_terminal_liability_survives_without_new_service(canonical_run):
    model = canonical_run.g2c_result.financing_result.project_model_result
    senior = model.senior_debt
    residual = senior.senior_debt_closing_keur[-1]
    statements = canonical_run.financial_statements_result
    post_maturity = [b for b in statements.balance_sheet_periods
                     if b.period_index > senior.period_indices[-1]]
    assert post_maturity
    assert all(b.senior_debt_balance_keur == residual for b in post_maturity)
    for period in statements.pf_cash_waterfall_periods:
        if period.period_index > senior.period_indices[-1]:
            assert period.senior_debt_service_keur == 0.0
            assert period.senior_principal_keur == 0.0
            assert period.senior_cash_interest_keur == 0.0
    # Independent high-precision recomputation, not the engine's balance_check.
    with localcontext() as ctx:
        ctx.prec = 50
        for b in statements.balance_sheet_periods:
            if b.balance_check_keur is None:
                continue
            assets = (decimal(b.gross_fixed_assets_keur) - decimal(b.accumulated_book_depreciation_keur)
                      + decimal(b.unrestricted_cash_keur) + decimal(b.dsra_balance_keur)
                      + decimal(b.distribution_account_balance_keur))
            liabilities_equity = sum(decimal(getattr(b, field)) for field in (
                "senior_debt_balance_keur", "shl_balance_keur", "share_capital_keur",
                "share_premium_keur", "additional_equity_keur", "legal_reserve_keur",
                "retained_earnings_keur", "net_cit_payable_keur"))
            assert abs(assets - liabilities_equity) <= Decimal("1e-6")
    report = run_integrity_checks(build_run_integrity_evidence(canonical_run)).to_dict()
    assert report["overall"] == "PASS", report


def test_original_16mw_lender_case_runs_through_real_workspace_projection(tmp_path, monkeypatch):
    from app.persistence import db
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
    from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex
    from app.workbook.service import WorkbookService
    from finco_core.inputs import YieldScenario

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "precision.db"))
    db.init_db()
    record = create_reference_seeded_project(user_id="synthetic-precision-owner",
        requested_name="Synthetic Solar 16", template_source="generic_solar_reference", capacity_mw=16)
    ws = get_workspace_state("synthetic-precision-owner", record.project_id)
    pi = WorkbookService.build_draft_input_set_from_workspace(ws).to_projectinputs()
    pi = replace(pi, capex=apply_user_sub_lines_replacing_base(pi.capex, project_id=record.project_id),
        opex=apply_user_sub_lines_to_opex(pi.opex, project_id=record.project_id),
        financing=replace(pi.financing, senior_tenor_years=10,
            debt_sizing_case=replace(pi.financing.debt_sizing_case, production_yield_scenario=YieldScenario.P50)))
    run = authority.run_clean_production(pi, "Base", project_type="solar")
    financing = run.g2c_result.financing_result
    senior = financing.project_model_result.senior_debt
    assert senior.debt_size_keur == min(senior.diagnostics["dscr_debt_capacity_keur"],
                                      senior.diagnostics["gearing_debt_capacity_keur"])
    assert run_integrity_checks(build_run_integrity_evidence(run)).overall.value == "PASS"


@pytest.mark.parametrize("fault", ["minimum", "gearing", None, True, -1., float("nan"), float("inf")])
def test_capacity_guard_still_rejects_inconsistent_or_missing_evidence(monkeypatch, fault):
    import financial_engine.financing.project as project
    from financial_engine.senior_debt.policy import SeniorDebtSizingMode

    original = project.run_senior_debt_model

    def corrupt(mi, *args, **kwargs):
        result = original(mi, *args, **kwargs)
        if mi.senior_debt_policy.sizing_mode is not SeniorDebtSizingMode.COMBINED_MINIMUM:
            return result
        sd = result.senior_debt
        diag = dict(sd.diagnostics)
        if fault == "minimum":
            sd = replace(sd, debt_size_keur=sd.debt_size_keur + .001)
        elif fault == "gearing":
            diag["gearing_debt_capacity_keur"] += .001
        else:
            diag["dscr_debt_capacity_keur"] = fault
        return replace(result, senior_debt=replace(sd, diagnostics=diag))

    monkeypatch.setattr(project, "run_senior_debt_model", corrupt)
    authority._POLICY_RUN_CACHE.clear()
    with pytest.raises(authority.CleanProductionRunUnavailable, match="G2A"):
        authority.run_clean_production(factories.create_generic_solar_reference())


def test_precision_retry_changes_accuracy_only_and_uses_existing_kernel(monkeypatch):
    import financial_engine.financing.project as project
    from financial_engine.senior_debt.policy import SeniorDebtSizingMode

    original = project.run_senior_debt_model
    calls = []

    def capture(mi, *args, **kwargs):
        calls.append(mi)
        return original(mi, *args, **kwargs)

    monkeypatch.setattr(project, "run_senior_debt_model", capture)
    authority._POLICY_RUN_CACHE.clear()
    pi = factories.create_generic_solar_reference()
    pi = replace(pi, financing=replace(pi.financing, senior_tenor_years=10))
    run = authority.run_clean_production(pi)
    refinements = [i for i, mi in enumerate(calls)
                   if mi.senior_debt_policy.convergence_tolerance_keur == 1e-7]
    assert refinements
    for i in refinements:
        refined = calls[i]
        previous = calls[i - 1]
        assert refined.senior_debt_policy.sizing_mode is SeniorDebtSizingMode.COMBINED_MINIMUM
        assert refined.senior_debt_policy.convergence_relative_tolerance == 0.0
        assert replace(refined, senior_debt_policy=previous.senior_debt_policy) == previous
    assert run_integrity_checks(build_run_integrity_evidence(run)).overall.value == "PASS"


def test_budget_guard_uses_period_targets_availability_and_final_bank_cfads():
    from types import SimpleNamespace as NS
    from financial_engine.financing.project import _senior_service_budget_excess
    model = NS(senior_debt=NS(period_indices=(4, 5), senior_debt_service_keur=(80., 30.)),
               debt_sizing=NS(period_indices=(4, 5), bank_cfads_keur=(100., 90.)))
    inputs = NS(senior_debt_policy=NS(target_dscr=1.2), senior_debt_inputs=NS(
        period_dscr_targets=(NS(period_index=4, target_dscr=1.25),),
        period_debt_service_availability=(NS(period_index=5, availability_fraction=.4),)))
    assert _senior_service_budget_excess(model, inputs) == 0.
    model.senior_debt.senior_debt_service_keur = (80., 30.001)
    assert _senior_service_budget_excess(model, inputs) == pytest.approx(.001, abs=1e-12)
    model.debt_sizing.period_indices = (4, 6)
    with pytest.raises(RuntimeError, match="axis mismatch"):
        _senior_service_budget_excess(model, inputs)


def test_failed_numeric_refinement_is_not_published(monkeypatch):
    import financial_engine.financing.project as project
    monkeypatch.setattr(project, "_senior_service_budget_excess", lambda *args: .001)
    authority._POLICY_RUN_CACHE.clear()
    with pytest.raises(authority.CleanProductionRunUnavailable, match="G2A_SENIOR_SERVICE_EXCEEDS_BANK_BUDGET"):
        authority.run_clean_production(factories.create_generic_solar_reference())


def test_refinement_trigger_matches_unchanged_financial_evidence_precision():
    from app.run_integrity.contracts import TOL_KEUR
    from financial_engine.financing.project import G2A_SERVICE_BUDGET_ACCEPTANCE_TOLERANCE_KEUR
    assert TOL_KEUR == G2A_SERVICE_BUDGET_ACCEPTANCE_TOLERANCE_KEUR == 1e-6


def test_already_valid_wind_precision_case_is_not_refined(monkeypatch):
    import financial_engine.financing.project as project
    original = project.run_senior_debt_model
    calls = []

    def capture(mi, *args, **kwargs):
        calls.append(mi)
        return original(mi, *args, **kwargs)

    monkeypatch.setattr(project, "run_senior_debt_model", capture)
    authority._POLICY_RUN_CACHE.clear()
    pi = factories.create_generic_wind_reference()
    pi = replace(pi, financing=replace(pi.financing, gearing_ratio=.5))
    run = authority.run_clean_production(pi)
    assert calls and all(mi.senior_debt_policy.convergence_tolerance_keur == 1e-4 for mi in calls)
    assert run.g2c_result.financing_result.final_senior_commitment_keur == 23712.497031797535
