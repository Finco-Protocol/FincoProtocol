"""Synthetic tax assumptions for public reference markets.

Profiles are illustrative modelling defaults, not descriptions of real-world law.
"""
from dataclasses import dataclass
from enum import Enum


class Jurisdiction(Enum):
    MARKET_A = "XA"
    MARKET_B = "XB"
    MARKET_C = "XC"
    GENERIC = "GENERIC"


@dataclass(frozen=True)
class TaxParams:
    jurisdiction: str = "XA"
    corporate_tax_rate: float = 0.20
    depreciation_method: str = "straight_line"
    useful_life_solar_years: int = 25
    useful_life_wind_years: int = 20
    useful_life_bess_years: int = 10
    accelerated_depreciation: bool = False
    atad_applies: bool = True
    atad_ebitda_limit: float = 0.30
    atad_min_threshold_keur: float = 3000.0
    atad_carryforward_years: int = 0
    loss_carryforward_years: int = 5
    loss_carryforward_cap_pct: float = 1.0
    thin_cap_enabled: bool = True
    thin_cap_ratio: float = 4.0
    thin_cap_safe_harbor_keur: float = 0.0
    wht_dividends: float = 0.05
    wht_interest: float = 0.0
    wht_royalties: float = 0.0
    dtt_country: str = ""
    dtt_dividends_rate: float = 0.05
    dtt_interest_rate: float = 0.0
    tax_holiday_years: int = 0
    investment_allowance_pct: float = 0.0
    green_energy_tax_credit: float = 0.0
    property_tax_pct_of_capex: float = 0.0
    land_use_fee_keur_per_ha: float = 0.0
    grid_access_annual_keur: float = 0.0
    vat_rate: float = 0.20
    vat_on_capex_recoverable: bool = True
    shl_cap_applies: bool = True
    shl_interest_cap_rate: float = 0.0
    cit_cash_tax_start_operating_index: int | None = None

    def taxable_income(self, ebitda: float, interest: float, depreciation: float) -> float:
        deductible_interest = interest
        if self.atad_applies:
            limit = ebitda * self.atad_ebitda_limit
            if interest > limit and ebitda > self.atad_min_threshold_keur:
                deductible_interest = limit
        return max(0.0, ebitda - deductible_interest - depreciation)

    def tax_liability(self, taxable_profit: float) -> float:
        return taxable_profit * self.corporate_tax_rate

    def validate_configuration(self) -> list[str]:
        errors = []
        if not 0 <= self.corporate_tax_rate <= 1:
            errors.append("Corporate tax rate must be between 0 and 1")
        if self.loss_carryforward_years < 0:
            errors.append("Loss carryforward years cannot be negative")
        if self.thin_cap_ratio <= 0:
            errors.append("Thin cap ratio must be positive")
        if not 0 <= self.vat_rate <= 1:
            errors.append("VAT rate must be between 0 and 1")
        return errors

    @staticmethod
    def create_market_a_defaults() -> "TaxParams":
        return TaxParams(jurisdiction="XA", corporate_tax_rate=0.20, vat_rate=0.20)

    @staticmethod
    def create_market_b_defaults() -> "TaxParams":
        return TaxParams(
            jurisdiction="XB",
            corporate_tax_rate=0.22,
            vat_rate=0.18,
            atad_applies=False,
            wht_dividends=0.06,
        )

    @staticmethod
    def create_market_c_defaults() -> "TaxParams":
        return TaxParams(
            jurisdiction="XC",
            corporate_tax_rate=0.18,
            vat_rate=0.21,
            loss_carryforward_years=7,
            wht_dividends=0.04,
        )

    @staticmethod
    def create_for_jurisdiction(jurisdiction: str) -> "TaxParams":
        code = (jurisdiction or "XA").upper()
        if code == "XB":
            return TaxParams.create_market_b_defaults()
        if code == "XC":
            return TaxParams.create_market_c_defaults()
        return TaxParams.create_market_a_defaults()


__all__ = ["Jurisdiction", "TaxParams"]
