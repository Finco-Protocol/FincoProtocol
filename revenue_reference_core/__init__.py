"""Isolated, dormant, pure two-tier PPA numeric candidate (R01-A). Not wired to any engine, route or UI."""
from .core import (CAP_SEMANTICS, STATUS, PROVENANCE, PpaTierInput, Quantity, PeriodResult, TierResult,
                   ContractError, compute_ppa_tiers)

__all__ = ["CAP_SEMANTICS", "STATUS", "PROVENANCE", "PpaTierInput", "Quantity", "PeriodResult", "TierResult",
           "ContractError", "compute_ppa_tiers"]
