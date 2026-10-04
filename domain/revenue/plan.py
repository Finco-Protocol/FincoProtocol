"""Revenue V2 typed contracts — RevenuePlan and RevenueStream.

Domain-level contract system for composing MULTIPLE simultaneous revenue
streams on one project. This module owns the typed vocabulary and fail-closed
validation only; period evaluation lives in ``plan_engine.py`` and the
legacy-representation helper in ``legacy_plan_adapter.py``.

Design invariants:

- ONE domain math authority: price resolution reuses the existing
  ``PPAParams`` / ``MerchantParams`` / ``FeedInTariffParams`` /
  ``CfDParams`` authorities from ``revenue_config.py``. This module never
  re-implements their formulas.
- ONE lifecycle authority: ``RevenueStream.start_year`` / ``term_years``
  exclusively own when a contract is active. Nested price-authority objects
  never shorten or extend a stream: the evaluation engine neutralizes the
  legacy nested CfD term clock (the stream status gates activity; the CfD
  formula itself keeps owning strike-reference settlement and two-way /
  one-way direction). PPA / FiT price math carries no lifecycle of its own.
- DOUBLE-COUNTING GUARD (time-aware): within one allocation group, the
  explicit shares of primary streams that are SIMULTANEOUSLY ACTIVE must
  never exceed 100%. Sequential (non-overlapping) contracts are valid;
  overlapping contracts beyond 100% fail closed. Shares are never silently
  normalized, and a residual merchant never counts toward the explicit-share
  check.
- PRIMARY vs OVERLAY: a stream is either a PHYSICAL PRIMARY ALLOCATION
  (consumes eligible generation volume: PPA, Merchant, fixed/indexed/
  awarded tariffs) or a FINANCIAL SETTLEMENT OVERLAY (applies to an
  explicitly declared contractual volume on top of the market sale:
  CfD settlement, sliding premium support). A CfD therefore never consumes
  an additional physical 100% volume, and a market + CfD structure is a
  first-class valid plan.
- MISSING != ZERO, UNAVAILABLE != ZERO, INACTIVE != UNAVAILABLE,
  EXPIRED != INVALID: typed statuses, no silent zero substitution.
- ONE EFFECTIVE ALLOCATION GROUP in this phase: multi-group generation
  authority is deferred and fails closed rather than silently reusing one
  generation scalar across groups.
- Storage remains untouched: capacity/arbitrage/ancillary/firming types are
  reserved vocabulary only and fail closed when instantiated as active
  streams.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from domain.revenue.revenue_config import (
    CfDParams,
    FeedInTariffParams,
    MerchantParams,
    PPAParams,
)

# Dimensionless SHARE tolerance: the maximum accepted excess of summed
# explicit primary allocation shares above 1.0 (pure float-safety epsilon in
# share space; units: fraction of eligible generation). Runtime MWh identity
# uses its own separate MWh-scaled tolerance (see plan_engine).
SHARE_ALLOCATION_TOLERANCE = 1e-9

# Explicitly understood MerchantParams price scenarios (the existing domain
# contract). Anything else changes how market_price would be interpreted and
# fails closed instead of being silently accepted.
SUPPORTED_MERCHANT_PRICE_SCENARIOS = frozenset({"base", "high", "low", "custom"})


class RevenueStreamType(str, Enum):
    """Active V2 revenue stream types plus reserved future vocabulary.

    Reserved types (CAPACITY_MARKET, ARBITRAGE, ANCILLARY, FIRMING) are
    forward-compatibility vocabulary only: constructing an active stream of
    a reserved type fails closed. Storage is not activated.
    """

    PPA = "ppa"
    MERCHANT = "merchant"
    CFD = "cfd"
    FIT_FIXED = "fit_fixed"
    FIT_PREMIUM = "fit_premium"
    INDEXED_FIT = "indexed_fit"
    AUCTION_AWARDED_TARIFF = "auction_awarded_tariff"
    # Reserved — fail closed as active streams (Storage roadmap).
    CAPACITY_MARKET = "capacity_market"
    ARBITRAGE = "arbitrage"
    ANCILLARY = "ancillary"
    FIRMING = "firming"


RESERVED_STREAM_TYPES = frozenset({
    RevenueStreamType.CAPACITY_MARKET,
    RevenueStreamType.ARBITRAGE,
    RevenueStreamType.ANCILLARY,
    RevenueStreamType.FIRMING,
})

# PRIMARY: consumes eligible generation volume in its allocation group.
# OVERLAY: financial settlement on an explicitly declared contractual volume;
# never consumes allocation capacity.
PRIMARY_ALLOCATION_TYPES = frozenset({
    RevenueStreamType.PPA,
    RevenueStreamType.MERCHANT,
    RevenueStreamType.FIT_FIXED,
    RevenueStreamType.INDEXED_FIT,
    RevenueStreamType.AUCTION_AWARDED_TARIFF,
})
SETTLEMENT_OVERLAY_TYPES = frozenset({
    RevenueStreamType.CFD,
    RevenueStreamType.FIT_PREMIUM,
})

# Workflow 02 supports pay-as-produced PPA economics only: the existing
# authoritative domain math implements pay-as-produced. Baseload / shaped /
# synthetic delivery mechanics would be silently priced as
# pay-as-produced, so they fail closed at the contract boundary.
SUPPORTED_PPA_TYPES = frozenset({"pay_as_produced"})


class ContractRole(str, Enum):
    """Physical primary allocation vs financial settlement overlay."""

    PRIMARY_ALLOCATION = "primary_allocation"
    SETTLEMENT_OVERLAY = "settlement_overlay"


def contract_role_for(stream_type: RevenueStreamType) -> ContractRole:
    """Typed taxonomy — never hidden inside type conditionals at call sites."""
    if stream_type in PRIMARY_ALLOCATION_TYPES:
        return ContractRole.PRIMARY_ALLOCATION
    if stream_type in SETTLEMENT_OVERLAY_TYPES:
        return ContractRole.SETTLEMENT_OVERLAY
    raise ValueError(
        f"REVENUE_STREAM_ROLE_UNDEFINED: {stream_type!r} has no contract role"
    )


class PriceIndexation(str, Enum):
    """Typed price indexation basis for a stream."""

    NONE = "none"                 # flat nominal price
    ANNUAL_RATE = "annual_rate"   # base price × (1 + escalation_rate)^(year-1)
    EXPLICIT_FACTORS = "explicit_factors"  # base price × factor[year]


DEFAULT_ALLOCATION_GROUP = "generation"


@dataclass(frozen=True)
class RevenueAllocationGroup:
    """One generation pool whose eligible volume is shared by primary streams.

    Workflow 02 evaluates ONE effective allocation group per plan: the
    eligible generation scalar passed to the engine feeds that single pool.
    Declaring groups that no stream uses, duplicate group ids, or streams
    spread across multiple groups fail closed (multi-group generation
    authority is deferred, never silently approximated).
    """

    group_id: str
    description: str = ""


@dataclass(frozen=True)
class RevenueStream:
    """One typed revenue contract within a RevenuePlan.

    LIFECYCLE OWNER: ``start_year`` (integer >= 1, 1-based model year) and
    ``term_years`` (None = unlimited) exclusively decide activity. Nested
    price-authority lifecycle metadata (e.g. ``CfDParams.cfd_term_years``)
    is documentation only — the engine neutralizes it (see module docstring).

    Volume (primary streams):
        volume_share is the fraction of the allocation group's eligible
        generation purchased by this contract while the stream is ACTIVE.
        ``None`` is legal ONLY for a MERCHANT stream and means the RESIDUAL
        unallocated volume of the group (eligible minus the explicit shares
        of simultaneously active primary streams, floor zero).
    Volume (overlay streams):
        volume_share declares the contractual settlement volume as a
        fraction of the group's eligible generation (e.g. a CfD written for
        70% of production). It consumes no allocation capacity and is
        required (overlays cannot take the residual).

    Price authority (reused, never duplicated):
        PPA streams resolve price through ``ppa: PPAParams`` (pay-as-produced
        only); MERCHANT streams through ``merchant: MerchantParams`` (custom
        curves, escalation, cannibalization, capture rates preserved);
        FIT_FIXED / FIT_PREMIUM / AUCTION_AWARDED_TARIFF through
        ``fit: FeedInTariffParams`` with the matching ``fit_type``; CFD
        through ``cfd: CfDParams``. Overlay streams resolve their REFERENCE
        market price from ``reference_stream_id`` (a merchant stream in the
        plan) or from the plan-level ``market_price`` authority when None.

    Price clocks are model-year clocks (year 1 = first model year), matching
    the existing domain math exactly.
    """

    stream_id: str
    stream_type: RevenueStreamType
    name: str = ""

    enabled: bool = True
    start_year: int = 1
    term_years: Optional[float] = None  # None = unlimited; 0 is INVALID

    allocation_group: str = DEFAULT_ALLOCATION_GROUP
    # None → residual merchant (MERCHANT primary only).
    volume_share: Optional[float] = None

    # Price authority objects (exactly one non-None per stream type).
    ppa: Optional[PPAParams] = None
    merchant: Optional[MerchantParams] = None
    fit: Optional[FeedInTariffParams] = None
    cfd: Optional[CfDParams] = None

    # Indexed FiT (currency-neutral at this domain layer — no FX engine):
    indexed_fit_base_tariff_eur_mwh: Optional[float] = None
    indexed_fit_index_factors: tuple[float, ...] = ()  # factor[year-1]

    # Overlay reference-price routing.
    reference_stream_id: Optional[str] = None

    # Lender-eligibility metadata (documentation/taxonomy only — non-economic
    # at this domain layer; lender cases remain a runtime concern).
    lender_eligible: bool = True

    # Non-economic contract metadata.
    counterparty: str = ""

    def is_active(self, year: int) -> bool:
        """THE lifecycle authority: enabled AND start ≤ year ≤ start+term−1."""
        if not self.enabled:
            return False
        if year < self.start_year:
            return False
        if self.term_years is None:
            return True
        return year <= self.start_year + self.term_years - 1

    @property
    def contract_role(self) -> ContractRole:
        return contract_role_for(self.stream_type)

    @property
    def end_year(self) -> Optional[int]:
        """Last active model year (None when term is unlimited)."""
        if self.term_years is None:
            return None
        return int(self.start_year + self.term_years - 1)

    def validate(self) -> None:
        """Fail-closed contract validation. Raises ValueError on any defect."""
        sid = self.stream_id or "<missing-id>"
        if not self.stream_id or not self.stream_id.strip():
            raise ValueError("REVENUE_STREAM_ID_REQUIRED: every stream needs a non-empty id")
        if not isinstance(self.stream_type, RevenueStreamType):
            raise ValueError(
                f"REVENUE_STREAM_TYPE_UNSUPPORTED: stream {sid!r} carries "
                f"{self.stream_type!r}; use a RevenueStreamType member"
            )
        if self.stream_type in RESERVED_STREAM_TYPES:
            raise ValueError(
                f"REVENUE_STREAM_TYPE_RESERVED: stream {sid!r} uses reserved type "
                f"{self.stream_type.value!r}; Storage-adjacent streams are not "
                "activatable in this domain layer"
            )
        if not isinstance(self.start_year, int) or isinstance(self.start_year, bool) \
                or self.start_year < 1:
            raise ValueError(
                f"REVENUE_STREAM_START_INVALID: stream {sid!r} start_year must be an "
                f"integer >= 1, got {self.start_year!r}"
            )
        if self.term_years is not None:
            if self.term_years == 0:
                raise ValueError(
                    f"REVENUE_STREAM_TERM_INVALID: stream {sid!r} term_years=0 is "
                    "contradictory; use None for an unlimited term"
                )
            if not math.isfinite(float(self.term_years)) or self.term_years < 0:
                raise ValueError(
                    f"REVENUE_STREAM_TERM_INVALID: stream {sid!r} term_years must be "
                    "a finite positive number or None"
                )
        if self.volume_share is not None:
            if not math.isfinite(self.volume_share) or not (0.0 <= self.volume_share <= 1.0):
                raise ValueError(
                    f"REVENUE_STREAM_VOLUME_SHARE_INVALID: stream {sid!r} volume_share "
                    f"={self.volume_share!r} must be within [0.0, 1.0]"
                )
        if self.volume_share is None and self.stream_type != RevenueStreamType.MERCHANT:
            raise ValueError(
                f"REVENUE_STREAM_VOLUME_SHARE_REQUIRED: stream {sid!r} "
                f"({self.stream_type.value}) must declare an explicit volume_share; "
                "only a MERCHANT stream may take the residual (None)"
            )
        self._validate_price_authority(sid)
        self._validate_exactly_one_authority(sid)
        self._validate_economic_numbers(sid)

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _require_finite_non_negative(self, sid: str, label: str, value: float) -> None:
        if not math.isfinite(float(value)) or float(value) < 0.0:
            raise ValueError(
                f"REVENUE_STREAM_VALUE_INVALID: stream {sid!r} {label} must be "
                f"finite and non-negative, got {value!r}"
            )

    def _validate_price_authority(self, sid: str) -> None:
        needs = {
            RevenueStreamType.PPA: ("ppa", self.ppa),
            RevenueStreamType.MERCHANT: ("merchant", self.merchant),
            RevenueStreamType.FIT_FIXED: ("fit", self.fit),
            RevenueStreamType.FIT_PREMIUM: ("fit", self.fit),
            RevenueStreamType.AUCTION_AWARDED_TARIFF: ("fit", self.fit),
            RevenueStreamType.CFD: ("cfd", self.cfd),
        }
        if self.stream_type == RevenueStreamType.INDEXED_FIT:
            if self.indexed_fit_base_tariff_eur_mwh is None:
                raise ValueError(
                    f"REVENUE_STREAM_INDEXED_FIT_BASE_TARIFF_REQUIRED: stream {sid!r}"
                )
            if not self.indexed_fit_index_factors:
                raise ValueError(
                    f"REVENUE_STREAM_INDEX_FACTORS_REQUIRED: stream {sid!r} needs an "
                    "explicit index factor schedule (no silent implicit index)"
                )
            return
        attr, authority = needs[self.stream_type]
        if authority is None:
            raise ValueError(
                f"REVENUE_STREAM_PRICE_AUTHORITY_REQUIRED: stream {sid!r} "
                f"({self.stream_type.value}) requires the {attr!r} price authority"
            )
        # Contract type / price authority alignment (fail closed).
        if self.stream_type is RevenueStreamType.PPA:
            if self.ppa.ppa_type not in SUPPORTED_PPA_TYPES:
                raise ValueError(
                    f"REVENUE_STREAM_PPA_TYPE_UNSUPPORTED: stream {sid!r} declares "
                    f"ppa_type={self.ppa.ppa_type!r}; Workflow 02 supports "
                    f"{sorted(SUPPORTED_PPA_TYPES)} only — baseload/shaped/synthetic "
                    "delivery would be silently priced as pay-as-produced"
                )
        if self.stream_type is RevenueStreamType.FIT_FIXED and self.fit.fit_type != "fixed_fit":
            raise ValueError(
                f"REVENUE_STREAM_FIT_TYPE_MISMATCH: FIT_FIXED stream {sid!r} requires "
                f"fit_type='fixed_fit', got {self.fit.fit_type!r}"
            )
        if self.stream_type is RevenueStreamType.FIT_PREMIUM and self.fit.fit_type != "premium":
            raise ValueError(
                f"REVENUE_STREAM_FIT_TYPE_MISMATCH: FIT_PREMIUM stream {sid!r} requires "
                f"fit_type='premium', got {self.fit.fit_type!r}"
            )
        if self.stream_type is RevenueStreamType.AUCTION_AWARDED_TARIFF and (
            self.fit.fit_type != "fixed_fit"
        ):
            raise ValueError(
                f"REVENUE_STREAM_AUCTION_AUTHORITY_MISMATCH: awarded-tariff stream "
                f"{sid!r} uses the fixed-tariff price authority "
                f"(fit_type='fixed_fit'), got {self.fit.fit_type!r}"
            )

    def _validate_exactly_one_authority(self, sid: str) -> None:
        """Each typed stream carries EXACTLY ONE applicable price authority
        (plus the indexed FiT's explicit fields). Extra unrelated authority
        objects fail closed — they are never silently ignored."""
        if self.stream_type is RevenueStreamType.INDEXED_FIT:
            unrelated = [
                name for name, value in (
                    ("ppa", self.ppa), ("merchant", self.merchant),
                    ("fit", self.fit), ("cfd", self.cfd),
                ) if value is not None
            ]
            if unrelated:
                raise ValueError(
                    f"REVENUE_STREAM_MULTIPLE_PRICE_AUTHORITIES: indexed-FiT stream "
                    f"{sid!r} must use only its explicit indexed tariff fields; "
                    f"found unrelated authority object(s) {unrelated}"
                )
            return
        required = {
            RevenueStreamType.PPA: "ppa",
            RevenueStreamType.MERCHANT: "merchant",
            RevenueStreamType.FIT_FIXED: "fit",
            RevenueStreamType.FIT_PREMIUM: "fit",
            RevenueStreamType.AUCTION_AWARDED_TARIFF: "fit",
            RevenueStreamType.CFD: "cfd",
        }[self.stream_type]
        extras = [
            name for name, value in (
                ("ppa", self.ppa), ("merchant", self.merchant),
                ("fit", self.fit), ("cfd", self.cfd),
            ) if value is not None and name != required
        ]
        if extras:
            raise ValueError(
                f"REVENUE_STREAM_MULTIPLE_PRICE_AUTHORITIES: stream {sid!r} "
                f"({self.stream_type.value}) requires only the {required!r} price "
                f"authority; found extra unrelated authority object(s) {extras}"
            )

    def _validate_economic_numbers(self, sid: str) -> None:
        if self.ppa is not None:
            self._require_finite_non_negative(sid, "ppa_base_price_eur_mwh",
                                              self.ppa.ppa_base_price_eur_mwh)
            self._require_finite_non_negative(sid, "ppa_price_index",
                                              self.ppa.ppa_price_index)
            self._require_finite_non_negative(sid, "ppa_price_floor",
                                              self.ppa.ppa_price_floor)
            self._require_finite_non_negative(sid, "ppa_price_cap",
                                              self.ppa.ppa_price_cap)
            if not math.isfinite(self.ppa.balancing_cost_pct) or not (
                0.0 <= self.ppa.balancing_cost_pct <= 1.0
            ):
                raise ValueError(
                    f"REVENUE_STREAM_VALUE_INVALID: stream {sid!r} balancing_cost_pct "
                    f"must be within [0, 1], got {self.ppa.balancing_cost_pct!r}"
                )
            if (self.ppa.ppa_price_floor > 0.0 and self.ppa.ppa_price_cap > 0.0
                    and self.ppa.ppa_price_floor > self.ppa.ppa_price_cap):
                raise ValueError(
                    f"REVENUE_STREAM_FLOOR_ABOVE_CAP: stream {sid!r} PPA price floor "
                    "exceeds price cap"
                )
        if self.merchant is not None:
            self._require_finite_non_negative(sid, "merchant_base_price_eur_mwh",
                                              self.merchant.base_price_eur_mwh)
            self._require_finite_non_negative(sid, "price_escalation_annual",
                                              self.merchant.price_escalation_annual)
            self._require_finite_non_negative(sid, "price_cannibalization_pct",
                                              self.merchant.price_cannibalization_pct)
            for i, p in enumerate(self.merchant.custom_price_curve):
                self._require_finite_non_negative(sid, f"custom_price_curve[{i}]", p)
            for label, rate in (
                ("capture_rate_solar", self.merchant.capture_rate_solar),
                ("capture_rate_wind", self.merchant.capture_rate_wind),
                ("capture_rate_bess", self.merchant.capture_rate_bess),
            ):
                if not math.isfinite(rate) or not (0.0 <= rate <= 1.0):
                    raise ValueError(
                        f"REVENUE_STREAM_VALUE_INVALID: stream {sid!r} {label} must "
                        f"be within [0, 1], got {rate!r}"
                    )
        if self.fit is not None:
            self._require_finite_non_negative(sid, "fit_price_eur_mwh",
                                              self.fit.fit_price_eur_mwh)
            self._require_finite_non_negative(sid, "fit_index", self.fit.fit_index)
            self._require_finite_non_negative(sid, "premium_eur_mwh",
                                              self.fit.premium_eur_mwh)
            self._require_finite_non_negative(sid, "premium_floor_eur_mwh",
                                              self.fit.premium_floor_eur_mwh)
            self._require_finite_non_negative(sid, "premium_cap_eur_mwh",
                                              self.fit.premium_cap_eur_mwh)
            if (self.fit.premium_floor_eur_mwh > 0.0 and self.fit.premium_cap_eur_mwh > 0.0
                    and self.fit.premium_floor_eur_mwh > self.fit.premium_cap_eur_mwh):
                raise ValueError(
                    f"REVENUE_STREAM_FLOOR_ABOVE_CAP: stream {sid!r} premium floor "
                    "exceeds premium cap"
                )
        if self.cfd is not None:
            self._require_finite_non_negative(sid, "strike_price_eur_mwh",
                                              self.cfd.strike_price_eur_mwh)
        if self.stream_type is RevenueStreamType.INDEXED_FIT:
            self._require_finite_non_negative(sid, "indexed_fit_base_tariff_eur_mwh",
                                              self.indexed_fit_base_tariff_eur_mwh)
            for i, f in enumerate(self.indexed_fit_index_factors):
                self._require_finite_non_negative(sid, f"index_factor[{i}]", f)


@dataclass(frozen=True)
class RevenuePlan:
    """Typed multi-stream revenue plan for one project.

    Validation is fail-closed at construction via ``RevenuePlan.create``;
    the raw constructor stays permissive for dataclass tooling but every
    evaluation entry point re-checks first.
    """

    streams: tuple[RevenueStream, ...]
    allocation_groups: tuple[RevenueAllocationGroup, ...] = ()
    # Plan-level market price authority for overlays without an explicit
    # reference stream (existing MerchantParams math — no duplication).
    market_price: Optional[MerchantParams] = None

    # ------------------------------------------------------------------
    # Construction / validation
    # ------------------------------------------------------------------

    @staticmethod
    def create(
        streams: tuple[RevenueStream, ...] | list[RevenueStream],
        *,
        allocation_groups: tuple[RevenueAllocationGroup, ...] | list[RevenueAllocationGroup] = (),
        market_price: Optional[MerchantParams] = None,
    ) -> "RevenuePlan":
        plan = RevenuePlan(
            streams=tuple(streams),
            allocation_groups=tuple(allocation_groups),
            market_price=market_price,
        )
        plan.validate()
        return plan

    def validate(self) -> None:
        """Fail-closed plan validation."""
        seen: set[str] = set()
        for stream in self.streams:
            stream.validate()
            if stream.stream_id in seen:
                raise ValueError(
                    f"REVENUE_STREAM_ID_DUPLICATE: {stream.stream_id!r} appears "
                    "more than once in the plan"
                )
            seen.add(stream.stream_id)

        self._validate_allocation_groups()
        self._validate_time_aware_allocation()
        self._validate_residual_merchant_uniqueness()
        self._validate_overlay_references(seen)
        self._validate_plan_market_price()

    def _validate_allocation_groups(self) -> None:
        """One effective allocation group in this phase (fail closed)."""
        declared_ids = [g.group_id for g in self.allocation_groups]
        if len(declared_ids) != len(set(declared_ids)):
            raise ValueError(
                "REVENUE_ALLOCATION_GROUP_DUPLICATE: allocation_groups declare "
                f"duplicate ids {sorted(declared_ids)}"
            )
        stream_groups = {s.allocation_group for s in self.streams}
        if len(stream_groups) > 1:
            raise ValueError(
                f"REVENUE_PLAN_MULTIPLE_ALLOCATION_GROUPS_DEFERRED: streams span "
                f"groups {sorted(stream_groups)}; Workflow 02 evaluates ONE "
                "effective generation allocation group and refuses to silently "
                "reuse a single generation scalar across multiple pools"
            )
        if declared_ids:
            undeclared = stream_groups - set(declared_ids)
            if undeclared:
                raise ValueError(
                    f"REVENUE_ALLOCATION_GROUP_UNDECLARED: streams reference group(s) "
                    f"{sorted(undeclared)} missing from allocation_groups"
                )
            unused = set(declared_ids) - stream_groups
            if unused:
                raise ValueError(
                    f"REVENUE_ALLOCATION_GROUP_UNUSED: declared group(s) "
                    f"{sorted(unused)} are not referenced by any stream"
                )

    def _validate_time_aware_allocation(self) -> None:
        """Deterministic time-aware overlap validation.

        Coverage of explicit primary shares only increases at contract start
        years, so checking every start year finds every simultaneous-coverage
        maximum. Sequential contracts (A ends before B starts) never overlap;
        partial overlaps beyond 100% fail closed with the first offending
        year. Residual merchants do not count toward the explicit cap.
        """
        explicit = [
            s for s in self.streams
            if s.contract_role is ContractRole.PRIMARY_ALLOCATION
            and s.enabled
            and s.volume_share is not None
        ]
        by_group: dict[str, list[RevenueStream]] = {}
        for s in explicit:
            by_group.setdefault(s.allocation_group, []).append(s)
        for group, members in by_group.items():
            candidate_years = sorted({m.start_year for m in members})
            for year in candidate_years:
                active_share = sum(
                    float(m.volume_share) for m in members if m.is_active(year)
                )
                if active_share > 1.0 + SHARE_ALLOCATION_TOLERANCE:
                    raise ValueError(
                        "REVENUE_ALLOCATION_EXCEEDS_ELIGIBLE_GENERATION: allocation "
                        f"group {group!r} contracts {active_share:.6f} of eligible "
                        f"generation in model year {year} (explicit shares are never "
                        "normalized; only simultaneously ACTIVE contracts count)"
                    )

    def _validate_residual_merchant_uniqueness(self) -> None:
        residual_by_group: dict[str, int] = {}
        for stream in self.streams:
            if (
                stream.contract_role is ContractRole.PRIMARY_ALLOCATION
                and stream.enabled
                and stream.volume_share is None
            ):
                residual_by_group[stream.allocation_group] = (
                    residual_by_group.get(stream.allocation_group, 0) + 1
                )
        for group, count in residual_by_group.items():
            if count > 1:
                raise ValueError(
                    f"REVENUE_RESIDUAL_MERCHANT_AMBIGUOUS: allocation group "
                    f"{group!r} declares {count} residual (share=None) merchant "
                    "streams; at most one residual merchant per group"
                )

    def _validate_overlay_references(self, known_ids: set[str]) -> None:
        """Overlay references must resolve structurally to a merchant price
        authority — not discovered at evaluation time."""
        for s in self.streams:
            if s.contract_role is not ContractRole.SETTLEMENT_OVERLAY:
                continue
            if s.reference_stream_id is not None:
                if s.reference_stream_id == s.stream_id:
                    raise ValueError(
                        f"REVENUE_STREAM_REFERENCE_SELF: stream {s.stream_id!r} "
                        "cannot reference itself as its market-price authority"
                    )
                if s.reference_stream_id not in known_ids:
                    raise ValueError(
                        "REVENUE_OVERLAY_REFERENCE_UNRESOLVABLE: overlay stream "
                        f"{s.stream_id!r} references unknown stream id "
                        f"{s.reference_stream_id!r}"
                    )
                ref = self.stream_by_id(s.reference_stream_id)
                if (
                    ref.stream_type is not RevenueStreamType.MERCHANT
                    or ref.merchant is None
                    or not ref.merchant.merchant_enabled
                ):
                    raise ValueError(
                        "REVENUE_OVERLAY_REFERENCE_NOT_A_MARKET_AUTHORITY: overlay "
                        f"stream {s.stream_id!r} references {s.reference_stream_id!r}, "
                        "which cannot provide the required market reference price"
                    )
            elif self.market_price is None:
                raise ValueError(
                    "REVENUE_OVERLAY_REFERENCE_MARKET_REQUIRED: overlay stream "
                    f"{s.stream_id!r} has no reference_stream_id and the plan has "
                    "no plan-level market price authority"
                )

    def _validate_plan_market_price(self) -> None:
        """Plan-level market price authority (§ Correction B): validated with
        the same rigour as a merchant stream's authority — an overlay-only
        plan must not carry a malformed authority into evaluation.

        Retained canonical Merchant contract (documented): a non-custom
        ``price_scenario`` ("base" | "high" | "low") resolves through
        ``base_price_eur_mwh`` + ``price_escalation_annual`` and IGNORES the
        custom curve; ``"custom"`` requires a usable non-empty curve. Unknown
        scenario strings fail closed.
        """
        if self.market_price is None:
            return
        mp = self.market_price
        if not isinstance(mp, MerchantParams):
            raise ValueError(
                f"REVENUE_PLAN_MARKET_AUTHORITY_INVALID: market_price must be a "
                f"MerchantParams instance, got {type(mp).__name__}"
            )
        if str(mp.price_scenario) not in SUPPORTED_MERCHANT_PRICE_SCENARIOS:
            raise ValueError(
                f"REVENUE_PLAN_MARKET_SCENARIO_UNSUPPORTED: price_scenario="
                f"{mp.price_scenario!r} is not an understood merchant scenario "
                f"(supported: {sorted(SUPPORTED_MERCHANT_PRICE_SCENARIOS)})"
            )
        if mp.price_scenario == "custom" and not mp.custom_price_curve:
            raise ValueError(
                "REVENUE_PLAN_MARKET_CUSTOM_CURVE_REQUIRED: price_scenario='custom' "
                "requires a non-empty custom_price_curve on the plan-level market "
                "authority (no silent fallback to the base price)"
            )
        self._validate_merchant_economics("plan-level market_price", mp)

    @staticmethod
    def _validate_merchant_economics(label: str, mp: MerchantParams) -> None:
        """Finite / non-negative validation for every merchant field that can
        affect ``price_at_year`` or capture selection."""
        def _num(field: str, value: float, *, non_negative: bool = True) -> None:
            if not math.isfinite(float(value)) or (non_negative and value < 0.0):
                raise ValueError(
                    f"REVENUE_PLAN_MARKET_AUTHORITY_INVALID: {label} {field} must "
                    f"be finite and non-negative, got {value!r}"
                )

        _num("base_price_eur_mwh", mp.base_price_eur_mwh)
        _num("price_escalation_annual", mp.price_escalation_annual)
        _num("price_cannibalization_pct", mp.price_cannibalization_pct)
        for i, price in enumerate(mp.custom_price_curve):
            _num(f"custom_price_curve[{i}]", price)
        for name in ("capture_rate_solar", "capture_rate_wind", "capture_rate_bess"):
            rate = float(getattr(mp, name))
            if not math.isfinite(rate) or not (0.0 <= rate <= 1.0):
                raise ValueError(
                    f"REVENUE_PLAN_MARKET_AUTHORITY_INVALID: {label} {name} must "
                    f"be within [0, 1], got {rate!r}"
                )

    # ------------------------------------------------------------------
    # Convenience accessors (deterministic ordering: by stream id)
    # ------------------------------------------------------------------

    def stream_by_id(self, stream_id: str) -> Optional[RevenueStream]:
        for stream in self.streams:
            if stream.stream_id == stream_id:
                return stream
        return None

    def ordered_streams(self) -> tuple[RevenueStream, ...]:
        """Deterministic presentation order (by stream id). Evaluation order
        is allocation-safe regardless of declaration order."""
        return tuple(sorted(self.streams, key=lambda s: s.stream_id))
