"""Correction C regression ring for PUBLIC_GENERIC_DETAIL_V1."""
from __future__ import annotations

import pytest

from app.reference_detail_catalog import (
    PUBLIC_GENERIC_DETAIL_V1,
    OPEX_PARENT_NAMES,
    allocate_parent_amount,
    capex_children,
    opex_children,
)
from app.project_factories import create_generic_solar_reference, create_generic_wind_reference
from app.ui.project_context import _build_capex_detail_items, _build_opex_detail_items


@pytest.mark.parametrize("technology", ["solar", "wind"])
def test_public_catalog_has_real_multi_line_capex_taxonomy_and_exact_allocation(technology):
    children = capex_children(technology, "C.01")
    assert len(children) > 1
    assert len({child.code for child in children}) == len(children)
    assert all(child.code.startswith("C.01.") and child.label for child in children)
    assert sum(child.weight for child in children) == 1
    allocation = allocate_parent_amount(1234.56789123, children)
    assert sum(amount for _, amount in allocation) == pytest.approx(1234.56789123, abs=1e-9)
    # Wind intentionally retains a meaningful visible zero-value TSA optional.
    if technology == "wind":
        assert any(child.label == "Turbine Supply Agreement Optionals" and amount == 0 for child, amount in allocation)


@pytest.mark.parametrize("parent", ["B.01", "B.02", "B.06", "B.07"])
def test_public_catalog_has_real_multi_line_opex_taxonomy_and_exact_allocation(parent):
    children = opex_children(parent)
    assert len(children) > 1
    assert len({child.code for child in children}) == len(children)
    assert all(child.code.startswith(f"{parent}.") and child.label for child in children)
    assert sum(child.weight for child in children) == 1
    assert sum(amount for _, amount in allocate_parent_amount(777.12345678, children)) == pytest.approx(777.12345678, abs=1e-9)


@pytest.mark.parametrize(
    ("factory", "technology", "code"),
    [
        (create_generic_solar_reference, "solar", "GENERIC_SOLAR_REFERENCE"),
        (create_generic_wind_reference, "wind", "Generic Wind Reference"),
    ],
)
def test_reference_detail_is_exact_decomposition_not_new_economic_authority(factory, technology, code):
    project = factory()
    capex = _build_capex_detail_items(project.capex, project.info.construction_months, technology)
    hard_children = sum(
        sum(child["amount_keur"] for child in category["children"])
        for category in capex["categories"]
        if category["code"] not in {"C.17", "C.18"}
    )
    assert hard_children == pytest.approx(project.capex.total_capex, abs=1e-8)
    assert all(
        child["detail_catalog_authority"] == PUBLIC_GENERIC_DETAIL_V1
        for category in capex["categories"][:16]
        for child in category["children"]
    )

    opex = _build_opex_detail_items(project, code, project.info.horizon_years)
    assert {category["code"] for category in opex["categories"]} == set(OPEX_PARENT_NAMES)
    assert sum(category["yearly_totals"][0] for category in opex["categories"]) == pytest.approx(
        sum(item.y1_amount_keur for item in project.opex), abs=1e-8
    )
    assert len(next(c for c in opex["categories"] if c["code"] == "B.01")["children"]) > 1
    assert len(next(c for c in opex["categories"] if c["code"] == "B.02")["children"]) > 1


@pytest.fixture
def seeded_detail_db(tmp_path, monkeypatch):
    from app.persistence import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "public-detail.db"))
    db.init_db()


@pytest.mark.parametrize("template_source", ["generic_solar_reference", "generic_wind_reference"])
def test_seeded_public_detail_rows_reconcile_and_keep_immutable_provenance(seeded_detail_db, template_source):
    from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
    from app.persistence.opex_sub_lines import get_active_sub_lines_for_project as get_opex
    from app.services.reference_seed_service import create_reference_seeded_project

    record = create_reference_seeded_project(
        user_id=f"catalog-{template_source}", template_source=template_source,
        requested_name="Public Detail", capacity_mw=64.0 if "solar" in template_source else 48.0,
    )
    capex = get_active_sub_lines_for_project(record.project_id)
    opex = get_opex(record.project_id)
    assert len([line for line in capex if line.parent_category_code == "C.01"]) > 1
    assert len([line for line in opex if line.parent_group_code == "B.01"]) > 1
    assert len({line.business_code for line in capex}) == len(capex)
    assert len({line.business_code for line in opex}) == len(opex)
    for line in [*capex, *opex]:
        metadata = line.replay_metadata
        assert metadata["detail_catalog_authority"] == PUBLIC_GENERIC_DETAIL_V1
        assert metadata["detail_code"] == line.business_code
        assert metadata["reference_seed"] is True
        assert metadata["scaling_mode"] == "PER_MW"
