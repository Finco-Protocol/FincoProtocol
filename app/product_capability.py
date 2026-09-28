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

DERIVED HELPERS
---------------
LIVE_KEYS          — frozenset of capability keys at LIVE status
API_AVAILABLE_KEYS — frozenset of keys with api_available=True
live_vertical_names() — ordered tuple of public_name strings for LIVE verticals

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

# Canonical ordered registry — do not reorder without updating tests.
PRODUCT_CAPABILITIES: tuple[ProductCapability, ...] = (
    _solar,
    _wind,
    _data_center,
    _storage,
    _ev_charging,
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
    """Ordered tuple of public_name strings for LIVE model verticals."""
    return tuple(c.public_name for c in LIVE_CAPABILITIES)


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
    }
