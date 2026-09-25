"""Protected reference project helpers.

Protected synthetic reference models are read-only until a user explicitly
creates a working copy. The canonical protection predicate lives in
``app.services.project_library_service``; this module provides UI-facing
helpers for the first-edit confirmation flow.
"""
from __future__ import annotations

from typing import Any, Optional


# Internal codes identifying the protected reference projects.
# Hidden != deleted: the data model still has project_origin =
# "factory_template" and template_source = "generic_wind_reference" / "generic_solar_reference".
PROTECTED_REFERENCE_TEMPLATE_SOURCES: frozenset[str] = frozenset({
    "generic_wind_reference",
    "generic_solar_reference",
    "generic_storage_reference",
<<<<<<< HEAD
    "generic_data_center_reference",
=======
    "generic_ev_charging_reference",
>>>>>>> a1613ed (EV Charging V1 (4/5): canonical reference registry integration)
})


def is_protected_reference(project_record: Any) -> bool:
    """Return True if the project is a protected reference.

    Delegates to the canonical implementation in
    app.services.project_library_service so there is a single source of
    truth for the protection predicate.
    """
    from app.services.project_library_service import (
        is_protected_reference as _canonical,
    )
    return _canonical(project_record)


def first_edit_response(project_record: Any) -> dict[str, Any]:
    """The 409 response that /scenarios/state/draft returns when a
    draft save is attempted on a protected reference. The frontend
    uses this to show a 'Create editable copy?' confirmation prompt.

    The response includes the project_code, project_name, and
    template_source so the frontend can build the confirm dialog
    without a follow-up request.
    """
    return {
        "error": "protected_reference",
        "needs_copy_confirmation": True,
        "project_code": getattr(project_record, "project_code", None),
        "project_name": getattr(project_record, "project_name", None),
        "template_source": getattr(project_record, "template_source", None),
        "message": (
            "This is a protected reference project. "
            "Create an editable copy?"
        ),
    }


def working_copy_replay_metadata(
    source_project_code: str,
    source_project_origin: str,
) -> dict[str, Any]:
    """Replay metadata for a working copy created from a protected
    reference. The metadata records the source project and the
    transition type so audit / reviewer can trace the lineage."""
    return {
        "export_type": "working_copy_from_protected_reference",
        "source_project_code": source_project_code,
        "source_project_origin": source_project_origin,
        "created_via": "p2fix3_first_edit_confirmation",
        "baseline_source": False,
    }
