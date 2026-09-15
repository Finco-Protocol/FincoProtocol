"""Workbook V2 flag helpers — single source of truth.

All workbook-flag decisions, destination URL construction, and the
``require_v2_active`` FastAPI dependency live here so no router or
service duplicates the logic.

Flag contract (PR-A)
--------------------
FINCO_WORKBOOK_V2
  absent or empty → **ACTIVE** (default-on)
  canonical truthy  → ACTIVE   ("1","true","yes","on")
  canonical falsy   → INACTIVE ("0","false","no","off")
  any other value   → INACTIVE (treated as explicit opt-out)

FINCO_INPUTS_SLICE1_ENABLED
  absent or empty → **ACTIVE** (default-on)
  canonical truthy  → ACTIVE
  canonical falsy   → INACTIVE
  any other value   → INACTIVE
"""
from __future__ import annotations

import os
from urllib.parse import quote, urlencode

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

# ---------------------------------------------------------------------------
# Canonical truthy / falsy sets
# ---------------------------------------------------------------------------

_TRUTHY: frozenset[str] = frozenset({"1", "true", "yes", "on"})
_FALSY: frozenset[str] = frozenset({"0", "false", "no", "off"})


def env_flag(name: str, *, default: bool) -> bool:
    """Parse an environment variable as a boolean with an explicit default.

    - Absent or empty → *default*
    - Canonical truthy → True
    - Canonical falsy  → False
    - Any other value  → False  (unknown value treated as explicit opt-out)
    """
    raw = os.environ.get(name, "").strip().lower()
    if raw == "":
        return default
    if raw in _TRUTHY:
        return True
    return False


# ---------------------------------------------------------------------------
# Per-flag accessors (absent=ACTIVE)
# ---------------------------------------------------------------------------


def workbook_v2_active() -> bool:
    """Return True when Workbook V2 is active.

    absent or empty → active (True); canonical truthy → active; canonical falsy → inactive; unknown value → inactive.
    """
    return env_flag("FINCO_WORKBOOK_V2", default=True)


def inputs_slice1_active() -> bool:
    """Return True when Canonical Inputs Slice 1 is active (default: True when absent)."""
    return env_flag("FINCO_INPUTS_SLICE1_ENABLED", default=True)


# ---------------------------------------------------------------------------
# Destination URL helper
# ---------------------------------------------------------------------------


def project_workbook_url(
    project_code: str,
    *,
    sheet: str | None = None,
) -> str:
    """Return the correct normal-user workbook destination.

    Workbook V2 active (default when flag is absent):
        /v2/workbook?project=<encoded>[&sheet=<encoded>]

    Workbook V2 inactive (explicit falsy flag):
        /?project=<encoded>          (no sheet)
        /?project=<encoded>#inputs   (sheet="inputs")
    """
    code = (project_code or "").strip()
    if workbook_v2_active():
        params: dict[str, str] = {"project": code}
        if sheet:
            params["sheet"] = sheet
        return f"/v2/workbook?{urlencode(params)}"
    else:
        encoded = quote(code, safe="")
        if sheet == "inputs":
            return f"/?project={encoded}#inputs"
        return f"/?project={encoded}"


# ---------------------------------------------------------------------------
# FastAPI dependency — guards all V2 mutation endpoints
# ---------------------------------------------------------------------------


async def require_v2_active() -> None:
    """FastAPI dependency that returns 409 when Workbook V2 is inactive.

    Attach to every V2 POST endpoint.  The GET /v2/workbook handler manages
    its own redirect (not via this dependency) so the 302 beats the 409.
    """
    if not workbook_v2_active():
        raise HTTPException(
            status_code=409,
            detail="Workbook V2 is currently disabled on this server.",
        )
