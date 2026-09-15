"""Synthetic regulatory assumptions for public reference markets."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RegulatoryParams:
    jurisdiction: str = "XA"
    permitting_timeline_months: int = 24
    grid_connection_timeline_months: int = 18
    construction_permit_timeline_months: int = 6
    grid_connection_type: str = "distribution"
    grid_congestion_risk: str = "medium"
    grid_upgrade_required: bool = False
    grid_upgrade_cost_keur: float = 0.0
    mandatory_curtailment_pct: float = 0.0
    curtailment_compensation: bool = True
    curtailment_compensation_pct: float = 1.0
    balancing_responsibility: str = "aggregator"
    balancing_zone: str = "GENERIC_ZONE"
    balancing_cost_pct_of_revenue: float = 0.025
    rec_enabled: bool = True
    rec_price_eur_mwh: float = 0.5
    rec_policy_stability: str = "stable"
    carbon_credit_enabled: bool = False
    carbon_price_eur_tco2: float = 0.0
    capital_grant_pct: float = 0.0
    capital_grant_keur: float = 0.0
    production_subsidy_eur_mwh: float = 0.0
    subsidy_term_years: int = 0
    grid_access_fee_keur_per_mw: float = 0.0
    transmission_fee_eur_mwh: float = 0.0
    distribution_fee_eur_mwh: float = 0.0
    environmental_impact_assessment_required: bool = True
    eia_timeline_months: int = 12
    biodiversity_offset_cost_keur: float = 0.0
    decommissioning_bond_keur: float = 0.0

    def validate_configuration(self) -> list[str]:
        errors = []
        if not 0 <= self.mandatory_curtailment_pct <= 1:
            errors.append("Mandatory curtailment must be between 0 and 1")
        if not 0 <= self.curtailment_compensation_pct <= 1:
            errors.append("Curtailment compensation must be between 0 and 1")
        if not 0 <= self.capital_grant_pct <= 1:
            errors.append("Capital grant % must be between 0 and 1")
        return errors

    def curtailment_cost_mwh(self, energy_mwh: float, price_eur_mwh: float) -> float:
        lost_energy = energy_mwh * self.mandatory_curtailment_pct
        lost_revenue = lost_energy * price_eur_mwh
        if self.curtailment_compensation:
            return lost_revenue * (1 - self.curtailment_compensation_pct) / 1000
        return lost_revenue / 1000

    def rec_revenue_keur(self, generation_mwh: float) -> float:
        if not self.rec_enabled:
            return 0.0
        return generation_mwh * self.rec_price_eur_mwh / 1000

    @staticmethod
    def create_market_a_defaults() -> "RegulatoryParams":
        return RegulatoryParams(jurisdiction="XA", balancing_zone="GENERIC_A")

    @staticmethod
    def create_market_b_defaults() -> "RegulatoryParams":
        return RegulatoryParams(
            jurisdiction="XB",
            balancing_zone="GENERIC_B",
            grid_congestion_risk="high",
            balancing_responsibility="generator",
            balancing_cost_pct_of_revenue=0.035,
        )

    @staticmethod
    def create_market_c_defaults() -> "RegulatoryParams":
        return RegulatoryParams(
            jurisdiction="XC",
            balancing_zone="GENERIC_C",
            grid_congestion_risk="low",
            balancing_cost_pct_of_revenue=0.020,
        )

    @staticmethod
    def create_for_jurisdiction(jurisdiction: str) -> "RegulatoryParams":
        code = (jurisdiction or "XA").upper()
        if code == "XB":
            return RegulatoryParams.create_market_b_defaults()
        if code == "XC":
            return RegulatoryParams.create_market_c_defaults()
        return RegulatoryParams.create_market_a_defaults()


__all__ = ["RegulatoryParams"]
