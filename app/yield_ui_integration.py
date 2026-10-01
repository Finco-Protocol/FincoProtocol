"""Explicit FINCO Yield public integration boundary.

This module composes the stable canonical ``finco_yield.web.router`` into the
application shell. Feature state is evaluated by canonical Yield handlers at
request time; route topology never depends on environment state at import time.
This module owns no product authority.
"""
from fastapi import APIRouter

from finco_yield.web import router as _yield_router


router = APIRouter()
router.include_router(_yield_router)
