"""Explicit FINCO Yield UI integration boundary.

This module composes the feature-gated Yield router without changing
``app.protocol_ui`` package import semantics. It owns no product authority.
"""
from fastapi import APIRouter

from finco_yield.web import router as _yield_router

router = APIRouter()
router.include_router(_yield_router)
