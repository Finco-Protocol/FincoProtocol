from app.api.project_runner import run_project
from app.project_factories import create_generic_solar_reference, create_generic_wind_reference


def test_solar_reference_runs_clean_engine():
    result = run_project("Solar", "Base", project_inputs_override=create_generic_solar_reference())
    assert result["messages"] == []
    assert result["kpis"]["project_irr"] is not None
    assert result["kpis"]["min_dscr"] > 0


def test_wind_reference_runs_clean_engine():
    result = run_project("Wind", "Base", project_inputs_override=create_generic_wind_reference())
    assert result["messages"] == []
    assert result["kpis"]["project_irr"] is not None
    assert result["kpis"]["min_dscr"] > 0
