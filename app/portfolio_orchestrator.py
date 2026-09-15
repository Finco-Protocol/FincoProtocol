"""Portfolio orchestrator — routes between pooled (legacy) and independent (Phase 1+) paths."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Any
from enum import Enum


class PortfolioMode(str, Enum):
    POOLED = "pooled"
    INDEPENDENT = "independent"


@dataclass
class PortfolioRunOutput:
    mode: str
    independent_result: Any = None
    pooled_result: Any = None
    holdco_result: Any = None
    warnings: tuple[str, ...] = field(default_factory=tuple)


def run_portfolio_orchestrated(
    portfolio_inputs: Any,
    mode: str,
    holdco_inputs: Optional[Any] = None,
    strict: bool = False,
) -> PortfolioRunOutput:
    """Run portfolio in specified mode.

    mode="independent": calls run_independent_portfolio, optionally builds HoldCo result
    mode="pooled": calls existing legacy pooled route with deprecation warning
    """
    if mode not in (PortfolioMode.POOLED, PortfolioMode.INDEPENDENT):
        raise ValueError(f"Invalid mode '{mode}'. Must be 'pooled' or 'independent'.")

    if mode == PortfolioMode.INDEPENDENT:
        from domain.portfolio.independent.runner import run_independent_portfolio

        result = run_independent_portfolio(portfolio_inputs, strict=strict)
        warnings = list(result.warnings or ())
        holdco_result = None

        if holdco_inputs is not None:
            from domain.portfolio.holdco.runner import build_holdco_result

            holdco_result = build_holdco_result(holdco_inputs, result)
            if holdco_result.warnings:
                warnings.extend(holdco_result.warnings)

        return PortfolioRunOutput(
            mode=mode,
            independent_result=result,
            holdco_result=holdco_result,
            warnings=tuple(warnings),
        )
    else:
        # pooled mode — legacy path, no HoldCo support
        from app.portfolio_runner import run_portfolio_from_inputs  # existing pooled path

        pooled_result = run_portfolio_from_inputs(portfolio_inputs)
        warnings = [
            "Pooled portfolio path is legacy/experimental — does not support HoldCo/DSRF Phase 2/3 features."
        ]
        if holdco_inputs is not None:
            warnings.append("HoldCo cannot be used with pooled portfolio mode.")

        return PortfolioRunOutput(
            mode=mode,
            pooled_result=pooled_result,
            warnings=tuple(warnings),
        )


__all__ = [
    "PortfolioMode",
    "PortfolioRunOutput",
    "run_portfolio_orchestrated",
]