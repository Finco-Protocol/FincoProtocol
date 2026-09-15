"""domain/senior_debt_sizing/policy — Senior Debt Sizing Policy dataclasses."""
from dataclasses import dataclass
from enum import Enum
from typing import Tuple, Optional


class SizingMode(Enum):
    """Senior debt sizing mode.

    Attributes
    ----------
    EXPLICIT_CFADS : str
        Use explicit sizing CFADS per period from a typed authority input.
        The sizing CFADS is provided directly as input — not derived.
        This mode is used when an explicit sizing-CFADS authority is supplied.

    DERIVE_FROM_MINIMUM_DSCR : str
        Derive sizing CFADS from a minimum DSCR target.
        sizing_cfads[t] = senior_debt_service_capacity[t] × target_dscr[t]
        where senior_debt_service_capacity is derived from available cash
        and the target minimum DSCR.
        This is a future canonical/new-project mode.
    """
    EXPLICIT_CFADS = "explicit_cfads"
    DERIVE_FROM_MINIMUM_DSCR = "derive_from_minimum_dscr"


@dataclass(frozen=True)
class SeniorDebtSizingPolicy:
    """Explicit sizing CFADS per period from a typed authority or equivalent config.

    This is NOT derived from actual_cfads. It is a separate explicit input
    that represents the canonical sizing assumption for the current model run.

    Attributes
    ----------
    project_name : str
        Project display name.
    sizing_mode : SizingMode
        Sizing mode selected by the caller.
    sizing_cfads_keur_by_period : Tuple[float, ...]
        Explicit sizing CFADS per period (kEUR).
        For EXPLICIT_CFADS mode: supplied directly by the typed authority.
        For DERIVE_FROM_MINIMUM_DSCR mode: holds actual_cfads (input),
        from which sizing_cfads is derived as actual / minimum_sizing_dscr.
    source_cell : str, default "model_source_ref"
        Provenance marker. Value depends on sizing_mode:
        - EXPLICIT_CFADS: "explicit_authority"
        - DERIVE_FROM_MINIMUM_DSCR: "derived-from-actual-cfads"
    notes : str, default ""
        Additional notes.
    inferred_minimum_dscr : float, optional
        The minimum actual DSCR that this sizing CFADS appears to support.
        Optional interpretation supplied by the caller; it is not inferred from repository fixtures.
    minimum_sizing_dscr : float, optional
        For DERIVE_FROM_MINIMUM_DSCR mode only: the minimum DSCR floor applied
        to actual_cfads to derive sizing_cfads. Default 1.45.
        Ignored for EXPLICIT_CFADS mode.
    """
    project_name: str
    sizing_mode: SizingMode
    sizing_cfads_keur_by_period: Tuple[float, ...]
    source_cell: str = "explicit_authority"
    notes: str = ""
    inferred_minimum_dscr: Optional[float] = None
    minimum_sizing_dscr: Optional[float] = None


@dataclass(frozen=True)
class SeniorDebtDSCRPolicy:
    """Per-period DSCR target — supports PPA/merchant dual regime.

    Attributes
    ----------
    target_dscr_by_period : Tuple[float, ...]
        Per-period DSCR target.
    ppa_dscr : float, default 1.20
        DSCR target in PPA regime.
    merchant_dscr : float, default 1.41
        DSCR target in merchant regime.
    switch_period : int, optional
        1-based period index where PPA → merchant switch occurs.
        Set explicitly by the caller when a regime switch applies.
    source_cell : str, default "debt_source_ref"
        Provenance marker.
    notes : str, default ""
        Additional notes.
    """
    target_dscr_by_period: Tuple[float, ...]
    ppa_dscr: float = 1.20
    merchant_dscr: float = 1.41
    switch_period: Optional[int] = None
    source_cell: str = "typed_policy"
    notes: str = ""


@dataclass(frozen=True)
class SeniorDebtSizingResult:
    """Result of applying SeniorDebtSizingPolicy.

    Attributes
    ----------
    sizing_mode : SizingMode
        The sizing mode used.
    debt_service_capacity_keur_by_period : Tuple[float, ...]
        Per-period debt service capacity = sizing_cfads / target_dscr.
    sizing_cfads_keur_by_period : Tuple[float, ...]
        The sizing CFADS used (may differ from policy if DERIVE mode).
    target_dscr_by_period : Tuple[float, ...]
        Per-period DSCR targets.
    total_sizing_cfads_keur : float
        Sum of sizing CFADS across all periods.
    total_debt_service_capacity_keur : float
        Sum of debt service capacity.
    """
    sizing_mode: SizingMode
    debt_service_capacity_keur_by_period: Tuple[float, ...]
    sizing_cfads_keur_by_period: Tuple[float, ...]
    target_dscr_by_period: Tuple[float, ...]
    total_sizing_cfads_keur: float
    total_debt_service_capacity_keur: float