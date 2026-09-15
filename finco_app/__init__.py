"""
finco_app — FINCO Protocol v2 application layer.

This package wraps finco_core with a deployable application: an API,
service orchestration, and persistence. It depends on finco_core and
has no dependency on finco_ui or finco_parity.

Subpackages (populated during V2-6 through V2-8):
    api         — FastAPI routes, request/response models, OpenAPI schema
    services    — Use-case orchestration (run engine, store result, fetch audit)
    persistence — Project, scenario, run, audit snapshot, export storage
"""
