"""RC-UX Completion V1 — single mount point for the RC-UX React adapters.

The pinned ``react_workspace_router`` includes this router once; every RC-UX adapter module is added here, so the pinned file does
not change again.  Each adapter lives in its own ``react_*`` module and states its own authority boundary.  Feature flag:
``FINCO_MODEL_REACT_V1`` (checked inside each adapter).
"""
from __future__ import annotations

from fastapi import APIRouter

from app.v2.react_compare import router as _compare_router

router = APIRouter()
router.include_router(_compare_router)

RCUX_ADAPTERS = ("react_compare",)
