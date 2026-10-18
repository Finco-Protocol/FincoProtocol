"""Immutable, run-bound evidence package for institutional reporting (RC-7 / E3).

``RunEvidence`` is a frozen, plain-data copy of ONE committed Run's persisted
evidence: the Last Run on the workspace row, or one append-only Run History
row.  Reporting reads ONLY this object, so a later Working Copy edit (or a
newer Run) cannot alter a report built from it.

Rules:
- No engine import, no recalculation, no rounding: values are passed through
  exactly as persisted.
- Missing evidence stays ``None`` (never zero).
- ``evidence_digest`` is a SHA-256 over the canonical JSON of the persisted
  evidence, so two equivalent source snapshots are provably the same input.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

STATE_CURRENT = "CURRENT"
STATE_STALE = "STALE"
STATE_HISTORICAL = "HISTORICAL"

SOURCE_LAST_RUN = "LAST_RUN"
SOURCE_RUN_HISTORY = "RUN_HISTORY"

NOT_AVAILABLE = "NOT_AVAILABLE"


def thaw(obj: Any) -> Any:
    """Deep, plain-data copy (MappingProxyType / tuples -> dict / list)."""
    if isinstance(obj, Mapping):
        return {k: thaw(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [thaw(v) for v in obj]
    return obj


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":"), default=str)


def number(value: Any) -> float | None:
    """Finite float or None.  Booleans, strings and non-finite values are missing."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


@dataclass(frozen=True)
class RunEvidence:
    source: str                      # LAST_RUN | RUN_HISTORY
    state: str                       # CURRENT | STALE | HISTORICAL
    state_reason: str
    project_id: str
    project_code: str
    project_name: str
    owner_id: str
    history_id: str | None
    snapshot_id: str
    ran_at: str
    runtime_origin: str | None
    engine_version: str | None
    workbook_version: str | None
    composite_hash: str | None
    scenario_id: str | None
    scenario_name: str | None
    last_runtime_scenario_id: str | None
    identity: dict
    runtime_summary: dict
    financial_statements: dict
    debt_schedule: dict
    tax_schedule: dict
    distribution_schedule: dict
    sponsor_schedule: dict
    integrity_evidence: dict
    evidence_digest: str = field(default="")

    # ── persisted-section accessors (None / [] when absent; never fabricated) ──
    def statement_periods(self, key: str) -> list[dict]:
        section = self.financial_statements.get(key)
        periods = section.get("periods") if isinstance(section, Mapping) else None
        return [p for p in (periods or []) if isinstance(p, Mapping)]

    def schedule_periods(self, schedule: str) -> list[dict]:
        section = getattr(self, schedule, None) or {}
        periods = section.get("periods") if isinstance(section, Mapping) else None
        return [p for p in (periods or []) if isinstance(p, Mapping)]

    @property
    def financing_evidence(self) -> dict:
        fe = self.runtime_summary.get("financing_evidence")
        return fe if isinstance(fe, dict) else {}

    @property
    def construction_periods(self) -> list[dict]:
        cf = self.financing_evidence.get("construction_funding")
        periods = cf.get("periods") if isinstance(cf, Mapping) else None
        return [p for p in (periods or []) if isinstance(p, Mapping)]


def _digest(parts: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(parts).encode("utf-8")).hexdigest()


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value else ""


def _build(*, source, state, state_reason, project_record, owner_id, history_id,
           snapshot_id, ran_at, runtime_origin, engine_version, workbook_version,
           composite_hash, scenario_id, scenario_name, last_runtime_scenario_id,
           identity, runtime_summary, financial_statements, debt_schedule,
           tax_schedule, distribution_schedule, sponsor_schedule,
           integrity_evidence) -> RunEvidence:
    sections = dict(
        runtime_summary=thaw(runtime_summary or {}),
        financial_statements=thaw(financial_statements or {}),
        debt_schedule=thaw(debt_schedule or {}),
        tax_schedule=thaw(tax_schedule or {}),
        distribution_schedule=thaw(distribution_schedule or {}),
        sponsor_schedule=thaw(sponsor_schedule or {}),
        integrity_evidence=thaw(integrity_evidence or {}),
    )
    identity_d = thaw(identity) if isinstance(identity, Mapping) else {}
    digest = _digest({
        "snapshot_id": snapshot_id, "ran_at": _iso(ran_at), "engine_version": engine_version,
        "composite_hash": composite_hash, "scenario_id": scenario_id, **sections,
    })
    return RunEvidence(
        source=source, state=state, state_reason=state_reason,
        project_id=str(getattr(project_record, "project_id", "") or ""),
        project_code=str(getattr(project_record, "project_code", "") or ""),
        project_name=str(getattr(project_record, "project_name", "") or ""),
        owner_id=str(owner_id or ""), history_id=history_id,
        snapshot_id=str(snapshot_id or ""), ran_at=_iso(ran_at),
        runtime_origin=runtime_origin, engine_version=engine_version,
        workbook_version=workbook_version, composite_hash=composite_hash,
        scenario_id=scenario_id, scenario_name=scenario_name,
        last_runtime_scenario_id=last_runtime_scenario_id,
        identity=identity_d, evidence_digest=digest, **sections,
    )


