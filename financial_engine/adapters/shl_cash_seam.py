"""financial_engine.adapters.shl_cash_seam — Typed production seam for SHL cash (C3B3D2B1).

Derives cash_available_for_shl_keur per period from a Phase 2C (senior debt) result.

Production cash lineage (Generic Solar Reference SOURCE_VECTOR_IDENTITY_FOR_GENERIC_SOLAR_REFERENCE)
---------------------------------------------------------------------
    CFADS[p]              = EBITDA[p] - cash_tax[p]        (Phase 2B)
    senior_ds[p]          = interest[p] + principal[p]     (Phase 2C)
    candidate_cash[p]     = CFADS[p] - senior_ds[p]        (this seam)

The output is labelled candidate_cash_before_unresolved_reserve_adjustments
because waterfall ordering between SHL and DSRA is DSRA_ORDERING_UNRESOLVED.

Waterfall ordering (partially proven for Generic Solar Reference):
    Revenue
    OPEX
    EBITDA
    − cash_tax                     → CFADS (pre-debt)  [SOURCE_VECTOR_IDENTITY_FOR_GENERIC_SOLAR_REFERENCE]
    − senior_interest              ↘
    − senior_principal             → CFADS − senior_ds_keur
    − shl_cash_interest            ↘  [DSRA_ORDERING_UNRESOLVED — position of DSRA
    − shl_principal_repayment      →   relative to SHL not policy-defined]
    [DSRA — DSRA_ORDERING_UNRESOLVED, not modelled in C3B3D2B1]
    [distributions — not modelled in C3B3D2B1]

Construction period treatment
------------------------------
Construction periods (is_construction=True) return cash_available_for_shl = 0.0.
The construction SHL period is PIK (no cash service required).

Post-senior-maturity treatment
-------------------------------
For operating periods after senior debt maturity (senior_ds = 0), the full
CFADS is available for SHL service: candidate_cash = CFADS.

DSRA_ORDERING_UNRESOLVED
------------------------
Whether DSRA movements are deducted before or after SHL service is NOT
policy-defined in C3B3D2B1.  The seam output is a candidate cash figure
pending resolution of DSRA ordering.  Do not claim DSRA is downstream
of SHL without source evidence.  This is deferred to C3B3D2B2+.

Period alignment contract
--------------------------
Every model period in phase2c_result.periods MUST appear in both
tax_and_cfads.period_indices and (for operating periods) senior_debt.period_indices.
Silently treating a missing period as zero is structurally dangerous and is
NOT permitted.  A missing period raises ValueError.  Duplicate period indices
in either schedule also raise ValueError.

Tax interaction
---------------
SHL gross accrued interest SHOULD feed into PeriodInterestInput.shl_interest_keur
in the tax engine, reducing taxable income.  In C3B3D2B1, SHL interest is NOT
fed back into the Phase 2C fixed-point loop (SHL_OUTSIDE_FIXED_POINT).
The approximation magnitude is bounded by shl_interest × tax_rate and documented
in the reconciliation doc.  Full circular resolution is deferred to C3B3D2B2.

Independence
------------
This seam reads SeniorDebtSchedules and TaxAndCfadsSchedules from the Phase 2C
result.  It does NOT read SHL inputs, SHL balance, or SHL interest.
Changing Senior Debt convention (ACT/360) does NOT alter SHL convention (ACT/365).
Changing SHL convention does NOT alter Senior Debt convention.

No imports from app, finco_core waterfall, or any production runtime beyond
the clean engine result types.
"""
from __future__ import annotations

from finco_core.engine.period_engine import map_period_vector

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from financial_engine.results import ProjectModelResult


@dataclass(frozen=True)
class ShlCashAvailableByPeriod:
    """Cash available for SHL service in one model period.

    Fields
    ------
    period_index : int
        0-based model period index.
    is_construction : bool
        True for the construction period.
    cfads_keur : float
        CFADS from Phase 2B (EBITDA - cash_tax). 0.0 for construction.
    senior_debt_service_keur : float
        Senior debt service (interest + principal) from Phase 2C.
        0.0 for construction and post-maturity periods.
    cash_available_for_shl_keur : float
        CFADS - senior_debt_service.  0.0 for construction (SHL is PIK).
    """
    period_index: int
    is_construction: bool
    cfads_keur: float
    senior_debt_service_keur: float
    cash_available_for_shl_keur: float


