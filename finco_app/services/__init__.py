"""
finco_app.services — Application service layer.

Extraction target (V2-6/V2-8): use-case orchestration. Accepts requests
from the API layer, calls finco_core engine, stores results via persistence,
returns typed responses. The only layer that crosses the core/app boundary.
"""
