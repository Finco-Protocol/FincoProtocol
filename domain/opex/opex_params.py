"""OPEX parameters by technology.

Supports: Solar PV, Wind, BESS, Hybrid
Includes: fixed/variable O&M, insurance, land lease, grid fees, step changes.
"""
from dataclasses import dataclass, field
from typing import Optional


# =============================================================================
# SOLAR OPEX
# =============================================================================
@dataclass(frozen=True)
class SolarOpexParams:
    """Solar PV OPEX parameters."""
    # O&M costs
    om_fixed_eur_kw_year: float = 0.0  # 12-18 EUR/kW/year typical
    om_variable_eur_mwh: float = 0.0  # 0.5-1.5 EUR/MWh typical
    
    # Major maintenance
    inverter_replacement_keur: float = 0.0  # Y10-15 inverter replacement
    inverter_replacement_year: int = 12
    module_replacement_pct: float = 0.0  # % of CAPEX at Y20
    
    # Insurance (% of CAPEX annually)
    insurance_annual_pct: float = 0.005  # 0.5% of CAPEX/year
    
    # Land lease
    land_lease_annual_keur: float = 0.0
    
    # Grid fees
    grid_fees_annual_keur: float = 0.0
    
    # Other
    scada_monitoring_keur: float = 0.0
    legal_admin_keur: float = 0.0
    environmental_keur: float = 0.0
    security_keur: float = 0.0
    
    def annual_opex_keur(self, capacity_mw: float, generation_mwh: float, year: int) -> float:
        """Calculate annual OPEX.
        
        Args:
            capacity_mw: AC capacity in MW
            generation_mwh: Annual generation in MWh
            year: Operating year (1-based)
        
        Returns:
            Annual OPEX in kEUR
        """
        # Fixed O&M
        fixed = capacity_mw * 1000 * self.om_fixed_eur_kw_year / 1000  # Convert to kEUR
        
        # Variable O&M
        variable = generation_mwh * self.om_variable_eur_mwh / 1000
        
        # Major maintenance in replacement year
        maintenance = 0.0
        if year == self.inverter_replacement_year and self.inverter_replacement_keur > 0:
            maintenance = self.inverter_replacement_keur
        
        # Insurance
        # (Assume 750k EUR/MW for solar CAPEX)
        insurance = capacity_mw * 750 * self.insurance_annual_pct
        
        total = (fixed + variable + maintenance + insurance +
                self.land_lease_annual_keur + self.grid_fees_annual_keur +
                self.scada_monitoring_keur + self.legal_admin_keur +
                self.environmental_keur + self.security_keur)
        
        return total


# =============================================================================
# WIND OPEX
# =============================================================================
@dataclass(frozen=True)
class WindOpexParams:
    """Wind OPEX parameters."""
    # O&M costs (typically higher than solar due to turbine complexity)
    om_fixed_eur_kw_year: float = 0.0  # 30-50 EUR/kW/year (full service)
    om_variable_eur_mwh: float = 0.0  # 1-3 EUR/MWh typical
    
    # Major maintenance
    major_overhaul_keur: float = 0.0  # Y10 general overhaul
    blade_replacement_keur: float = 0.0  # Y15-20 blade replacement
    
    # Insurance (% of CAPEX)
    insurance_annual_pct: float = 0.007  # 0.7% of CAPEX/year (higher than solar)
    
    # Land (turbine sites need more land)
    land_lease_annual_keur: float = 0.0
    
    # Grid fees
    grid_fees_annual_keur: float = 0.0
    
    # Other
    scada_monitoring_keur: float = 0.0
    legal_admin_keur: float = 0.0
    environmental_keur: float = 0.0  # Bat/bird monitoring
    security_keur: float = 0.0
    
    def annual_opex_keur(self, capacity_mw: float, generation_mwh: float, year: int) -> float:
        """Calculate annual OPEX for wind."""
        fixed = capacity_mw * 1000 * self.om_fixed_eur_kw_year / 1000
        variable = generation_mwh * self.om_variable_eur_mwh / 1000
        
        maintenance = 0.0
        if year == 10 and self.major_overhaul_keur > 0:
            maintenance += self.major_overhaul_keur
        if year >= 15 and self.blade_replacement_keur > 0:
            maintenance += self.blade_replacement_keur
        
        # Insurance
        insurance = capacity_mw * 1100 * self.insurance_annual_pct  # ~1100k EUR/MW wind CAPEX
        
        total = (fixed + variable + maintenance + insurance +
                self.land_lease_annual_keur + self.grid_fees_annual_keur +
                self.scada_monitoring_keur + self.legal_admin_keur +
                self.environmental_keur + self.security_keur)
        
        return total


