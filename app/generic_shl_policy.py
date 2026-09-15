"""Generic Solar/Wind SHL policy resolver — single authority for generic SHL contract."""
from __future__ import annotations
import math
from dataclasses import replace as dc_replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.inputs import ProjectInputs

_PERIODS_PER_YEAR = {"Semestrial": 2, "SEMESTRIAL": 2, "Annual": 1, "ANNUAL": 1}


def resolve_generic_shl_policy(project: "ProjectInputs") -> "ProjectInputs":
    """Recompute CASH_SWEEP SHL indices from the FINAL effective ProjectInputs.

    Must be called AFTER all user overrides are applied (construction_months,
    horizon_years, senior_tenor_years). Fails closed if the project is
    geometrically unserviceable (maturity < elig_start).
    """
    from finco_core.inputs import SHLRepaymentMethod

    pf = getattr(project.info.period_frequency, "value", "Semestrial")
    periods_per_year = _PERIODS_PER_YEAR.get(pf, 2)
    months_per_period = 12 // periods_per_year

    construction_months = project.info.construction_months
    horizon_years = project.info.horizon_years
    senior_tenor_years = project.financing.senior_tenor_years

    constr_periods = math.ceil(construction_months / months_per_period)
    elig_start = constr_periods + senior_tenor_years * periods_per_year
    maturity = constr_periods + horizon_years * periods_per_year - 1

    if maturity < elig_start:
        raise ValueError(
            f"GENERIC_SHL_POLICY_UNSERVICEABLE: SHL maturity (period {maturity}) "
            f"is before eligibility start (period {elig_start}). "
            f"Horizon ({horizon_years}y) must exceed Senior tenor ({senior_tenor_years}y)."
        )

    return dc_replace(
        project,
        financing=dc_replace(
            project.financing,
            clean_shl_repayment_method=SHLRepaymentMethod.CASH_SWEEP,
            shl_principal_eligibility_start_period=elig_start,
            shl_maturity_period_index=maturity,
        ),
    )
