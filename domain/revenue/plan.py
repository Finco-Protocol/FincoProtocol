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
- DOUBLE-COUNTING GUARD: generation-backed primary streams in the same
  allocation group may not allocate more than 100% of eligible generation.
  Shares are never silently normalized.
- PRIMARY vs OVERLAY: a stream is either a PHYSICAL PRIMARY ALLOCATION
  (consumes eligible generation volume: PPA, Merchant, fixed/indexed/
  awarded tariffs) or a FINANCIAL SETTLEMENT OVERLAY (applies to an
  explicitly declared contractual volume on top of the market sale:
  CfD settlement, sliding premium support). A CfD therefore never consumes
  an additional physical 100% volume, and a market + CfD structure is a
  first-class valid plan.
- MISSING != ZERO, UNAVAILABLE != ZERO, INACTIVE != UNAVAILABLE,
  EXPIRED != INVALID: typed statuses, no silent zero substitution.
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

    ``eligible_generation_mwh`` is resolved per period by the evaluation
    engine; the group itself only declares the sharing policy. Overlay
    streams never participate in group capacity.
    """

    group_id: str
    description: str = ""


@dataclass(frozen=True)
class RevenueStream:
    """One typed revenue contract within a RevenuePlan.

    Volume (primary streams):
        volume_share is the fraction of the allocation group's eligible
        generation purchased by this contract. ``None`` is legal ONLY for a
        MERCHANT stream and means the RESIDUAL unallocated volume of the
        group (eligible minus all explicit primary shares, floor zero).
    Volume (overlay streams):
        volume_share declares the contractual settlement volume as a
        fraction of the group's eligible generation (e.g. a CfD written for
        70% of production). It consumes no allocation capacity.

    Price authority (reused, never duplicated):
        PPA streams resolve price through ``ppa: PPAParams``;
        MERCHANT streams through ``merchant: MerchantParams`` (custom
        curves, escalation, cannibalization, capture rates preserved);
        FIT_FIXED / FIT_PREMIUM / AUCTION_AWARDED_TARIFF through
        ``fit: FeedInTariffParams``; CFD through ``cfd: CfDParams``.
        Overlay streams resolve their REFERENCE market price from
        ``reference_stream_id`` (a MERCHANT stream in the plan) or from the
        plan-level ``market_price`` authority when None.

    Term: ``start_year`` is the 1-based model year the contract begins;
        ``term_years`` None means unlimited. Mirrors the existing domain
        is_active semantics exactly.
    """

    stream_id: str
    stream_type: RevenueStreamType
    name: str = ""

    enabled: bool = True
    start_year: int = 1
    term_years: Optional[float] = None  # None = unlimited

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
        """Existing domain term semantics: start ≤ year ≤ start+term−1."""
        if not self.enabled:
            return False
        if self.start_year > 1 and year < self.start_year:
            return False
        if self.term_years is not None and self.term_years <= 0:
            return False
        if self.term_years is not None:
            return self.start_year <= year <= self.start_year + self.term_years - 1
        return year >= self.start_year

    @property
    def contract_role(self) -> ContractRole:
        return contract_role_for(self.stream_type)

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
        if self.term_years is not None:
            if not math.isfinite(float(self.term_years)) or self.term_years < 0:
                raise ValueError(
                    f"REVENUE_STREAM_TERM_INVALID: stream {sid!r} term_years must be "
                    "a finite non-negative number or None"
                )
        if self.start_year < 1 or not math.isfinite(float(self.start_year)):
            raise ValueError(
                f"REVENUE_STREAM_START_INVALID: stream {sid!r} start_year must be a "
                "finite integer >= 1"
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
        # Price-authority presence per type.
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
            if not math.isfinite(self.indexed_fit_base_tariff_eur_mwh) or (
                self.indexed_fit_base_tariff_eur_mwh < 0.0
            ):
                raise ValueError(
                    f"REVENUE_STREAM_INDEXED_FIT_TARIFF_INVALID: stream {sid!r} base "
                    "tariff must be finite and non-negative"
                )
            if not self.indexed_fit_index_factors:
                raise ValueError(
                    f"REVENUE_STREAM_INDEX_FACTORS_REQUIRED: stream {sid!r} needs an "
                    "explicit index factor schedule (no silent implicit index)"
                )
            if any((not math.isfinite(f)) or f < 0.0 for f in self.indexed_fit_index_factors):
                raise ValueError(
                    f"REVENUE_STREAM_INDEX_FACTORS_INVALID: stream {sid!r} index "
                    "factors must be finite and non-negative"
                )
        else:
            attr, authority = needs[self.stream_type]
            if authority is None:
                raise ValueError(
                    f"REVENUE_STREAM_PRICE_AUTHORITY_REQUIRED: stream {sid!r} "
                    f"({self.stream_type.value}) requires the {attr!r} price authority"
                )
        # Overlay streams need a reachable reference market price authority.
        if self.stream_type in SETTLEMENT_OVERLAY_TYPES and self.reference_stream_id:
            if self.reference_stream_id == self.stream_id:
                raise ValueError(
                    f"REVENUE_STREAM_REFERENCE_SELF: stream {sid!r} cannot reference "
                    "itself as its market-price authority"
                )
        # Negative price authorities where policy disallows them.
        if self.ppa is not None and self.ppa.ppa_base_price_eur_mwh < 0.0:
            raise ValueError(
                f"REVENUE_STREAM_PPA_PRICE_NEGATIVE: stream {sid!r}"
            )
        if self.merchant is not None and self.merchant.base_price_eur_mwh < 0.0:
            raise ValueError(
                f"REVENUE_STREAM_MERCHANT_PRICE_NEGATIVE: stream {sid!r}"
            )
        if self.fit is not None and (
            self.fit.fit_price_eur_mwh < 0.0 or self.fit.premium_eur_mwh < 0.0
        ):
            raise ValueError(
                f"REVENUE_STREAM_FIT_PRICE_NEGATIVE: stream {sid!r}"
            )
        if self.cfd is not None and self.cfd.strike_price_eur_mwh < 0.0:
            raise ValueError(
                f"REVENUE_STREAM_CFD_STRIKE_NEGATIVE: stream {sid!r}"
            )
        if self.fit is not None and (
            self.fit.premium_floor_eur_mwh > 0.0
            and self.fit.premium_cap_eur_mwh > 0.0
            and self.fit.premium_floor_eur_mwh > self.fit.premium_cap_eur_mwh
        ):
            raise ValueError(
                f"REVENUE_STREAM_FLOOR_ABOVE_CAP: stream {sid!r} premium floor "
                "exceeds premium cap"
            )
        if self.ppa is not None and (
            self.ppa.ppa_price_floor > 0.0
            and self.ppa.ppa_price_cap > 0.0
            and self.ppa.ppa_price_floor > self.ppa.ppa_price_cap
        ):
            raise ValueError(
                f"REVENUE_STREAM_FLOOR_ABOVE_CAP: stream {sid!r} PPA price floor "
                "exceeds price cap"
            )


@dataclass(frozen=True)
class RevenuePlan:
    """Typed multi-stream revenue plan for one project.

    Validation is fail-closed at construction via ``RevenuePlan.create``;
    the raw constructor stays permissive for dataclass tooling but every
    evaluation entry point re-checks ``validated`` first.
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
        """Fail-closed plan validation (duplicate ids, allocation capacity,
        overlay reference reachability)."""
        seen: set[str] = set()
        for stream in self.streams:
            stream.validate()
            if stream.stream_id in seen:
                raise ValueError(
                    f"REVENUE_STREAM_ID_DUPLICATE: {stream.stream_id!r} appears "
                    "more than once in the plan"
                )
            seen.add(stream.stream_id)

        # Allocation capacity: primary streams share group eligible volume.
        shares_by_group: dict[str, float] = {}
        residual_by_group: dict[str, int] = {}
        for stream in self.streams:
            if stream.contract_role is not ContractRole.PRIMARY_ALLOCATION:
                continue
            if not stream.enabled:
                continue
            group = stream.allocation_group
            if stream.volume_share is None:
                # residual merchant: at most one per group
                residual_by_group[group] = residual_by_group.get(group, 0) + 1
                continue
            shares_by_group[group] = shares_by_group.get(group, 0.0) + float(stream.volume_share)
        for group, total in shares_by_group.items():
            if total > 1.0 + 1e-12:
                raise ValueError(
                    f"REVENUE_ALLOCATION_EXCEEDS_ELIGIBLE_GENERATION: allocation "
                    f"group {group!r} contracts {total:.6f} of eligible generation "
                    "(explicit shares are never normalized)"
                )
        for group, count in residual_by_group.items():
            if count > 1:
                raise ValueError(
                    f"REVENUE_RESIDUAL_MERCHANT_AMBIGUOUS: allocation group "
                    f"{group!r} declares {count} residual (share=None) merchant "
                    "streams; at most one residual merchant per group"
                )

        # Overlay reference routing must resolve.
        overlay_refs = {
            s.reference_stream_id
            for s in self.streams
            if s.contract_role is ContractRole.SETTLEMENT_OVERLAY and s.reference_stream_id
        }
        missing = overlay_refs - seen
        if missing:
            raise ValueError(
                f"REVENUE_OVERLAY_REFERENCE_UNRESOLVABLE: overlay streams reference "
                f"unknown stream ids {sorted(missing)}"
            )
        for s in self.streams:
            if s.contract_role is ContractRole.SETTLEMENT_OVERLAY and s.reference_stream_id is None:
                if self.market_price is None:
                    raise ValueError(
                        "REVENUE_OVERLAY_REFERENCE_MARKET_REQUIRED: overlay stream "
                        f"{s.stream_id!r} has no reference_stream_id and the plan has "
                        "no plan-level market price authority"
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
