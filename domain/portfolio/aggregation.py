"""Summary aggregation of project KPIs (not a portfolio finance model).

This module provides weighted-average aggregation for presenting
portfolio-level summaries.  It is NOT the pooled-financing portfolio model.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AggregationWeight:
    name: str
    weight: float
    capacity_mw: Optional[float] = None


@dataclass(frozen=True)
class PortfolioAggregationInputs:
    name: str
    projects: tuple[AggregationWeight, ...]

    def __post_init__(self):
        total = sum(p.weight for p in self.projects)
        if not (0.99 <= total <= 1.01):
            raise ValueError(f"Weights must sum to ~1.0, got {total}")


@dataclass(frozen=True)
class PortfolioAggregationResult:
    avg_project_irr: float
    weighted_capacity_mw: float
    total_revenue_keur: float
    total_ebitda_keur: float


def aggregate_project_kpis(
    inputs: PortfolioAggregationInputs,
    project_results: dict[str, dict],
) -> PortfolioAggregationResult:
    """Simple weighted-average KPI aggregation (not pooled finance)."""
    total_rev = 0.0
    total_ebitda = 0.0
    irr_vals = []
    irr_weights = []
    cap_weighted = 0.0

    for proj in inputs.projects:
        if proj.name not in project_results:
            continue
        r = project_results[proj.name]
        total_rev += r.get("revenue_keur", 0.0)
        total_ebitda += r.get("ebitda_keur", 0.0)
        irr = r.get("project_irr", 0.0)
        if irr > 0:
            irr_vals.append(irr)
            irr_weights.append(proj.weight)
        if proj.capacity_mw:
            cap_weighted += proj.capacity_mw * proj.weight

    avg_irr = sum(v * w for v, w in zip(irr_vals, irr_weights)) / sum(irr_weights) if irr_weights else 0.0

    return PortfolioAggregationResult(
        avg_project_irr=avg_irr,
        weighted_capacity_mw=cap_weighted,
        total_revenue_keur=total_rev,
        total_ebitda_keur=total_ebitda,
    )


__all__ = [
    "AggregationWeight",
    "PortfolioAggregationInputs",
    "PortfolioAggregationResult",
    "aggregate_project_kpis",
]