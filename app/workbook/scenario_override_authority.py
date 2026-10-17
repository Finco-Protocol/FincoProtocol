"""Scenario override admission: only an override the canonical Run provably consumes may be saved or run.

Chain per field: UI field -> persisted override -> effective ``ProjectInputs`` -> canonical Run -> committed result.

The Run materialises its inputs from the Working Copy draft.  Of the scalar override keys the editor can persist, ONLY the ones in
``EFFECTIVE_SCALAR_KEYS`` (explicit tariff binding at the scenario boundary), the contract/engine JSON payloads written by their own
CAS-protected editors, and the single reviewed Q4 What-if candidate are applied.  Every other scalar override used to be saved,
displayed as active and followed by a "successful" Run that ignored it.  Those are UNBOUND here: rejected at Save and refused before
a Run is committed, with ``SCENARIO_OVERRIDE_UNBOUND``.  Nothing in this module changes a financial input, formula or Run path, and
binding any further field (gearing, DSCR, tenor, interest, P50 hours, aggregate CAPEX/OPEX) is a financial-owner decision.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

UNBOUND_CODE = "SCENARIO_OVERRIDE_UNBOUND"
Q4_ACTION = "q4_finding_whatif_v1"

#: Scalar editor keys applied by the canonical Run (``bind_scenario_tariff`` in the Run route).
EFFECTIVE_SCALAR_KEYS = frozenset({"tariff_eur_mwh"})
#: Payload keys applied by their own authority (Revenue V2 contract book, BESS config, developer economics): not scalar editor keys.
EFFECTIVE_PAYLOAD_KEYS = frozenset({"rev_multistream_config_json", "bess_native_config_json", "developer_economics_json"})


class ScenarioOverrideUnbound(ValueError):
    """A scenario override is not consumed by the canonical Run."""

    code = UNBOUND_CODE

    def __init__(self, keys: Iterable[str]):
        self.keys = tuple(sorted(keys))
        super().__init__(
            f"{UNBOUND_CODE}: the canonical Run does not apply {', '.join(self.keys)}. "
            "No Run was committed and nothing was changed. Remove the override (restore the Base Case value) or change the "
            "assumption in the Working Copy; a scenario can currently override the PPA tariff only.")


def _q4_key(replay_metadata: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not isinstance(replay_metadata, Mapping) or replay_metadata.get("action") != Q4_ACTION:
        return None
    from app.v2.whatif import CANDIDATES
    mapping = CANDIDATES.get(replay_metadata.get("finding_id"))
    return mapping[2] if mapping else None


def unbound_override_keys(overrides: Optional[Mapping[str, Any]], replay_metadata: Optional[Mapping[str, Any]] = None) -> list[str]:
    """Scalar override keys the Run would silently ignore (reserved/payload keys are governed by their own authorities)."""
    from app.persistence._helpers import SCENARIO_INPUT_FIELDS
    effective = set(EFFECTIVE_SCALAR_KEYS) | set(EFFECTIVE_PAYLOAD_KEYS)
    q4 = _q4_key(replay_metadata)
    if q4 and set(overrides or {}) == {q4}:       # the Run itself requires exactly this one key for a reviewed What-if
        effective.add(q4)
    return sorted(k for k in (overrides or {}) if k in SCENARIO_INPUT_FIELDS and k not in effective)


def assert_overrides_bound(overrides: Optional[Mapping[str, Any]], replay_metadata: Optional[Mapping[str, Any]] = None) -> None:
    unbound = unbound_override_keys(overrides, replay_metadata)
    if unbound:
        raise ScenarioOverrideUnbound(unbound)


def authority_matrix() -> list[dict[str, Any]]:
    """Field-by-field authority for every override the editor offers (documentation and tests read this; no behaviour depends on it)."""
    from app.v2.scenario_presentation import OVERRIDE_EDITOR_FIELDS
    from app.workbook.registry import WORKBOOK
    rows = []
    for key, label, unit in OVERRIDE_EDITOR_FIELDS:
        spec = WORKBOOK.field_by_snapshot_key(key) if hasattr(WORKBOOK, "field_by_snapshot_key") else None
        rows.append({
            "ui_field": key, "label": label, "unit": unit,
            "workbook_field": getattr(spec, "field_id", None),
            "workbook_scenario_policy": getattr(getattr(spec, "scenario_policy", None), "value", None),
            "binding": "RUN_CONSUMED" if key in EFFECTIVE_SCALAR_KEYS else "UNBOUND",
            "run_binding_path": ("bind_scenario_tariff -> ProjectInputs.revenue (Solar/Wind)" if key in EFFECTIVE_SCALAR_KEYS else
                                 "none: the Run materialises ProjectInputs from the Working Copy draft"),
        })
    return rows


def supported_editor_fields() -> list[str]:
    from app.v2.scenario_presentation import OVERRIDE_EDITOR_FIELDS
    return [key for key, _l, _u in OVERRIDE_EDITOR_FIELDS if key in EFFECTIVE_SCALAR_KEYS]


__all__ = ["UNBOUND_CODE", "EFFECTIVE_SCALAR_KEYS", "EFFECTIVE_PAYLOAD_KEYS", "ScenarioOverrideUnbound", "unbound_override_keys",
           "assert_overrides_bound", "authority_matrix", "supported_editor_fields"]
