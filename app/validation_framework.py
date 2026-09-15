"""Validation framework for FINCO Protocol — run cases and compare results."""

from typing import Any

def run_validation_case(inputs, expected_outputs=None, project_type: str = "Solar"):
    """Run a project and return structured KPI/waterfall/DSCR summary.
    
    Args:
        inputs: ProjectInputs (from project factories)
        expected_outputs: optional dict of expected KPIs for comparison
        project_type: "Solar" or "Wind"
        
    Returns:
        dict with keys: kpis, waterfall_summary, dscr_summary
    """
    from app.ui_runner import run_demo_project
    
    result = run_demo_project(project_type, project_inputs_override=inputs)
    if result.result is None:
        return {"error": "Model run failed"}
    
    r = result.result
    return {
        "kpis": {
            "project_irr": r.project_irr,
            "equity_irr": r.equity_irr,
            "total_revenue_keur": r.total_revenue_keur,
            "total_ebitda_keur": r.total_ebitda_keur,
            "total_tax_keur": r.total_tax_keur,
            "total_senior_ds_keur": r.total_senior_ds_keur,
        },
        "waterfall_summary": {
            "period_count": len(r.periods),
            "min_dscr": r.min_dscr,
            "avg_dscr": r.avg_dscr,
            "project_irr": r.project_irr,
        },
        "dscr_summary": {
            "target_dscr": r.target_dscr,
            "actual_min_dscr": r.actual_min_dscr,
            "actual_avg_dscr": r.actual_avg_dscr,
            "deviation": r.actual_min_dscr - r.target_dscr,
        }
    }


def compare_to_expected(actual: dict, expected: dict, tolerance: float = 0.01):
    """Compare actual results to expected using tolerance-based matching.
    
    Args:
        actual: dict of actual KPI values
        expected: dict of expected KPI values
        tolerance: relative tolerance for comparison (default 1%)
        
    Returns:
        dict with keys: matches (bool), deviations (list), pct_differences (list)
    """
    deviations = []
    pct_differences = []
    
    for key in expected:
        if key not in actual:
            deviations.append(f"{key}: missing in actual")
            pct_differences.append(None)
            continue
        actual_val = actual[key]
        expected_val = expected[key]
        if actual_val is None or expected_val is None:
            deviations.append(f"{key}: None value")
            pct_differences.append(None)
            continue
        if expected_val == 0:
            if actual_val == 0:
                continue
            deviations.append(f"{key}: expected 0, got {actual_val}")
            pct_differences.append(None)
            continue
        pct_diff = abs(actual_val - expected_val) / abs(expected_val)
        pct_differences.append(pct_diff)
        if pct_diff > tolerance:
            deviations.append(f"{key}: diff {pct_diff:.2%} (actual={actual_val}, expected={expected_val})")
    
    matches = len(deviations) == 0
    return {"matches": matches, "deviations": deviations, "pct_differences": pct_differences}


def generate_validation_report(case_name: str, actual: dict, expected: dict | None = None) -> dict:
    """Generate a structured validation report.
    
    Args:
        case_name: identifier for this validation case
        actual: actual results dict
        expected: optional expected results for comparison
        
    Returns:
        dict with: case_name, timestamp, kpis, deviations, summary, printable
    """
    from datetime import datetime, timezone
    
    report = {
        "case_name": case_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kpis": actual,
        "deviations": [],
        "summary": "PASS",
        "printable": "",
    }
    
    if expected is not None:
        comparison = compare_to_expected(actual, expected)
        report["deviations"] = comparison["deviations"]
        report["matches"] = comparison["matches"]
        if not comparison["matches"]:
            report["summary"] = "FAIL"
    
    # Build printable summary
    lines = [
        f"Validation Report: {case_name}",
        f"Timestamp: {report['timestamp']}",
        f"Summary: {report['summary']}",
        "",
        "KPIs:",
    ]
    for k, v in report.get("kpis", {}).items():
        lines.append(f"  {k}: {v}")
    
    if report["deviations"]:
        lines.append("")
        lines.append("Deviations:")
        for d in report["deviations"]:
            lines.append(f"  - {d}")
    
    report["printable"] = "\n".join(lines)
    return report