"""No seed/default can turn a missing field into a ready canonical model."""
import pytest
from app.services.blank_readiness_service import catalogue, readiness, VERTICALS


@pytest.mark.parametrize("technology", VERTICALS)
def test_missing_economics_never_ready_and_real_registry_fields_have_units(technology, monkeypatch):
    import app.project_factories as factories
    def forbidden(*args, **kwargs):
        raise AssertionError("Economic seed factory called by readiness")
    for name in ("create_generic_solar_reference", "create_generic_wind_reference",
                 "create_generic_data_center_reference", "create_generic_ev_charging_reference"):
        monkeypatch.setattr(factories,name,forbidden)
    empty=readiness(technology,{})
    assert not empty["can_promote"] and empty["state"]=="SETUP_DRAFT"
    assert empty["unresolved"] and empty["conditional_closure"]=="UNPROVEN"
    fields=catalogue(technology)
    assert fields and all("field_id" in f and "unit" in f for f in fields)
    assert all(f["field_id"]!="project_setup.identity.project_type" for f in fields)


def test_storage_is_release_closed():
    with pytest.raises(ValueError,match="NOT_RELEASED"):
        catalogue("storage")


def test_explicit_zero_is_preserved_as_input_and_invalid_is_reported():
    fields=catalogue("wind")
    field=next(f for f in fields if f["field_id"]=="project_setup.technical.capacity_mw")
    bad=readiness("wind",{field["field_id"]:"0"})
    assert any(e["field_id"]==field["field_id"] for e in bad["invalid"])
    assert not any(e["field_id"]==field["field_id"] for e in bad["missing"])
