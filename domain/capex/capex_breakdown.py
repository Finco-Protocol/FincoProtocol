"""CAPEX breakdown by technology - generic parametrized structure.

Supports: Solar PV, Wind, BESS, Hybrid
Includes benchmark validation and EUR/kWp, EUR/MW, EUR/kWh metrics.
"""
from dataclasses import dataclass, field
from typing import Optional


# =============================================================================
# CAPEX BREAKDOWN PER TECHNOLOGY
# =============================================================================
@dataclass(frozen=True)
class SolarCapexBreakdown:
    """Solar PV CAPEX breakdown in EUR/kWp or EUR/MWp.
    
    All values should be validated against benchmark ranges:
    - Generic Market A: 700-850k EUR/MWp total
    - Generic Market B: 680-820k EUR/MWp
    - Generic Market C: 650-800k EUR/MWp
    - Generic Market D: 720-870k EUR/MWp
    - Generic Market E: 640-780k EUR/MWp
    """
    # Module costs (EUR/kWp)
    modules_eur_kwp: float = 0.0  # 180-280 EUR/kWp typical
    
    # BoS costs (EUR/kWp)
    inverters_eur_kwp: float = 0.0  # 50-80 EUR/kWp
    mounting_eur_kwp: float = 0.0  # 40-80 EUR/kWp (fixed) or 100-150 (tracker)
    dc_electrical_eur_kwp: float = 0.0  # 30-50 EUR/kWp
    ac_electrical_eur_kwp: float = 0.0  # 40-60 EUR/kWp
    
    # Construction and commissioning
    civil_works_eur_kwp: float = 0.0  # 20-40 EUR/kWp
    installation_eur_kwp: float = 0.0  # 30-50 EUR/kWp
    
    @property
    def total_eur_kwp(self) -> float:
        """Total CAPEX in EUR/kWp."""
        return (self.modules_eur_kwp + self.inverters_eur_kwp + 
                self.mounting_eur_kwp + self.dc_electrical_eur_kwp +
                self.ac_electrical_eur_kwp + self.civil_works_eur_kwp +
                self.installation_eur_kwp)
    
    def total_eur_mwp(self) -> float:
        """Total CAPEX in EUR/MWp."""
        return self.total_eur_kwp * 1000
    
    def validate_benchmark(self, jurisdiction: str = "XA") -> list[str]:
        """Validate against benchmark ranges.
        
        Returns list of warning messages if outside benchmarks.
        """
        warnings = []
        total = self.total_eur_mwp
        
        benchmarks = {
            "XA": (700000, 850000),
            "XB": (680000, 820000),
            "XC": (650000, 800000),
            "XD": (720000, 870000),
            "XE": (640000, 780000),
        }
        
        if jurisdiction in benchmarks:
            low, high = benchmarks[jurisdiction]
            total_val = self.total_eur_mwp()
            if total_val < low:
                warnings.append(f"Solar CAPEX ({total_val/1000:.0f}k EUR/MWp) is below {jurisdiction} benchmark ({low/1000:.0f}-{high/1000:.0f}k EUR/MWp)")
            elif total_val > high:
                warnings.append(f"Solar CAPEX ({total_val/1000:.0f}k EUR/MWp) exceeds {jurisdiction} benchmark ({low/1000:.0f}-{high/1000:.0f}k EUR/MWp)")
        
        return warnings


