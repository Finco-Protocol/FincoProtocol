"""P1.3 — per-vertical validation contracts.

Each contract is a tuple of ValidationMetric entries describing what is
claimed for a vertical and how it maps to the P1.1 registry authority.

Contracts are declarative: they are consumed by the runner which executes
the actual assertions via BUNDLE_EXTRACTORS.

AUTHORITY MAPPINGS (corrected in Correction A)
-----------------------------------------------
total_capex_keur  → registry key 'total_capex'
                    source: finco_core/inputs/_models.py::CapexInputs.total_capex
                    formula: total_capex_before_idc + idc_keur

senior_debt_keur  → registry key 'initial_senior_debt'
                    source: financial_engine/financing/project.py::run_project_financing_model
                    field: final_senior_commitment_keur

NOT valid:
  total_capex_keur → ebitda         (ebitda is revenue minus opex, not CAPEX)
  total_capex_keur → revenue_*      (revenue is a flow, not capital expenditure)
  senior_debt_keur → senior_debt_service  (debt_service is a per-period flow, not a commitment)
"""
from __future__ import annotations

from app.model_validation import ValidationMetric

SOLAR_CONTRACT: tuple[ValidationMetric, ...] = (
    ValidationMetric(
        name="Solar project_irr ≈ 11.56%",
        registry_key="project_irr",
        tolerance_policy="irr_abs",
        vertical="solar",
        category="kpi_pinning",
        extractor_key="project_irr",
        expected_value=0.11557,
        assertion="irr in [0.1146, 0.1166]",
    ),
    ValidationMetric(
        name="Solar equity_irr ≈ 50.47%",
        registry_key="equity_irr",
        tolerance_policy="irr_abs",
        vertical="solar",
        category="kpi_pinning",
        extractor_key="equity_irr",
        expected_value=0.50468,
        assertion="irr in [0.5037, 0.5057]",
    ),
    ValidationMetric(
        name="Solar total_sponsor_xirr ≈ 17.90%",
        registry_key="total_sponsor_xirr",
        tolerance_policy="xirr_abs",
        vertical="solar",
        category="kpi_pinning",
        extractor_key="total_sponsor_xirr",
        expected_value=0.17896,
        assertion="xirr in [0.1770, 0.1810]",
    ),
    ValidationMetric(
        name="Solar senior_debt_keur = 24,750",
        registry_key="initial_senior_debt",
        tolerance_policy="money_keur_rel",
        vertical="solar",
        category="kpi_pinning",
        extractor_key="senior_debt_keur",
        expected_value=24_750.0,
        assertion="senior_debt_keur == 24750.0",
    ),
    ValidationMetric(
        name="Solar total_capex_keur = 33,000",
        registry_key="total_capex",
        tolerance_policy="money_keur_rel",
        vertical="solar",
        category="kpi_pinning",
        extractor_key="total_capex_keur",
        expected_value=33_000.0,
        assertion="total_capex_keur == 33000.0",
    ),
)

WIND_CONTRACT: tuple[ValidationMetric, ...] = (
    ValidationMetric(
        name="Wind project_irr ≈ 13.72%",
        registry_key="project_irr",
        tolerance_policy="irr_abs",
        vertical="wind",
        category="kpi_pinning",
        extractor_key="project_irr",
        expected_value=0.13722,
        assertion="irr in [0.1362, 0.1382]",
    ),
    ValidationMetric(
        name="Wind equity_irr ≈ 74.60%",
        registry_key="equity_irr",
        tolerance_policy="irr_abs",
        vertical="wind",
        category="kpi_pinning",
        extractor_key="equity_irr",
        expected_value=0.74595,
        assertion="irr in [0.7450, 0.7470]",
    ),
    ValidationMetric(
        name="Wind total_sponsor_xirr ≈ 20.79%",
        registry_key="total_sponsor_xirr",
        tolerance_policy="xirr_abs",
        vertical="wind",
        category="kpi_pinning",
        extractor_key="total_sponsor_xirr",
        expected_value=0.20794,
        assertion="xirr in [0.2059, 0.2099]",
    ),
    ValidationMetric(
        name="Wind senior_debt_keur = 32,250",
        registry_key="initial_senior_debt",
        tolerance_policy="money_keur_rel",
        vertical="wind",
        category="kpi_pinning",
        extractor_key="senior_debt_keur",
        expected_value=32_250.0,
        assertion="senior_debt_keur == 32250.0",
    ),
    ValidationMetric(
        name="Wind total_capex_keur = 43,000",
        registry_key="total_capex",
        tolerance_policy="money_keur_rel",
        vertical="wind",
        category="kpi_pinning",
        extractor_key="total_capex_keur",
        expected_value=43_000.0,
        assertion="total_capex_keur == 43000.0",
    ),
)

