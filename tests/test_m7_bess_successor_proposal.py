"""Review-only successor proof; no release guard imports this proposal."""
from copy import deepcopy

import pytest


def test_ev_book_tax_and_other_non_bess_depreciation_are_bit_exact_to_rc2():
    from tests.test_m7_bess_boundaries import historical_module
    from app import project_factories as F
    from financial_engine.adapters.project_inputs import from_project_inputs
    from finco_core.debt.depreciation_schedule import build_depreciation_schedule
    old = historical_module("financial_engine/adapters/project_inputs.py", "financial_engine.adapters.m7_depreciation_before")
    for factory in (F.create_generic_solar_reference, F.create_generic_wind_reference,
                    F.create_generic_data_center_reference, F.create_generic_ev_charging_reference):
        pi = factory()
        assert old.from_project_inputs(pi).depreciation == from_project_inputs(pi).depreciation
    pi = F.create_generic_ev_charging_reference()
    dep = from_project_inputs(pi).depreciation
    for entries in (dep.book_capex_items_for_depreciation, dep.tax_capex_items_for_depreciation):
        assert next(e for e in entries if e.name == "Charging Equipment").useful_life_override == 10
    schedule = build_depreciation_schedule((pi.capex.production_units,), horizon_years=pi.info.horizon_years)
    assert all(schedule[y] == 400 for y in range(1, 11))
    assert sum(schedule.get(y, 0) for y in range(11, pi.info.horizon_years + 1)) == 0


def test_legacy_storage_adaptation_is_compatible_but_execution_stays_rejected():
    """Correction B: the adapter keeps the historical Storage metadata/depreciation behaviour; the unsupported legacy
    spread economics are rejected at the execution boundary (no financial authority added, no silent calculation)."""
    from tests.test_m7_bess_boundaries import historical_module
    from app.project_factories import create_generic_storage_reference
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.bess import LegacyBessTechnicalInput
    from financial_engine.orchestrator import run_operating_model
    old = historical_module("financial_engine/adapters/project_inputs.py", "financial_engine.adapters.m7_storage_before")
    source = create_generic_storage_reference()
    historical = old.from_project_inputs(source)
    current = from_project_inputs(source)
    assert next(e for e in current.depreciation.book_capex_items_for_depreciation
                if e.name == "BESS Cells").useful_life_override is None
    assert current.depreciation == historical.depreciation                       # identical metadata / depreciation
    assert isinstance(current.technical, LegacyBessTechnicalInput) and current.technical.bess_legacy_unsupported
    with pytest.raises(ValueError, match="BESS_NATIVE_CONTRACT_REQUIRED"):
        run_operating_model(current)                                              # execution is still rejected


def test_non_bess_adaptation_is_unchanged_and_native_contract_is_still_required_for_native_execution():
    from app.project_factories import create_generic_solar_reference, create_generic_wind_reference
    from financial_engine.adapters.project_inputs import from_project_inputs
    for factory in (create_generic_solar_reference, create_generic_wind_reference):
        technical = from_project_inputs(factory()).technical
        assert type(technical).__name__ == "TechnicalInput" and not getattr(technical, "bess_legacy_unsupported", False)


def test_correction_b_financial_activation_and_freeze_gates_are_not_wired_to_the_proposal():
    """The proposal never relaxes a frozen-namespace guard: those historical zero-diff controls stay failing/closed."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent
    for name in ("model_v2_governance.py", "finance_integrity_governance.py", "test_finance_integrity_governance.py",
                 "test_wf07_revenue_governance.py", "test_ci_acceptance.py"):
        assert "m7_bess_successor_proposal" not in (root / name).read_text(encoding="utf-8"), name
    from app.workbook.bess_config import ACTIVATION_ENABLED
    assert ACTIVATION_ENABLED is False