def evidence_from_workspace(ws: Any, project_record: Any, owner_id: str, *,
                            is_stale: bool, freshness_source: str, history_id: str | None = None) -> RunEvidence:
    """Last Run evidence from ONE already-read workspace row."""
    identity = getattr(ws, "last_runtime_identity", None)
    identity = identity if isinstance(identity, Mapping) else {}
    engine = identity.get("engine_version")
    return _build(
        source=SOURCE_LAST_RUN,
        state=STATE_STALE if is_stale else STATE_CURRENT,
        state_reason=("Working Copy differs from this Run's inputs"
                      if is_stale else "Working Copy identity equals this Run's inputs")
        + f" (freshness basis: {freshness_source})",
        project_record=project_record, owner_id=owner_id, history_id=history_id,
        snapshot_id=getattr(ws, "last_runtime_snapshot_id", None),
        ran_at=getattr(ws, "last_runtime_at", None),
        runtime_origin=getattr(ws, "last_runtime_origin", None),
        engine_version=str(engine) if engine else None,
        workbook_version=identity.get("workbook_version"),
        composite_hash=getattr(ws, "last_runtime_composite_hash", None),
        # the Run's own scenario, not whichever scenario is active now; a name is
        # only known when the active scenario still is the Run's scenario
        scenario_id=getattr(ws, "last_runtime_scenario_id", None),
        scenario_name=(getattr(ws, "active_scenario_name", None)
                       if getattr(ws, "active_scenario_id", None)
                       == getattr(ws, "last_runtime_scenario_id", None) else None),
        last_runtime_scenario_id=getattr(ws, "last_runtime_scenario_id", None),
        identity=identity,
        runtime_summary=getattr(ws, "last_runtime_summary", None),
        financial_statements=getattr(ws, "last_financial_statements", None),
        debt_schedule=getattr(ws, "last_debt_schedule", None),
        tax_schedule=getattr(ws, "last_tax_schedule", None),
        distribution_schedule=getattr(ws, "last_distribution_schedule", None),
        sponsor_schedule=getattr(ws, "last_sponsor_schedule", None),
        integrity_evidence=getattr(ws, "last_integrity_evidence", None),
    )


def evidence_from_history_entry(entry: Any, project_record: Any, *, last_run_snapshot_id: str | None,
                                last_run_is_stale: bool, freshness_source: str) -> RunEvidence:
    """Evidence from ONE append-only Run History row.

    State follows the existing Run History semantics: only the canonical Last
    Run is CURRENT/STALE; every older immutable run is HISTORICAL.
    """
    if last_run_snapshot_id and entry.runtime_snapshot_id == last_run_snapshot_id:
        state = STATE_STALE if last_run_is_stale else STATE_CURRENT
        reason = ("This history row is the canonical Last Run; "
                  + ("the Working Copy has changed since it ran" if last_run_is_stale
                     else "the Working Copy still matches it")
                  + f" (freshness basis: {freshness_source})")
    else:
        state = STATE_HISTORICAL
        reason = "Superseded by a later Run; immutable historical evidence, not the Last Run"
    return _build(
        source=SOURCE_RUN_HISTORY, state=state, state_reason=reason,
        project_record=project_record, owner_id=entry.user_id, history_id=entry.history_id,
        snapshot_id=entry.runtime_snapshot_id, ran_at=entry.ran_at,
        runtime_origin=entry.runtime_origin, engine_version=entry.engine_version,
        workbook_version=entry.workbook_version, composite_hash=entry.composite_hash,
        scenario_id=entry.active_scenario_id, scenario_name=entry.active_scenario_name,
        last_runtime_scenario_id=entry.last_runtime_scenario_id,
        identity=entry.last_runtime_identity,
        runtime_summary=entry.runtime_summary, financial_statements=entry.financial_statements,
        debt_schedule=entry.debt_schedule, tax_schedule=entry.tax_schedule,
        distribution_schedule=entry.distribution_schedule, sponsor_schedule=entry.sponsor_schedule,
        integrity_evidence=entry.integrity_evidence,
    )