# =============================================================================
# BESS OPEX
# =============================================================================
@dataclass(frozen=True)
class BESSOpexParams:
    """BESS OPEX parameters."""
    # O&M (typically per kWh or per kW)
    om_eur_kwh_year: float = 0.0  # 4-8 EUR/kWh/year
    om_eur_kw_year: float = 0.0  # Additional per kW (Balance of System)
    
    # Augmentation (capacity补充, not full replacement)
    augmentation_keur: float = 0.0  # Y8-10 capacity augmentation
    augmentation_year: int = 8
    
    # Battery replacement (if not doing augmentation)
    battery_replacement_cost_pct: float = 0.70  # 70% of original CAPEX at replacement
    battery_replacement_year: int = 10
    
    # Insurance (% of CAPEX)
    insurance_annual_pct: float = 0.008  # 0.8% (higher risk)
    
    # Grid fees (BESS has different fee structure)
    grid_fees_annual_keur: float = 0.0
    
    # Other
    monitoring_keur: float = 0.0
    legal_admin_keur: float = 0.0
    
    def annual_opex_keur(self, capacity_mwh: float, capacity_kw: float, year: int) -> float:
        """Calculate annual OPEX for BESS."""
        # O&M per energy and power
        om_energy = capacity_mwh * self.om_eur_kwh_year / 1000  # Convert to kEUR
        om_power = capacity_kw * self.om_eur_kw_year / 1000
        
        # Augmentation or replacement
        augmentation = 0.0
        if year == self.augmentation_year and self.augmentation_keur > 0:
            augmentation = self.augmentation_keur
        
        # Insurance
        insurance = capacity_mwh * 200 * self.insurance_annual_pct  # ~200k EUR/MWh BESS CAPEX
        
        total = om_energy + om_power + augmentation + insurance + self.grid_fees_annual_keur + self.monitoring_keur + self.legal_admin_keur
        
        return total


# =============================================================================
# COMMON OPEX (all technologies)
# =============================================================================
@dataclass(frozen=True)
class CommonOpexParams:
    """Common OPEX costs across all technologies."""
    # Property tax (annual % of CAPEX)
    property_tax_pct: float = 0.001  # 0.1% of CAPEX/year
    
    # Asset management / admin
    asset_management_keur: float = 0.0  # Annual asset management fee
    accounting_audit_keur: float = 0.0  # Annual audit and accounting
    
    # Corporate overhead allocation
    corporate_overhead_keur: float = 0.0


