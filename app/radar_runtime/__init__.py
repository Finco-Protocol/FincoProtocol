"""Post-R12 acquisition runtime: one acquisition -> one immutable
observation snapshot -> one snapshot_id; all later reads reuse that
exact snapshot.

Orchestration only — R0-R12 financial/market authority remains frozen
and untouched.  Provider callables are wired at composition time to the
frozen R0-R12 provider adapters; this package never re-implements
provider parsing and never depends on private live_proof orchestration.
"""
