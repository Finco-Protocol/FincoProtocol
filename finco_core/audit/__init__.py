"""
finco_core.audit — Typed audit output contract.

Extraction target (V2-5): AuditResult — a fully typed, immutable record
produced after EngineResult. The audit layer reads EngineResult; it does
not mutate it. No post-engine modification of financial fields is permitted.

The audit layer is the only place where bridge reconciliation fields,
diagnostic traces, and formula provenance are assembled for export.
"""