# =============================================================================
# OPEX CONFIG (generic wrapper)
# =============================================================================
@dataclass(frozen=True)
class OpexParams:
    """Generic OPEX configuration for all technology types.
    
    Use annual_opex_keur() method to calculate total OPEX for given year.
    """
    technology: str = "solar"  # "solar" | "wind" | "bess" | "solar_bess" | "wind_bess"
    
    # Technology-specific
    solar: Optional[SolarOpexParams] = None
    wind: Optional[WindOpexParams] = None
    bess: Optional[BESSOpexParams] = None
    
    # Common
    common: CommonOpexParams = field(default_factory=CommonOpexParams)
    
    # Escalation (general inflation for OPEX)
    om_inflation: float = 0.02  # 2% annual escalation
    insurance_inflation: float = 0.015  # 1.5% (lower than O&M)
    land_lease_escalation: float = 0.0  # Often fixed by contract
    
    # Step changes: tuple of (year, category, new_amount_keur)
    step_changes: tuple = field(default_factory=lambda: ())
    
    def annual_opex_keur(
        self, 
        capacity_mw: float = 0.0,
        capacity_mwh: float = 0.0,
        generation_mwh: float = 0.0,
        year: int = 1
    ) -> float:
        """Calculate total annual OPEX.
        
        Args:
            capacity_mw: AC capacity (for solar/wind)
            capacity_mwh: Energy capacity (for BESS)
            generation_mwh: Annual generation
            year: Operating year (1-based)
        
        Returns:
            Total annual OPEX in kEUR
        """
        # Check step changes first
        for step_year, category, new_amount in self.step_changes:
            if year == step_year:
                return new_amount
        
        # Base OPEX from technology
        base_opex = 0.0
        
        if self.technology == "solar" and self.solar:
            base_opex = self.solar.annual_opex_keur(capacity_mw, generation_mwh, year)
        elif self.technology == "wind" and self.wind:
            base_opex = self.wind.annual_opex_keur(capacity_mw, generation_mwh, year)
        elif self.technology == "bess" and self.bess:
            base_opex = self.bess.annual_opex_keur(capacity_mwh, capacity_mw, year)
        
        # Apply escalation
        escalation_factor = (1 + self.om_inflation) ** (year - 1)
        base_opex *= escalation_factor
        
        # Common costs
        common_opex = (
            self.common.property_tax_pct * capacity_mw * 750 +  # Approx CAPEX
            self.common.asset_management_keur +
            self.common.accounting_audit_keur +
            self.common.corporate_overhead_keur
        )
        
        return base_opex + common_opex
    
    def validate_configuration(self) -> list[str]:
        """Validate OPEX configuration."""
        errors = []
        
        if self.om_inflation < 0 or self.om_inflation > 0.1:
            errors.append("O&M inflation should be between 0% and 10%")
        
        if self.technology not in ("solar", "wind", "bess", "solar_bess", "wind_bess"):
            errors.append(f"Unknown technology: {self.technology}")
        
        # Check step changes format
        for step in self.step_changes:
            if len(step) != 3:
                errors.append(f"Step change should be (year, category, amount): {step}")
            elif step[0] < 1 or step[0] > 50:
                errors.append(f"Step change year should be 1-50: {step[0]}")
        
        return errors
    
    # Factory methods
    @staticmethod
    def create_solar_defaults(capacity_mw: float = 75.0) -> "OpexParams":
        """Create default solar OPEX."""
        solar = SolarOpexParams(
            om_fixed_eur_kw_year=15.0,
            om_variable_eur_mwh=0.8,
            inverter_replacement_keur=800.0,
            inverter_replacement_year=12,
            insurance_annual_pct=0.005,
            land_lease_annual_keur=150.0,
            grid_fees_annual_keur=80.0,
            scada_monitoring_keur=50.0,
            legal_admin_keur=30.0,
        )
        
        return OpexParams(technology="solar", solar=solar)
    
    @staticmethod
    def create_wind_defaults(capacity_mw: float = 50.0) -> "OpexParams":
        """Create default wind OPEX."""
        wind = WindOpexParams(
            om_fixed_eur_kw_year=40.0,
            om_variable_eur_mwh=1.5,
            major_overhaul_keur=600.0,
            blade_replacement_keur=1200.0,
            insurance_annual_pct=0.007,
            land_lease_annual_keur=200.0,
            grid_fees_annual_keur=100.0,
            scada_monitoring_keur=60.0,
            legal_admin_keur=40.0,
            environmental_keur=50.0,  # Bat/bird monitoring
        )
        
        return OpexParams(technology="wind", wind=wind)
    
    @staticmethod
    def create_bess_defaults(power_mw: float = 20.0, duration_hours: float = 2.0) -> "OpexParams":
        """Create default BESS OPEX."""
        bess = BESSOpexParams(
            om_eur_kwh_year=6.0,
            om_eur_kw_year=20.0,
            augmentation_keur=500.0,
            augmentation_year=8,
            insurance_annual_pct=0.008,
        )
        
        return OpexParams(technology="bess", bess=bess)


__all__ = [
    "SolarOpexParams",
    "WindOpexParams",
    "BESSOpexParams",
    "CommonOpexParams",
    "OpexParams",
]