def _compute_shl_cash_from_post_senior_cash(
    phase2c_result: "ProjectModelResult",
) -> tuple[ShlCashAvailableByPeriod, ...]:
    """Fast path: consume PostSeniorCashSchedules when present (C3B3D2B4).

    PostSeniorCashSchedules is the authoritative Base-CFADS-derived cash schedule.
    Bank CFADS (debt_sizing.bank_cfads_keur) is never read here.
    """
    psc = phase2c_result.post_senior_cash
    periods = phase2c_result.periods

    all_period_indices = [p.period_index for p in periods]
    if len(all_period_indices) != len(set(all_period_indices)):
        raise ValueError(
            "compute_shl_cash_from_phase2c: duplicate period_index values in "
            "phase2c_result.periods — each model period must appear exactly once"
        )

    psc_len = len(psc.period_indices)
    for name, vec in (
        ("base_cfads_keur", psc.base_cfads_keur),
        ("senior_debt_service_keur", psc.senior_debt_service_keur),
        ("cash_after_senior_before_reserves_keur", psc.cash_after_senior_before_reserves_keur),
        ("cash_available_for_shl_before_reserves_keur", psc.cash_available_for_shl_before_reserves_keur),
    ):
        if len(vec) != psc_len:
            raise ValueError(
                f"compute_shl_cash_from_phase2c: post_senior_cash.{name} length "
                f"mismatch — expected {psc_len}, got {len(vec)}"
            )
    if len(psc.period_indices) != len(set(psc.period_indices)):
        raise ValueError(
            "compute_shl_cash_from_phase2c: duplicate period indices in "
            "post_senior_cash.period_indices"
        )

    # Independently-derived canonical full axis (Correction C / TASK 1).
    psc_expected_full_axis: tuple[int, ...] = tuple(p.period_index for p in periods)
    psc_cfads = map_period_vector(
        psc.period_indices, psc.base_cfads_keur, label="shl_cash_seam.base_cfads",
        expected_indices=psc_expected_full_axis,
    )
    psc_sds = map_period_vector(
        psc.period_indices, psc.senior_debt_service_keur,
        label="shl_cash_seam.senior_debt_service",
        expected_indices=psc_expected_full_axis,
    )
    psc_avail = map_period_vector(
        psc.period_indices, psc.cash_available_for_shl_before_reserves_keur,
        label="shl_cash_seam.cash_available",
        expected_indices=psc_expected_full_axis,
    )

    periods_meta = {p.period_index: p for p in periods}
    results: list[ShlCashAvailableByPeriod] = []
    for idx in all_period_indices:
        if idx not in psc_cfads:
            raise ValueError(
                f"compute_shl_cash_from_phase2c: period_index={idx} is missing "
                f"from post_senior_cash.period_indices — all periods are required"
            )
        p = periods_meta[idx]
        is_constr = p.is_construction
        cfads = psc_cfads[idx]
        senior_ds = psc_sds[idx]
        cash_for_shl = 0.0 if is_constr else psc_avail[idx]
        results.append(ShlCashAvailableByPeriod(
            period_index=idx,
            is_construction=is_constr,
            cfads_keur=cfads,
            senior_debt_service_keur=senior_ds,
            cash_available_for_shl_keur=cash_for_shl,
        ))
    return tuple(results)


