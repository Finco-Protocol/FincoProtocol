"""Minimal ASGI app for the RC-M multi-process idempotency tests (not collected by pytest, never imported by production code).

It mounts exactly the routers the React New Project wizard uses, on the SAME database file as its sibling processes
(``FINCO_DB_PATH``).  ``RCM_CRASH_AT`` makes THIS process terminate abruptly (no cleanup, no response) at one exact point of the
create, to prove what the other processes then observe:

* ``after_create_before_finish`` — the project exists, the claim is still CLAIMED, the stamp is not written;
* ``after_finish_before_stamp``  — the project exists, the claim is DONE, the stamp is not written.
"""
from __future__ import annotations

import os

from fastapi import FastAPI

from app.v2 import react_request_claims as claims
from app.v2.react_poc_router import router as poc_router
from app.v2.react_workspace_router import router as workspace_router
from app.v2.router import router as v2_router

app = FastAPI()
app.include_router(v2_router, prefix="/v2")
app.include_router(workspace_router, prefix="/v2")
app.include_router(poc_router, prefix="/v2")

_CRASH = os.environ.get("RCM_CRASH_AT", "")
if _CRASH == "after_create_before_finish":
    def _die(*_a, **_k):
        os._exit(137)
    claims.finish = _die
elif _CRASH == "after_finish_before_stamp":
    _real_finish = claims.finish

    def _finish_then_die(*args, **kwargs):
        _real_finish(*args, **kwargs)
        os._exit(137)
    claims.finish = _finish_then_die
