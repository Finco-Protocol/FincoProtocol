"""Worker-side sensitivity execution (module-level so it can run in a spawned process).

One request = ONE admitted execution. The grid runs sequentially inside a single worker, in the
order given, so result ordering is deterministic and one request can never fan out into
uncontrolled concurrent model runs. This module changes where the runs execute, not what they
compute: every point is the same ``run_project`` call the inline path made.
"""
from __future__ import annotations

from typing import Any, Sequence

# Explicit ceiling on model evaluations per sensitivity request (shocks x levels + base). The V2 workbook
# grid is 5 points; the legacy default grid is 8 shocks x 6 levels + 1 base = 49. Anything larger fails closed.
MAX_SENSITIVITY_EVALUATIONS = 49
SENSITIVITY_TOO_LARGE_CODE = "SENSITIVITY_GRID_TOO_LARGE"


def sensitivity_grid_size_error(evaluations: int) -> str | None:
    """Typed validation error for an oversized request, else None."""
    if evaluations > MAX_SENSITIVITY_EVALUATIONS:
        return (f"{SENSITIVITY_TOO_LARGE_CODE}: {evaluations} evaluations requested; "
                f"the maximum is {MAX_SENSITIVITY_EVALUATIONS}.")
    return None


def run_sensitivity_points(project_type: str, project_inputs: Sequence[Any]) -> list[dict]:
    """Run each ProjectInputs through the production engine, in order. Never raises per point."""
    from app.api.project_runner import run_project

    outputs: list[dict] = []
    for pi in project_inputs:
        try:
            result = run_project(project_type, "Base", project_inputs_override=pi)
            outputs.append({"kpis": dict(result.get("kpis", {}))})
        except Exception as exc:  # noqa: BLE001 - one failed point must not abort the grid
            outputs.append({"error": str(exc)[:120]})
    return outputs
