"""Canonical deterministic serialization for CostTemplate versions.

The serialized JSON document IS the immutable version artifact (and, in a
later integration step, the direct persistence payload). Identical
templates serialize to identical bytes: sorted keys, explicit schema stamp,
no timestamps or volatile data inside the payload.
"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any

from app.services.cost_template.contracts import (
    CapexTemplateItem,
    CostDriver,
    CostTemplate,
    ItemClassification,
    OpexTemplateItem,
    ScalingBasis,
    TemplateKind,
    TemplateSource,
    TemplateStatus,
)


def _encode(obj: Any) -> Any:
    # Correction C (defect 7): scalar metadata is stored as an immutable
    # MappingProxyType; asdict()/deepcopy cannot pickle it, so dataclass
    # conversion here is manual-safe: encode field-by-field for dataclasses.
    import types as _types
    if is_dataclass(obj) and not isinstance(obj, type):
        return {
            f: _encode(getattr(obj, f))
            for f in obj.__dataclass_fields__
        }
    if isinstance(obj, _types.MappingProxyType):
        return {k: _encode(v) for k, v in obj.items()}
    if isinstance(obj, (TemplateKind, TemplateStatus, CostDriver,
                        ScalingBasis, ItemClassification, TemplateSource)):
        return obj.value
    if isinstance(obj, tuple):
        return [_encode(v) for v in obj]
    if isinstance(obj, list):
        return [_encode(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _encode(v) for k, v in obj.items()}
    return obj


def cost_template_to_json(template: CostTemplate) -> str:
    """Canonical JSON (sorted keys, 2-space indent). Deterministic."""
    template.validate()
    doc = {
        "_schema": template._schema,
        "template": _encode(template),
    }
    return json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=True)


def cost_template_from_json(payload: str) -> CostTemplate:
    """Rebuild a template from its canonical JSON. Fail closed on unknown
    enum values; the rebuilt template is re-validated."""
    doc = json.loads(payload)
    if doc.get("_schema") != "finco-cost-template-1":
        raise ValueError(
            f"COST_TEMPLATE_SCHEMA_UNKNOWN: {doc.get('_schema')!r} is not "
            "'finco-cost-template-1'"
        )
    t = doc["template"]

    def capex_item(d: dict) -> CapexTemplateItem:
        d = dict(d)
        d["driver"] = CostDriver(d["driver"])
        d["scaling_basis"] = ScalingBasis(d["scaling_basis"])
        d["classification"] = ItemClassification(d["classification"])
        d["source"] = TemplateSource(d["source"])
        d["spending_profile"] = tuple(
            float(s) for s in (d.get("spending_profile") or ()))
        # validate() wraps scalar_metadata into the immutable proxy
        return CapexTemplateItem(**d)

    def opex_item(d: dict) -> OpexTemplateItem:
        d = dict(d)
        d["driver"] = CostDriver(d["driver"])
        d["scaling_basis"] = ScalingBasis(d["scaling_basis"])
        d["classification"] = ItemClassification(d["classification"])
        d["source"] = TemplateSource(d["source"])
        d["step_changes"] = tuple((int(y), float(a)) for y, a in (d.get("step_changes") or ()))
        return OpexTemplateItem(**d)

    template = CostTemplate(
        template_id=t["template_id"],
        version=t["version"],
        name=t["name"],
        technology=t["technology"],
        kind=TemplateKind(t["kind"]),
        capex_items=tuple(capex_item(d) for d in t["capex_items"]),
        opex_items=tuple(opex_item(d) for d in t["opex_items"]),
        status=TemplateStatus(t["status"]),
        provenance=t.get("provenance", ""),
        created_at=t.get("created_at", ""),
        reference_capacity_mw=t.get("reference_capacity_mw"),
        source_project_ref=t.get("source_project_ref"),
        # Applicability addendum (A9): contingency applicability flags are
        # part of the immutable version payload.
        capex_contingency_active=t.get("capex_contingency_active", True),
        opex_contingency_active=t.get("opex_contingency_active", True),
        _schema=t["_schema"],
    )
    template.validate()
    return template
