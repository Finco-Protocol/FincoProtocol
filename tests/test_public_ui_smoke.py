"""Public sanitized UI/data-model smoke tests."""

from app.project_factories import (
    create_generic_solar_reference,
    create_generic_wind_reference,
)
from app.ui.project_context import get_project_context
from app.ui.capex_view_model import build_capex_view_model


def test_reference_project_context_and_capex_projection_are_canonical():
    cases = [
        ("generic_solar_reference", create_generic_solar_reference),
        ("generic_wind_reference", create_generic_wind_reference),
    ]
    for template_source, factory in cases:
        project = factory()
        context = get_project_context(template_source)
        assert context is not None
        assert len(context.capex_detail_items) == 18
        view = build_capex_view_model(context)
        assert len(view.groups) == 18
        assert abs(view.total_capex_keur - context.total_capex_keur) < 1e-9
        assert view.total_capex_keur > 0
