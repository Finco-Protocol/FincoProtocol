"""Strict explicit-input setup validation. Never seeds/materializes economics.

The released adapter inherits factory components not closed by the editable
registry. Promotion is deliberately disabled until a complete no-seed mapping
exists; valid editable fields alone are not evidence of runtime completeness.
"""
from __future__ import annotations

from app.workbook.registry import WORKBOOK
from app.workbook.update_service import WorkbookUpdateService

VERTICALS = {"solar": "Solar", "wind": "Wind", "data_center": "Data Center", "ev_charging": "Ev Charging"}

# Exact existing consumed/inherited authorities. These are blockers, not newly
# required economic assumptions or permission to edit the underlying formulas.
UNCLOSED = {
    "solar": ["technical.pv_degradation", "technical.plant_availability", "technical.grid_availability",
              "technical.yield_scenario", "tax", "shl", "revenue.merchant"],
    "wind": ["technical.plant_availability", "technical.grid_availability", "technical.yield_scenario",
             "tax", "shl", "revenue.merchant"],
    "data_center": ["tax", "shl", "data_center.contract_term_years", "data_center.capacity_basis"],
    "ev_charging": ["tax", "shl", "ev_charging.capacity_basis"],
}


def catalogue(technology):
    if technology not in VERTICALS:
        raise ValueError("SETUP_TECHNOLOGY_NOT_RELEASED")
    from app.workbook.update_service import _assert_batch_field_applicable, BatchApplyError
    fields = []
    for spec in WORKBOOK.all_fields():
        if spec.field_id in {"project_setup.identity.project_name", "project_setup.identity.country_market"}:
            continue  # explicit metadata, not a second competing field value
        if not spec.editable or not spec.persisted:
            continue
        try:
            WorkbookUpdateService.validate_field_update(spec.field_id, "")
            # Name/capacity have non-atomic cascades in a CANONICAL batch save;
            # this separate setup store performs no cascade or financial write.
            if spec.field_id not in {"project_setup.identity.project_name", "project_setup.technical.capacity_mw"}:
                _assert_batch_field_applicable(spec.field_id, project_type=VERTICALS[technology], template_source="")
        except (ValueError, BatchApplyError):
            continue
        fields.append({"field_id": spec.field_id, "label": spec.label, "unit": spec.unit,
                       "required": spec.required, "type": spec.field_type.value,
                       "min": spec.min_value, "max": spec.max_value,
                       "snapshot_key": spec.snapshot_key})
    return fields


def readiness(technology, explicit, *, name="", country=""):
    fields = catalogue(technology)
    allowed = {f["field_id"]: f for f in fields}
    missing, invalid = [], []
    if not name.strip():
        missing.append({"field_id":"project_setup.identity.project_name","unit":None,"label":"Setup name"})
    if not country.strip():
        missing.append({"field_id":"project_setup.identity.country_market","unit":None,"label":"Country / market"})
    for field in fields:
        key = field["field_id"]
        raw = explicit.get(key)
        if raw is None or raw.strip() == "":
            if field["required"]:
                missing.append({"field_id": key, "unit": field["unit"], "label": field["label"]})
            continue
        checked = WorkbookUpdateService.validate_field_update(key, raw)
        if not checked.is_valid:
            invalid.append({"field_id": key, "unit": field["unit"], "message": checked.error})
    for key in set(explicit)-set(allowed):
        invalid.append({"field_id": key, "message": "This field is not an editable input for this technology."})
    unresolved = [{"input": key, "code": "UNSEEDED_MAPPING_UNPROVEN",
                   "source": "app/input_adapter.py::_resolve_user_inputs"} for key in UNCLOSED[technology]]
    if technology == "data_center":
        unresolved.append({"input": "data_center_missing_driver_fallbacks", "code": "UNSEEDED_MAPPING_UNPROVEN",
                           "source": "app/data_center_authority.py::drivers_from_snapshot"})
    if technology == "ev_charging":
        unresolved.append({"input": "ev_missing_driver_fallbacks", "code": "UNSEEDED_MAPPING_UNPROVEN",
                           "source": "app/ev_charging_economics.py::drivers_from_snapshot"})
    return {"can_promote": False, "state": "SETUP_DRAFT", "missing": missing, "invalid": invalid,
            "unresolved": unresolved, "required": [f for f in fields if f["required"]],
            "conditional": [], "conditional_closure": "UNPROVEN", "registry_version": WORKBOOK.version,
            "message": "Saved setup only. Creating a runnable model without starting assumptions is not yet validated for this technology."}
