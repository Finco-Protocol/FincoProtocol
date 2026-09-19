"""FINCO Radar v1 UI — narrow read-only product surface over the frozen
R0–R12 authority and the canonical P1 acquisition runtime.

Core product rule: one refresh → one P1 immutable snapshot_id → all
visible Radar panels + Evidence Inspector reference that exact snapshot.

This package is PRESENTATION + COMPOSITION only.  It never recomputes
market/reference/GAP values, never redefines freshness or verification,
and never modifies frozen authority.
"""
