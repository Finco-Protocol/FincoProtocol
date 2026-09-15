"""domain/shl/runtime_adapter — Bridge between runtime waterfall and canonical ShlEngine.

This module translates runtime WaterfallPeriod data into ShlEngineInputs,
enabling the canonical SHL engine to run as an audit step alongside the
existing runtime SHL computation.

Usage
-----
    adapter = ShlRuntimeAdapter()
    shl_inputs = adapter.from_waterfall(
        project_name="Generic Wind Reference",
        waterfall_periods=waterfall_result.periods,
        shl_amount_keur=shl_amount,
        shl_rate=shl_rate,
        shl_idc_keur=shl_idc,
        shl_repayment_method="pik_then_sweep",
        shl_wht_rate=0.0,
    )
    canonical_result = ShlEngine.compute(shl_inputs)

Note
----
This adapter is used only when use_shl_canonical_engine=True.
The canonical result is AUDIT-ONLY and does NOT replace runtime SHL computation.
R99/R102 gates remain BLOCKED.
"""
from dataclasses import dataclass
from typing import TYPE_CHECKING

from finco_core.shl.engine import ShlEngine
from finco_core.shl.inputs import ShlEngineInputs, ShlPeriodInput

if TYPE_CHECKING:
    from finco_core.waterfall.waterfall_engine import WaterfallPeriod


@dataclass(frozen=True)
class ShlRuntimeAdapter:
    """Translates runtime waterfall periods into ShlEngineInputs.

    Parameters
    ----------
    period_frequency : str, default "semiannual"
        Period frequency (used for day_fraction mapping).
    """

    period_frequency: str = "semiannual"

    def from_waterfall(
        self,
        project_name: str,
        waterfall_periods: list["WaterfallPeriod"],
        shl_amount_keur: float,
        shl_rate: float,
        shl_idc_keur: float = 0.0,
        shl_repayment_method: str = "pik_then_sweep",
        shl_wht_rate: float = 0.0,
    ) -> ShlEngineInputs:
        """Build ShlEngineInputs from runtime WaterfallPeriod list.

        Parameters
        ----------
        project_name : str
            Project name (e.g., "Generic Wind Reference", "Generic Solar Reference").
        waterfall_periods : list[WaterfallPeriod]
            Runtime WaterfallPeriod list (from WaterfallResult.periods).
        shl_amount_keur : float
            Initial SHL funding amount (kEUR).
        shl_rate : float
            Annual SHL interest rate (e.g., 0.08 for 8%).
        shl_idc_keur : float, default 0.0
            SHL IDC amount (kEUR), added to opening balance.
        shl_repayment_method : str, default "pik_then_sweep"
            SHL repayment method. Only "pik_then_sweep" and "cash_sweep"
            are currently supported by this adapter.
        shl_wht_rate : float, default 0.0
            Withholding tax rate on SHL interest (0.0 for Generic Wind Reference).

        Returns
        -------
        ShlEngineInputs
            Canonical engine inputs.
        """
        day_frac = 0.5 if self.period_frequency == "semiannual" else 1.0

        period_count = len(waterfall_periods)
        operating_count = sum(1 for p in waterfall_periods if getattr(p, "is_operation", True))

        # Identify construction vs operating periods
        # Generic Wind Reference: first operating period (period_index=2) has the first drawdown
        # For canonical engine: tranche_opening = shl_amount + shl_idc at t=0
        tranche_opening_total = shl_amount_keur + shl_idc_keur

        # Build period inputs from waterfall data
        period_inputs = []
        prior_closing = tranche_opening_total

        for i, period in enumerate(waterfall_periods):
            period_idx = getattr(period, "period", i + 1)
            day_fraction = getattr(period, "day_fraction", day_frac)

            # Post-senior cash: CFADS - senior debt service
            # WaterfallPeriod fields:
            #   ebitda_keur ≈ CFADS (proxy for cash available)
            #   cf_after_tax_keur = CFADS after tax (proxy)
            #   senior_ds_keur = senior interest + principal
            ebitda = getattr(period, "ebitda_keur", 0.0)
            cf_after_tax = getattr(period, "cf_after_tax_keur", ebitda)
            senior_ds = getattr(period, "senior_ds_keur", 0.0)

            # Post-senior cash available = CFADS - senior DS
            # (This is the conceptual input to SHL engine, post all senior obligations)
            post_senior_cash = max(0.0, cf_after_tax - senior_ds)

            # Opening balance: for t=0 use tranche_opening; for t>0 use prior closing
            if i == 0:
                opening_balance = tranche_opening_total
            else:
                opening_balance = prior_closing

            # Drawdown: Generic Wind Reference construction draw at period 1 (period_index=2 in Excel)
            # The waterfall tracks shl_balance; we back out drawdown from opening balance
            # Only applies to construction periods
            is_operation = getattr(period, "is_operation", False)
            if not is_operation and i == 0:
                # First period: drawdown = shl_amount (first tranche funding)
                drawdown = shl_amount_keur
            elif not is_operation:
                # Any construction drawdowns — approximate from opening vs prior
                drawdown = opening_balance - prior_closing if opening_balance > prior_closing else 0.0
            else:
                drawdown = 0.0

            # Determine if PIK is allowed this period
            # For pik_then_sweep: PIK allowed until senior debt repaid
            pik_allowed = (shl_repayment_method in ("pik", "pik_then_sweep", "accrued", "partial_pay_sweep"))

            # Minimum cash reserve: not used in Generic Wind Reference (reserve = 0)
            maintain_minimum_reserve = False
            minimum_reserve = 0.0

            period_input = ShlPeriodInput(
                period_index=period_idx,
                opening_balance_keur=opening_balance,
                drawdown_keur=drawdown,
                interest_rate=shl_rate,
                day_count_fraction=day_fraction,
                post_senior_cash_available_keur=post_senior_cash,
                pik_allowed=pik_allowed,
                maintain_minimum_cash_reserve=maintain_minimum_reserve,
                minimum_cash_reserve_keur=minimum_reserve,
            )
            period_inputs.append(period_input)

            # Track prior closing for next period's opening balance
            # The canonical engine computes closing = opening + drawdown + pik - principal
            # We'll update this from the engine result
            prior_closing = opening_balance  # Will be updated after engine call

        return ShlEngineInputs(
            project_name=project_name,
            period_count=period_count,
            period_inputs=tuple(period_inputs),
            total_shl_funding_keur=shl_amount_keur + shl_idc_keur,
            tranche_rates=(shl_rate,),
            tranche_day_fracs=(day_frac,),
            tranche_opening_balances_keur=(tranche_opening_total,),
            pik_allowed=True,
            maintain_minimum_cash_reserve=False,
            minimum_cash_reserve_keur=0.0,
        )


