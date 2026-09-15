"""Technology configuration - supports Solar PV, Wind, BESS, and Hybrid projects.

This module provides generički konfiguracijski objekt koji zamjenjuje Generic Solar Reference-specifičan TechnicalParams.
Supports 6 technology types: solar, wind, bess, solar_bess, wind_bess, agrivoltaic
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TechnologyType(Enum):
    """Supported technology types for project finance model."""
    SOLAR = "solar"
    WIND = "wind"
    BESS = "bess"
    SOLAR_BESS = "solar_bess"
    WIND_BESS = "wind_bess"
    AGRIVOLTAIC = "agrivoltaic"


class BatteryChemistry(Enum):
    """Battery chemistry types."""
    LFP = "LFP"
    NMC = "NMC"
    NAS = "NaS"
    FLOW = "flow"


class PPAType(Enum):
    """PPA structure types."""
    PAY_AS_PRODUCED = "pay_as_produced"
    BASELOAD = "baseload"
    SHAPED = "shaped"
    SYNTHETIC = "synthetic"


class AmortizationType(Enum):
    """Debt amortization types."""
    SCULPTED = "sculpted"
    ANNUITY = "annuity"
    STRAIGHT_LINE = "straight_line"
    BULLET = "bullet"


# =============================================================================
# SOLAR TECHNICAL PARAMS
# =============================================================================
@dataclass(frozen=True)
class SolarTechnicalParams:
    """Technical parameters for Solar PV projects.
    
    Covers standalone solar and solar component of hybrid projects.
    All values should be validated against benchmark ranges.
    """
    # Capacity
    capacity_dc_mwp: float = 0.0  # DC capacity (MWp)
    capacity_ac_mw: float = 0.0   # AC capacity (MW) — DC/AC ratio derived
    
    # Yield scenarios (hours at full load)
    operating_hours_p50: float = 0.0  # P50 yield hours
    operating_hours_p90_1y: float = 0.0  # P90-1y (single year exceedance)
    operating_hours_p90_10y: float = 0.0  # P90-10y (10-year average)
    operating_hours_p99_1y: float = 0.0  # P99-1y (extreme year)
    
    # Degradation
    pv_degradation_annual: float = 0.004  # 0.4% annual degradation
    
    # System losses
    bifaciality_factor: float = 0.0  # 0 for monofacial, 0.05-0.15 for bifacial
    tracker_type: str = "fixed_tilt"  # "fixed_tilt" | "single_axis" | "dual_axis"
    tracker_yield_gain: float = 0.0  # Yield gain from trackers vs fixed (%)

    soiling_loss_pct: float = 0.02  # Soiling losses (2% for Central Europe)
    shading_loss_pct: float = 0.01  # Near + far shading (1%)
    mismatch_loss_pct: float = 0.015  # Mismatch losses (1.5%)
    dc_wiring_loss_pct: float = 0.02  # DC cable losses (2%)
    ac_wiring_loss_pct: float = 0.01  # AC cable losses (1%)
    transformer_loss_pct: float = 0.005  # Transformer losses (0.5%)
    inverter_efficiency: float = 0.98  # Inverter efficiency (98%)
    
    # Performance ratio (aggregate of all losses)
    performance_ratio_p50: float = 0.82  # PR for P50 scenario (0.78-0.85 typical)
    
    # Curtailment
    grid_curtailment_pct: float = 0.0  # Grid operator curtailment
    self_consumption_pct: float = 0.0  # Self-consumption deduction
    
    # Agrivoltaics (optional)
    agrivoltaic_enabled: bool = False
    agrivoltaic_yield_reduction: float = 0.0  # Reduction due to panels above crops
    agrivoltaic_land_rental_premium: float = 0.0  # Premium on land lease


# =============================================================================
# WIND TECHNICAL PARAMS
# =============================================================================
@dataclass(frozen=True)
class WindTechnicalParams:
    """Technical parameters for onshore wind projects.
    
    Validates turbine configuration and wake losses.
    """
    # Capacity
    capacity_mw: float = 0.0  # Installed capacity (MW)
    num_turbines: int = 0  # Number of turbines
    turbine_rating_mw: float = 0.0  # Rating per turbine (MW)
    hub_height_m: float = 0.0  # Hub height (m)
    rotor_diameter_m: float = 0.0  # Rotor diameter (m)
    
    # Yield scenarios
    operating_hours_p50: float = 0.0
    operating_hours_p90_1y: float = 0.0
    operating_hours_p90_10y: float = 0.0
    operating_hours_p99_1y: float = 0.0
    
    # Wind-specific losses
    wake_loss_pct: float = 0.05  # Wake effect (3-8% typical)
    availability_mechanical: float = 0.97  # Mechanical availability (97%)
    availability_grid: float = 0.99  # Grid availability (99%)
    hysteresis_loss_pct: float = 0.01  # High/low wind cut-off (1%)
    icing_loss_pct: float = 0.0  # Icing losses (for mountain sites)
    curtailment_noise_pct: float = 0.0  # Noise curtailment (night hours)
    curtailment_bat_pct: float = 0.0  # Bat protection curtailment
    curtailment_grid_pct: float = 0.0  # Grid operator curtailment
    
    # Degradation
    wind_degradation_annual: float = 0.003  # 0.2-0.5% annual
    
    # Power curve (optional - for advanced analysis)
    wind_speed_mean_ms: float = 0.0  # Mean wind speed at hub height
    weibull_k: float = 2.0  # Weibull shape parameter
    weibull_c: float = 0.0  # Weibull scale parameter


# =============================================================================
# BESS TECHNICAL PARAMS
# =============================================================================
@dataclass(frozen=True)
class BESSTechnicalParams:
    """Technical parameters for Battery Energy Storage Systems.
    
    Supports standalone BESS and BESS as hybrid component.
    Includes degradation modeling and replacement scheduling.
    """
    # Capacity
    energy_capacity_mwh: float = 0.0  # Energy capacity (MWh)
    power_capacity_mw: float = 0.0  # Power capacity (MW)
    duration_hours: float = 1.0  # Discharge duration (1h, 2h, 4h, 8h)
    
    # Technology
    battery_chemistry: str = "LFP"  # "LFP" | "NMC" | "NaS" | "flow"
    
    # Efficiency
    roundtrip_efficiency: float = 0.88  # RTE (85-92% for LFP)
    auxiliary_consumption_pct: float = 0.01  # Parasitic consumption (1%)
    
    # Degradation
    calendar_degradation_annual: float = 0.015  # 1.5% per year
    cycle_degradation_per_cycle: float = 0.0001  # Per cycle (0.01%)
    eol_capacity_threshold: float = 0.80  # End of life at 80% original capacity
    
    # Operating parameters
    soc_min_pct: float = 0.10  # Min state of charge (10%)
    soc_max_pct: float = 0.95  # Max state of charge (95%)
    annual_cycles_target: int = 365  # Target cycles per year
    
    # Battery replacement
    replacement_year: int = 10  # Year of replacement (Y10-Y12 typical)
    replacement_cost_pct_of_capex: float = 0.70  # 70% of original CAPEX
    
    # Reserve capacity (for ancillary services)
    reserve_capacity_pct: float = 0.0  # % reserved for frequency response


# =============================================================================
# HYBRID CONFIG
# =============================================================================
@dataclass(frozen=True)
class HybridConfig:
    """Configuration for hybrid projects (Solar+BESS or Wind+BESS).
    
    Defines how multiple technologies interact in a hybrid project.
    """
    technology_primary: str = "solar"  # "solar" | "wind"
    bess_enabled: bool = False
    shared_grid_connection: bool = False  # Shared grid connection
    grid_connection_mw: float = 0.0  # Grid connection capacity (MW) - often bottleneck
    
    # Clipping (when solar+wind+BESS exceeds grid capacity)
    clipping_loss_pct: float = 0.0  # Estimated annual clipping %
    
    # BESS operation strategy in hybrid
    bess_strategy: str = "peak_shaving"  # "peak_shaving" | "arbitrage" | "firm_power" | "mixed"
    firm_power_target_mw: float = 0.0  # Target firm power (for "firm_power" strategy)


# =============================================================================
# TECHNOLOGY CONFIG (generic wrapper)
# =============================================================================
@dataclass(frozen=True)
class TechnologyConfig:
    """Generic technology configuration for project finance model.
    
    Replaces Generic Solar Reference-specific TechnicalParams with generički konfiguracijski objekt.
    Supports: Solar PV, Wind (onshore), BESS, Solar+BESS, Wind+BESS, Agrivoltaics
    
    Usage:
        config = TechnologyConfig(
            technology_type=TechnologyType.SOLAR,
            solar=SolarTechnicalParams(...)
        )
        total_mw = config.total_capacity_mw()
        gen_mwh = config.annual_generation_mwh(year=1, scenario="P50")
    """
    technology_type: str = "solar"  # "solar" | "wind" | "bess" | "solar_bess" | "wind_bess" | "agrivoltaic"
    
    # Components (optional - None for non-relevant technologies)
    solar: Optional[SolarTechnicalParams] = None
    wind: Optional[WindTechnicalParams] = None
    bess: Optional[BESSTechnicalParams] = None
    hybrid: Optional[HybridConfig] = None
    
    def total_capacity_mw(self) -> float:
        """Total AC capacity of the project (MW).
        
        For hybrid: returns AC capacity of primary technology.
        BESS contributes MW but doesn't count toward "capacity" in traditional sense.
        """
        if self.technology_type == "solar" and self.solar:
            return self.solar.capacity_ac_mw
        elif self.technology_type == "wind" and self.wind:
            return self.wind.capacity_mw
        elif self.technology_type in ("solar_bess", "wind_bess", "agrivoltaic") and self.solar:
            return self.solar.capacity_ac_mw
        return 0.0
    
    def total_dc_capacity_mwp(self) -> float:
        """Total DC capacity for solar projects (MWp)."""
        if self.solar:
            return self.solar.capacity_dc_mwp
        return 0.0
    
    def annual_generation_mwh(self, year: int, scenario: str = "P50") -> float:
        """Annual energy generation for the given year and scenario.
        
        Args:
            year: 1-based year index (1=Y1 operation, 2=Y2, etc.)
            scenario: "P50" | "P90-1y" | "P90-10y" | "P99-1y"
        
        Returns:
            Generation in MWh for that year
        """
        if self.technology_type == "solar" and self.solar:
            return self._solar_generation(year, scenario)
        elif self.technology_type == "wind" and self.wind:
            return self._wind_generation(year, scenario)
        elif self.technology_type == "bess" and self.bess:
            return self._bess_generation(year, scenario)
        elif self.technology_type in ("solar_bess", "wind_bess", "agrivoltaic"):
            # Hybrid: generation from primary technology
            if self.solar:
                return self._solar_generation(year, scenario)
            elif self.wind:
                return self._wind_generation(year, scenario)
        
        return 0.0
    
    def _solar_generation(self, year: int, scenario: str) -> float:
        """Calculate solar generation for given year/scenario."""
        if not self.solar:
            return 0.0
        
        # Get base hours based on scenario
        hours = self._get_solar_hours(scenario)
        
        # Apply degradation: generation = base * (1-deg)^(year-1)
        degradation_factor = (1 - self.solar.pv_degradation_annual) ** (year - 1)
        
        # Apply curtailment
        curtailment_factor = 1 - self.solar.grid_curtailment_pct - self.solar.self_consumption_pct
        
        # Agrivoltaic reduction
        agrivoltaic_factor = 1.0
        if self.solar.agrivoltaic_enabled:
            agrivoltaic_factor = 1 - self.solar.agrivoltaic_yield_reduction
        
        # Calculate generation: capacity * hours * PR * degradation * curtailment * agrivoltaic
        gen = (self.solar.capacity_ac_mw * hours * 
               self.solar.performance_ratio_p50 * 
               degradation_factor * 
               curtailment_factor * 
               agrivoltaic_factor)
        
        return max(0.0, gen)
    
    def _wind_generation(self, year: int, scenario: str) -> float:
        """Calculate wind generation for given year/scenario."""
        if not self.wind:
            return 0.0
        
        hours = self._get_wind_hours(scenario)
        
        # Degradation
        degradation_factor = (1 - self.wind.wind_degradation_annual) ** (year - 1)
        
        # Availability factors
        avail_factor = self.wind.availability_mechanical * self.wind.availability_grid
        
        # Curtailment total
        curtailment = (self.wind.curtailment_noise_pct + 
                      self.wind.curtailment_bat_pct + 
                      self.wind.curtailment_grid_pct)
        
        # Calculate generation
        gen = (self.wind.capacity_mw * hours * 
               avail_factor * 
               (1 - self.wind.wake_loss_pct) * 
               (1 - self.wind.hysteresis_loss_pct) * 
               (1 - self.wind.icing_loss_pct) * 
               (1 - curtailment) * 
               degradation_factor)
        
        return max(0.0, gen)
    
    def _bess_generation(self, year: int, scenario: str) -> float:
        """Calculate BESS available energy (not purely generation - it's dispatch).
        
        For BESS, annual generation = power * hours * cycles * efficiency.
        This is dispatchable energy, not renewably produced.
        """
        if not self.bess:
            return 0.0
        
        # Calendar degradation
        calendar_deg = (1 - self.bess.calendar_degradation_annual) ** (year - 1)
        
        # Effective capacity after degradation
        effective_capacity = self.bess.energy_capacity_mwh * calendar_deg
        
        # Reserve deduction
        available_capacity = effective_capacity * (1 - self.bess.reserve_capacity_pct)
        
        # Annual cycles
        annual_cycles = self.bess.annual_cycles_target
        
        # Available energy = capacity * cycles * roundtrip_efficiency
        # But cycles might reduce as battery degrades
        energy = available_capacity * annual_cycles * self.bess.roundtrip_efficiency
        
        # Replacement handling - if replacement_year reached, capacity restores
        if self.bess.replacement_year and year >= self.bess.replacement_year:
            # After replacement, capacity is back to original (less degradation)
            replacement_deg = (1 - self.bess.calendar_degradation_annual) ** (year - self.bess.replacement_year)
            energy = (self.bess.energy_capacity_mwh * replacement_deg * 
                     annual_cycles * self.bess.roundtrip_efficiency * 
                     (1 - self.bess.reserve_capacity_pct))
        
        return max(0.0, energy)
    
    def _get_solar_hours(self, scenario: str) -> float:
        """Get solar operating hours for scenario."""
        if not self.solar:
            return 0.0
        
        mapping = {
            "P50": self.solar.operating_hours_p50,
            "P90-1y": self.solar.operating_hours_p90_1y,
            "P90-10y": self.solar.operating_hours_p90_10y,
            "P99-1y": self.solar.operating_hours_p99_1y,
        }
        return mapping.get(scenario, self.solar.operating_hours_p50)
    
    def _get_wind_hours(self, scenario: str) -> float:
        """Get wind operating hours for scenario."""
        if not self.wind:
            return 0.0
        
        mapping = {
            "P50": self.wind.operating_hours_p50,
            "P90-1y": self.wind.operating_hours_p90_1y,
            "P90-10y": self.wind.operating_hours_p90_10y,
            "P99-1y": self.wind.operating_hours_p99_1y,
        }
        return mapping.get(scenario, self.wind.operating_hours_p50)
    
    def validate_configuration(self) -> list[str]:
        """Validate technology configuration consistency.
        
        Returns:
            List of validation error messages. Empty list = valid.
        """
        errors = []
        
        # Solar validation
        if self.technology_type in ("solar", "solar_bess", "agrivoltaic"):
            if not self.solar:
                errors.append("Solar technology requires SolarTechnicalParams")
            elif self.solar.capacity_ac_mw <= 0:
                errors.append("Solar capacity_ac_mw must be > 0")
            elif self.solar.capacity_dc_mwp <= 0:
                errors.append("Solar capacity_dc_mwp must be > 0")
            elif self.solar.capacity_dc_mwp < self.solar.capacity_ac_mw:
                errors.append("Solar DC capacity should be >= AC capacity (DC/AC ratio > 1)")
            elif self.solar.operating_hours_p50 <= 0:
                errors.append("Solar operating_hours_p50 must be > 0")
        
        # Wind validation
        if self.technology_type in ("wind", "wind_bess"):
            if not self.wind:
                errors.append("Wind technology requires WindTechnicalParams")
            elif self.wind.capacity_mw <= 0:
                errors.append("Wind capacity_mw must be > 0")
            elif self.wind.num_turbines <= 0:
                errors.append("Wind num_turbines must be > 0")
            elif self.wind.operating_hours_p50 <= 0:
                errors.append("Wind operating_hours_p50 must be > 0")
        
        # BESS validation
        if self.technology_type in ("bess", "solar_bess", "wind_bess"):
            if not self.bess:
                errors.append("BESS technology requires BESSTechnicalParams")
            elif self.bess.power_capacity_mw <= 0:
                errors.append("BESS power_capacity_mw must be > 0")
            elif self.bess.energy_capacity_mwh <= 0:
                errors.append("BESS energy_capacity_mwh must be > 0")
            elif self.bess.duration_hours <= 0:
                errors.append("BESS duration_hours must be > 0")
        
        # Hybrid validation
        if self.technology_type in ("solar_bess", "wind_bess"):
            if self.bess_enabled and not self.bess:
                errors.append("Hybrid with BESS requires BESSTechnicalParams")
        
        return errors
    
    @staticmethod
    def create_solar_defaults(capacity_mw: float = 75.0, jurisdiction: str = "XA") -> "TechnologyConfig":
        """Create default solar technology config (Generic Solar Reference-style).
        
        Args:
            capacity_mw: AC capacity in MW
            jurisdiction: Country code for benchmark adjustments
        
        Returns:
            TechnologyConfig with solar parameters
        """
        solar = SolarTechnicalParams(
            capacity_dc_mwp=capacity_mw * 1.2,  # DC/AC ratio ~1.2
            capacity_ac_mw=capacity_mw,
            operating_hours_p50=1494.0,
            operating_hours_p90_1y=1410.0,
            operating_hours_p90_10y=1410.0,
            operating_hours_p99_1y=1200.0,
            pv_degradation_annual=0.004,
            bifaciality_factor=0.0,
            tracker_type="fixed_tilt",
            tracker_yield_gain=0.0,
            soiling_loss_pct=0.02,
            shading_loss_pct=0.01,
            mismatch_loss_pct=0.015,
            dc_wiring_loss_pct=0.02,
            ac_wiring_loss_pct=0.01,
            transformer_loss_pct=0.005,
            inverter_efficiency=0.98,
            performance_ratio_p50=0.82,
            grid_curtailment_pct=0.0,
            self_consumption_pct=0.0,
        )
        
        return TechnologyConfig(
            technology_type="solar",
            solar=solar,
        )
    
    @staticmethod
    def create_wind_defaults(capacity_mw: float = 50.0, jurisdiction: str = "XA") -> "TechnologyConfig":
        """Create default wind technology config.
        
        Args:
            capacity_mw: Installed capacity in MW
            jurisdiction: Country code
        
        Returns:
            TechnologyConfig with wind parameters
        """
        # Estimate turbine count
        turbine_rating = 4.0  # Assume 4MW turbines
        num_turbines = max(1, int(capacity_mw / turbine_rating))
        
        wind = WindTechnicalParams(
            capacity_mw=capacity_mw,
            num_turbines=num_turbines,
            turbine_rating_mw=turbine_rating,
            hub_height_m=100.0,
            rotor_diameter_m=130.0,
            operating_hours_p50=2200.0,  # Wind typically 2000-3000 hrs
            operating_hours_p90_1y=2000.0,
            operating_hours_p90_10y=2000.0,
            operating_hours_p99_1y=1600.0,
            wake_loss_pct=0.05,
            availability_mechanical=0.97,
            availability_grid=0.99,
        )
        
        return TechnologyConfig(
            technology_type="wind",
            wind=wind,
        )
    
    @staticmethod
    def create_bess_defaults(power_mw: float = 20.0, duration_hours: float = 2.0, jurisdiction: str = "XA") -> "TechnologyConfig":
        """Create default BESS technology config.
        
        Args:
            power_mw: Power capacity in MW
            duration_hours: Storage duration in hours
            jurisdiction: Country code
        
        Returns:
            TechnologyConfig with BESS parameters
        """
        bess = BESSTechnicalParams(
            energy_capacity_mwh=power_mw * duration_hours,
            power_capacity_mw=power_mw,
            duration_hours=duration_hours,
            battery_chemistry="LFP",
            roundtrip_efficiency=0.88,
            auxiliary_consumption_pct=0.01,
            calendar_degradation_annual=0.015,
            cycle_degradation_per_cycle=0.0001,
            eol_capacity_threshold=0.80,
            soc_min_pct=0.10,
            soc_max_pct=0.95,
            annual_cycles_target=365,
            replacement_year=10,
            replacement_cost_pct_of_capex=0.70,
        )
        
        return TechnologyConfig(
            technology_type="bess",
            bess=bess,
        )