@dataclass(frozen=True)
class WindCapexBreakdown:
    """Wind CAPEX breakdown in EUR/kW or EUR/MW.
    
    Benchmark: 1.0-1.4M EUR/MW total (varies by size and location)
    """
    # Turbine supply (EUR/kW)
    turbine_eur_kw: float = 0.0  # 900-1300 EUR/kW typical
    
    # Balance of Plant (EUR/kW)
    civil_works_eur_kw: float = 0.0  # 150-250 EUR/kW (foundations, roads)
    electrical_eur_kw: float = 0.0  # 100-150 EUR/kW (cables, trafo, SCADA)
    transport_install_eur_kw: float = 0.0  # 50-100 EUR/kW
    
    @property
    def total_eur_kw(self) -> float:
        """Total CAPEX in EUR/kW."""
        return (self.turbine_eur_kw + self.civil_works_eur_kw +
                self.electrical_eur_kw + self.transport_install_eur_kw)
    
    def total_eur_mw(self) -> float:
        """Total CAPEX in EUR/MW."""
        return self.total_eur_kw * 1000
    
    def validate_benchmark(self, jurisdiction: str = "XA") -> list[str]:
        """Validate against benchmark ranges."""
        warnings = []
        total = self.total_eur_mw
        
        benchmarks = {
            "XA": (1100000, 1400000),
            "XB": (1000000, 1300000),
            "XC": (1000000, 1250000),
            "XD": (1150000, 1400000),
            "XE": (950000, 1200000),
        }
        
        if jurisdiction in benchmarks:
            low, high = benchmarks[jurisdiction]
            total_val = self.total_eur_mw()
            if total_val < low:
                warnings.append(f"Wind CAPEX ({total_val/1000:.0f}k EUR/MW) is below {jurisdiction} benchmark")
            elif total_val > high:
                warnings.append(f"Wind CAPEX ({total_val/1000:.0f}k EUR/MW) exceeds {jurisdiction} benchmark")
        
        return warnings


@dataclass(frozen=True)
class BESSCapexBreakdown:
    """BESS CAPEX breakdown in EUR/kWh.
    
    Benchmark: 180-260k EUR/MWh total for LFP chemistry
    """
    # Cell/module costs (EUR/kWh)
    cells_eur_kwh: float = 0.0  # 100-180 EUR/kWh for LFP
    
    # Power conversion (EUR/kW)
    pcs_eur_kw: float = 0.0  # 50-100 EUR/kW
    
    # Balance of System (EUR/kWh)
    bos_eur_kwh: float = 0.0  # 20-40 EUR/kWh (containers, HVAC, BMS)
    
    # Installation (EUR/kWh)
    installation_eur_kwh: float = 0.0  # 10-30 EUR/kWh
    
    @property
    def total_eur_kwh(self) -> float:
        """Total CAPEX in EUR/kWh."""
        return self.cells_eur_kwh + self.bos_eur_kwh + self.installation_eur_kwh
    
    def total_eur_mwh(self) -> float:
        """Total CAPEX in EUR/MWh."""
        return self.total_eur_kwh * 1000
    
    @property
    def cost_per_kw(self) -> float:
        """Cost per kW of power capacity (for P20 equipment)."""
        duration_hours = 2.0  # Assume 2h duration for cost per kW
        return (self.cells_eur_kwh * duration_hours + self.pcs_eur_kw + 
                self.bos_eur_kwh * duration_hours + self.installation_eur_kwh * duration_hours)
    
    def validate_benchmark(self, jurisdiction: str = "XA") -> list[str]:
        """Validate against benchmark ranges."""
        warnings = []
        total = self.total_eur_mwh
        
        benchmarks = {
            "XA": (180000, 260000),
            "XB": (170000, 250000),
            "XC": (160000, 240000),
            "XD": (185000, 265000),
            "XE": (155000, 235000),
        }
        
        if jurisdiction in benchmarks:
            low, high = benchmarks[jurisdiction]
            total_val = self.total_eur_mwh()
            if total_val < low:
                warnings.append(f"BESS CAPEX ({total_val/1000:.0f}k EUR/MWh) is below {jurisdiction} benchmark")
            elif total_val > high:
                warnings.append(f"BESS CAPEX ({total_val/1000:.0f}k EUR/MWh) exceeds {jurisdiction} benchmark")
        
        return warnings


