"""FINCO Utility Registry — single source of truth for P4 capabilities.

Three stable machine identifiers define the FINCO capability surface.
Templates, API responses, and access decisions all read from UTILITY_REGISTRY;
constants are never duplicated in Jinja or caller code.
"""
from __future__ import annotations

from typing import NamedTuple


# ── Stable machine identifiers ───────────────────────────────────────────────
# These strings are permanent.  Do NOT rename them; downstream consumers
# (API contracts, access logs, tests) depend on exact string equality.

FINCO_COMPUTE = "FINCO_COMPUTE"
FINCO_VERIFY_PUBLISH = "FINCO_VERIFY_PUBLISH"
FINCO_INTELLIGENCE = "FINCO_INTELLIGENCE"


# ── Typed metadata ───────────────────────────────────────────────────────────

class FincoUtility(NamedTuple):
    identifier: str
    display_name: str
    description: str


# ── Authoritative registry ───────────────────────────────────────────────────

UTILITY_REGISTRY: dict[str, FincoUtility] = {
    FINCO_COMPUTE: FincoUtility(
        identifier=FINCO_COMPUTE,
        display_name="Compute",
        description="Model computation and financial analysis.",
    ),
    FINCO_VERIFY_PUBLISH: FincoUtility(
        identifier=FINCO_VERIFY_PUBLISH,
        display_name="Verify & Publish",
        description="Run integrity and evidence publication services.",
    ),
    FINCO_INTELLIGENCE: FincoUtility(
        identifier=FINCO_INTELLIGENCE,
        display_name="Intelligence",
        description="Radar and protocol intelligence services.",
    ),
}
