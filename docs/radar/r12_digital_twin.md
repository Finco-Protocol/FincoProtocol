# FINCO Radar R12 — DIGITAL TWIN AUTHORITY

## Objective

R12 constructs a deterministic, typed **Digital Twin state snapshot** from independently verified R11 evidence. It is a state authority, not a new valuation engine.

> **A verified Digital Twin is a deterministic representation of verified evidence. It is not a statement that the underlying economic assumptions or market observations are objectively true.**

## Authority chain

```text
R0 quotes → R1 identity → R2 gap → R3 liquidity → R4 reference
→ R5 signals → R6 terminal → R7 cross-market → R8 execution
→ R9 asset graph → R10 model × radar → R11 verification → R12 digital twin
```

R12 consumes only R11 `VERIFICATION_OK` evidence. It does NOT independently redo R10/R9/R8/R7 verification.

## What Digital Twin means here

The Digital Twin is an organized, deterministic representation of verified economic states (identity, deployment, reference, execution, model, verification). It is not itself a market price, fair value, execution price, trading recommendation, NAV, forecast, oracle, valuation, or blockchain attestation.

## Stable twin identity

`digital-twin:<sha256>` derived from canonical `{economicAssetUid, economicNodeId}` only. Stable across snapshots of the same economic asset. Never includes price, timestamp, snapshot digest, or model value.

## Snapshot identity

`r12SnapshotDigest`: canonical SHA-256 over the complete serialized R12 evidence excluding only `r12SnapshotDigest`.

## Status semantics

- `DIGITAL_TWIN_OK`: all required twin components available and authority-consistent
- `DIGITAL_TWIN_PARTIAL`: R11 verification valid, one or more economic twin components honestly unavailable
- `DIGITAL_TWIN_INPUT_INVALID`: malformed R12/R11 serialized boundary
- `DIGITAL_TWIN_EVIDENCE_MISMATCH`: digest/identity/lineage mismatch
- `DIGITAL_TWIN_VERIFICATION_REJECTED`: R11 status not `VERIFICATION_OK`

## Component semantics

Six mandatory components: `IDENTITY_GRAPH`, `DEPLOYMENT_STATE`, `REFERENCE_STATE`, `EXECUTION_STATE`, `MODEL_STATE`, `VERIFICATION_STATE`. Each carries `AVAILABLE`, `UNAVAILABLE`, or `NOT_APPLICABLE` state with source phase and digest.

## R11 prerequisite

R12 requires `VERIFICATION_OK` from R11. It validates R11 integrity independently (local digest reconstruction) plus the frozen R11 verifier as secondary cross-check.

## Live no-model behavior

Current live R10 subject has no model binding. Expected R12 state: `DIGITAL_TWIN_PARTIAL` with `MODEL_COMPONENT_UNAVAILABLE` gap and preserved upstream `MODEL_BINDING_UNAVAILABLE` gap.

## Synthetic provenance

R12 synthetic state is derived from the verified causal chain (R11/R10/R9/R8/R7 synthetic flags), never from a caller boolean.

## Deterministic serialization

Canonical ordering before hashing. No sort after digest. Exact Decimal textual representation from upstream evidence. No rounding of economic values.

## Known limitations

- No source-proven live model binding
- No FX authority in R10 v1
- No discount-rate policy authority
- No on-chain anchoring
- No R12 streaming/autonomous refresh/event bus

## Reproduction commands

```bash
pytest -q tests/test_radar_r12_digital_twin.py   # 21 offline deterministic tests
python -m finco_radar.r12.live_proof             # live proof (re-runs frozen chain)
```
