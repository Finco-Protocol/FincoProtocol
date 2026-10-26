"""Minimal real ASGI app for D-029 multi-worker / multi-process evidence (not a pytest module).

Serves the REAL ``/v2/workbook/run`` route against a shared SQLite file.  Every engine
execution appends one line to FINCO_D029_COUNTER so cross-process execution counts are exact.
"""
from __future__ import annotations

import os

from fastapi import FastAPI

from app.persistence import db

db.DB_PATH = os.environ["FINCO_D029_DB"]

import app.api.project_runner as _pr  # noqa: E402
from app.v2.router import router  # noqa: E402

_original = _pr.run_project
_counter = os.environ.get("FINCO_D029_COUNTER")


def _counted(*args, **kwargs):
    if _counter:
        with open(_counter, "a", encoding="utf-8") as handle:
            handle.write("%d\n" % os.getpid())
    return _original(*args, **kwargs)


_pr.run_project = _counted
app = FastAPI()
app.include_router(router, prefix="/v2")
