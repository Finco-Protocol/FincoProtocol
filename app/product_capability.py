"""Canonical FINCO product-capability registry.

This module is the SINGLE SOURCE OF TRUTH for what FINCO supports today.
All public product surfaces (Roadmap, Docs, Known Limitations, API, UI) must
agree with the registry defined here.

EV Promotion procedure
----------------------
When EV Charging is ready to ship:
1. Change ``_ev_charging.status`` to ``ProductStatus.LIVE``
2. Set all capability flags to ``True`` (reference_available, runnable, …)
3. Remove ``status_note``
4. Run the full test suite — the fail-closed consistency tests will catch any
   surface that has not been updated yet.
Do NOT infer EV availability from GitHub PR state or code presence.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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
)

_ev_charging = ProductCapability(
    key="ev_charging",
    public_name="EV Charging",
    status=ProductStatus.IN_DEVELOPMENT,
    public_visible=True,
    reference_available=False,
    runnable=False,
    cloneable=False,
    working_copy_editable=False,
    canonical_last_run=False,
    api_available=False,
    export_available=False,
    status_note=(
        "In development. To promote: change status to LIVE, set all capability "
        "flags to True, remove this note, run full test suite."
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
