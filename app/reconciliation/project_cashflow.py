"""Project cashflow bridge helper."""
from typing import Any, Optional


def build_project_cf_rows(
    result: Any,
    project_inputs: Optional[Any] = None,
) -> list[dict]:
    """Build project cashflow bridge rows from a DemoResult or WaterfallResult.

    Returns list of dicts with columns:
        period, date, revenue, opex, ebitda, depreciation,
        unlevered_tax, project_free_cf, cumulative_project_cf

    Project free CF = EBITDA - unlevered_tax
    Unlevered tax = corporate_rate * max(0, EBITDA - depreciation)

    This matches the Project IRR tax basis (financing-independent).
    When project_inputs is provided, uses its corporate tax rate.
    Falls back to waterfall period tax_keur if inputs unavailable.
    """
    wf = None
    if hasattr(result, "result") and hasattr(result, "waterfall_result"):
        wf = result.waterfall_result
    elif hasattr(result, "periods"):
        wf = result

    if wf is None:
        return []

    periods = wf.periods if hasattr(wf, "periods") else []
    if not periods:
        return []

    # Resolve tax rate from project_inputs
    tax_rate = 0.0
    if project_inputs is not None:
        tax_params = getattr(project_inputs, "tax", None)
        if tax_params is not None:
            tax_rate = getattr(tax_params, "corporate_rate", 0.0)

    rows = []
    cumulative = 0.0

    for p in periods:
        if p.is_operation:
            rev = p.revenue_keur
            opex = p.opex_keur
            ebitda = p.ebitda_keur
            dep = p.depreciation_keur

            # Unlevered tax: tax_rate * max(0, EBITDA - depreciation)
            if tax_rate > 0:
                unlev_tax = tax_rate * max(0.0, ebitda - dep)
            else:
                unlev_tax = p.tax_keur  # fallback to levered tax if no rate available

            pcf = ebitda - unlev_tax
            cumulative += pcf
        else:
            rev = 0.0
            opex = 0.0
            ebitda = 0.0
            dep = 0.0
            unlev_tax = 0.0
            pcf = p.cf_after_tax_keur
            cumulative += pcf

        rows.append({
            "period": p.period,
            "date": p.date,
            "revenue": round(rev, 1),
            "opex": round(opex, 1),
            "ebitda": round(ebitda, 1),
            "depreciation": round(dep, 1),
            "unlevered_tax": round(unlev_tax, 1),
            "project_free_cf": round(pcf, 1),
            "cumulative_project_cf": round(cumulative, 1),
        })

    return rows