"""Read-only adapters over immutable Run History and approved financial projections.

No engine execution, financial arithmetic, persistence, tokens, or mutable scenario
assumptions belong here. Callers authorize project access before reading entries.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping, Sequence

from app.v2.credit_decision_projection import HISTORICAL, LAST_CURRENT, RunInput, build_credit_decision
from app.v2.output_metric_projection import KPI_CATALOG, SPONSOR_SUMMARY_SOURCE_KEYS
from app.v2.returns_projection import build_returns_projection
from app.v2.run_history_projection import _enriched_kpis
from app.v2.scenario_kpi_projection import build_compare_rows, build_scenario_projection

SCHEMA = "wf-react-3-v1"
MAX_RUNS = 3


class InsightsIdentityError(ValueError):
    """Stored evidence contradicts its immutable Run binding."""


def validate_entry(entry: Any, *, project_id: str, project_code: str, owner: str | None = None) -> None:
    if entry.project_id != project_id or entry.project_code != project_code or (owner is not None and entry.user_id != owner):
        raise InsightsIdentityError("Run project binding mismatch.")
    if not entry.history_id or not entry.runtime_snapshot_id:
        raise InsightsIdentityError("Run identity unavailable.")
    if entry.active_scenario_id is not None and entry.active_scenario_id != entry.last_runtime_scenario_id:
        raise InsightsIdentityError("Run scenario binding mismatch.")
    identity = entry.last_runtime_identity or {}
    for key, expected in (("snapshot_id", entry.runtime_snapshot_id),
                          ("composite_hash", entry.composite_hash),
                          ("scenario_id", entry.last_runtime_scenario_id),
                          ("engine_version", entry.engine_version),
                          ("workbook_version", entry.workbook_version)):
        if key in identity and identity[key] != expected:
            raise InsightsIdentityError("Stored Run identity mismatch.")
    binding = identity.get("model_v2")
    if binding is not None:
        from app.model_v2.persistence import validate_run_binding_payload
        try:
            binding = validate_run_binding_payload(dict(binding))
        except Exception as exc:
            raise InsightsIdentityError("Run binding invalid.") from exc
        if (binding.get("snapshot_id") != entry.runtime_snapshot_id
                or binding.get("scenario_id") != entry.last_runtime_scenario_id
                or binding.get("working_copy_ref") != project_code):
            raise InsightsIdentityError("Run binding mismatch.")
    if "financing_evidence" in (entry.runtime_summary or {}):
        # The approved source validator owns the binding schema and correlation.
        from app.v2.financing_sources_uses_projection import build_sources_uses_projection
        try:
            build_sources_uses_projection(
                runtime_result=entry, integrity_evidence=entry.integrity_evidence,
                freshness="NOT_RUN", run_kind="HISTORICAL_RUN",
                expected_snapshot_id=entry.runtime_snapshot_id,
                expected_composite_hash=entry.composite_hash,
                expected_scenario_id=entry.last_runtime_scenario_id)
        except ValueError as exc:
            raise InsightsIdentityError("Committed financing evidence binding invalid.") from exc


def scenario_label(entry: Any) -> str:
    """Use committed labels only; a renamed live scenario cannot rewrite history."""
    if entry.last_runtime_scenario_id is None:
        return "Base Case"
    if entry.active_scenario_id == entry.last_runtime_scenario_id and entry.active_scenario_name:
        return entry.active_scenario_name
    return "UNAVAILABLE"


def run_identity(entry: Any, state: str = HISTORICAL) -> dict[str, Any]:
    return {"history_id": entry.history_id, "snapshot_id": entry.runtime_snapshot_id,
            "scenario_id": entry.last_runtime_scenario_id, "scenario": scenario_label(entry),
            "ran_at": entry.ran_at, "composite_hash": entry.composite_hash,
            "engine_version": entry.engine_version, "workbook_version": entry.workbook_version,
            "state": state, "runtime_origin": entry.runtime_origin}


def run_links(project_code: str, history_id: str) -> dict[str, str]:
    from urllib.parse import urlencode
    query = urlencode({"project": project_code, "history_id": history_id})
    return {"statements": "/v2/workbook/run-history/statements?" + query,
            "run_detail": "/v2/workbook/run-history/detail?" + query}


def build_insights(entries: Sequence[Any], *, project_code: str, project_id: str,
                   project_name: str = "", states: Mapping[str, str] | None = None,
                   terms: Mapping[str, Any] | None = None,
                   working: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Adapt one to three explicitly selected committed Runs. Pure projection."""
    if not 1 <= len(entries) <= MAX_RUNS or len({e.history_id for e in entries}) != len(entries):
        raise ValueError("INSIGHTS_EXPLICIT_RUN_SELECTION_REQUIRED")
    for entry in entries:
        validate_entry(entry, project_id=project_id, project_code=project_code)
    states, terms, working = states or {}, terms or {}, working or {}
    inputs = [RunInput(entry=e, state=states.get(e.history_id, HISTORICAL),
                       scenario_label=scenario_label(e),
                       terms=terms.get(e.history_id) if states.get(e.history_id) == LAST_CURRENT else None,
                       working=working.get(e.history_id) if states.get(e.history_id) == LAST_CURRENT else None)
              for e in entries]
    credit = build_credit_decision(inputs, project_code=project_code)
    projections, runs = [], []
    for entry, credit_run in zip(entries, credit["runs"]):
        identity = run_identity(entry, states.get(entry.history_id, HISTORICAL))
        kpis = _enriched_kpis(entry)
        # Sponsor return keys have an explicit schedule authority; a same-named
        # runtime scalar must never silently replace that schedule's definition.
        sponsor_summary = (entry.sponsor_schedule or {}).get("summary") or {}
        for key, field in SPONSOR_SUMMARY_SOURCE_KEYS.items():
            kpis[key] = sponsor_summary.get(field)
        projection = build_scenario_projection(identity["scenario"], kpis, entry.ran_at, False)
        projections.append(projection)
        metrics = []
        for key, _label, _unit, _fmt, source in KPI_CATALOG:
            metric = asdict(projection.metrics[key])
            # Catalog provenance is refined to the actual same-row fallback.
            if key in ("min_llcr", "target_dscr") and entry.runtime_summary.get(key) is not None:
                source = "runtime_summary"
            metric.update(source=source + "." + SPONSOR_SUMMARY_SOURCE_KEYS.get(key, key),
                          scenario_id=entry.last_runtime_scenario_id, history_id=entry.history_id,
                          snapshot_id=entry.runtime_snapshot_id, freshness="committed",
                          period="AGGREGATE", reason="" if metric["raw_value"] is not None else
                          "This metric is not persisted by the selected committed Run.")
            metrics.append(metric)
        metrics.append({"key": "plcr", "label": "PLCR", "raw_value": None,
                        "display_value": "—", "unit": "x", "availability": "not_available",
                        "source": "No approved persisted PLCR projection", "reason": "PLCR authority unavailable.",
                        "scenario_id": entry.last_runtime_scenario_id, "history_id": entry.history_id,
                        "snapshot_id": entry.runtime_snapshot_id, "period": "AGGREGATE", "freshness": "committed"})
        sponsor = asdict(build_returns_projection(entry, entry, runtime_is_stale=False))
        sponsor.update(state=identity["state"], scenario_name=identity["scenario"], identity=identity)
        for metric in sponsor["metrics"]:
            metric.update(availability="available" if metric["value"] is not None else "not_available",
                          reason="" if metric["value"] is not None else "Evidence not persisted by the selected committed Run.")
        # All link targets remain bound to the selected historical Run.
        links = run_links(project_code, entry.history_id)
        runs.append({"identity": identity, "links": links, "metrics": metrics,
                     "credit": credit_run, "sponsor": sponsor,
                     "timeline_modes": {"model_period": True, "annual": False,
                                        "reason": "No approved annual credit timeline projection is available."}})
    rows = []
    catalog = {row[0]: row for row in KPI_CATALOG}
    for row in build_compare_rows(projections):
        data = asdict(row)
        data.update(unit=catalog[row.key][2], source=catalog[row.key][4],
                    availability=["available" if v is not None else "not_available" for v in row.raw_values],
                    sources=[next(m["source"] for m in r["metrics"] if m["key"] == row.key) for r in runs])
        rows.append(data)
    return {"ok": True, "schema": SCHEMA,
            "project": {"code": project_code, "project_id": project_id, "name": project_name},
            "max_runs": MAX_RUNS, "runs": runs,
            "comparison": {"columns": [r["identity"] for r in runs], "rows": rows,
                           "authority": "app.v2.scenario_kpi_projection.build_compare_rows"},
            "credit": credit}