@dataclass(frozen=True)
class CommonCapexBreakdown:
    """Common costs across all technologies (EUR).
    
    These are typically independent of MW/MWh size.
    """
    # Grid connection (EUR) - varies enormously by location
    grid_connection_keur: float = 0.0  # 500-5000 kEUR typical
    
    # Substation (EUR)
    substation_keur: float = 0.0  # 300-1500 kEUR
    
    # Land (EUR)
    land_acquisition_keur: float = 0.0
    land_lease_annual_keur: float = 0.0  # Annual, not one-time
    
    # Permits and EIA (EUR)
    permitting_keur: float = 0.0  # 100-500 kEUR
    eia_keur: float = 0.0  # Environmental impact assessment
    
    # Project development (EUR)
    project_development_keur: float = 0.0  # 200-800 kEUR
    
    # EPC margin (% of hard CAPEX)
    epc_margin_pct: float = 0.10  # 10% typical
    
    # Owner's engineer (EUR)
    owners_engineer_keur: float = 0.0  # 100-300 kEUR
    
    # Insurance during construction (EUR)
    insurance_construction_keur: float = 0.0  # 200-500 kEUR
    
    # Legal and financial advisors (EUR)
    legal_financial_keur: float = 0.0  # 300-700 kEUR
    
    # Contingency (% of hard CAPEX)
    contingency_pct: float = 0.05  # 3-7% typical
    
    def total_common_keur(self) -> float:
        """Total common costs in kEUR."""
        return (self.grid_connection_keur + self.substation_keur +
                self.land_acquisition_keur + self.permitting_keur +
                self.eia_keur + self.project_development_keur +
                self.owners_engineer_keur + self.insurance_construction_keur +
                self.legal_financial_keur)


@dataclass(frozen=True)
class FinancialCapexBreakdown:
    """Financial costs during construction.
    
    These are computed, not direct inputs.
    """
    # Interest during construction
    idc_keur: float = 0.0  # Computed iteratively
    
    # Commitment fee on undrawn debt
    commitment_fee_keur: float = 0.0
    
    # Arrangement and structuring fees
    arrangement_fee_keur: float = 0.0
    structuring_fee_keur: float = 0.0
    
    # Reserve accounts funded at financial close
    dsra_funding_keur: float = 0.0
    mra_funding_keur: float = 0.0
    
    # VAT during construction
    vat_costs_keur: float = 0.0
    
    @property
    def total_financial_keur(self) -> float:
        """Total financial costs in kEUR."""
        return (self.idc_keur + self.commitment_fee_keur +
                self.arrangement_fee_keur + self.structuring_fee_keur +
                self.dsra_funding_keur + self.mra_funding_keur + self.vat_costs_keur)


