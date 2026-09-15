"""
app.v2 — Workbook V2 feature-flagged shell.

Activated when the environment variable ``FINCO_WORKBOOK_V2`` is set to a
truthy value (``"1"``, ``"true"``, ``"yes"`` — case-insensitive).

When the flag is absent or falsy the router is not mounted and the existing
legacy routes in ``main_web.py`` are unaffected.

Architecture position:

  main_web.py
      │
      ├── (flag OFF) existing legacy @app routes continue to serve everything
      │
      └── (flag ON)  app.include_router(v2_router, prefix="/v2")
                          │
                          └── app/v2/router.py    ← GET /v2/workbook
                                  │
                                  └── WorkbookService (PR 4)
                                          ├── build_draft_input_set_from_workspace()
                                          └── get_runtime_result()

Design invariants:
- No engine, persistence, scenario, export, or parity changes.
- No reuse of legacy ambiguous state helpers.
- No sheet migration in this PR (PR 6).
- The flag gate lives entirely in main_web.py; this package is pure routing.
"""
