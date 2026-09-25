from app.project_factories import (
    create_generic_solar_reference,
    create_generic_wind_reference,
    create_generic_storage_reference,
    create_generic_data_center_reference,
    create_generic_ev_charging_reference,
)


def test_reference_models_are_synthetic_and_generic():
    refs = [
        create_generic_solar_reference(),
        create_generic_wind_reference(),
        create_generic_storage_reference(),
        create_generic_data_center_reference(),
        create_generic_ev_charging_reference(),
    ]
    assert [p.info.name for p in refs] == [
        "Generic Solar Reference",
        "Generic Wind Reference",
        "Generic Storage Reference",
        "Generic Data Center Reference",
        "Generic EV Charging Hub Reference",
    ]
    assert [p.info.country_iso for p in refs] == ["XA", "XB", "XC", "XD", "XE"]
    assert all(p.info.company.startswith("Synthetic Sponsor") for p in refs)
    assert len({p.info.code for p in refs}) == 5


def test_library_bootstrap_exposes_three_canonical_references(tmp_path, monkeypatch):
    db_path = tmp_path / "finco-public.db"
    monkeypatch.setenv("FINCO_DB_PATH", str(db_path))

    # Reload the lightweight DB module so the environment-specific path is applied.
    import importlib
    import app.persistence.db as db_module
    import app.persistence.projects_repository as projects_repository
    import app.services.project_library_service as project_library_service

    importlib.reload(db_module)
    importlib.reload(projects_repository)
    importlib.reload(project_library_service)

    project_library_service.ensure_reference_models()
    refs = projects_repository.get_reference_projects()

    assert len(refs) == 5
    assert {r.template_source for r in refs} == {
        "generic_solar_reference",
        "generic_wind_reference",
        "generic_storage_reference",
        "generic_data_center_reference",
        "generic_ev_charging_reference",
    }
    assert all(r.project_role == "reference" and r.is_protected for r in refs)


def test_all_three_reference_models_are_protected_in_ui_contract(tmp_path, monkeypatch):
    db_path = tmp_path / "finco-reference-protection.db"
    monkeypatch.setenv("FINCO_DB_PATH", str(db_path))

    import importlib
    import app.persistence.db as db_module
    import app.persistence.projects_repository as projects_repository
    import app.services.project_library_service as project_library_service

    importlib.reload(db_module)
    importlib.reload(projects_repository)
    importlib.reload(project_library_service)

    project_library_service.ensure_reference_models()
    refs = projects_repository.get_reference_projects()
    assert {r.template_source for r in refs} == {
        "generic_solar_reference",
        "generic_wind_reference",
        "generic_storage_reference",
        "generic_data_center_reference",
        "generic_ev_charging_reference",
    }
    assert all(project_library_service.is_protected_reference(r) for r in refs)
