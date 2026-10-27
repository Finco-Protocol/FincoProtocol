"""Canonical FIN-V2-3 Goal Seek worker and availability contract.

Preview only: calls run_project without any persistence authority. Apply uses
the existing Goal Seek Save/CAS route; this module cannot save or create Runs.
"""
from dataclasses import replace


def available_targets(project_inputs, project_type, canonical_kpis):
    """Typed RC-M handoff: only configured authoritative targets are offered."""
    from app.services.goal_seek import GOAL_SEEK_METRICS, resolve_solve_variable
    if resolve_solve_variable(project_type) is None or getattr(project_inputs.revenue, "multistream_config_json", ""):
        return []
    result = ["total_sponsor_irr", "min_dscr"]
    policy = project_inputs.valuation
    if policy.project is not None and policy.project.annual_discount_rate is not None:
        result.append("project_npv")
    if policy.sponsor is not None and policy.sponsor.annual_discount_rate is not None:
        result.append("sponsor_npv")
    return [{"key": k, "unit": GOAL_SEEK_METRICS[k].unit, "kpi_key": GOAL_SEEK_METRICS[k].kpi_key}
            for k in result if canonical_kpis.get(GOAL_SEEK_METRICS[k].kpi_key) is not None]
