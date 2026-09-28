"""Typed contracts for the experimental FINCO RWA Reflex state.

Reflex is strictly downstream of FINCO's canonical authority layer.  Context may
add versioned statistics for an experiment, but never establishes identity,
reference prices, premium, execution truth, or canonical evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from finco_radar.assets.contracts import AssetKey, normalize_asset_uid
from finco_radar.authority.contracts import AuthorityState


REFLEX_SCHEMA_VERSION = "RWA_REFLEX_STATE_V2"
CONTEXT_BUILDER_VERSION = "RWA_REFLEX_CONTEXT_BUILDER_V2"
HISTORY_METHODOLOGY_VERSION = "RWA_REFLEX_PREMIUM_HISTORY_V2"
LIQUIDITY_METHODOLOGY_VERSION = "RWA_REFLEX_LIQUIDITY_CONTEXT_V2"
SESSION_RESOLVER_VERSION = "RWA_REFLEX_SESSION_V1"


class MarketSession(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PRE_MARKET = "PRE_MARKET"
    AFTER_HOURS = "AFTER_HOURS"
    UNKNOWN = "UNKNOWN"


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _finite(value: Decimal | None, name: str, *, nonnegative: bool = False) -> None:
    if value is None:
        return
    if not value.is_finite() or (nonnegative and value < 0):
        qualifier = "finite and nonnegative" if nonnegative else "finite"
        raise ValueError(f"{name} must be {qualifier} when present")


@dataclass(frozen=True)
class BasisHistoryStats:
    """Pre-t0 canonical premium history; no future observations are permitted."""

    mean_bps: Decimal
    std_bps: Decimal
    sample_count: int
    observed_at: datetime
    source: str
    window: str
    median_bps: Decimal | None = None
    methodology_version: str = HISTORY_METHODOLOGY_VERSION

    def __post_init__(self) -> None:
        _finite(self.mean_bps, "mean_bps")
        _finite(self.std_bps, "std_bps", nonnegative=True)
        _finite(self.median_bps, "median_bps")
        if isinstance(self.sample_count, bool) or self.sample_count < 2:
            raise ValueError("sample_count must be an integer >= 2")
        _aware(self.observed_at, "observed_at")
        if not self.source.strip() or not self.window.strip() or not self.methodology_version.strip():
            raise ValueError("history source, window and methodology are required")


@dataclass(frozen=True)
class LiquidityContext:
    """Optional venue observation; never used as canonical identity authority."""

    observed_at: datetime
    source: str
    liquidity_usd: Decimal | None = None
    depth_1pct_usd: Decimal | None = None
    methodology_version: str = LIQUIDITY_METHODOLOGY_VERSION
    venue_id: str | None = None

    def __post_init__(self) -> None:
        _aware(self.observed_at, "observed_at")
        if not self.source.strip() or not self.methodology_version.strip():
            raise ValueError("liquidity source and methodology are required")
        if self.venue_id is not None and not self.venue_id.strip():
            raise ValueError("venue_id must be named when present")
        _finite(self.liquidity_usd, "liquidity_usd", nonnegative=True)
        _finite(self.depth_1pct_usd, "depth_1pct_usd", nonnegative=True)
        if self.liquidity_usd is None and self.depth_1pct_usd is None:
            raise ValueError("liquidity context needs at least one observed quantity")


@dataclass(frozen=True)
class RwaReflexContext:
    market_session: MarketSession = MarketSession.UNKNOWN
    basis_history: BasisHistoryStats | None = None
    liquidity: LiquidityContext | None = None
    session_source: str = "UNSPECIFIED"
    session_resolver_version: str = SESSION_RESOLVER_VERSION

    def __post_init__(self) -> None:
        if not self.session_source.strip() or not self.session_resolver_version.strip():
            raise ValueError("session source and resolver version are required")


@dataclass(frozen=True)
class ReflexProvenance:
    """Evidence identity material retained in FINCO, never sent to Jev."""

    registry_source: str | None
    registry_observed_at: datetime | None
    history_source: str | None = None
    history_observed_at: datetime | None = None
    history_window: str | None = None
    history_sample_count: int | None = None
    history_mean_bps: Decimal | None = None
    history_std_bps: Decimal | None = None
    history_median_bps: Decimal | None = None
    history_methodology_version: str | None = None
    liquidity_source: str | None = None
    liquidity_observed_at: datetime | None = None
    liquidity_methodology_version: str | None = None
    liquidity_venue_id: str | None = None
    session_source: str = "UNSPECIFIED"
    session_resolver_version: str = SESSION_RESOLVER_VERSION
    context_builder_version: str = CONTEXT_BUILDER_VERSION

    def __post_init__(self) -> None:
        for name in ("registry_observed_at", "history_observed_at", "liquidity_observed_at"):
            value = getattr(self, name)
            if value is not None:
                _aware(value, name)
        for name in ("history_mean_bps", "history_std_bps", "history_median_bps"):
            _finite(getattr(self, name), name, nonnegative=name == "history_std_bps")
        if self.history_sample_count is not None and self.history_sample_count < 2:
            raise ValueError("history_sample_count must be >= 2")
        if not self.session_source.strip() or not self.session_resolver_version.strip() or not self.context_builder_version.strip():
            raise ValueError("provenance versions/sources must be named")


@dataclass(frozen=True)
class RwaReflexState:
    """Deterministic state. Canonical identity stays in FINCO and is blinded from Jev."""

    economic_asset_uid: str | None
    canonical_token: AssetKey
    state: AuthorityState
    reason: str | None
    market_session: MarketSession
    underlying_reference_usd: Decimal | None
    token_reference_usd: Decimal | None
    reference_premium_bps: Decimal | None
    execution_impact_bps: Decimal | None
    effective_gap_bps: Decimal | None
    basis_z_score: Decimal | None
    liquidity_usd: Decimal | None
    depth_1pct_usd: Decimal | None
    observed_at: datetime | None
    evidence_sources: tuple[str, ...]
    structural_premium_bps: Decimal | None = None
    premium_deviation_bps: Decimal | None = None
    provenance: ReflexProvenance | None = None
    context_warnings: tuple[str, ...] = ()
    schema_version: str = REFLEX_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != REFLEX_SCHEMA_VERSION:
            raise ValueError("unsupported Reflex schema version")
        if self.economic_asset_uid is not None:
            object.__setattr__(self, "economic_asset_uid", normalize_asset_uid(self.economic_asset_uid))
        if self.observed_at is not None:
            _aware(self.observed_at, "observed_at")
        for name in (
            "underlying_reference_usd", "token_reference_usd", "reference_premium_bps",
            "execution_impact_bps", "effective_gap_bps", "basis_z_score",
            "liquidity_usd", "depth_1pct_usd", "structural_premium_bps", "premium_deviation_bps",
        ):
            _finite(getattr(self, name), name, nonnegative=name in ("liquidity_usd", "depth_1pct_usd"))
        if any(not source.strip() for source in self.evidence_sources):
            raise ValueError("evidence sources must be named")
        if self.state is AuthorityState.AVAILABLE:
            if self.economic_asset_uid is None:
                raise ValueError("available Reflex state requires canonical economic identity")
            if self.underlying_reference_usd is None or self.token_reference_usd is None:
                raise ValueError("available Reflex state requires both reference layers")
            if self.reference_premium_bps is None or self.observed_at is None:
                raise ValueError("available Reflex state requires premium and observation time")
            if self.provenance is None:
                raise ValueError("available Reflex state requires reconstructable provenance")