DATA_CENTER_CONTRACT: tuple[ValidationMetric, ...] = (
    ValidationMetric(
        name="DC project_irr ≈ 2.29% (distressed reference)",
        registry_key="project_irr",
        tolerance_policy="distressed_irr_abs",
        vertical="data_center",
        category="kpi_pinning",
        extractor_key="project_irr",
        expected_value=0.02293,
        assertion="irr in [0.0179, 0.0279]",
        notes=(
            "Synthetic distressed reference: 55% Y1 occupancy, 175 EUR/kW/month. "
            "Sub-bankable by design (see DC_A3_ECONOMICS_DISTRESSED_DOCUMENTED). "
            "Uses distressed_irr_abs tolerance (0.5 pp) due to wider solver convergence."
        ),
    ),
    ValidationMetric(
        name="DC total_capex_keur = 200,000",
        registry_key="total_capex",
        tolerance_policy="money_keur_rel",
        vertical="data_center",
        category="kpi_pinning",
        extractor_key="total_capex_keur",
        expected_value=200_000.0,
        assertion="total_capex_keur == 200000.0",
    ),
    ValidationMetric(
        name="DC senior_debt_keur ≈ 80,437",
        registry_key="initial_senior_debt",
        tolerance_policy="dc_senior_debt_abs",
        vertical="data_center",
        category="kpi_pinning",
        extractor_key="senior_debt_keur",
        expected_value=80_436.5,
        assertion="senior_debt_keur ≈ 80437",
        notes=(
            "DC senior debt is DSCR-sculpted (not gearing-capped). "
            "Uses dc_senior_debt_abs tolerance (500 kEUR) for sculpting precision."
        ),
    ),
)

EV_CHARGING_CONTRACT: tuple[ValidationMetric, ...] = (
    ValidationMetric(
        name="EV project_irr ≈ 14.68%",
        registry_key="project_irr",
        tolerance_policy="distressed_irr_abs",
        vertical="ev_charging",
        category="kpi_pinning",
        extractor_key="project_irr",
        expected_value=0.14679,
        assertion="irr in [0.1418, 0.1518]",
        notes="Uses distressed_irr_abs tolerance (0.5 pp) for EV convergence margin.",
    ),
    ValidationMetric(
        name="EV equity_irr ≈ 39.54%",
        registry_key="equity_irr",
        tolerance_policy="distressed_irr_abs",
        vertical="ev_charging",
        category="kpi_pinning",
        extractor_key="equity_irr",
        expected_value=0.39541,
        assertion="irr in [0.3904, 0.4004]",
        notes="Uses distressed_irr_abs tolerance (0.5 pp) for EV convergence margin.",
    ),
    ValidationMetric(
        name="EV total_capex_keur = 9,000",
        registry_key="total_capex",
        tolerance_policy="money_keur_rel",
        vertical="ev_charging",
        category="kpi_pinning",
        extractor_key="total_capex_keur",
        expected_value=9_000.0,
        assertion="total_capex_keur == 9000.0",
    ),
    ValidationMetric(
        name="EV senior_debt_keur = 5,850",
        registry_key="initial_senior_debt",
        tolerance_policy="money_keur_rel",
        vertical="ev_charging",
        category="kpi_pinning",
        extractor_key="senior_debt_keur",
        expected_value=5_850.0,
        assertion="senior_debt_keur == 5850.0",
    ),
)

ALL_CONTRACTS: dict[str, tuple[ValidationMetric, ...]] = {
    "solar": SOLAR_CONTRACT,
    "wind": WIND_CONTRACT,
    "data_center": DATA_CENTER_CONTRACT,
    "ev_charging": EV_CHARGING_CONTRACT,
}
