"""Scenario Engine — P50/P90/P99 multi-scenario analysis.

Enterprise Implementation Brief §2.1
Supports: P50, P90-1y, P90-10y, P99-1y scenarios
"""
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from domain.inputs import ProjectInputs


class YieldScenario(Enum):
    """Yield scenario types for generation analysis."""
    P50 = "P50"          # Median scenario (50th percentile)
    P90_1Y = "P90-1y"    # P90 single-year exceedance
    P90_10Y = "P90-10y"  # P90 10-year average
    P99_1Y = "P99-1y"    # P99 single-year (extreme year)


@dataclass(frozen=True)
class ScenarioResult:
    """Result of a single scenario run."""
    scenario: YieldScenario
    equity_irr: float
    project_irr: float
    npv_keur: float
    lcoe_eur_mwh: float
    avg_dscr: float
    min_dscr: float
    total_distribution_keur: float
    total_tax_keur: float
    generation_mwh_y1: float
    revenue_keur_y1: float


def get_scenario_hours(
    inputs: ProjectInputs,
    scenario: YieldScenario,
) -> float:
    """Get operating hours for a given yield scenario.
    
    Args:
        inputs: ProjectInputs with technical params
        scenario: YieldScenario enum value
    
    Returns:
        Operating hours for the scenario
    """
    tech = inputs.technical
    p99_1y = getattr(tech, 'operating_hours_p99_1y', None)
    
    if scenario == YieldScenario.P50:
        return tech.operating_hours_p50
    elif scenario == YieldScenario.P90_1Y:
        # P90-1y — use p90_10y as proxy if p90_1y not available
        return getattr(tech, 'operating_hours_p90_1y', tech.operating_hours_p90_10y)
    elif scenario == YieldScenario.P90_10Y:
        return tech.operating_hours_p90_10y
    elif scenario == YieldScenario.P99_1Y:
        if p99_1y is not None:
            return p99_1y
        # Fallback: P99 = P50 × 0.75 (rough approximation)
        return tech.operating_hours_p50 * 0.75
    return tech.operating_hours_p50


def _inputs_for_scenario(base_inputs: ProjectInputs, scenario: YieldScenario) -> ProjectInputs:
    """Create scenario-specific ProjectInputs by adjusting yield scenario hours.
    
    This is needed because cached_run_waterfall_v3 builds generation schedule
    from inputs.technical.operating_hours_p50. For P90 scenario, we need
    P90 hours as the "P50" hours in the inputs.
    
    Args:
        base_inputs: Base ProjectInputs (from UI)
        scenario: Target scenario
    
    Returns:
        ProjectInputs with scenario-specific operating hours
    """
    from dataclasses import replace
    hours = get_scenario_hours(base_inputs, scenario)
    scenario_name_map = {
        YieldScenario.P50: "P_50",
        YieldScenario.P90_1Y: "P90_1Y",
        YieldScenario.P90_10Y: "P90_10Y",
        YieldScenario.P99_1Y: "P99_1Y",
    }
    scenario_name = scenario_name_map.get(scenario, "P_50")
    return replace(
        base_inputs,
        technical=replace(
            base_inputs.technical,
            yield_scenario=scenario_name,
            operating_hours_p50=hours,
        ),
    )