def compute_shl_cash_from_phase2c(
    phase2c_result: "ProjectModelResult",
) -> tuple[ShlCashAvailableByPeriod, ...]:
    """Derive cash_available_for_shl_keur from a Phase 2C result.

    When post_senior_cash is present (C3B3D2B4+), consumes it directly — it is
    the authoritative Base-CFADS-derived cash schedule.  Bank CFADS
    (debt_sizing.bank_cfads_keur) is NEVER read by this function.

    Falls back to the legacy tac+sd path when post_senior_cash is absent.

    Parameters
    ----------
    phase2c_result : ProjectModelResult
        A result produced by financial_engine.orchestrator.run_senior_debt_model.
        Must have tax_and_cfads and senior_debt populated.

    Returns
    -------
    tuple[ShlCashAvailableByPeriod, ...]
        One entry per model period (construction + all operating), in period order.

    Raises
    ------
    ValueError
        If required sections are missing from the result.
    """
    # Fast path: post_senior_cash is the explicit Base-CFADS authority (C3B3D2B4+).
    if phase2c_result.post_senior_cash is not None:
        return _compute_shl_cash_from_post_senior_cash(phase2c_result)

    # Legacy path: derive from tax_and_cfads + senior_debt directly.
    tac = phase2c_result.tax_and_cfads
    sd = phase2c_result.senior_debt
    periods = phase2c_result.periods

    # Fail closed on duplicate period indices in the top-level periods list.
    all_period_indices = [p.period_index for p in periods]
    if len(all_period_indices) != len(set(all_period_indices)):
        raise ValueError(
            "compute_shl_cash_from_phase2c: duplicate period_index values in "
            "phase2c_result.periods — each model period must appear exactly once"
        )

    if tac is None:
        raise ValueError(
            "compute_shl_cash_from_phase2c: tax_and_cfads is None — "
            "Phase 2C result must include Tax/CFADS schedules"
        )
    if sd is None:
        raise ValueError(
            "compute_shl_cash_from_phase2c: senior_debt is None — "
            "Phase 2C result must include SeniorDebtSchedules"
        )

    # Build lookup maps keyed by period_index — fail closed on parallel-vector length
    # mismatch (prevents zip() truncation from silently converting malformed data)
    # and on duplicate indices.
    tac_indices = list(tac.period_indices)
    tac_cfads = list(tac.cfads_keur)
    if len(tac_indices) != len(tac_cfads):
        raise ValueError(
            f"compute_shl_cash_from_phase2c: tax_and_cfads parallel-vector length "
            f"mismatch — period_indices has {len(tac_indices)} entries but "
            f"cfads_keur has {len(tac_cfads)} entries; these must be equal"
        )
    if len(tac_indices) != len(set(tac_indices)):
        raise ValueError(
            "compute_shl_cash_from_phase2c: duplicate period indices in "
            "tax_and_cfads.period_indices"
        )
    # Independently-derived canonical full axis for CFADS (Correction C / TASK 1).
    _legacy_full_axis: tuple[int, ...] = tuple(p.period_index for p in periods)
    cfads_by_idx: dict[int, float] = map_period_vector(
        tac_indices, tac_cfads, label="shl_cash_seam.tax_cfads",
        expected_indices=_legacy_full_axis,
    )

    sd_indices = list(sd.period_indices)
    sd_service = list(sd.senior_debt_service_keur)
    if len(sd_indices) != len(sd_service):
        raise ValueError(
            f"compute_shl_cash_from_phase2c: senior_debt parallel-vector length "
            f"mismatch — period_indices has {len(sd_indices)} entries but "
            f"senior_debt_service_keur has {len(sd_service)} entries; these must be equal"
        )
    if len(sd_indices) != len(set(sd_indices)):
        raise ValueError(
            "compute_shl_cash_from_phase2c: duplicate period indices in "
            "senior_debt.period_indices"
        )
    sd_service_by_idx: dict[int, float] = map_period_vector(
        sd_indices, sd_service, label="shl_cash_seam.senior_debt_service"
    )

    # The senior debt schedule covers only the debt tenor [min..max].
    # Operating periods outside this range (pre-debt or post-maturity) legitimately
    # have zero service and are not listed.  Within the tenor, a missing entry is
    # a contract violation and fails closed.
    sd_tenor_min = min(sd_indices) if sd_indices else None
    sd_tenor_max = max(sd_indices) if sd_indices else None

    results: list[ShlCashAvailableByPeriod] = []
    for p in periods:
        idx = p.period_index
        is_constr: bool = p.is_construction

        # Fail closed: every period must be present in CFADS schedule.
        if idx not in cfads_by_idx:
            raise ValueError(
                f"compute_shl_cash_from_phase2c: period_index={idx} is missing "
                f"from tax_and_cfads.period_indices — all periods are required"
            )
        cfads = cfads_by_idx[idx]

        if is_constr:
            # Construction SHL is PIK: no cash service required.
            senior_ds = 0.0
            cash_for_shl = 0.0
        else:
            if idx in sd_service_by_idx:
                senior_ds = sd_service_by_idx[idx]
            elif sd_tenor_min is not None and sd_tenor_min <= idx <= sd_tenor_max:
                # Within the debt tenor but missing — contract violation.
                raise ValueError(
                    f"compute_shl_cash_from_phase2c: operating period_index={idx} "
                    f"is within the senior debt tenor [{sd_tenor_min}..{sd_tenor_max}] "
                    f"but absent from senior_debt.period_indices — missing periods "
                    f"within the tenor are a contract violation"
                )
            else:
                # Pre-debt or post-maturity: senior_ds = 0.0 (no active debt).
                senior_ds = 0.0
            cash_for_shl = max(0.0, cfads - senior_ds)

        results.append(ShlCashAvailableByPeriod(
            period_index=idx,
            is_construction=is_constr,
            cfads_keur=cfads,
            senior_debt_service_keur=senior_ds,
            cash_available_for_shl_keur=cash_for_shl,
        ))

    return tuple(results)
