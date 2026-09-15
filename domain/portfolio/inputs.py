"""Portfolio inputs for pooled-financing project finance.

This is the actual portfolio model for multi-project finance.
"""
from dataclasses import dataclass
from domain.inputs import ProjectInputs, FinancingParams


@dataclass(frozen=True)
class ProjectWeight:
    """Legacy project weight — used only for weighted-average aggregation.

    The actual pooled-financing portfolio uses PortfolioInputs (below).
    This class is kept for backward compatibility with existing tests.
    """
    name: str
    weight: float
    capacity_mw: float | None = None


@dataclass(frozen=True)
class PortfolioInputs:
    """Portfolio of projects with shared pooled financing."""
    projects: tuple[ProjectInputs, ...]
    portfolio_name: str
    shared_financing: FinancingParams
    cross_default: bool = True
    cash_pooling: bool = True

    def __post_init__(self):
        if len(self.projects) < 2:
            raise ValueError("Portfolio must contain at least 2 projects")
        codes = [p.info.code for p in self.projects]
        if len(set(codes)) != len(codes):
            raise ValueError(f"Project codes must be unique, got: {codes}")

    @property
    def project_codes(self) -> tuple[str, ...]:
        return tuple(p.info.code for p in self.projects)


__all__ = ["PortfolioInputs", "ProjectWeight"]