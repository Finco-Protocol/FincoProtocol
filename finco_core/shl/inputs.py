"""domain/shl/inputs — SHL Engine inputs dataclasses."""
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class ShlPeriodInput:
    """Canonical input for one semiannual period.

    Attributes
    ----------
    period_index : int
        1-based semiannual period index.
    opening_balance_keur : float
        SHL opening balance at start of period.
    drawdown_keur : float
        New SHL funding drawn this period (0 if no drawdown).
    interest_rate : float
        Annual interest rate (e.g., 0.08 for 8%).
    day_count_fraction : float
        Day-count fraction for the period (e.g., 0.5 for semiannual).
    post_senior_cash_available_keur : float
        Cash available after senior debt service (CFADS - senior DS).
    maintain_minimum_cash_reserve : bool, default False
        Whether to retain a minimum cash reserve before SHL service.
    minimum_cash_reserve_keur : float, default 0.0
        Minimum cash to retain if maintain_minimum_cash_reserve is True.
    pik_allowed : bool, default True
        Whether PIK capitalization is allowed for this period.
    distribution_account_r102_sweep_candidate_keur : float | None, default None
        R102 sweep candidate from DistributionAccount (kEUR).
        When provided (>= 0): ShlEngine applies as explicit sweep input
        before internal R102 computation — applied first to cash interest,
        then PIK, then principal reduction.
        When None: ShlEngine computes R102 internally (legacy behavior).
        Generic Solar Reference projects always receive None.
    """
    period_index: int
    opening_balance_keur: float
    drawdown_keur: float
    interest_rate: float
    day_count_fraction: float
    post_senior_cash_available_keur: float
    maintain_minimum_cash_reserve: bool = False
    minimum_cash_reserve_keur: float = 0.0
    pik_allowed: bool = True
    distribution_account_r102_sweep_candidate_keur: float | None = None


@dataclass(frozen=True)
class ShlEngineInputs:
    """Full model inputs for the SHL engine across all periods.

    Attributes
    ----------
    project_name : str
        Project name (e.g., "Generic Wind Reference", "Generic Solar Reference").
    period_count : int
        Total number of semiannual periods (e.g., 63 for Generic Wind Reference).
    period_inputs : Tuple[ShlPeriodInput, ...]
        One ShlPeriodInput per period.
    total_shl_funding_keur : float
        Total SHL funding amount (debt_source_ref reference).
    tranche_rates : Tuple[float, ...]
        Annual interest rate per tranche.
    tranche_day_fracs : Tuple[float, ...]
        Day-count fraction per tranche.
    tranche_opening_balances_keur : Tuple[float, ...]
        Initial opening balances per tranche.
    pik_allowed : bool, default True
        Whether PIK is allowed for this project.
    maintain_minimum_cash_reserve : bool, default False
        Default reserve policy for this project.
    minimum_cash_reserve_keur : float, default 0.0
        Default minimum reserve amount.
    """
    project_name: str
    period_count: int
    period_inputs: Tuple[ShlPeriodInput, ...]
    total_shl_funding_keur: float
    tranche_rates: Tuple[float, ...] = (0.08,)
    tranche_day_fracs: Tuple[float, ...] = (0.5,)
    tranche_opening_balances_keur: Tuple[float, ...] = (0.0,)
    pik_allowed: bool = True
    maintain_minimum_cash_reserve: bool = False
    minimum_cash_reserve_keur: float = 0.0


@dataclass(frozen=True)
class ShlTaxInterface:
    """Config for how SHL interest feeds the tax engine.

    Attributes
    ----------
    interest_deductibility : bool, default True
        Whether SHL interest is tax-deductible when accrued.
    pik_deductibility : bool, default False
        Whether PIK is deductible (typically False until paid in cash).
    withholding_tax_rate : float, default 0.0
        Withholding tax rate on SHL interest.
    effective_deductible_rate : float, default 1.0
        Effective deductible rate = interest_deductibility × (1 - WHT).
    """
    interest_deductibility: bool = True
    pik_deductibility: bool = False
    withholding_tax_rate: float = 0.0

    @property
    def effective_deductible_rate(self) -> float:
        return self.interest_deductibility * (1.0 - self.withholding_tax_rate)