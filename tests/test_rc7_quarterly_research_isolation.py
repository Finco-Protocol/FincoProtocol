"""Research isolation and actual baseline production-admission proofs."""
import ast
from dataclasses import replace
import importlib
from pathlib import Path
import subprocess

import pytest

from tools.quarterly_research import RESEARCH_ONLY, RELEASE_CLOSED, NOT_A_PROJECT_RUN, ACTIVATION_ENABLED
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


# RC-7B Correction B (historical checkpoint, source-proven): this guard states PR #313's isolation claim - the research candidate changed
# no production path. That claim is judged at the #313 merge commit against the #313 base, both immutable. Comparing the moving HEAD to the
# #313 base made the claim fail for every later, separately governed change; CURRENT production authority is enforced by the live
# frozen-namespace and financial-integrity guards, none of which this change relaxes.
RESEARCH_BASE = "78e4c0edcc1bdb5013df79f11b3ba7b9c2151013"
RESEARCH_MERGE = "5be8c4b149712dd39b38b54c6fabcf3fcf47ef0d"
PROTECTED_PATHS = ["financial_engine", "finco_core", "domain", "tests/model_v2_governance.py",
                   "tests/finance_integrity_governance.py", "tests/m7_rc3_candidate_successor.py",
                   "tests/ppa01_candidate_authority.py"]


def test_protected_production_tree_and_historical_guards_are_exact_main():
    subprocess.check_call(["git", "merge-base", "--is-ancestor", RESEARCH_BASE, RESEARCH_MERGE], cwd=ROOT)
    subprocess.check_call(["git", "merge-base", "--is-ancestor", RESEARCH_MERGE, "HEAD"], cwd=ROOT)
    changed = subprocess.check_output(["git", "diff", RESEARCH_BASE, RESEARCH_MERGE,
                                       "--name-only", "--", *PROTECTED_PATHS], cwd=ROOT, text=True)
    assert changed.strip() == ""
    for research_only in ("financial_engine/quarterly/calendar.py", "financial_engine/quarterly/runtime.py"):
        absent = subprocess.run(["git", "cat-file", "-e", f"{RESEARCH_MERGE}:{research_only}"], cwd=ROOT, capture_output=True)
        assert absent.returncode != 0, research_only
    assert not (ROOT / "financial_engine/quarterly/calendar.py").exists()
    assert not (ROOT / "financial_engine/quarterly/runtime.py").exists()



def test_no_production_source_imports_or_dynamically_names_research_package():
    for directory in ("app", "financial_engine", "finco_core", "domain"):
        for path in (ROOT / directory).rglob("*.py"):
            source = path.read_text(encoding="utf-8-sig")
            assert "quarterly_research" not in source, path
    assert "quarterly_research" not in (ROOT / "main_web.py").read_text(encoding="utf-8-sig")
    assert RESEARCH_ONLY and RELEASE_CLOSED and NOT_A_PROJECT_RUN and ACTIVATION_ENABLED is False


