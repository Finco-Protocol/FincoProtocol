"""
financial_engine — Clean parallel financial engine (Phase 2A operating core).

This package implements the first executable layer of the clean financial engine.
Phase 2A scope: period grid, production, revenue, OPEX, EBITDA, book/tax depreciation.

Out of scope (Phase 2B+): tax, CFADS, debt, SHL, waterfall, financial statements, returns.

Import boundary
---------------
This package must NOT import from:
  app, main_web, main_api, finco_parity, persistence, FastAPI, Jinja, requests,
  openpyxl, pandas (unless an already-reused leaf requires it — see reuse_inventory.md).

It may import from:
  finco_core.engine, finco_core.revenue, finco_core.opex, finco_core.depreciation,
  finco_core.inputs
"""
from financial_engine.version import ENGINE_VERSION

__all__ = ["ENGINE_VERSION"]
