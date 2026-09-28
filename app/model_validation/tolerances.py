"""P1.3 Institutional Validation — centralized tolerance policy.

All numerical comparisons in the validation suite use the tolerances
defined here.  No test hard-codes a tolerance; every check references
one of these named keys so the policy can be updated in one place.

POLICY RATIONALE
----------------
irr_abs              0.001  — 0.1 pp absolute; dates are exact so IRR
                              should agree within solver precision.
money_keur_rel       1e-4   — 0.01% relative; kEUR values agree to sub-EUR.
ratio_abs            0.002  — ratios (DSCR etc.); matches solver precision.
balance_check_abs    0.10   — 100 EUR; balance check field may accumulate
                              two-decimal rounding over many periods.
debt_rollforward_abs 1.0    — 1 kEUR; serialized debt schedule is rounded
                              to 2 dp, so per-step error ≤ 0.005 kEUR.
xlsx_vs_runtime_rel  1e-3   — 0.1% relative; XLSX read-back vs runtime KPI.
xirr_abs             0.002  — 0.2 pp; XIRR solver convergence + rounding.
distressed_irr_abs   0.005  — 0.5 pp; distressed/high-leverage verticals
                              (DC synthetic reference, EV Charging) where
                              solver convergence margin is wider.
dc_senior_debt_abs   500.0  — 500 kEUR absolute; DC senior debt is DSCR-
                              sculpted to many decimal places; 500 kEUR
                              tolerance accommodates sculpting precision.
"""
from __future__ import annotations

TOLERANCES: dict[str, float] = {
    "irr_abs": 0.001,
    "money_keur_rel": 1e-4,
    "ratio_abs": 0.002,
    "balance_check_abs": 0.10,
    "debt_rollforward_abs": 1.0,
    "xlsx_vs_runtime_rel": 1e-3,
    "xirr_abs": 0.002,
    "distressed_irr_abs": 0.005,
    "dc_senior_debt_abs": 500.0,
}
