"""RC-UX Completion V1 — single mount point for the RC-UX React adapters.

The pinned ``react_workspace_router`` includes this router once; every RC-UX adapter module is added here, so the pinned file does
not change again.  Each adapter lives in its own ``react_*`` module and states its own authority boundary.  Feature flag:
``FINCO_MODEL_REACT_V1`` (checked inside each adapter).
"""
from __future__ import annotations

from fastapi import APIRouter

from app.v2.react_capex import router as _capex_router
from app.v2.react_compare import router as _compare_router
from app.v2.react_compare_projects import router as _compare_projects_router
from app.v2.react_goal_seek_targets import router as _goal_seek_targets_router
from app.v2.react_import import router as _import_router
from app.v2.react_opex_projection import router as _opex_projection_router
from app.v2.react_projects import router as _projects_router
from app.v2.react_trust import router as _trust_router
from app.v2.react_whatif import router as _whatif_router

router = APIRouter()
router.include_router(_compare_router)
router.include_router(_compare_projects_router)
router.include_router(_goal_seek_targets_router)
router.include_router(_import_router)
router.include_router(_capex_router)
router.include_router(_opex_projection_router)
router.include_router(_projects_router)
router.include_router(_trust_router)
router.include_router(_whatif_router)

RCUX_ADAPTERS = ("react_capex", "react_compare", "react_compare_projects", "react_goal_seek_targets", "react_import", "react_opex_projection", "react_projects", "react_trust", "react_whatif")
