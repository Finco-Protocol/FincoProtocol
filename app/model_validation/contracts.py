"""P1.3 — per-vertical validation contracts.

Each contract is a tuple of ValidationMetric entries describing what is
claimed for a vertical and how it maps to the P1.1 registry authority.
Contracts are declarative: they are consumed by the runner which executes
the actual assertions.

The contracts serve as a machine-readable claim register: any metric
listed here MUST correspond to a key in METRIC_REGISTRY (P1.1 authority).
"""
from __future__ import annotations

from app.model_validation import ValidationMetric

SOLAR_CONTRACT: tuple[ValidationMetric, ...] = (
    ValidationMetric(
        name="Solar project_irr ≈ 11.56%",
        registry_key="project_irr",
        tolerance_policy="irr_abs",
        vertical="solar",
        assertion="irr in [0.1146, 0.1166]",
    ),
    ValidationMetric(
        name="Solar equity_irr ≈ 50.47%",
        registry_key="equity_irr",
        tolerance_policy="irr_abs",
        vertical="solar",
        assertion="irr in [0.5037, 0.5057]",
    ),
    ValidationMetric(
        name="Solar total_sponsor_xirr ≈ 17.90%",
        registry_key="total_sponsor_xirr",
        tolerance_policy="xirr_abs",
        vertical="solar",
        assertion="xirr in [0.1770, 0.1810]",
    ),
    ValidationMetric(
        name="Solar senior_debt_keur = 24,750",
        registry_key="senior_debt_service",
        tolerance_policy="money_keur_rel",
        vertical="solar",
        assertion="senior_debt_keur == 24750.0",
    ),
    ValidationMetric(
        name="Solar total_capex_keur = 33,000",
        registry_key="ebitda",
        tolerance_policy="money_keur_rel",
        vertical="solar",
        assertion="total_capex_keur == 33000.0",
    ),
)

WIND_CONTRACT: tuple[ValidationMetric, ...] = (
    ValidationMetric(
        name="Wind project_irr ≈ 13.72%",
        registry_key="project_irr",
        tolerance_policy="irr_abs",
        vertical="wind",
        assertion="irr in [0.1362, 0.1382]",
    ),
    ValidationMetric(
        name="Wind equity_irr ≈ 74.60%",
        registry_key="equity_irr",
        tolerance_policy="irr_abs",
        vertical="wind",
        assertion="irr in [0.7450, 0.7470]",
    ),
    ValidationMetric(
        name="Wind total_sponsor_xirr ≈ 20.79%",
        registry_key="total_sponsor_xirr",
        tolerance_policy="xirr_abs",
        vertical="wind",
        assertion="xirr in [0.2059, 0.2099]",
    ),
    ValidationMetric(
        name="Wind senior_debt_keur = 32,250",
        registry_key="senior_debt_service",
        tolerance_policy="money_keur_rel",
        vertical="wind",
        assertion="senior_debt_keur == 32250.0",
    ),
    ValidationMetric(
        name="Wind total_capex_keur = 43,000",
        registry_key="ebitda",
        tolerance_policy="money_keur_rel",
        vertical="wind",
        assertion="total_capex_keur == 43000.0",
    ),
)

DATA_CENTER_CONTRACT: tuple[ValidationMetric, ...] = (
    ValidationMetric(
        name="DC project_irr ≈ 2.29% (distressed reference)",
        registry_key="project_irr",
        tolerance_policy="irr_abs",
        vertical="data_center",
        assertion="irr in [0.0179, 0.0279]",
        notes=(
            "Synthetic distressed reference: 55% Y1 occupancy, 175 EUR/kW/month. "
            "Sub-bankable by design (see DC_A3_ECONOMICS_DISTRESSED_DOCUMENTED)."
        ),
    ),
    ValidationMetric(
        name="DC total_capex_keur = 200,000",
        registry_key="revenue_data_center",
        tolerance_policy="money_keur_rel",
        vertical="data_center",
        assertion="total_capex_keur == 200000.0",
    ),
    ValidationMetric(
        name="DC senior_debt_keur ≈ 80,437",
        registry_key="senior_debt_service",
        tolerance_policy="money_keur_rel",
        vertical="data_center",
        assertion="senior_debt_keur ≈ 80437",
    ),
)

EV_CHARGING_CONTRACT: tuple[ValidationMetric, ...] = (
    ValidationMetric(
        name="EV project_irr ≈ 14.68%",
        registry_key="project_irr",
        tolerance_policy="irr_abs",
        vertical="ev_charging",
        assertion="irr in [0.1418, 0.1518]",
    ),
    ValidationMetric(
        name="EV equity_irr ≈ 39.54%",
        registry_key="equity_irr",
        tolerance_policy="irr_abs",
        vertical="ev_charging",
        assertion="irr in [0.3904, 0.4004]",
    ),
    ValidationMetric(
        name="EV total_capex_keur = 9,000",
        registry_key="revenue_ev_charging",
        tolerance_policy="money_keur_rel",
        vertical="ev_charging",
        assertion="total_capex_keur == 9000.0",
    ),
    ValidationMetric(
        name="EV senior_debt_keur = 5,850",
        registry_key="senior_debt_service",
        tolerance_policy="money_keur_rel",
        vertical="ev_charging",
        assertion="senior_debt_keur == 5850.0",
    ),
)

ALL_CONTRACTS: dict[str, tuple[ValidationMetric, ...]] = {
    "solar": SOLAR_CONTRACT,
    "wind": WIND_CONTRACT,
    "data_center": DATA_CENTER_CONTRACT,
    "ev_charging": EV_CHARGING_CONTRACT,
}
