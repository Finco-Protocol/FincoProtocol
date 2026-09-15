"""Debt configuration - supports Senior, Mezzanine, SHL, and EBL structures.

This module provides generički DebtConfig koji zamjenjuje Generic Solar Reference-specifičan FinancingParams.
Supports: Senior Secured Debt, Mezzanine Debt, Shareholder Loan, Equity Bridge Loan.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# =============================================================================
# ENUMS
# =============================================================================
class BaseRateType(Enum):
    """Base rate types for debt pricing."""
    EURIBOR_3M = "EURIBOR_3M"
    EURIBOR_6M = "EURIBOR_6M"
    FIXED = "fixed"


# =============================================================================
# SENIOR DEBT PARAMS
# =============================================================================
@dataclass(frozen=True)
class SeniorDebtParams:
    """Senior Secured Debt parameters.
    
    Primary debt instrument in project finance.
    """
    # Amount and gearing
    gearing_ratio: float = 0.75  # Debt / Total CAPEX (70-80% typical)
    senior_debt_keur: float = 0.0  # Absolute amount (computed from gearing × CAPEX)
    
    # Interest rate
    base_rate_type: str = "FLAT"  # "FLAT" | "EURIBOR_1M" | "EURIBOR_3M" | "EURIBOR_6M" | "fixed"
    # Note: "FLAT" uses all_in_rate directly (no EURIBOR curve) — hedge-equivalent
    base_rate_floor: float = 0.0  # Floor on EURIBOR (typically 0%)
    base_rate: float = 0.02427  # Base rate = EURIBOR 6M spot (April 2026 = 2.427%)
    margin_bps: int = 265  # Credit margin in bps (200-350 bps typical)
    floating_share: float = 0.2  # Share of floating rate debt (20%)
    fixed_share: float = 0.8  # Share of fixed rate debt (80%)
    hedging_enabled: bool = True  # Interest rate hedge (swap)
    hedged_share: float = 0.80  # % of debt hedged (70-85% typical)
    hedge_cost_bps: int = 0  # Hedging cost in bps
    
    # Tenor and amortization
    tenor_years: int = 14  # Total tenor (12-18 years typical)
    grace_period_years: float = 0.0  # Grace period (0 = starts at COD)
    amortization_type: str = "sculpted"  # "sculpted" | "annuity" | "straight_line" | "bullet"
    
    # Covenants
    target_dscr: float = 1.15  # Target DSCR (1.15-1.30x typical)
    min_dscr_lockup: float = 1.10  # Lockup threshold (1.05-1.15x)
    min_llcr: float = 1.15  # Min LLCR (1.15-1.20x)
    min_plcr: float = 1.20  # Min PLCR (1.20-1.30x)
    cash_sweep_dscr: float = 1.35  # Cash sweep when DSCR > this
    
    # Reserve accounts
    dsra_months: int = 6  # DSRA funding months (6 months typical)
    mra_months: int = 0  # MRA (Maintenance Reserve)
    
    # Fees
    arrangement_fee_pct: float = 0.0  # Upfront arrangement fee
    commitment_fee_pct: float = 0.01  # On undrawn amount (0.35-0.75% typical)
    agency_fee_keur: float = 0.0  # Annual agency fee
    security_trustee_keur: float = 0.0  # Security trustee fee
    
    @property
    def all_in_rate(self) -> float:
        """All-in interest rate (base + margin).
        
        Note: For EURIBOR modes, this is the STARTING all-in rate.
        The actual rate schedule varies with EURIBOR curve.
        For FLAT mode, this IS the constant rate used.
        """
        return self.base_rate + self.margin_bps / 10000
    
    @property
    def all_in_rate_fixed(self) -> float:
        """All-in rate for fixed portion."""
        return self.all_in_rate + (self.hedge_cost_bps / 10000 if self.hedging_enabled else 0)
    
    @property
    def all_in_rate_floating(self) -> float:
        """All-in rate for floating portion."""
        return self.all_in_rate
    
    def compute_debt_from_gearing(self, total_capex_keur: float) -> float:
        """Compute senior debt amount from gearing ratio.
        
        Args:
            total_capex_keur: Total project CAPEX
        
        Returns:
            Senior debt amount in kEUR
        """
        return total_capex_keur * self.gearing_ratio


# =============================================================================
# MEZZANINE DEBT PARAMS
# =============================================================================
@dataclass(frozen=True)
class MezzanineParams:
    """Mezzanine / Junior Debt parameters.
    
    Subordinated to senior debt, higher risk = higher rate.
    Often structured as PIK (Payment in Kind) with equity kicker.
    """
    mezzanine_enabled: bool = False
    mezzanine_keur: float = 0.0  # Absolute amount
    
    # Subordination
    subordinated_to_senior: bool = True  # Always True for true mezz
    payment_blocked_if_lockup: bool = True  # Blocked if senior in lockup
    
    # Interest rate
    mezz_rate: float = 0.10  # Fixed rate (8-15% typical)
    pik_interest: bool = True  # PIK (Payment in Kind) - interest capitalizes
    pik_rate: float = 0.0  # PIK component rate (if not cash)
    cash_rate: float = 0.08  # Cash component rate
    
    # Tenor
    mezz_tenor_years: int = 10  # Usually shorter than senior
    mezz_bullet: bool = True  # Bullet at end
    
    # Equity kicker
    equity_kicker_pct: float = 0.0  # % equity stake as compensation
    warrants_enabled: bool = False


# =============================================================================
# SHAREHOLDER LOAN PARAMS
# =============================================================================
@dataclass(frozen=True)
class SHLParams:
    """Shareholder Loan (SHL) parameters.
    
    Subordinated loan from sponsor, often structured as PIK.
    Subject to thin cap rules in some jurisdictions.
    """
    shl_enabled: bool = False
    shl_keur: float = 0.0  # Absolute amount
    
    # Interest rate
    shl_rate: float = 0.08  # 8-12% typical - arm's length (transfer pricing)
    shl_compounding: str = "annual"  # "annual" | "semi_annual" | "pik"
    shl_accrual_during_construction: bool = True  # Accrue interest during construction
    
    # Repayment
    shl_repayment_year: int = 0  # First repayment year (0 = at COD)
    shl_bullet: bool = True  # Bullet or gradual
    shl_subordinated_to_senior: bool = True
    shl_subordinated_to_mezz: bool = True  # True if mezz exists
    
    # Tax treatment
    shl_deductible: bool = True  # Interest tax-deductible
    thin_cap_ratio: float = 4.0  # D/E ratio for thin cap safe harbor
    
    # WHT on interest
    wht_rate_interest: float = 0.0  # WHT on interest (varies by DTT)


# =============================================================================
# EQUITY BRIDGE LOAN PARAMS
# =============================================================================
@dataclass(frozen=True)
class EBLParams:
    """Equity Bridge Loan (EBL) parameters.
    
    Short-term loan bridging equity for duration of construction.
    Repaid at COD or first distribution.
    """
    ebl_enabled: bool = False
    ebl_keur: float = 0.0  # Amount
    
    # Interest
    ebl_rate: float = 0.05  # EURIBOR + 2-3% typical
    ebl_tenor_months: int = 24  # Short tenor
    
    # Repayment
    ebl_repayment_trigger: str = "COD"  # "COD" | "first_distribution" | "refinancing"
    
    # Collateral
    ebl_security: str = "shares_pledge"  # "shares_pledge" | "upstream_guarantee"


# =============================================================================
# DEBT CONFIG (generic wrapper)
# =============================================================================
@dataclass(frozen=True)
class DebtConfig:
    """Generic debt configuration combining all debt instruments.
    
    Replaces Generic Solar Reference-specific FinancingParams with generički debt structure.
    Use total_debt_keur() for total debt, weighted_average_cost() for WACD.
    """
    senior: SeniorDebtParams = field(default_factory=SeniorDebtParams)
    mezzanine: Optional[MezzanineParams] = None
    shl: Optional[SHLParams] = None
    ebl: Optional[EBLParams] = None
    
    def total_debt_keur(self, total_capex_keur: float = 0.0) -> float:
        """Calculate total debt (senior + mezz + SHL + EBL).
        
        Args:
            total_capex_keur: Total CAPEX for computing senior if not set
        
        Returns:
            Total debt in kEUR
        """
        total = 0.0
        
        # Senior debt
        if self.senior.senior_debt_keur > 0:
            total += self.senior.senior_debt_keur
        elif self.senior.gearing_ratio > 0 and total_capex_keur > 0:
            total += self.senior.compute_debt_from_gearing(total_capex_keur)
        
        # Mezzanine
        if self.mezzanine and self.mezzanine.mezzanine_enabled:
            total += self.mezzanine.mezzanine_keur
        
        # SHL
        if self.shl and self.shl.shl_enabled:
            total += self.shl.shl_keur
        
        # EBL
        if self.ebl and self.ebl.ebl_enabled:
            total += self.ebl.ebl_keur
        
        return total
    
    def equity_keur(self, total_capex_keur: float = 0.0) -> float:
        """Calculate equity contribution (CAPEX - total debt).
        
        Args:
            total_capex_keur: Total project CAPEX
        
        Returns:
            Equity in kEUR
        """
        return total_capex_keur - self.total_debt_keur(total_capex_keur)
    
    def weighted_average_cost_of_debt(self, total_capex_keur: float = 0.0) -> float:
        """Calculate weighted average cost of debt (WACD).
        
        Args:
            total_capex_keur: Total project CAPEX for computing senior debt if not set
        
        Returns:
            WACD as decimal (e.g., 0.07 = 7%)
        """
        # Senior amount
        senior_amt = self.senior.senior_debt_keur
        if senior_amt <= 0 and total_capex_keur > 0:
            senior_amt = total_capex_keur * self.senior.gearing_ratio
        
        if senior_amt <= 0:
            return 0.0
        
        # Senior cost (blended floating + fixed)
        senior_cost = (self.senior.all_in_rate_floating * self.senior.floating_share +
                      self.senior.all_in_rate_fixed * self.senior.fixed_share)
        
        # Mezz amount
        mezz_amt = self.mezzanine.mezzanine_keur if (self.mezzanine and self.mezzanine.mezzanine_enabled) else 0.0
        
        # SHL amount
        shl_amt = self.shl.shl_keur if (self.shl and self.shl.shl_enabled) else 0.0
        
        # Total debt for weighting
        total_debt = senior_amt + mezz_amt + shl_amt
        
        if total_debt <= 0:
            return 0.0
        
        # Weighted sum
        weighted = senior_cost * senior_amt
        
        # Mezz cost
        if mezz_amt > 0:
            mezz_cost = self.mezzanine.mezz_rate if self.mezzanine else 0.10
            weighted += mezz_cost * mezz_amt
        
        # SHL cost
        if shl_amt > 0:
            weighted += self.shl.shl_rate * shl_amt
        
        return weighted / total_debt
    
    def validate_configuration(self) -> list[str]:
        """Validate debt configuration consistency.
        
        Returns:
            List of validation error messages. Empty = valid.
        """
        errors = []
        
        # Senior debt validation
        if self.senior.gearing_ratio <= 0 or self.senior.gearing_ratio > 1:
            errors.append("Senior debt gearing_ratio must be between 0 and 1")
        
        if self.senior.target_dscr < 1.0:
            errors.append("Target DSCR must be >= 1.0")
        
        if self.senior.min_dscr_lockup < self.senior.target_dscr:
            errors.append("Lockup DSCR should be <= Target DSCR")
        
        if self.senior.tenor_years <= 0:
            errors.append("Senior tenor must be > 0")
        
        # Mezzanine validation
        if self.mezzanine and self.mezzanine.mezzanine_enabled:
            if self.mezzanine.mezz_rate <= 0:
                errors.append("Mezzanine rate must be > 0")
        
        # SHL validation
        if self.shl and self.shl.shl_enabled:
            if self.shl.shl_rate <= 0:
                errors.append("SHL rate must be > 0")
        
        return errors
    
    @staticmethod
    def create_senior_only_defaults(gearing: float = 0.75, tenor: int = 14) -> "DebtConfig":
        """Create default senior-only debt structure.
        
        Args:
            gearing: Gearing ratio (0.0-1.0)
            tenor: Tenor in years
        
        Returns:
            DebtConfig with senior debt only
        """
        return DebtConfig(
            senior=SeniorDebtParams(
                gearing_ratio=gearing,
                tenor_years=tenor,
                base_rate=0.03,
                margin_bps=265,
                target_dscr=1.15,
                min_dscr_lockup=1.10,
                dsra_months=6,
            )
        )
    
    @staticmethod
    def create_senior_shl_defaults(gearing: float = 0.70, shl_amount: float = 0.0) -> "DebtConfig":
        """Create senior + SHL debt structure.
        
        Args:
            gearing: Senior gearing ratio
            shl_amount: SHL amount in kEUR
        
        Returns:
            DebtConfig with senior and SHL
        """
        return DebtConfig(
            senior=SeniorDebtParams(
                gearing_ratio=gearing,
                tenor_years=14,
            ),
            shl=SHLParams(
                shl_enabled=True,
                shl_keur=shl_amount,
                shl_rate=0.08,
                shl_repayment_year=15,
            )
        )
    
    def debt_service_schedule(
        self, 
        ebitda_schedule: list[float],
        total_capex_keur: float = 0.0
    ) -> dict[str, list[float]]:
        """Calculate debt service schedule for all instruments.
        
        Args:
            ebitda_schedule: EBITDA per period (for DSCR-based sculpting)
            total_capex_keur: Total CAPEX for computing senior debt if not set
        
        Returns:
            Dict with keys: 'senior_interest', 'senior_principal', 'senior_ds',
            'mezz_interest', 'mezz_principal', 'mezz_ds',
            'shl_interest', 'shl_principal', 'shl_ds',
            'total_ds'
        """
        # Compute debt amounts
        senior_debt = self.senior.senior_debt_keur
        if senior_debt <= 0 and total_capex_keur > 0:
            senior_debt = self.senior.compute_debt_from_gearing(total_capex_keur)
        
        mezz_debt = self.mezzanine.mezzanine_keur if (self.mezzanine and self.mezzanine.mezzanine_enabled) else 0.0
        shl_debt = self.shl.shl_keur if (self.shl and self.shl.shl_enabled) else 0.0
        
        num_periods = len(ebitda_schedule)
        periods_per_year = 2  # Semi-annual
        total_years = num_periods / periods_per_year
        
        # Initialize schedules
        result = {
            'senior_interest': [0.0] * num_periods,
            'senior_principal': [0.0] * num_periods,
            'senior_ds': [0.0] * num_periods,
            'mezz_interest': [0.0] * num_periods,
            'mezz_principal': [0.0] * num_periods,
            'mezz_ds': [0.0] * num_periods,
            'shl_interest': [0.0] * num_periods,
            'shl_principal': [0.0] * num_periods,
            'shl_ds': [0.0] * num_periods,
            'total_ds': [0.0] * num_periods,
        }
        
        if senior_debt <= 0:
            return result
        
        rate = self.senior.all_in_rate / periods_per_year  # Per period rate
        senior_tenor_periods = self.senior.tenor_years * periods_per_year
        
        # Use sculpted approach - DSCR-based allocation
        # Target: maintain target_dscr while paying interest + principal
        target_dscr = self.senior.target_dscr
        
        remaining_debt = senior_debt
        balance = senior_debt
        
        for i, ebitda in enumerate(ebitda_schedule):
            # Interest on remaining balance
            interest = balance * rate
            result['senior_interest'][i] = interest
            
            # Sculpt principal to maintain target DSCR
            target_ds = ebitda / target_dscr if target_dscr > 0 else ebitda
            principal = max(0, target_ds - interest)
            
            # Ensure we don't over-pay (balance shouldn't go negative)
            if principal > balance + interest:
                principal = max(0, balance)
            
            result['senior_principal'][i] = principal
            result['senior_ds'][i] = interest + principal
            
            # Update balance
            balance = max(0, balance - principal)
            
            # Mezzanine (PIK or cash)
            if mezz_debt > 0 and self.mezzanine:
                mezz_rate = self.mezzanine.mezz_rate / periods_per_year
                if self.mezzanine.pik_interest:
                    # PIK - interest capitalizes
                    mezz_interest = mezz_debt * mezz_rate
                    mezz_debt += mezz_interest  # Capitalize
                    result['mezz_interest'][i] = mezz_interest
                    # Principal only at bullet
                    if i == num_periods - 1 or (i + 1) % (self.mezzanine.mezz_tenor_years * periods_per_year) == 0:
                        result['mezz_principal'][i] = mezz_debt
                        mezz_debt = 0
                else:
                    # Cash interest
                    result['mezz_interest'][i] = mezz_debt * mezz_rate
                result['mezz_ds'][i] = result['mezz_interest'][i] + result['mezz_principal'][i]
            
            # SHL (subordinated, typically bullet or later repayment)
            if shl_debt > 0 and self.shl:
                shl_rate = self.shl.shl_rate / periods_per_year
                result['shl_interest'][i] = shl_debt * shl_rate
                # SHL repayment typically at end or after senior paid
                # Check if in repayment year range
                years_in = i / periods_per_year
                if years_in >= self.shl.shl_repayment_year - 1:
                    # Start repaying SHL (bullet)
                    if i == num_periods - 1 or (i == int(self.shl.shl_repayment_year * periods_per_year) - 1):
                        result['shl_principal'][i] = shl_debt
                        shl_debt = 0
                result['shl_ds'][i] = result['shl_interest'][i] + result['shl_principal'][i]
            
            # Total debt service
            result['total_ds'][i] = (result['senior_ds'][i] + 
                                     result['mezz_ds'][i] + 
                                     result['shl_ds'][i])
        
        return result
    
    def mezzanine_schedule(self, mezz_debt_keur: float, tenor_years: int, rate: float, pik: bool = True) -> list[float]:
        """Calculate mezzanine payment schedule.
        
        Args:
            mezz_debt_keur: Mezzanine debt amount
            tenor_years: Tenor in years
            rate: Interest rate (decimal)
            pik: True if PIK (interest capitalizes)
        
        Returns:
            List of annual payment amounts
        """
        if mezz_debt_keur <= 0:
            return []
        
        periods = tenor_years * 2  # Semi-annual
        schedule = [0.0] * periods
        balance = mezz_debt_keur
        period_rate = rate / 2
        
        for i in range(periods):
            if pik:
                # PIK: cash interest = 0, but interest capitalizes
                interest = balance * period_rate
                balance += interest  # Capitalize
                schedule[i] = 0  # No cash payment
            else:
                # Cash interest
                interest = balance * period_rate
                principal = mezz_debt_keur / periods  # Amortizing
                schedule[i] = interest + principal
        
        # Bullet at end
        if pik:
            schedule[-1] = balance
        
        return schedule
    
    def shl_schedule(self, shl_keur: float, repayment_year: int, rate: float, tenor_years: int = 30) -> list[float]:
        """Calculate SHL payment schedule.
        
        Args:
            shl_keur: SHL amount
            repayment_year: Year when principal repaid
            rate: Interest rate (decimal)
            tenor_years: Total tenor
        
        Returns:
            List of semi-annual payment amounts
        """
        if shl_keur <= 0:
            return []
        
        total_periods = tenor_years * 2
        schedule = [0.0] * total_periods
        period_rate = rate / 2
        
        for i in range(total_periods):
            # Interest every period
            schedule[i] += shl_keur * period_rate
            
            # Principal at repayment year
            if i == (repayment_year - 1) * 2:  # Period index (0-based)
                schedule[i] += shl_keur
        
        return schedule