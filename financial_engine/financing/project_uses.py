"""financial_engine.financing.project_uses — Canonical Total Project Uses authority.

Single source of truth for computing Total Project Uses from a ProjectInputs contract.
Used by:
  - financial_engine.financing.project (G2A fixed-point)
  - financial_engine.senior_debt.project_adapter (gearing-basis contract)

Do NOT reproduce this arithmetic elsewhere.
"""
from __future__ import annotations

from finco_core.inputs import DebtServiceReserveSupportMode, ProjectInputs

from financial_engine.financing.contracts import ProjectUses
from financial_engine.financing.reserve_policy import resolve_cash_dsra_requirement_keur


def compute_project_uses(project_inputs: ProjectInputs) -> ProjectUses:
    """Compute canonical Total Project Uses from a ProjectInputs contract.

    Authority: G2A financing stack definition.
      Total Project Uses = hard_capex + explicit_financing_costs + cash_reserve_funding

    DSRA modes:
      NONE      → reserve_use = 0 (requirement and legacy_cap must both be 0)
      CASH_DSRA → reserve_use = resolve_cash_dsra_requirement_keur() [shared resolver]
      DSRF      → reserve_use = 0 (no cash reserve at close; requirement = sufficiency only)

    CAPEX MISMATCH CHECK (non-reserve):
      We validate only the non-reserve capex components against capex.total_capex, because:
        - capex.total_capex includes reserve_accounts_keur (legacy field)
        - resolve_cash_dsra_requirement_keur() may use the primary typed field
          (debt_service_reserve_requirement_keur) independently of reserve_accounts_keur
      Checking: (capex.total_capex - reserve_accounts_keur) == (hard_capex + financing_costs)
      This validates the structural capex integrity without conflating primary and legacy fields.

    Raises ValueError for contract violations.
    """
    capex = project_inputs.capex
    fin = project_inputs.financing
    financing_costs = (
        capex.idc_keur
        + capex.commitment_fees_keur
        + capex.bank_fees_keur
        + capex.other_financial_keur
        + capex.vat_costs_keur
    )

    # Delegate all reserve resolution to the shared resolver — raises on any violation.
    reserve_use = resolve_cash_dsra_requirement_keur(project_inputs)
    dsra_mode = fin.dsra_support_mode

    # Validate non-reserve capex components only.
    # capex.total_capex includes reserve_accounts_keur; strip it out before comparing.
    # This allows the primary typed authority to be used independently of the legacy field.
    legacy_reserve_in_total = capex.reserve_accounts_keur
    capex_non_reserve_total = capex.total_capex - legacy_reserve_in_total
    computed_non_reserve_total = capex.hard_capex_keur + financing_costs

    if dsra_mode != DebtServiceReserveSupportMode.DSRF:
        if abs(capex_non_reserve_total - computed_non_reserve_total) > 1e-9:
            raise ValueError(
                "G2A_PROJECT_USES_CAPEX_CONTRACT_MISMATCH: non-reserve capex components "
                f"do not reconcile. capex.total_capex - reserve_accounts_keur = "
                f"{capex_non_reserve_total} != hard_capex + financing_costs = "
                f"{computed_non_reserve_total}."
            )

    total = computed_non_reserve_total + reserve_use

    return ProjectUses(
        hard_project_capex_keur=capex.hard_capex_keur,
        explicit_financing_cost_uses_keur=financing_costs,
        reserve_account_funding_keur=reserve_use,
        other_explicit_project_uses_keur=0.0,
        total_project_uses_keur=total,
    )
