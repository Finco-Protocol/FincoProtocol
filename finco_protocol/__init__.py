"""FINCO Protocol — cross-surface verification primitives.

The package sits above FINCO Model and FINCO Radar.  It does not own either
calculation engine.  Its role is to validate already-produced evidence and
create deterministic, content-addressed verification artifacts that can later
be anchored by an on-chain protocol without moving financial calculations
on-chain.
"""

__all__ = ["verification"]