# =============================================================================
# COMBINED CAPEX STRUCTURE
# =============================================================================
@dataclass(frozen=True)
class CapexBreakdown:
    """Combined CAPEX structure for project finance.
    
    Aggregates technology-specific + common + financial costs.
    Provides total CAPEX calculation with benchmark validation.
    """
    technology: str = "solar"  # "solar" | "wind" | "bess" | "solar_bess" | "wind_bess"
    
    # Technology-specific
    solar: Optional[SolarCapexBreakdown] = None
    wind: Optional[WindCapexBreakdown] = None
    bess: Optional[BESSCapexBreakdown] = None
    
    # Common costs
    common: CommonCapexBreakdown = field(default_factory=CommonCapexBreakdown)
    
    # Financial costs (computed)
    financial: FinancialCapexBreakdown = field(default_factory=FinancialCapexBreakdown)
    
    # Capacity for normalization
    capacity_mw: float = 0.0  # AC capacity for solar/wind
    capacity_mwh: float = 0.0  # Energy capacity for BESS
    
    def hard_capex_keur(self) -> float:
        """Total hard CAPEX (equipment + construction)."""
        total = self.common.total_common_keur()
        
        # Add technology-specific
        if self.technology in ("solar", "solar_bess", "agrivoltaic") and self.solar:
            total += self.solar.total_eur_mwp() * self.capacity_mw / 1000
        
        if self.technology in ("wind", "wind_bess") and self.wind:
            total += self.wind.total_eur_mw() * self.capacity_mw / 1000
        
        if self.technology in ("bess", "solar_bess", "wind_bess") and self.bess:
            total += self.bess.total_eur_mwh() * self.capacity_mwh / 1000
        
        return total
    
    def epc_keur(self, hard_capex: float) -> float:
        """EPC contractor margin."""
        return hard_capex * self.common.epc_margin_pct
    
    def contingency_keur(self, hard_capex: float) -> float:
        """Contingency reserve."""
        return hard_capex * self.common.contingency_pct
    
    def total_capex_keur(self) -> float:
        """Total CAPEX including financial costs."""
        hard = self.hard_capex_keur()
        epc = self.epc_keur(hard)
        cont = self.contingency_keur(hard)
        fin = self.financial.total_financial_keur
        
        return hard + epc + cont + fin
    
    def validate_benchmark(self, jurisdiction: str = "XA") -> list[str]:
        """Validate all components against benchmarks."""
        warnings = []
        
        if self.technology in ("solar", "solar_bess", "agrivoltaic") and self.solar:
            warnings.extend(self.solar.validate_benchmark(jurisdiction))
        
        if self.technology in ("wind", "wind_bess") and self.wind:
            warnings.extend(self.wind.validate_benchmark(jurisdiction))
        
        if self.technology in ("bess", "solar_bess", "wind_bess") and self.bess:
            warnings.extend(self.bess.validate_benchmark(jurisdiction))
        
        return warnings
    
    # Factory methods
    @staticmethod
    def create_solar_defaults(capacity_mw: float = 75.0, jurisdiction: str = "XA") -> "CapexBreakdown":
        """Create default solar CAPEX breakdown."""
        solar = SolarCapexBreakdown(
            modules_eur_kwp=200.0,
            inverters_eur_kwp=65.0,
            mounting_eur_kwp=80.0,
            dc_electrical_eur_kwp=40.0,
            ac_electrical_eur_kwp=50.0,
            civil_works_eur_kwp=30.0,
            installation_eur_kwp=40.0,
        )
        
        common = CommonCapexBreakdown(
            grid_connection_keur=1500.0,
            substation_keur=500.0,
            land_acquisition_keur=300.0,
            permitting_keur=200.0,
            eia_keur=100.0,
            project_development_keur=400.0,
            epc_margin_pct=0.10,
            owners_engineer_keur=150.0,
            insurance_construction_keur=300.0,
            legal_financial_keur=400.0,
            contingency_pct=0.05,
        )
        
        return CapexBreakdown(
            technology="solar",
            solar=solar,
            common=common,
            capacity_mw=capacity_mw,
        )
    
    @staticmethod
    def create_wind_defaults(capacity_mw: float = 50.0, jurisdiction: str = "XA") -> "CapexBreakdown":
        """Create default wind CAPEX breakdown."""
        wind = WindCapexBreakdown(
            turbine_eur_kw=1100.0,
            civil_works_eur_kw=200.0,
            electrical_eur_kw=120.0,
            transport_install_eur_kw=80.0,
        )
        
        common = CommonCapexBreakdown(
            grid_connection_keur=2000.0,
            substation_keur=800.0,
            land_acquisition_keur=500.0,
            permitting_keur=300.0,
            eia_keur=200.0,
            project_development_keur=600.0,
            epc_margin_pct=0.08,
            owners_engineer_keur=200.0,
            insurance_construction_keur=400.0,
            legal_financial_keur=500.0,
            contingency_pct=0.05,
        )
        
        return CapexBreakdown(
            technology="wind",
            wind=wind,
            common=common,
            capacity_mw=capacity_mw,
        )
    
    @staticmethod
    def create_bess_defaults(power_mw: float = 20.0, duration_hours: float = 2.0, jurisdiction: str = "XA") -> "CapexBreakdown":
        """Create default BESS CAPEX breakdown."""
        bess = BESSCapexBreakdown(
            cells_eur_kwh=140.0,
            pcs_eur_kw=80.0,
            bos_eur_kwh=30.0,
            installation_eur_kwh=20.0,
        )
        
        common = CommonCapexBreakdown(
            grid_connection_keur=800.0,
            substation_keur=400.0,
            permitting_keur=150.0,
            project_development_keur=300.0,
            epc_margin_pct=0.08,
            owners_engineer_keur=100.0,
            insurance_construction_keur=200.0,
            legal_financial_keur=300.0,
            contingency_pct=0.05,
        )
        
        return CapexBreakdown(
            technology="bess",
            bess=bess,
            common=common,
            capacity_mw=power_mw,
            capacity_mwh=power_mw * duration_hours,
        )


__all__ = [
    "SolarCapexBreakdown",
    "WindCapexBreakdown",
    "BESSCapexBreakdown",
    "CommonCapexBreakdown",
    "FinancialCapexBreakdown",
    "CapexBreakdown",
]