def run_scenario(
    inputs: ProjectInputs,
    scenario: YieldScenario,
    run_waterfall_fn,
    fixed_debt_keur: float | None = None,
) -> ScenarioResult:
    """Run waterfall for a specific scenario with optional fixed debt.
    
    If fixed_debt_keur is provided, debt is NOT re-sized — the same
    P90-sized debt is used for all scenarios (bank standard).
    
    Args:
        inputs: ProjectInputs (scenario-specific hours are applied)
        scenario: Scenario to run
        run_waterfall_fn: Callable that runs the waterfall (from cached_run_waterfall_v3)
        fixed_debt_keur: Optional fixed debt amount (from P90 sizing run)
    
    Returns:
        ScenarioResult with scenario-specific metrics
    """
    # Run waterfall for this scenario (with or without fixed debt)
    result = run_waterfall_fn(
        inputs=inputs,
        fixed_debt_keur=fixed_debt_keur,
    )
    
    # Compute LCOE
    lcoe = _compute_lcoe_from_waterfall(result, inputs)
    
    return ScenarioResult(
        scenario=scenario,
        equity_irr=result.equity_irr,
        project_irr=result.project_irr,
        npv_keur=int(result.project_npv),
        lcoe_eur_mwh=round(lcoe, 2),
        avg_dscr=result.avg_dscr,
        min_dscr=result.min_dscr,
        total_distribution_keur=int(result.total_distribution_keur),
        total_tax_keur=int(result.total_tax_keur),
        generation_mwh_y1=_get_y1_generation(result),
        revenue_keur_y1=_get_y1_revenue(result),
    )


def _get_y1_generation(result) -> int:
    """Extract Y1 generation from waterfall result."""
    for p in result.periods:
        if p.is_operation and p.year_index == 1:
            return int(p.generation_mwh * 2)  # H1 * 2 ≈ Y1
    total_gen = sum(p.generation_mwh for p in result.periods if p.is_operation)
    return int(total_gen * 0.035)


def _get_y1_revenue(result) -> int:
    """Extract Y1 revenue from waterfall result."""
    for p in result.periods:
        if p.is_operation and p.year_index == 1:
            return int(p.revenue_keur * 2)  # H1 * 2 ≈ Y1
    total_rev = sum(p.revenue_keur for p in result.periods if p.is_operation)
    return int(total_rev * 0.035)


def _compute_lcoe_from_waterfall(result, inputs) -> float:
    """Compute economic LCOE from waterfall result.

    Formula (Option A — economic LCOE):
        LCOE = (Total CapEx + Total OpEx) / Total Generation

    Units:
        - numerator: kEUR
        - denominator: total_gen / 1000 → GWh
        - result: kEUR/GWh = EUR/MWh (since 1 kEUR/GWh × 1000 = EUR/MWh)
        - expressed as EUR/MWh for readability

    Notes:
        - Excludes debt service (economic vs. financed LCOE)
        - Uses operating periods only
        - OpEx includes all operating costs (OM, insurance, land, etc.)
    """
    total_gen = sum(p.generation_mwh for p in result.periods if p.is_operation)
    if total_gen <= 0:
        return 0.0

    total_capex = inputs.capex.total_capex
    total_opex = sum(p.opex_keur for p in result.periods if p.is_operation)
    # Economic LCOE: CapEx + OpEx (NOT debt service)
    numerator = total_capex + total_opex
    denominator = total_gen / 1000  # MWh → GWh → result is kEUR/GWh = EUR/MWh
    return numerator / denominator if denominator > 0 else 0.0


def compare_scenarios(
    results: Sequence[ScenarioResult],
) -> dict:
    """Build comparison table from multiple scenario results.
    
    Returns:
        Dict with comparison data for UI rendering
    """
    if not results:
        return {}
    
    scenarios = [r.scenario.value for r in results]
    
    return {
        "scenario": scenarios,
        "equity_irr": [f"{r.equity_irr:.2%}" for r in results],
        "project_irr": [f"{r.project_irr:.2%}" for r in results],
        "npv_keur": [f"{r.npv_keur:,}" for r in results],
        "lcoe": [f"{r.lcoe_eur_mwh:.1f}" for r in results],
        "avg_dscr": [f"{r.avg_dscr:.2f}x" for r in results],
        "min_dscr": [f"{r.min_dscr:.2f}x" for r in results],
        "distribution_keur": [f"{r.total_distribution_keur:,}" for r in results],
        "tax_keur": [f"{r.total_tax_keur:,}" for r in results],
    }