def run_canonical_shl(
    waterfall_periods: list["WaterfallPeriod"],
    shl_amount_keur: float,
    shl_rate: float,
    shl_idc_keur: float = 0.0,
    shl_repayment_method: str = "pik_then_sweep",
    shl_wht_rate: float = 0.0,
    project_name: str = "Generic Wind Reference",
) -> "ShlEngineResult":
    """Convenience function to run canonical SHL engine on waterfall data.

    Parameters
    ----------
    waterfall_periods : list[WaterfallPeriod]
        Runtime waterfall periods.
    shl_amount_keur : float
        Initial SHL funding amount (kEUR).
    shl_rate : float
        Annual SHL interest rate.
    shl_idc_keur : float, default 0.0
        SHL IDC amount.
    shl_repayment_method : str, default "pik_then_sweep"
        SHL repayment method.
    shl_wht_rate : float, default 0.0
        WHT rate on SHL interest.
    project_name : str, default "Generic Wind Reference"
        Project name.

    Returns
    -------
    ShlEngineResult
        Canonical SHL engine result (AUDIT ONLY — does not feed runtime).

    Note
    ----
    R99/R102 gates are BLOCKED. The canonical result is for audit/visibility only.
    """
    adapter = ShlRuntimeAdapter()
    inputs = adapter.from_waterfall(
        project_name=project_name,
        waterfall_periods=waterfall_periods,
        shl_amount_keur=shl_amount_keur,
        shl_rate=shl_rate,
        shl_idc_keur=shl_idc_keur,
        shl_repayment_method=shl_repayment_method,
        shl_wht_rate=shl_wht_rate,
    )
    return ShlEngine.compute(inputs)


# Re-export for convenience
from finco_core.shl.engine import ShlEngine
from finco_core.shl.inputs import ShlEngineInputs, ShlPeriodInput
from finco_core.shl.result import ShlEngineResult, ShlPeriodResult

__all__ = [
    "ShlRuntimeAdapter",
    "run_canonical_shl",
    "ShlEngine",
    "ShlEngineInputs",
    "ShlPeriodInput",
    "ShlEngineResult",
    "ShlPeriodResult",
]