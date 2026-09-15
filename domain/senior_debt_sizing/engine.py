"""domain/senior_debt_sizing/engine — Senior Debt Sizing Engine."""
from typing import Tuple

from domain.senior_debt_sizing.policy import (
    SeniorDebtSizingPolicy,
    SeniorDebtDSCRPolicy,
    SeniorDebtSizingResult,
    SizingMode,
)


class SeniorDebtSizingEngine:
    """Computes debt service capacity from sizing CFADS and DSCR policy.

    Does NOT compute actual debt service (that is SeniorDebtEngine's job).
    Does NOT wire SHL, tax, or distribution.
    Does NOT apply R99/R102 gates.

    Usage (EXPLICIT_CFADS mode)
    ----------------------------
    policy = SeniorDebtSizingPolicy(
        project_name="Generic Wind Reference",
        sizing_mode=SizingMode.EXPLICIT_CFADS,
        sizing_cfads_keur_by_period=(2627.90, ...),
        inferred_minimum_dscr=1.45,
    )
    dscr_policy = SeniorDebtDSCRPolicy(
        target_dscr_by_period=(1.20,) * 25 + (1.41,) * 38,
        ppa_dscr=1.20,
        merchant_dscr=1.41,
        switch_period=26,
    )
    result = SeniorDebtSizingEngine.compute(policy, dscr_policy)
    # result.debt_service_capacity_keur_by_period[t] = sizing_cfads[t] / target_dscr[t]

    Usage (DERIVE_FROM_MINIMUM_DSCR mode)
    --------------------------------------
    actual_cfads = (3000.0, ...)  # from cashflow_source_ref
    policy = SeniorDebtSizingPolicy(
        project_name="NewProject",
        sizing_mode=SizingMode.DERIVE_FROM_MINIMUM_DSCR,
        sizing_cfads_keur_by_period=actual_cfads,
        minimum_sizing_dscr=1.45,
    )
    dscr_policy = SeniorDebtDSCRPolicy(target_dscr_by_period=(1.20,) * 63)
    result = SeniorDebtSizingEngine.compute(policy, dscr_policy)
    # sizing_cfads[t] = actual_cfads[t] / 1.45
    # capacity[t] = sizing_cfads[t] / target_dscr[t]
    """

    @staticmethod
    def compute(
        sizing_policy: SeniorDebtSizingPolicy,
        dscr_policy: SeniorDebtDSCRPolicy,
    ) -> SeniorDebtSizingResult:
        """Compute debt service capacity per period.

        Parameters
        ----------
        sizing_policy : SeniorDebtSizingPolicy
            Contains sizing CFADS and sizing mode.
        dscr_policy : SeniorDebtDSCRPolicy
            Contains per-period target DSCR.

        Returns
        -------
        SeniorDebtSizingResult
            Per-period debt service capacity and totals.

        Raises
        ------
        ValueError
            If sizing_mode is DERIVE_FROM_MINIMUM_DSCR (not implemented yet).
        """
        if sizing_policy.sizing_mode == SizingMode.EXPLICIT_CFADS:
            return SeniorDebtSizingEngine._compute_explicit(sizing_policy, dscr_policy)
        elif sizing_policy.sizing_mode == SizingMode.DERIVE_FROM_MINIMUM_DSCR:
            return SeniorDebtSizingEngine._compute_derive_from_minimum_dscr(sizing_policy, dscr_policy)
        else:
            raise ValueError(f"Unknown sizing mode: {sizing_policy.sizing_mode}")

    @staticmethod
    def _compute_explicit(
        sizing_policy: SeniorDebtSizingPolicy,
        dscr_policy: SeniorDebtDSCRPolicy,
    ) -> SeniorDebtSizingResult:
        sizing_cfads = sizing_policy.sizing_cfads_keur_by_period
        target_dsrs = dscr_policy.target_dscr_by_period

        # Keep sizing CFADS signed. Only debt-service capacity is bounded at
        # zero; negative financial flow cannot support negative debt service.
        debt_service_capacity = []
        for cfads, dscr in zip(sizing_cfads, target_dsrs):
            if dscr > 0:
                capacity = max(0.0, cfads / dscr)
            else:
                capacity = 0.0
            debt_service_capacity.append(capacity)

        total_sizing_cfads = sum(sizing_cfads)
        total_ds_capacity = sum(debt_service_capacity)

        return SeniorDebtSizingResult(
            sizing_mode=SizingMode.EXPLICIT_CFADS,
            debt_service_capacity_keur_by_period=tuple(debt_service_capacity),
            sizing_cfads_keur_by_period=sizing_cfads,
            target_dscr_by_period=target_dsrs,
            total_sizing_cfads_keur=total_sizing_cfads,
            total_debt_service_capacity_keur=total_ds_capacity,
        )

    @staticmethod
    def _compute_derive_from_minimum_dscr(
        sizing_policy: SeniorDebtSizingPolicy,
        dscr_policy: SeniorDebtDSCRPolicy,
    ) -> SeniorDebtSizingResult:
        """Derive sizing CFADS from actual CFADS via minimum DSCR floor.

        sizing_cfads[t] = actual_cfads[t] / minimum_sizing_dscr
        capacity[t] = sizing_cfads[t] / target_dscr[t]

        This mode does NOT claim model_source_ref provenance.
        """
        actual_cfads = sizing_policy.sizing_cfads_keur_by_period
        minimum_dscr = (
            sizing_policy.minimum_sizing_dscr
            if sizing_policy.minimum_sizing_dscr is not None
            else 1.45
        )
        target_dsrs = dscr_policy.target_dscr_by_period

        # Derive sizing CFADS = actual / minimum_dscr
        sizing_cfads = tuple(
            cfads / minimum_dscr for cfads in actual_cfads
        )

        # Keep derived sizing CFADS signed and bound only the capacity.
        debt_service_capacity = []
        for cfads, dscr in zip(sizing_cfads, target_dsrs):
            if dscr > 0:
                capacity = max(0.0, cfads / dscr)
            else:
                capacity = 0.0
            debt_service_capacity.append(capacity)

        total_sizing_cfads = sum(sizing_cfads)
        total_ds_capacity = sum(debt_service_capacity)

        return SeniorDebtSizingResult(
            sizing_mode=SizingMode.DERIVE_FROM_MINIMUM_DSCR,
            debt_service_capacity_keur_by_period=tuple(debt_service_capacity),
            sizing_cfads_keur_by_period=sizing_cfads,
            target_dscr_by_period=target_dsrs,
            total_sizing_cfads_keur=total_sizing_cfads,
            total_debt_service_capacity_keur=total_ds_capacity,
        )
