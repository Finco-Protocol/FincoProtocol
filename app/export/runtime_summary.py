"""Runtime summary CSV export foundation for Phase 10.

This module reads existing runtime outputs and formats them for review. It does
not change waterfall, tax, SHL, DistributionAccount, or R99/R102 behavior.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
import csv
import os

from app.persistence.provenance import build_replay_metadata
from app.project_factories import (
    create_generic_solar_reference,
    create_default_solar_project,
    create_generic_wind_reference,
    create_default_wind_project,
)


RUNTIME_SUMMARY_COLUMNS = [
    "project",
    "metric",
    "value",
    "unit",
    "runtime_or_evidence",
    "governance_status",
    "g20_status",
    "r99_r102_status",
    "export_type",
    "generated_at",
    "export_generated_at",
    "source_branch",
    "branch_name",
    "commit_sha",
    "runtime_timestamp",
    "runtime_generated_at",
    "active_project",
    "scenario_id",
    "scenario_name",
    "scenario_revision",
    "runtime_snapshot_id",
    "runtime_origin",
    "template_origin",
    "template_revision",
    "export_template_version",
    "runtime_flag_count",
    "runtime_flags_json",
    "replay_limitations",
    "governance_posture_summary",
    "notes",
]


PROJECT_FACTORIES = {
    "generic_wind_reference": create_generic_wind_reference,
    "generic_solar_reference": create_generic_solar_reference,
    "generic_solar": create_default_solar_project,
    "generic_wind": create_default_wind_project,
}


def _project_key(project: str) -> str:
    key = (project or "").strip().lower()
    if key not in PROJECT_FACTORIES:
        raise ValueError(
            f"project must be one of: {', '.join(sorted(PROJECT_FACTORIES))}"
        )
    return key


def _run_project(project: str, *, project_inputs=None):
    # PR-8 final correction: the runtime-summary module no longer implements
    # its own authority router — it resolves the factory input and executes
    # through the ONE shared production seam (clean G2C for promoted
    # projects, explicitly classified legacy for blocked projects). No
    # WaterfallRunner / run_clean_production / classifier references here.
    # R5/F04: callers may pass the snapshot-authoritative inputs for a user's
    # persisted working copy; without one the factory remains the authority.
    if project_inputs is None:
        project_inputs = PROJECT_FACTORIES[_project_key(project)]()
    from app.services.production_waterfall_seam import execute_production_waterfall

    execution = execute_production_waterfall(project_inputs)
    return execution.project_inputs, execution.result


def _sum_period_attr(result, attr: str) -> float:
    return sum(float(getattr(period, attr, 0.0) or 0.0) for period in result.periods)


def _source_branch() -> str:
    return os.getenv("GIT_BRANCH") or os.getenv("BRANCH_NAME") or "unknown"


def build_runtime_summary_rows(
    project: str,
    *,
    generated_at: str | None = None,
    source_branch: str | None = None,
    _precomputed=None,
    _project_inputs=None,
    runtime_origin: str | None = None,
    scenario_id: str | None = None,
    scenario_name: str | None = None,
) -> list[dict[str, str]]:
    if _precomputed is not None:
        # PR-8: single-calculation reuse — a caller that already ran the
        # project passes its (project_inputs, result) through (presentation
        # only; no second financial calculation).
        project_inputs, result = _precomputed
    else:
        project_inputs, result = _run_project(
            project, project_inputs=_project_inputs)
    project_name = project_inputs.info.name
    runtime_timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    timestamp = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    branch = source_branch or _source_branch()
    governance_status = "review_only"
    g20_status = "BLOCKED"
    r99_r102_status = "NOT APPROVED"
    replay_metadata = build_replay_metadata(
        project_key=_project_key(project),
        project_inputs=project_inputs,
        governance_state={
            "g20_status": g20_status,
            "r99_r102_status": r99_r102_status,
        },
        runtime_timestamp=runtime_timestamp,
        export_timestamp=timestamp,
        export_type="runtime_summary_csv",
        active_project=_project_key(project),
        runtime_origin=runtime_origin or "factory_base_runtime",
        # F07 — the artifact itself must carry scenario identity when the
        # exporter knows it (saved-state authority). Factory paths leave both
        # None and the NOT_APPLICABLE provenance markers are preserved.
        scenario_id=scenario_id,
        scenario_name=scenario_name,
    )

    values = [
        ("active_project", project_name, "", "Template-based active project runtime output."),
        ("project_irr", result.project_irr, "ratio", "Existing runtime summary value."),
        ("equity_irr", result.equity_irr, "ratio", "Existing runtime summary value."),
        ("total_revenue_keur", result.total_revenue_keur, "kEUR", "Existing runtime total."),
        ("total_ebitda_keur", result.total_ebitda_keur, "kEUR", "Existing runtime total."),
        ("total_opex_keur", result.total_opex_keur, "kEUR", "Existing runtime total."),
        ("avg_dscr", result.actual_avg_dscr, "x", "Existing runtime debt metric."),
        ("min_dscr", result.actual_min_dscr, "x", "Existing runtime debt metric."),
        (
            "total_distributions_keur",
            _sum_period_attr(result, "distribution_keur"),
            "kEUR",
            "Sum of existing period.distribution_keur values.",
        ),
        (
            "total_shl_service_keur",
            _sum_period_attr(result, "shl_interest_keur")
            + _sum_period_attr(result, "shl_principal_keur"),
            "kEUR",
            "Cash SHL interest plus principal from existing period fields.",
        ),
        ("g20_status", g20_status, "", "Governance label only; this export does not approve G20."),
        (
            "r99_r102_status",
            r99_r102_status,
            "",
            "Governance label only; runtime promotion remains not approved.",
        ),
    ]

    rows: list[dict[str, str]] = []
    for metric, value, unit, notes in values:
        rows.append(
            {
                "project": project_name,
                "metric": metric,
                "value": str(value),
                "unit": unit,
                "runtime_or_evidence": "runtime",
                "governance_status": governance_status,
                "g20_status": g20_status,
                "r99_r102_status": r99_r102_status,
                "export_type": "runtime_summary_csv",
                "generated_at": timestamp,
                "export_generated_at": replay_metadata["export_generated_at"],
                "source_branch": branch,
                "branch_name": replay_metadata["branch_name"],
                "commit_sha": replay_metadata["commit_sha"],
                "runtime_timestamp": replay_metadata["runtime_timestamp"],
                "runtime_generated_at": replay_metadata["runtime_generated_at"],
                "active_project": replay_metadata["active_project"],
                "scenario_id": replay_metadata["scenario_id"],
                "scenario_name": replay_metadata["scenario_name"],
                "scenario_revision": replay_metadata["scenario_revision"],
                "runtime_snapshot_id": replay_metadata["runtime_snapshot_id"],
                "runtime_origin": replay_metadata["runtime_origin"],
                "template_origin": replay_metadata["template_origin"],
                "template_revision": replay_metadata["template_revision"],
                "export_template_version": replay_metadata["export_template_version"],
                "runtime_flag_count": str(replay_metadata["runtime_flag_count"]),
                "runtime_flags_json": replay_metadata["runtime_flags_json"],
                "replay_limitations": replay_metadata["replay_limitations_notice"],
                "governance_posture_summary": replay_metadata["governance_posture_summary"],
                "notes": notes,
            }
        )
    return rows


def build_runtime_summary_csv(
    project: str,
    *,
    generated_at: str | None = None,
    source_branch: str | None = None,
    rows: list[dict[str, str]] | None = None,
) -> str:
    """Serialize runtime-summary rows to CSV.

    PR-8 single-calculation contract: when ``rows`` are supplied by a caller
    that already executed the production authority, this serializer performs
    ZERO financial calculations. Without ``rows`` it performs exactly ONE
    (build_runtime_summary_rows).
    """
    if rows is None:
        rows = build_runtime_summary_rows(
            project,
            generated_at=generated_at,
            source_branch=source_branch,
        )
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=RUNTIME_SUMMARY_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def write_runtime_summary_csv(
    project: str,
    output_path: str | Path,
    *,
    generated_at: str | None = None,
    source_branch: str | None = None,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        build_runtime_summary_csv(
            project,
            generated_at=generated_at,
            source_branch=source_branch,
        ),
        encoding="utf-8",
    )
    return path

