"""Revenue configuration - supports PPA, Merchant, FiT, CfD, Capacity Market, BESS revenue.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional


# =============================================================================
# PPA PARAMS
# =============================================================================
@dataclass(frozen=True)
class PPAParams:
    """PPA (Power Purchase Agreement) parameters.
    
    Supports: pay_as_produced, baseload, shaped, synthetic PPA types.
    """
    ppa_enabled: bool = False
    ppa_counterparty: str = ""  # Counterparty name (for documentation)
    ppa_type: str = "pay_as_produced"  # "pay_as_produced" | "baseload" | "shaped" | "synthetic"
    
    # Price
    ppa_base_price_eur_mwh: float = 0.0  # Base price (EUR/MWh)
    ppa_price_index: float = 0.02  # Annual indexation (e.g., 0.02 = 2% HICP)
    ppa_price_floor: float = 0.0  # Minimum price (floor) - 0 if no floor
    ppa_price_cap: float = 0.0  # Maximum price (cap) - 0 if no cap
    
    # Duration and volume
    ppa_start_year: int = 1  # Start year (from COD)
    ppa_term_years: float = 0  # Contract duration in years (supports fractional, e.g. 12.5)
    ppa_volume_share: float = 1.0  # Share of production under PPA (0.0-1.0)
    ppa_shape_hours: tuple = ()  # Hours for shaped PPA (optional)
    
    # Balancing
    balancing_cost_pct: float = 0.025  # Balancing cost (% of revenue) - 2.5% typical
    imbalance_penalty_pct: float = 0.0  # Penalty above balancing cost
    
    # Credit risk
    offtaker_credit_rating: str = ""  # Rating for due diligence
    termination_fee_keur: float = 0.0  # Termination fee (force majeure/default)
    
    def price_at_year(self, year: int) -> float:
        """Return PPA price in year with indexation.
        
        Args:
            year: 1-based year index
        
        Returns:
            Price in EUR/MWh
        """
        price = self.ppa_base_price_eur_mwh * (1 + self.ppa_price_index) ** (year - 1)
        
        # Apply floor
        if self.ppa_price_floor > 0:
            price = max(price, self.ppa_price_floor)
        
        # Apply cap
        if self.ppa_price_cap > 0:
            price = min(price, self.ppa_price_cap)
        
        return price
    
    def is_active(self, year: int) -> bool:
        """Check if PPA is active in given year.
        
        Args:
            year: 1-based year index
        
        Returns:
            True if PPA covers this year
        """
        if not self.ppa_enabled:
            return False
        if self.ppa_term_years <= 0:
            return True  # No term limit
        return self.ppa_start_year <= year <= self.ppa_start_year + self.ppa_term_years - 1


# =============================================================================
# MERCHANT PARAMS
# =============================================================================
@dataclass(frozen=True)
class MerchantParams:
    """Merchant / spot market revenue parameters.
    
    Models revenue from selling electricity on spot market.
    """
    merchant_enabled: bool = False
    market_zone: str = "XA"  # Market zone: XA, XB, XC, XD, XE
    
    # Price curve
    base_price_eur_mwh: float = 0.0  # Base spot price (EUR/MWh)
    price_escalation_annual: float = 0.02  # Annual price growth (%)
    price_volatility_pct: float = 0.0  # Annual volatility (for Monte Carlo)
    price_cannibalization_pct: float = 0.0  # Price reduction from renewable penetration
    
    # Capture rate (renewables produce more when prices are lower)
    capture_rate_solar: float = 0.85  # Solar capture rate (% of baseload) - 75-90% typical
    capture_rate_wind: float = 0.90  # Wind capture rate - 80-95% typical
    capture_rate_bess: float = 1.0  # BESS capture rate (can charge/discharge at will)
    
    # Scenarios
    price_scenario: str = "base"  # "base" | "high" | "low" | "custom"
    custom_price_curve: tuple = ()  # Custom EUR/MWh by year (30 values)
    
    def price_at_year(self, year: int) -> float:
        """Return merchant price in year.
        
        Args:
            year: 1-based year index
        
        Returns:
            Price in EUR/MWh
        """
        if self.price_scenario == "custom" and self.custom_price_curve:
            idx = year - 1
            if idx < len(self.custom_price_curve):
                return self.custom_price_curve[idx]
        
        base = self.base_price_eur_mwh
        # Escalation
        price = base * (1 + self.price_escalation_annual) ** (year - 1)
        # Cannibalization (price reduction over time as renewables grow)
        cannibalization = self.price_cannibalization_pct * (year - 1)
        price *= (1 - cannibalization)
        
        return max(0.0, price)
    
    def capture_rate_for_tech(self, technology: str) -> float:
        """Get capture rate for technology type.
        
        Args:
            technology: "solar" | "wind" | "bess"
        
        Returns:
            Capture rate (0.0-1.0)
        """
        if technology == "solar":
            return self.capture_rate_solar
        elif technology == "wind":
            return self.capture_rate_wind
        elif technology == "bess":
            return self.capture_rate_bess
        return 0.85  # Default


# =============================================================================
# FEED-IN TARIFF PARAMS
# =============================================================================
@dataclass(frozen=True)
class FeedInTariffParams:
    """Feed-in Tariff / state premium parameters.
    
    Supports: fixed_fit, premium, net_metering
    """
    fit_enabled: bool = False
    fit_type: str = "fixed_fit"  # "fixed_fit" | "premium" | "net_metering"
    
    # Fixed FiT
    fit_price_eur_mwh: float = 0.0  # Guaranteed price (EUR/MWh)
    fit_term_years: int = 0  # Duration of guaranteed period
    fit_index: float = 0.0  # Indexation (many FiT are fixed = 0)
    
    # Premium (paid on top of spot price)
    premium_eur_mwh: float = 0.0  # Premium amount
    premium_cap_eur_mwh: float = 0.0  # Cap on total (spot + premium)
    premium_floor_eur_mwh: float = 0.0  # Floor on total (spot + premium)
    
    # Jurisdiction-specific
    fit_scheme: str = ""  # generic support-scheme identifier
    eligible_capacity_mw: float = 0.0  # Regulatory cap on eligible capacity
    annual_production_cap_mwh: float = 0.0  # Annual cap on supported production
    
    def is_active(self, year: int) -> bool:
        """Check if FiT is active in year."""
        if not self.fit_enabled:
            return False
        if self.fit_term_years <= 0:
            return True
        return 1 <= year <= self.fit_term_years
    
    def price_at_year(self, year: int, spot_price: float = 0.0) -> float:
        """Return FiT price in year.
        
        Args:
            year: 1-based year index
            spot_price: Current spot price (for premium calculation)
        
        Returns:
            Price in EUR/MWh
        """
        if self.fit_type == "fixed_fit":
            price = self.fit_price_eur_mwh * (1 + self.fit_index) ** (year - 1)
        elif self.fit_type == "premium":
            # Premium on top of spot
            price = spot_price + self.premium_eur_mwh
            if self.premium_cap_eur_mwh > 0:
                price = min(price, self.premium_cap_eur_mwh)
            if self.premium_floor_eur_mwh > 0:
                price = max(price, self.premium_floor_eur_mwh)
        else:
            price = 0.0
        
        return price


# =============================================================================
# CFD PARAMS
# =============================================================================
@dataclass(frozen=True)
class CfDParams:
    """Contract for Difference parameters.
    
    Two-way CfD: generator pays when spot > strike, receives when spot < strike.
    """
    cfd_enabled: bool = False
    strike_price_eur_mwh: float = 0.0  # Strike price (EUR/MWh)
    reference_price_type: str = "day_ahead"  # "day_ahead" | "intraday" | "monthly_average"
    cfd_term_years: int = 0
    cfd_volume_mwh_annual: float = 0.0  # Annual volume (can be < total production)
    
    # CfD mechanics
    two_way_cfd: bool = True  # True = both payment directions, False = one-way (in only)
    
    # Counterparty
    cfd_counterparty: str = "government"  # "government" | "utility" | "corporate"
    cfd_guarantee: str = ""  # Type of state guarantee
    
    def is_active(self, year: int) -> bool:
        """Check if CfD is active in year."""
        if not self.cfd_enabled:
            return False
        if self.cfd_term_years <= 0:
            return True
        return 1 <= year <= self.cfd_term_years
    
    def cfd_payment_at_year(self, year: int, spot_price: float) -> float:
        """Calculate net CfD payment for year.
        
        Returns:
            Positive = generator receives payment
            Negative = generator pays (when spot > strike in two-way CfD)
        """
        if not self.is_active(year):
            return 0.0
        
        # Volume limited to cfd_volume_mwh_annual
        volume = self.cfd_volume_mwh_annual if self.cfd_volume_mwh_annual > 0 else float('inf')
        
        if spot_price > self.strike_price_eur_mwh:
            # Generator pays difference (outpayment)
            payment = -(spot_price - self.strike_price_eur_mwh) * volume
        else:
            # Generator receives difference (inpayment)
            payment = (self.strike_price_eur_mwh - spot_price) * volume
        
        if not self.two_way_cfd:
            # One-way: only inpayment, no outpayment
            payment = max(0.0, payment)
        
        return payment


# =============================================================================
# CAPACITY MARKET PARAMS
# =============================================================================
@dataclass(frozen=True)
class CapacityMarketParams:
    """Capacity market / capacity payment parameters.
    
    Revenue for being available to dispatch power.
    """
    capacity_market_enabled: bool = False
    capacity_payment_eur_mw_year: float = 0.0  # Payment per MW per year
    capacity_payment_term_years: int = 0
    firm_capacity_mw: float = 0.0  # Firm capacity (for BESS or hybrid)
    availability_requirement_pct: float = 0.95  # Required availability (95% typical)
    penalty_per_mwh_unavailable: float = 0.0  # Penalty for unavailability (EUR/MWh)
    
    def is_active(self, year: int) -> bool:
        """Check if capacity market is active in year."""
        if not self.capacity_market_enabled:
            return False
        if self.capacity_payment_term_years <= 0:
            return True
        return 1 <= year <= self.capacity_payment_term_years
    
    def revenue_at_year(self, year: int) -> float:
        """Capacity market revenue for year (kEUR)."""
        if not self.is_active(year):
            return 0.0
        return self.firm_capacity_mw * self.capacity_payment_eur_mw_year


# =============================================================================
# BESS REVENUE PARAMS
# =============================================================================
@dataclass(frozen=True)
class BESSRevenueParams:
    """BESS-specific revenue streams.
    
    Includes: arbitrage, FCR, aFRR, voltage support, capacity firming.
    """
    # Arbitrage (buy low / sell high)
    arbitrage_enabled: bool = False
    avg_daily_spread_eur_mwh: float = 0.0  # Average daily price spread (EUR/MWh)
    arbitrage_cycles_per_day: float = 1.0  # Cycles per day (0.5-2.0 typical)
    
    # Frequency Containment Reserve (FCR)
    fcr_enabled: bool = False
    fcr_price_eur_mw_day: float = 0.0  # FCR market price (EUR/MW/day)
    fcr_committed_mw: float = 0.0  # Committed MW for FCR
    fcr_availability_pct: float = 0.98  # FCR availability (98% typical)
    
    # Automatic Frequency Restoration Reserve (aFRR)
    afrr_enabled: bool = False
    afrr_capacity_price_eur_mw_h: float = 0.0
    afrr_activation_revenue_eur_mwh: float = 0.0
    afrr_committed_mw: float = 0.0
    
    # Voltage support / reactive power
    reactive_power_enabled: bool = False
    reactive_power_eur_mvar_year: float = 0.0
    
    # Capacity firming (in hybrid project)
    capacity_firming_enabled: bool = False
    firmed_capacity_mw: float = 0.0
    firming_premium_eur_mwh: float = 0.0  # Premium on spot for firm delivery
    
    def annual_revenue_keur(self, bess_capacity_mwh: float, year: int) -> float:
        """Calculate total BESS annual revenue.
        
        Args:
            bess_capacity_mwh: BESS energy capacity
            year: 1-based year index
        
        Returns:
            Annual revenue in kEUR
        """
        revenue = 0.0
        
        # Arbitrage
        if self.arbitrage_enabled:
            arb_rev = (bess_capacity_mwh * 
                      self.avg_daily_spread_eur_mwh * 
                      365 * 
                      self.arbitrage_cycles_per_day)
            revenue += arb_rev / 1000  # Convert to kEUR
        
        # FCR
        if self.fcr_enabled:
            fcr_rev = (self.fcr_committed_mw * 
                      self.fcr_price_eur_mw_day * 
                      365 * 
                      self.fcr_availability_pct)
            revenue += fcr_rev / 1000
        
        # aFRR
        if self.afrr_enabled:
            afrr_rev = (self.afrr_committed_mw * 
                       self.afrr_capacity_price_eur_mw_h * 
                       8760 +  # hours per year
                       self.afrr_committed_mw * 
                       self.afrr_activation_revenue_eur_mwh * 
                       365 * 24 * 0.1)  # approximate activation
            revenue += afrr_rev / 1000
        
        # Reactive power
        if self.reactive_power_enabled:
            revenue += self.reactive_power_eur_mvar_year / 1000
        
        # Capacity firming
        if self.capacity_firming_enabled:
            firming_rev = self.firmed_capacity_mw * self.firming_premium_eur_mwh * 8760
            revenue += firming_rev / 1000
        
        return revenue


# =============================================================================
# REVENUE CONFIG (generic wrapper)
# =============================================================================
@dataclass(frozen=True)
class RevenueConfig:
    """Generic revenue configuration combining all revenue streams.
    
    Only active revenue streams are used in calculations.
    Use total_annual_revenue_keur() to get aggregate revenue.
    """
    ppa: Optional[PPAParams] = None
    merchant: Optional[MerchantParams] = None
    fit: Optional[FeedInTariffParams] = None
    cfd: Optional[CfDParams] = None
    capacity_market: Optional[CapacityMarketParams] = None
    bess_revenue: Optional[BESSRevenueParams] = None
    
    def total_annual_revenue_keur(
        self, 
        generation_mwh: float, 
        year: int,
        technology: str = "solar",
        bess_capacity_mwh: float = 0.0
    ) -> float:
        """Calculate total annual revenue from all active streams.
        
        Args:
            generation_mwh: Total generation (MWh) for the year
            year: 1-based year index
            technology: "solar" | "wind" | "bess"
            bess_capacity_mwh: BESS capacity for BESS revenue calculations
        
        Returns:
            Total revenue in kEUR
        """
        total = 0.0
        
        # PPA revenue
        if self.ppa and self.ppa.is_active(year):
            ppa_volume = generation_mwh * self.ppa.ppa_volume_share
            ppa_price = self.ppa.price_at_year(year)
            ppa_rev = ppa_volume * ppa_price
            
            # Balancing cost deduction
            if self.ppa.balancing_cost_pct > 0:
                ppa_rev *= (1 - self.ppa.balancing_cost_pct)
            
            total += ppa_rev / 1000  # Convert to kEUR
        
        # Merchant revenue
        if self.merchant and self.merchant.merchant_enabled:
            # Merchant volume is generation not under PPA
            merchant_share = 1.0
            if self.ppa and self.ppa.is_active(year):
                merchant_share = 1.0 - self.ppa.ppa_volume_share
            
            merchant_volume = generation_mwh * merchant_share
            merchant_price = self.merchant.price_at_year(year)
            
            # Apply capture rate
            capture = self.merchant.capture_rate_for_tech(technology)
            merchant_rev = merchant_volume * merchant_price * capture
            
            total += merchant_rev / 1000
        
        # FiT revenue
        if self.fit and self.fit.is_active(year):
            # Get spot price for premium calculation
            spot = 0.0
            if self.merchant:
                spot = self.merchant.price_at_year(year)
            
            fit_price = self.fit.price_at_year(year, spot)
            fit_rev = generation_mwh * fit_price
            
            # Check annual cap
            if self.fit.annual_production_cap_mwh > 0:
                fit_rev = min(fit_rev, generation_mwh * fit_price)
            
            total += fit_rev / 1000
        
        # CfD
        if self.cfd and self.cfd.is_active(year):
            spot = 0.0
            if self.merchant:
                spot = self.merchant.price_at_year(year)
            
            cfd_payment = self.cfd.cfd_payment_at_year(year, spot)
            total += cfd_payment / 1000
        
        # Capacity market
        if self.capacity_market and self.capacity_market.is_active(year):
            total += self.capacity_market.revenue_at_year(year)
        
        # BESS-specific revenue
        if self.bess_revenue and bess_capacity_mwh > 0:
            total += self.bess_revenue.annual_revenue_keur(bess_capacity_mwh, year)
        
        return total
    
    def revenue_breakdown(self, year: int, generation_mwh: float = 0.0, technology: str = "solar") -> dict[str, float]:
        """Get detailed revenue breakdown by source.
        
        Returns:
            Dict with revenue by source (in kEUR)
        """
        breakdown = {}
        
        if self.ppa and self.ppa.is_active(year):
            ppa_volume = generation_mwh * self.ppa.ppa_volume_share
            ppa_price = self.ppa.price_at_year(year)
            breakdown["ppa"] = ppa_volume * ppa_price / 1000
        
        if self.merchant and self.merchant.merchant_enabled:
            merchant_share = 1.0 - (self.ppa.ppa_volume_share if self.ppa and self.ppa.is_active(year) else 0.0)
            merchant_volume = generation_mwh * merchant_share
            merchant_price = self.merchant.price_at_year(year)
            capture = self.merchant.capture_rate_for_tech(technology)
            breakdown["merchant"] = merchant_volume * merchant_price * capture / 1000
        
        if self.fit and self.fit.is_active(year):
            spot = self.merchant.price_at_year(year) if self.merchant else 0.0
            breakdown["fit"] = generation_mwh * self.fit.price_at_year(year, spot) / 1000
        
        if self.capacity_market and self.capacity_market.is_active(year):
            breakdown["capacity_market"] = self.capacity_market.revenue_at_year(year)
        
        return breakdown
    
    @staticmethod
    def create_ppa_defaults(tariff: float = 57.0, term: int = 12) -> "RevenueConfig":
        """Create default PPA revenue config.
        
        Args:
            tariff: PPA base price (EUR/MWh)
            term: PPA term in years
        
        Returns:
            RevenueConfig with PPA enabled
        """
        return RevenueConfig(
            ppa=PPAParams(
                ppa_enabled=True,
                ppa_type="pay_as_produced",
                ppa_base_price_eur_mwh=tariff,
                ppa_price_index=0.02,
                ppa_term_years=term,
                ppa_volume_share=1.0,
                balancing_cost_pct=0.025,
            )
        )
    
    @staticmethod
    def create_merchant_defaults(base_price: float = 65.0) -> "RevenueConfig":
        """Create default merchant revenue config.
        
        Args:
            base_price: Base spot price (EUR/MWh)
        
        Returns:
            RevenueConfig with merchant enabled
        """
        return RevenueConfig(
            merchant=MerchantParams(
                merchant_enabled=True,
                base_price_eur_mwh=base_price,
                price_escalation_annual=0.02,
                capture_rate_solar=0.85,
                capture_rate_wind=0.90,
            )
        )
    
    @staticmethod
    def create_ppa_merchant_mix(ppa_share: float = 0.7, ppa_price: float = 57.0, merchant_price: float = 65.0) -> "RevenueConfig":
        """Create mixed PPA + merchant revenue config.
        
        Args:
            ppa_share: Share of production under PPA (0.0-1.0)
            ppa_price: PPA price (EUR/MWh)
            merchant_price: Merchant price (EUR/MWh)
        
        Returns:
            RevenueConfig with both PPA and merchant
        """
        return RevenueConfig(
            ppa=PPAParams(
                ppa_enabled=True,
                ppa_base_price_eur_mwh=ppa_price,
                ppa_term_years=15,
                ppa_volume_share=ppa_share,
                balancing_cost_pct=0.025,
            ),
            merchant=MerchantParams(
                merchant_enabled=True,
                base_price_eur_mwh=merchant_price,
                price_escalation_annual=0.02,
            )
        )