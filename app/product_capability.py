"""Canonical FINCO product-capability registry.

This module is the SINGLE SOURCE OF TRUTH for what FINCO supports today.
All public product surfaces (Roadmap, Docs, Known Limitations, API, UI) must
agree with the registry defined here.

STATUS VOCABULARY
-----------------
LIVE          — Implemented, current, intentionally exposed today. May still
                carry known limitations (see ProductCapability.limitations).
PREVIEW       — Implemented but intentionally limited in a documented way.
                Reference viewable; runtime/cloning not released.
IN_DEVELOPMENT — Not an advertised end-user capability today.

A capability may be LIVE while still having known limitations.  Do not
downgrade an actually supported capability to PREVIEW merely because future
enhancement remains.  Likewise, do not advertise a future enhancement as LIVE
because its internal groundwork exists.

PRODUCT AREAS
-------------
product_area="model"  — deterministic financial model vertical (Solar, Wind, etc.)
product_area="radar"  — read-only market-intelligence surface (Radar, RWA, etc.)
product_area="verify" — evidence/verification layer

DERIVED HELPERS
---------------
LIVE_KEYS          — frozenset of capability keys at LIVE status
API_AVAILABLE_KEYS — frozenset of keys with api_available=True
live_vertical_names() — ordered tuple of public_name strings for LIVE model verticals

PROMOTION PROCEDURE
-------------------
To promote a new vertical to LIVE:
1. Add a new ProductCapability with status=ProductStatus.LIVE and all flags set.
2. Run the full test suite — the fail-closed consistency tests will catch any
   surface that has not been updated yet.
Do NOT infer capability status from GitHub PR state or code presence alone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence


class ProductStatus(str, Enum):
    LIVE = "LIVE"
    PREVIEW = "PREVIEW"
    IN_DEVELOPMENT = "IN_DEVELOPMENT"


@dataclass(frozen=True)
class ProductCapability:
    key: str
    public_name: str
    status: ProductStatus
    public_visible: bool
    reference_available: bool
    runnable: bool
    cloneable: bool
    working_copy_editable: bool
    canonical_last_run: bool
    api_available: bool
    export_available: bool
    status_note: str = ""
    limitations: tuple[str, ...] = field(default_factory=tuple)
    product_area: str = "model"


_solar = ProductCapability(
    key="solar",
    public_name="Solar",
    status=ProductStatus.LIVE,
    public_visible=True,
    reference_available=True,
    runnable=True,
    cloneable=True,
    working_copy_editable=True,
    canonical_last_run=True,
    api_available=True,
    export_available=True,
    limitations=(
        "Generic market profiles are illustrative; country-specific tax conclusions require an explicit reviewed policy configuration.",
        "Portfolio-level analysis remains experimental relative to the core single-project engine.",
    ),
)

_wind = ProductCapability(
    key="wind",
    public_name="Wind",
    status=ProductStatus.LIVE,
    public_visible=True,
    reference_available=True,
    runnable=True,
    cloneable=True,
    working_copy_editable=True,
    canonical_last_run=True,
    api_available=True,
    export_available=True,
    limitations=(
        "Generic market profiles are illustrative; country-specific tax conclusions require an explicit reviewed policy configuration.",
        "Portfolio-level analysis remains experimental relative to the core single-project engine.",
    ),
)

_data_center = ProductCapability(
    key="data_center",
    public_name="Data Center",
    status=ProductStatus.LIVE,
    public_visible=True,
    reference_available=True,
    runnable=True,
    cloneable=True,
    working_copy_editable=True,
    canonical_last_run=True,
    api_available=True,
    export_available=True,
    limitations=(
        "Reference model uses a generic 20 MW IT-load configuration; real-asset specifics (colocation structures, hyperscaler contracts) are not represented.",
        "Generic market profiles are illustrative; country-specific tax conclusions require an explicit reviewed policy configuration.",
    ),
)

_storage = ProductCapability(
    key="storage",
    public_name="Storage",
    status=ProductStatus.PREVIEW,
    public_visible=True,
    reference_available=True,
    runnable=False,
    cloneable=False,
    working_copy_editable=False,
    canonical_last_run=False,
    api_available=False,
    export_available=False,
    status_note="Limited/reference workflow. Working-copy runtime not released.",
    limitations=(
        "Reference model is viewable but cannot be run or cloned.",
        "Runtime validation coverage is narrower than Solar/Wind/Data Center/EV Charging.",
        "Working-copy runtime not released.",
    ),
)

_ev_charging = ProductCapability(
    key="ev_charging",
    public_name="EV Charging",
    status=ProductStatus.LIVE,
    public_visible=True,
    reference_available=True,
    runnable=True,
    cloneable=True,
    working_copy_editable=True,
    canonical_last_run=True,
    api_available=True,
    export_available=True,
    limitations=(
        "Charging points are display metadata only; they do not drive modelled revenue.",
        "Payment/network fees are a fixed amount rather than dynamically percentage-linked.",
        "Availability is informational because equivalent full-load hours are net of availability.",
        "Generic market profiles are illustrative; country-specific tax conclusions require an explicit reviewed policy configuration.",
    ),
)

_bnb_rwa = ProductCapability(
    key="bnb_rwa",
    public_name="BNB Tokenized Assets",
    status=ProductStatus.LIVE,
    public_visible=True,
    reference_available=True,
    runnable=False,
    cloneable=False,
    working_copy_editable=False,
    canonical_last_run=False,
    api_available=False,
    export_available=False,
    product_area="radar",
    status_note=(
        "Read-only BNB chain RWA market observations (B1.1) with canonical cross-chain identity "
        "resolution (B1.2) and reference-premium, execution-gap, and exact-identity history "
        "intelligence (B1.3). CoinGecko observation authority. Robinhood registry-first identity "
        "binding — current production observations may carry IDENTITY_UNAVAILABLE if the live "
        "Robinhood registry contains zero chain-56 bindings. B1.3 calculation capability is "
        "implemented and live; numeric premium and execution-gap output appear only when canonical "
        "evidence prerequisites (approved independent token reference, exact execution quote) are "
        "AVAILABLE — absence of evidence yields UNAVAILABLE, never zero. "
        "No trading, no custody, no wallet signing."
    ),
    limitations=(
        "Read-only market observations — no order submission, no custody, no wallet signing.",
        "Canonical cross-chain identity (B1.2) is implemented; Robinhood registry-first binding "
        "is live but may produce IDENTITY_UNAVAILABLE if no chain-56 bindings exist in the "
        "current Robinhood registry — that is truthful, not a capability gap.",
        "B1.3 reference premium requires an approved independent token reference source; no "
        "approved production source may currently exist, so premium may be UNAVAILABLE.",
        "B1.3 execution gap requires an exact execution quote; absence of a quote yields "
        "UNAVAILABLE, never zero.",
        "RWA TVL aggregate is not claimed; observations are per-asset market data only.",
        "CoinGecko is the sole observation authority; data freshness depends on provider availability.",
    ),
)

# Canonical ordered registry — do not reorder without updating tests.
PRODUCT_CAPABILITIES: tuple[ProductCapability, ...] = (
    _solar,
    _wind,
    _data_center,
    _storage,
    _ev_charging,
    _bnb_rwa,
)

LIVE_CAPABILITIES: tuple[ProductCapability, ...] = tuple(
    c for c in PRODUCT_CAPABILITIES if c.status == ProductStatus.LIVE
)
PREVIEW_CAPABILITIES: tuple[ProductCapability, ...] = tuple(
    c for c in PRODUCT_CAPABILITIES if c.status == ProductStatus.PREVIEW
)
IN_DEVELOPMENT_CAPABILITIES: tuple[ProductCapability, ...] = tuple(
    c for c in PRODUCT_CAPABILITIES if c.status == ProductStatus.IN_DEVELOPMENT
)

LIVE_KEYS: frozenset[str] = frozenset(c.key for c in LIVE_CAPABILITIES)
API_AVAILABLE_KEYS: frozenset[str] = frozenset(
    c.key for c in PRODUCT_CAPABILITIES if c.api_available
)


def live_vertical_names() -> tuple[str, ...]:
    """Ordered tuple of public_name strings for LIVE model-area verticals."""
    return tuple(c.public_name for c in LIVE_CAPABILITIES if c.product_area == "model")


def capability_by_key(key: str) -> ProductCapability | None:
    """Return the capability for the given key, or None if not found."""
    for cap in PRODUCT_CAPABILITIES:
        if cap.key == key:
            return cap
    return None


def as_api_dict(cap: ProductCapability) -> dict:
    """Serialise a ProductCapability to a plain dict suitable for an API response."""
    return {
        "key": cap.key,
        "public_name": cap.public_name,
        "status": cap.status.value,
        "public_visible": cap.public_visible,
        "reference_available": cap.reference_available,
        "runnable": cap.runnable,
        "cloneable": cap.cloneable,
        "working_copy_editable": cap.working_copy_editable,
        "canonical_last_run": cap.canonical_last_run,
        "api_available": cap.api_available,
        "export_available": cap.export_available,
        "status_note": cap.status_note,
        "limitations": list(cap.limitations),
        "product_area": cap.product_area,
    }
