"""Protocol shell package integration hooks.

Yield-local runtime is mounted here without changing global Product Truth navigation/status surfaces owned by PR #147.
"""
from .router import router
from finco_yield.web import router as _yield_router

router.include_router(_yield_router)

__all__ = ["router"]
