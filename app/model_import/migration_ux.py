"""Read-only presentation projections for the Excel migration review workflow.

This module derives no write authority.  Source scenario labels remain unverified,
and workbook-level manifest progress is never promoted to a per-scenario status.
"""
from __future__ import annotations

from typing import Any, Mapping


_SCENARIO_UNPROVEN = "LABEL_ONLY_UNVERIFIED"
_UNTRACKED = "NOT_TRACKED"


def scenario_review_matrix(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Bounded display rows from observed scenario structures and proposed slices.

    An eligible slice is only eligible to *enter review*; neither human approval
    nor a financial Apply, Run or reconciliation is implied by that eligibility.
    """
    scenarios = plan.get("scenarios") or {}
    slices = plan.get("slices") or ()
    target = plan.get("target") or {}
    target_name = str(target.get("scenario_name") or "default Working Copy")
    candidates = {str(s.get("key")): s for s in slices if s.get("key") is not None}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def append(key: str, label: str, resolution: str, *, scenario_kind: str) -> None:
        if key in seen:
            return
        seen.add(key)
        slice_ = candidates.get(key)
        deps = list(dict.fromkeys(str(v) for v in (
            list((slice_ or {}).get("blockers") or ()) + list((slice_ or {}).get("notes") or ())
        )))
        if resolution == "SCENARIO_LOGIC_UNRESOLVED" and scenario_kind != "COMMON":
            deps = list(dict.fromkeys([*deps, "SCENARIO_LOGIC_UNRESOLVED"]))
        eligible = bool(slice_ and slice_.get("apply_eligible"))
        rows.append({
            "source_key": key,
            "source_scenario": label,
            "scenario_kind": scenario_kind,
            "scenario_resolution": resolution,
            "semantics": _SCENARIO_UNPROVEN,
            "target_scenario": target_name,
            "mapped_scalar_count": int((slice_ or {}).get("applyable_rows") or 0),
            "requires_review": True,
            "unsupported_dependencies": deps,
            "apply_eligibility": ("REVIEW_ELIGIBLE" if eligible else
                                  "BLOCKED" if slice_ or resolution == "SCENARIO_LOGIC_UNRESOLVED" else "NOT_TRACKED"),
            "applied_status": _UNTRACKED,
            "reconciliation_status": _UNTRACKED,
        })

    for structure in scenarios.get("structures") or ():
        for s in structure.get("scenarios") or ():
            key = str(s.get("key") or "")
            if key:
                append(key, str(s.get("label") or key), str(s.get("resolution") or "NOT_TRACKED"),
                       scenario_kind=str(s.get("kind") or "SOURCE_CASE"))
    for slice_ in slices:
        key = str(slice_.get("key") or "")
        if key:
            append(key, str(slice_.get("label") or key), str(slice_.get("resolution") or "NOT_TRACKED"),
                   scenario_kind=str(slice_.get("kind") or "SOURCE_CASE"))
    return rows


def scenario_review_acknowledged(value: str | None) -> bool:
    """An explicit source-to-target acknowledgement, never inferred from labels."""
    return value == "on"
