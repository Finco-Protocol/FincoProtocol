"""Minimal ASGI app for the RC-M multi-process creation tests (not collected by pytest, never imported by production code).

It mounts exactly the routers the React New Project wizard uses, on the SAME database file as its sibling processes
(``FINCO_DB_PATH``).  ``RCM_CRASH_AT`` makes THIS process terminate abruptly (no cleanup, no response) at one exact point of the
create, to prove what the other processes then observe:

* ``after_row``       — the project row (with its request identity) is committed; no workspace, scenario or seed exists;
* ``mid_seed_lines``  — the seed-lines transaction is open (``BEGIN IMMEDIATE``, first line written) and uncommitted;
* ``before_response`` — the project is COMPLETE; the response is never sent.

``RCM_LEASE_SECONDS`` overrides the lease after which an interrupted create is archived as abandoned.
"""
from __future__ import annotations

import os

from fastapi import FastAPI

from app.services import project_library_service as pls
from app.services import reference_seed_service as seed
from app.v2 import react_new_project as adapter
from app.v2.react_poc_router import router as poc_router
from app.v2.react_workspace_router import router as workspace_router
from app.v2.router import router as v2_router

app = FastAPI()
app.include_router(v2_router, prefix="/v2")
app.include_router(workspace_router, prefix="/v2")
app.include_router(poc_router, prefix="/v2")

if os.environ.get("RCM_LEASE_SECONDS"):
    pls.CREATE_INCOMPLETE_LEASE_SECONDS = int(os.environ["RCM_LEASE_SECONDS"])


def _die(*_a, **_k):
    os._exit(137)


_CRASH = os.environ.get("RCM_CRASH_AT", "")
if _CRASH == "after_row":
    _real_save = pls.save_workspace_state

    def _save_unless_working_copy(*args, **kwargs):
        if str(kwargs.get("user_id", "")).startswith("rcm-mp-"):
            _die()
        return _real_save(*args, **kwargs)
    pls.save_workspace_state = _save_unless_working_copy
elif _CRASH == "mid_seed_lines":
    seed.create_opex_line = _die
elif _CRASH == "before_response":
    adapter._project_payload = _die