def test_research_uses_original_primitives_without_patching_production_globals():
    from financial_engine import orchestrator as core
    from financial_engine.senior_debt import solver
    from tools.quarterly_research import calculation
    from tools.quarterly_research.runtime import evaluate_quarterly_candidate
    from test_rc7_quarterly_financial_candidate import study
    before = {name: value for name, value in vars(core).items() if callable(value)}
    assert calculation.solve_senior_debt is solver.solve_senior_debt
    evaluate_quarterly_candidate(study())
    assert all(getattr(core, name) is value for name, value in before.items())
    assert core.run_operating_model.__module__ == "financial_engine.orchestrator"
    assert core._build_period_engine.__module__ == "financial_engine.orchestrator"
    tree = ast.parse((ROOT / "tools/quarterly_research/calculation.py").read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert not any(isinstance(n.func, ast.Name) and n.func.id in {"exec", "eval", "setattr"} for n in calls)


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
@pytest.mark.parametrize("variant", ["default", "no_auto_construction", "explicit_construction"])
def test_real_production_entry_rejects_typed_quarters_after_baseline_adapter_restore(kind, variant):
    from app import project_factories as f
    from app.services.production_financial_authority import run_clean_production, CleanProductionRunUnavailable
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.financing.generic_product_policy import GenericFinancingPolicy, derive_construction_financing
    from finco_core.inputs import PeriodFrequency
    pi = getattr(f, "create_generic_" + kind + "_reference")()
    if variant == "explicit_construction":
        pi = replace(pi, financing=replace(pi.financing, construction_financing=derive_construction_financing(pi)))
    pi = replace(pi, info=replace(pi.info, period_frequency=PeriodFrequency.QUARTERLY))
    # Honest baseline limitation: this adapter does NOT reject or carry frequency.
    clean = from_project_inputs(pi)
    assert not hasattr(clean.calendar, "period_frequency")
    policy = GenericFinancingPolicy(apply_construction_financing=False, apply_cash_dsra=False) if variant == "no_auto_construction" else None
    with pytest.raises(CleanProductionRunUnavailable) as rejected:
        run_clean_production(pi, financing_policy=policy)
    message = str(rejected.value)
    assert ("H1_UNSUPPORTED_PERIOD_FREQUENCY" in message if variant == "default"
            else "build_tax_contract_from_project_inputs: unsupported period_frequency" in message)


@pytest.mark.parametrize("field", ["period_frequency", "project.period_frequency", "project_setup.period_frequency"])
def test_existing_workbook_field_admission_rejects_unregistered_frequency(field):
    from app.workbook.update_service import WorkbookUpdateService, UnknownFieldError
    with pytest.raises(UnknownFieldError):
        WorkbookUpdateService.validate_field_update(field, "Quarterly")


def test_api_schema_does_not_expose_frequency_and_ignores_extra_keys_honestly():
    from app.input_schema import ProjectInputsSchema
    from app.input_adapter import build_projectinputs
    from finco_core.inputs import PeriodFrequency
    assert "period_frequency" not in ProjectInputsSchema.model_fields
    schema = ProjectInputsSchema.model_validate({"project_type": "Solar", "period_frequency": "Quarterly"})
    assert "period_frequency" not in schema.model_dump()
    assert build_projectinputs(schema).info.period_frequency is PeriodFrequency.SEMESTRIAL
    # Extra-key ignoring is existing compatibility, not a new fail-closed guard.


def test_research_ordinary_tax_still_reuses_existing_calendar_fifo_engine():
    from tools.quarterly_research import calculation
    tax = importlib.import_module("financial_engine.tax.engine")
    assert calculation.calculate_tax is tax.calculate_tax
    assert calculation.calculate_cfads_and_cash_tax is tax.calculate_cfads_and_cash_tax


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_isolated_research_cannot_change_any_complete_legacy_financial_result(kind):
    from dataclasses import asdict
    from app import project_factories as f
    from app.services import production_financial_authority as authority
    from finco_core.inputs import hash_inputs_for_cache
    from tools.quarterly_research.runtime import evaluate_quarterly_candidate
    from test_rc7_quarterly_financial_candidate import study
    pi = getattr(f, "create_generic_" + kind + "_reference")()
    identity = hash_inputs_for_cache(pi)
    authority._POLICY_RUN_CACHE.clear()
    before = asdict(authority.run_clean_production(pi))
    evaluate_quarterly_candidate(study())
    assert hash_inputs_for_cache(pi) == identity
    authority._POLICY_RUN_CACHE.clear()
    after = asdict(authority.run_clean_production(pi))
    assert after == before


def test_actual_workbook_run_refusal_preserves_last_run_and_history(env, monkeypatch, caplog):
    from app import project_factories as factories
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.workspace_repository import get_workspace_state
    from finco_core.inputs import PeriodFrequency
    from tests.test_model_rc7_capex_profile_run import _run, OWNER
    project = env.create("solar")
    assert _run(env, project).status_code == 200
    before = [r.to_dict() for r in get_run_history(OWNER, project.project_id)]
    ws = get_workspace_state(OWNER, project.project_id)
    runtime = (ws.last_runtime_snapshot, ws.last_runtime_summary, ws.last_runtime_composite_hash)
    page = env.client.get("/v2/workbook", params={"project": project.project_code})
    normal = factories.create_generic_solar_reference

    def unsupported(*args, **kwargs):
        base = normal(*args, **kwargs)
        return replace(base, info=replace(base.info, period_frequency=PeriodFrequency.QUARTERLY))

    # Inject invalid typed input upstream, not a substituted engine/result.
    monkeypatch.setattr(factories, "create_generic_solar_reference", unsupported)
    response = env.client.post("/v2/workbook/run", headers={"HX-Request": "true"},
        data={"project": project.project_code, **tokens(page.text)})
    assert response.status_code == 200 and "v2-banner-error" in response.text
    assert "H1_UNSUPPORTED_PERIOD_FREQUENCY" in caplog.text
    assert [r.to_dict() for r in get_run_history(OWNER, project.project_id)] == before
    after = get_workspace_state(OWNER, project.project_id)
    assert (after.last_runtime_snapshot, after.last_runtime_summary, after.last_runtime_composite_hash) == runtime
