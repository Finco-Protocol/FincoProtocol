"""Sensitivity analysis — one-factor and multi-factor sensitivity tables.

Enterprise Implementation Brief §4.2
Supports: Tornado chart, spider table, DCF sensitivity tables.
"""
from dataclasses import dataclass
from typing import Callable, Any

import numpy as np


@dataclass(frozen=True)
class SensitivityResult:
    """Result of a sensitivity analysis run."""
    variable: str
    base_value: float
    min_value: float
    max_value: float
    step_count: int
    outputs: dict[str, list[float]]  # output_name → list of values


def run_one_way_sensitivity(
    base_value: float,
    variable_name: str,
    min_val: float,
    max_val: float,
    steps: int,
    compute_fn: Callable[[float], dict[str, float]],
) -> SensitivityResult:
    """Run one-way sensitivity analysis on a single variable.
    
    Args:
        base_value: Base case value of the variable
        variable_name: Name of the variable (for display)
        min_val: Minimum value for sensitivity range
        max_val: Maximum value for sensitivity range
        steps: Number of steps between min and max
        compute_fn: Function that takes variable value, returns dict of outputs.
                   Example: compute_fn(tariff) -> {"IRR": 0.091, "NPV": 29193}
    
    Returns:
        SensitivityResult with all output values at each step
    """
    values = np.linspace(min_val, max_val, steps).tolist()
    
    outputs = {}
    for val in values:
        try:
            result = compute_fn(val)
            for k, v in result.items():
                if k not in outputs:
                    outputs[k] = []
                outputs[k].append(v)
        except Exception:
            # If computation fails for a step, record None
            for k in outputs:
                outputs[k].append(None)
    
    return SensitivityResult(
        variable=variable_name,
        base_value=base_value,
        min_value=min_val,
        max_value=max_val,
        step_count=steps,
        outputs=outputs,
    )


def build_tornado_data(
    results: list[SensitivityResult],
    output_key: str,
    base_output: float,
) -> list[dict]:
    """Build tornado chart data from one-way sensitivities.
    
    Args:
        results: List of SensitivityResult from run_one_way_sensitivity
        output_key: Which output to show (e.g., "IRR", "NPV")
        base_output: Base case value of the output (for centering)
    
    Returns:
        List of dicts for tornado chart rendering:
        [{"name": "PPA Tariff", "low": -0.5, "high": +0.8}, ...]
        Sorted by impact magnitude (largest first).
    """
    tornado_items = []
    
    for res in results:
        if output_key not in res.outputs:
            continue
        
        vals = res.outputs[output_key]
        if not vals or any(v is None for v in vals):
            continue
        
        # Impact = deviation from base output
        low_impact = min(vals) - base_output
        high_impact = max(vals) - base_output
        
        # Choose the larger absolute impact for sorting
        impact_magnitude = max(abs(low_impact), abs(high_impact))
        
        tornado_items.append({
            "name": res.variable,
            "low": low_impact,
            "high": high_impact,
            "magnitude": impact_magnitude,
            "base": res.base_value,
            "min": res.min_value,
            "max": res.max_value,
        })
    
    # Sort by magnitude (descending — most impactful first)
    tornado_items.sort(key=lambda x: x["magnitude"], reverse=True)
    
    return tornado_items


def build_spider_table(
    results: list[SensitivityResult],
    output_key: str,
) -> list[dict]:
    """Build spider/sensitivity table for multi-factor comparison.
    
    Args:
        results: List of SensitivityResult
        output_key: Which output to track
    
    Returns:
        Table with rows = scenarios, cols = variables
    """
    if not results:
        return []
    
    # Row for each variable
    table = []
    for res in results:
        if output_key not in res.outputs:
            continue
        
        vals = res.outputs[output_key]
        if not vals:
            continue
        
        # Format values as percentages or absolute
        formatted = [f"{v:.2%}" if abs(v) < 10 else f"{v:,.0f}" for v in vals]
        
        row = {
            "Variable": res.variable,
            **{f"V{i+1}": v for i, v in enumerate(formatted)},
        }
        table.append(row)
    
    return table


def run_two_way_sensitivity(
    var1_vals: list[float],
    var2_vals: list[float],
    var1_name: str,
    var2_name: str,
    compute_fn: Callable[[float, float], float],
) -> list[list[float]]:
    """Run two-way sensitivity (DCF-style matrix).
    
    Args:
        var1_vals: Values for variable 1 (rows)
        var2_vals: Values for variable 2 (columns)
        var1_name: Name of variable 1
        var2_name: Name of variable 2
        compute_fn: Function(var1, var2) -> output_value
    
    Returns:
        Matrix of output values [row][col] where rows = var1, cols = var2
    """
    matrix = []
    for v1 in var1_vals:
        row = []
        for v2 in var2_vals:
            try:
                row.append(compute_fn(v1, v2))
            except Exception:
                row.append(None)
        matrix.append(row)
    
    return matrix


def format_tornado_for_plotly(tornado_items: list[dict]) -> dict:
    """Format tornado data for Plotly bar chart.
    
    Returns:
        dict with 'y' (variable names), 'x' (impacts), 'xaxis' labels
    """
    names = [item["name"] for item in tornado_items]
    
    # Separate low and high bars
    low_vals = [-item["low"] for item in tornado_items]  # Negate for left bars
    high_vals = [item["high"] for item in tornado_items]
    
    return {
        "names": names,
        "low": low_vals,
        "high": high_vals,
        "base": [item["base"] for item in tornado_items],
    }
