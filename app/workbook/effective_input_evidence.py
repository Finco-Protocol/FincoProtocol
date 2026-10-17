"""RC-5 / S7-01: Run-bound evidence that saved scenario overrides were EFFECTIVE in a Run.

Two different questions must never be conflated:

* **Run artifact integrity** - are the committed snapshot, hashes and (optionally) the signed certificate unaltered?  Answered by the
  Run Integrity Checks and the Signed Run Certificate signature.  Nothing here changes them.
* **Effective-input application** - did the canonical Run provably *apply* the scenario overrides that were saved when it ran?  Answered
  only by canonical binding evidence recorded by the Run itself (``scenario_revenue_input`` for the tariff / contract payload,
  ``q4_effective_input`` for the reviewed What-if).  A stored override, a scenario name or a valid signature is NOT such evidence.

The block below is a pure projection.  It reads committed evidence only, never rewrites a Run, and never infers application:
anything it cannot prove is ``EFFECTIVENESS_NOT_ESTABLISHED`` (older Runs, unbound fields, missing evidence).
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional

SCHEMA = "finco-effective-input-evidence-v1"
ESTABLISHED = "ESTABLISHED"
NOT_APPLICABLE = "NOT_APPLICABLE"
NOT_ESTABLISHED = "EFFECTIVENESS_NOT_ESTABLISHED"
STATUSES = (ESTABLISHED, NOT_APPLICABLE, NOT_ESTABLISHED)

SCOPE_NOTE = ("Run artifact integrity (hashes, snapshot, signature) is attested separately. This block states only whether the "
              "scenario overrides saved when the Run executed are proven to have been applied by it.")

R_NO_OVERRIDES = "NO_SCENARIO_OVERRIDES_AT_RUN"
R_ALL_BOUND = "ALL_OVERRIDES_BOUND_BY_CANONICAL_EVIDENCE"
R_UNRECORDED = "OVERRIDES_AT_RUN_NOT_RECORDED"
R_HISTORICAL = "RUN_PREDATES_EFFECTIVE_INPUT_EVIDENCE"
R_PARTIAL = "OVERRIDES_WITHOUT_CANONICAL_BINDING_EVIDENCE"
R_UNREADABLE = "SCENARIO_EVIDENCE_UNREADABLE"


def _num(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _same(a: Any, b: Any) -> bool:
    x, y = _num(a), _num(b)
    return x is not None and y is not None and math.isclose(x, y, rel_tol=0.0, abs_tol=1e-9)


def _field_bound(key: str, value: Any, revenue: Mapping[str, Any], q4: Mapping[str, Any]) -> bool:
    """True only when the Run itself recorded canonical evidence that this exact override value reached the engine inputs."""
    if key == "tariff_eur_mwh":
        return (revenue.get("authority") == "materialized_project_inputs"
                and _same(revenue.get("effective_tariff_eur_mwh"), value))
    if key == "rev_multistream_config_json":
        return (revenue.get("authority") == "materialized_project_inputs"
                and bool(revenue.get("multistream_config_json"))
                and revenue.get("multistream_config_json") == value)
    if q4 and q4.get("authority") == "q4_canonical_reviewed_scenario_v1" and q4.get("snapshot_key") == key:
        return _same(q4.get("value"), value)
    return False


def build_effective_input_evidence(*, overrides: Optional[Mapping[str, Any]], scenario_revenue_input: Optional[Mapping[str, Any]] = None,
                                   q4_effective_input: Optional[Mapping[str, Any]] = None, basis: str = "run_time") -> dict:
    """Classify the overrides that were saved when a Run executed.  ``overrides is None`` means "not recorded" (never "none")."""
    base = {"schema": SCHEMA, "basis": basis, "scope": SCOPE_NOTE}
    if overrides is None or not isinstance(overrides, Mapping):
        return {**base, "status": NOT_ESTABLISHED, "reason": R_UNRECORDED, "overrides_at_run": None, "bound_fields": [], "unbound_fields": []}
    saved = {k: v for k, v in overrides.items()}
    if not saved:
        return {**base, "status": NOT_APPLICABLE, "reason": R_NO_OVERRIDES, "overrides_at_run": {}, "bound_fields": [], "unbound_fields": []}
    revenue = scenario_revenue_input if isinstance(scenario_revenue_input, Mapping) else {}
    q4 = q4_effective_input if isinstance(q4_effective_input, Mapping) else {}
    bound = sorted(k for k, v in saved.items() if _field_bound(k, v, revenue, q4))
    unbound = sorted(k for k in saved if k not in bound)
    return {**base, "status": ESTABLISHED if not unbound else NOT_ESTABLISHED,
            "reason": R_ALL_BOUND if not unbound else R_PARTIAL,
            "overrides_at_run": {k: saved[k] for k in sorted(saved)}, "bound_fields": bound, "unbound_fields": unbound}


def _valid_stored(block: Any) -> bool:
    return (isinstance(block, Mapping) and block.get("schema") == SCHEMA and block.get("status") in STATUSES
            and isinstance(block.get("bound_fields"), list) and isinstance(block.get("unbound_fields"), list))


def resolve_effective_input_evidence(ws: Any, *, scenario_run_summary: Optional[Mapping[str, Any]] = None) -> dict:
    """Effective-input evidence for the committed Last Run of ``ws``.

    1. A Run that recorded its own block (every Run after RC-5) is reported exactly as recorded.
    2. An older Run is evaluated only from evidence that was recorded WITH that same Run: the owning scenario's persisted run summary,
       and only when its ``snapshot_id`` is the workspace's Last Run snapshot.  Nothing from the current Working Copy or the current
       scenario overrides is used.
    3. Otherwise the answer is the explicit historical status ``EFFECTIVENESS_NOT_ESTABLISHED`` - never a guess.
    """
    summary = getattr(ws, "last_runtime_summary", None)
    summary = summary if isinstance(summary, Mapping) else {}
    stored = summary.get("effective_input_evidence")
    if _valid_stored(stored):
        return dict(stored)
    base = {"schema": SCHEMA, "basis": "historical_run_evidence", "scope": SCOPE_NOTE}
    snapshot_id = getattr(ws, "last_runtime_snapshot_id", None)
    scenario_id = getattr(ws, "last_runtime_scenario_id", None)
    q4 = summary.get("q4_effective_input")
    if not scenario_id:                     # a Run with no scenario selected executed the Working Copy only: there was nothing to apply
        return {**base, "status": NOT_APPLICABLE, "reason": R_NO_OVERRIDES, "overrides_at_run": {}, "bound_fields": [], "unbound_fields": []}
    if scenario_run_summary is None:
        scenario_run_summary = _load_scenario_run_summary(ws, scenario_id)
        if scenario_run_summary is False:
            return {**base, "status": NOT_ESTABLISHED, "reason": R_UNREADABLE, "overrides_at_run": None, "bound_fields": [], "unbound_fields": []}
    if isinstance(scenario_run_summary, Mapping) and snapshot_id and scenario_run_summary.get("snapshot_id") == snapshot_id \
            and "scenario_overrides_at_run" in scenario_run_summary:
        return build_effective_input_evidence(
            overrides=scenario_run_summary.get("scenario_overrides_at_run"),
            scenario_revenue_input=scenario_run_summary.get("scenario_revenue_input") or summary.get("scenario_revenue_input"),
            q4_effective_input=q4, basis="historical_run_evidence")
    return {**base, "status": NOT_ESTABLISHED, "reason": R_HISTORICAL, "overrides_at_run": None, "bound_fields": [], "unbound_fields": []}


def _load_scenario_run_summary(ws: Any, scenario_id: str):
    """The persisted run summary of the scenario that owns the Last Run, ``None`` when it has none, ``False`` when unreadable."""
    try:
        from app.persistence.scenarios_repository import get_scenario
        record = get_scenario(scenario_id=scenario_id, user_id=getattr(ws, "user_id", None))
    except Exception:  # noqa: BLE001 - an evidence read failure is "unreadable", never "applied"
        return False
    if record is None:
        return False
    summary = getattr(record, "last_run_summary", None)
    return summary if isinstance(summary, Mapping) else None


__all__ = ["SCHEMA", "ESTABLISHED", "NOT_APPLICABLE", "NOT_ESTABLISHED", "STATUSES", "build_effective_input_evidence",
           "resolve_effective_input_evidence"]
