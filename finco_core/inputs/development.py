"""Typed Developer Economics input authority (V1).

Developer Economics is a SEPARATE investor/developer ledger, linked to — but
never confused with — the project and sponsor ledgers.  It distinguishes three
economic concepts that must never be collapsed into one ambiguous field:

  A. DEVELOPMENT SPEND            actual pre-FC cash spent by the developer.
                                  Developer ledger: negative, dated cash flows.
  B. DEVELOPMENT COST             the part of eligible development spend that the
     REIMBURSEMENT                project reimburses at Financial Close.
                                  Project ledger: a project USE.
                                  Developer ledger: a positive receipt.
  C. DEVELOPER FEE                additional developer compensation paid by the
                                  project.
                                  Project ledger: a project USE.
                                  Developer ledger: a positive receipt.

Reimbursement and developer fee are PROJECT USES (they are funded through the
canonical Sources & Uses / financing policy).  Developer flows themselves never
enter sponsor contributions, sponsor distributions, Pure Equity cash flows or
the shareholder waterfall.

When ``development_economics`` is absent or ``enabled=False`` (the default) the
capability is a neutral no-op: no project use is introduced, no fee is
fabricated, and every existing output is bit-exact unchanged.

Dating authority (V1):
  - development spend carries EXPLICIT typed dates supplied by the input (they
    are facts about the developer's own cash, never invented by the engine) and
    every spend date must be on or before the canonical Financial Close;
  - reimbursement and developer fee settle at the canonical Financial Close date
    (``ProjectInfo.financial_close``).  No arbitrary "N months after FC" timing.

Developer fee basis (V1) is non-circular by construction:
  - ``FIXED_KEUR``         fee = value (kEUR);
  - ``PCT_OF_HARD_CAPEX``  fee = value (a 0..1 fraction) x ``CapexStructure.
                           hard_capex_keur``.  The basis is a pure function of the
                           CAPEX inputs: it contains neither financing costs (IDC,
                           fees — which depend on how the fee itself is funded) nor
                           reserves nor the developer uses, so the fee can never
                           recursively size itself.

Book basis (V1): reimbursement and fee are capitalised as SOFT_COSTS through the
explicit typed ``book_basis_mode``; depreciation then flows through the existing
asset-class useful-life authority (no Developer-Economics-owned life or formula).

Fail closed: every numeric is finite and non-negative, flags are strict bool,
dates are real dates in strictly increasing order, an ABANDONED case carries no
receipts, reimbursement can never exceed the eligible (spent) amount, and an
enabled-but-economically-empty input is rejected rather than interpreted.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from finco_core._numeric import require_bool, require_finite_real

_TOL = 1e-9
_ERR = "DEV_ECON_INVALID"


class DeveloperFeeMode(str, Enum):
    """How the developer fee is sized. Both bases are non-circular."""

    FIXED_KEUR = "FIXED_KEUR"
    PCT_OF_HARD_CAPEX = "PCT_OF_HARD_CAPEX"


class DevelopmentOutcome(str, Enum):
    """Economic state of the development.  ABANDONED = spend without realization."""

    REALIZED = "REALIZED"
    ABANDONED = "ABANDONED"


class DeveloperSettlementAuthority(str, Enum):
    """Settlement-date authority.  V1 has exactly one: the canonical FC date."""

    AT_FINANCIAL_CLOSE = "AT_FINANCIAL_CLOSE"


class DeveloperBookBasisMode(str, Enum):
    """Explicit book-basis treatment of the developer project uses.

    V1 has exactly one mode: reimbursement and fee are capitalised into the
    depreciable asset base as soft costs (``AssetClass.SOFT_COSTS``), whose useful
    life is owned by the existing asset-class authority.  Never inferred from the
    existence of a fee and never silently defaulted to another asset class.
    """

    CAPITALISE_AS_SOFT_COSTS = "CAPITALISE_AS_SOFT_COSTS"


@dataclass(frozen=True)
class DevelopmentSpendEntry:
    """One dated development spend (developer's own cash, kEUR, non-negative)."""

    spend_date: date
    amount_keur: float

    def __post_init__(self) -> None:
        if not isinstance(self.spend_date, date) or isinstance(self.spend_date, datetime):
            raise ValueError(
                f"{_ERR}_SPEND_DATE: spend_date must be a date, got {self.spend_date!r}"
            )
        object.__setattr__(
            self,
            "amount_keur",
            require_finite_real(
                "amount_keur", self.amount_keur, minimum=0.0,
                error_code=f"{_ERR}_SPEND_AMOUNT",
            ),
        )


@dataclass(frozen=True)
class DevelopmentEconomicsInput:
    """Typed Developer Economics input (V1).  Default = disabled neutral no-op."""

    enabled: bool = False
    outcome: DevelopmentOutcome = DevelopmentOutcome.REALIZED
    spend_schedule: tuple[DevelopmentSpendEntry, ...] = ()
    # Eligible development cost reimbursed by the project at FC (kEUR).
    reimbursed_development_cost_keur: float = 0.0
    developer_fee_mode: DeveloperFeeMode = DeveloperFeeMode.FIXED_KEUR
    # FIXED_KEUR: kEUR.  PCT_OF_HARD_CAPEX: fraction in [0, 1].
    developer_fee_value: float = 0.0
    settlement: DeveloperSettlementAuthority = (
        DeveloperSettlementAuthority.AT_FINANCIAL_CLOSE
    )
    book_basis_mode: DeveloperBookBasisMode = (
        DeveloperBookBasisMode.CAPITALISE_AS_SOFT_COSTS
    )

    def __post_init__(self) -> None:
        require_bool("enabled", self.enabled, error_code=f"{_ERR}_ENABLED")
        for name, value, kind in (
            ("outcome", self.outcome, DevelopmentOutcome),
            ("developer_fee_mode", self.developer_fee_mode, DeveloperFeeMode),
            ("settlement", self.settlement, DeveloperSettlementAuthority),
            ("book_basis_mode", self.book_basis_mode, DeveloperBookBasisMode),
        ):
            if not isinstance(value, kind):
                raise ValueError(
                    f"{_ERR}_ENUM: {name} must be {kind.__name__}, got {value!r}"
                )
        if not isinstance(self.spend_schedule, tuple):
            raise ValueError(
                f"{_ERR}_SCHEDULE: spend_schedule must be a tuple of "
                f"DevelopmentSpendEntry, got {type(self.spend_schedule).__name__}"
            )
        for entry in self.spend_schedule:
            if not isinstance(entry, DevelopmentSpendEntry):
                raise ValueError(
                    f"{_ERR}_SCHEDULE: spend_schedule entries must be "
                    f"DevelopmentSpendEntry, got {entry!r}"
                )
        for previous, current in zip(self.spend_schedule, self.spend_schedule[1:]):
            if current.spend_date <= previous.spend_date:
                raise ValueError(
                    f"{_ERR}_SCHEDULE_ORDER: spend dates must be strictly increasing "
                    f"and unique ({previous.spend_date} then {current.spend_date})"
                )

        reimbursed = require_finite_real(
            "reimbursed_development_cost_keur", self.reimbursed_development_cost_keur,
            minimum=0.0, error_code=f"{_ERR}_REIMBURSEMENT",
        )
        fee_value = require_finite_real(
            "developer_fee_value", self.developer_fee_value,
            minimum=0.0, error_code=f"{_ERR}_FEE",
        )
        object.__setattr__(self, "reimbursed_development_cost_keur", reimbursed)
        object.__setattr__(self, "developer_fee_value", fee_value)
        if self.developer_fee_mode is DeveloperFeeMode.PCT_OF_HARD_CAPEX and fee_value > 1.0:
            raise ValueError(
                f"{_ERR}_FEE: PCT_OF_HARD_CAPEX fee is a 0..1 fraction, got {fee_value!r}"
            )

        total_spend = self.total_development_spend_keur
        # Reimbursement can never exceed the eligible amount (V1: eligible = all spend).
        if reimbursed > total_spend + _TOL:
            raise ValueError(
                f"{_ERR}_REIMBURSEMENT_EXCEEDS_ELIGIBLE: reimbursed "
                f"{reimbursed!r} kEUR exceeds eligible development spend "
                f"{total_spend!r} kEUR"
            )
        if self.outcome is DevelopmentOutcome.ABANDONED:
            if reimbursed > _TOL or fee_value > _TOL:
                raise ValueError(
                    f"{_ERR}_ABANDONED_WITH_RECEIPTS: an ABANDONED development "
                    "carries no reimbursement and no developer fee"
                )
            if self.enabled and total_spend <= _TOL:
                raise ValueError(
                    f"{_ERR}_ABANDONED_WITHOUT_SPEND: an enabled ABANDONED "
                    "development must carry development spend"
                )
        elif self.enabled and total_spend <= _TOL and reimbursed <= _TOL and fee_value <= _TOL:
            raise ValueError(
                f"{_ERR}_ENABLED_WITHOUT_ECONOMICS: enabled Developer Economics "
                "needs development spend, a reimbursement or a developer fee"
            )

    @property
    def total_development_spend_keur(self) -> float:
        return float(sum(entry.amount_keur for entry in self.spend_schedule))

    @property
    def is_active(self) -> bool:
        """True only when the capability can change anything (enabled)."""
        return self.enabled


def cache_key(value: "DevelopmentEconomicsInput | None") -> "tuple | None":
    """Deterministic hash element.  Absent and disabled are the SAME neutral
    ``None`` (no economic effect => identical cache identity => bit-exact)."""
    if value is None or not value.enabled:
        return None
    return (
        value.outcome.value,
        tuple((e.spend_date.isoformat(), e.amount_keur) for e in value.spend_schedule),
        value.reimbursed_development_cost_keur,
        value.developer_fee_mode.value,
        value.developer_fee_value,
        value.settlement.value,
        value.book_basis_mode.value,
    )
