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

## Correction A — serialized verification + provenance closure (F03)

Core rule: **R12_CONTENT_INTEGRITY != R12_COMPOSITION_AUTHORITY**.

`verify_serialized_r12_evidence` accepts an untrusted artifact only after
BOTH layers hold:

1. **Serialized/content integrity** — exact schema/phase, typed status,
   timezone-aware `generatedAt`, valid `gitHead`, exact-bool `synthetic`,
   non-empty identity, exact canonical `twinId`, exact R12 boundaries,
   exact R11 freeze anchor/tree, closed component vocabulary (mandatory
   components exactly once, `COMPARABILITY_STATE` at most once, unknown
   ids rejected, valid sourcePhase/source-digest semantics), typed gap
   and payload containers, exact R11/R10 digest-lineage bindings
   (`verification.r11SnapshotDigest == subjectR11Evidence.r11SnapshotDigest`;
   `verification.subjectR10SnapshotDigest == subjectR11Evidence
   .subjectSnapshotDigest == subjectEvidence.r10SnapshotDigest`),
   recomputed check counts, and `r12SnapshotDigest` reconstruction.
2. **Canonical R12 composition replay** — the embedded
   `subjectR11Evidence` must pass the corrected canonical R11 serialized
   verifier (PR #32 authority); the ONE canonical builder
   `build_digital_twin` is replayed from that exact subject under the
   serialized `generatedAt`/`gitHead` and must reproduce the artifact
   exactly.

Further Correction A properties:

- **Authority pins** — `R11_FREEZE_ANCHOR`/`R11_FREEZE_TREE` identify the
  corrected canonical R0-R11 main consumed by R12 (`537d255e…` /
  `443989d6…`); the historical R10 identity (`7ffaf3b1…` / `fba9d76d…`)
  is preserved.  Governance baseline and historical verification identity
  are separate concepts.
- **Stable twin identity** — `twinId = "digital-twin:" + SHA256(canonical
  JSON of {"economicAssetUid", "economicNodeId"})`; outer identity must
  exactly match the embedded verified R11/R10 identity.
- **No caller synthetic authority** — the `synthetic` parameter was
  removed from `build_digital_twin`; synthetic state is derived only from
  the verified causal chain with exact-boolean validation (no
  `bool(value)` coercion).
- **Fail-closed containers** — no `value or {}` / `value or []`
  fallbacks; malformed evidence structures raise typed `TwinError`, and
  no raw exception escapes the serialized boundary.
- **Status semantics** — `DIGITAL_TWIN_OK` requires every mandatory
  component AVAILABLE and zero R12 gaps; otherwise `DIGITAL_TWIN_PARTIAL`
  with typed R12 gaps; upstream R10/R11 gaps are preserved separately.
- **Live provenance** — the R12 live proof consumes the ONE canonical R11
  artifact object generated by the frozen R11 proof (no independent R11
  regeneration); the outer R12 `gitHead` is the actual R12 HEAD via the
  repository-approved `_git_head` helper; the manifest binds the R12/R11
  snapshot digests, the R10 snapshot digest through the verified R11
  subject binding, evidence JSON SHA256, consumed R11 freeze anchor/tree,
  identity, twinId, status, synthetic, boundaries, component count and
  recomputed check counts.
- **Adversarial matrix** — 25 resealed attacks (digest recomputation
  included) all fail, including freshness laundering and a same-identity
  different-R11-observation substitution; canonical partial, full-model,
  JSON round-trip and replay-equivalence controls pass.

## Reproduction commands

```bash
pytest -q tests/test_radar_r12_digital_twin.py   # 51 offline deterministic tests
python -m finco_radar.r11.live_proof             # frozen R11 canonical artifact
RADAR_R11_EVIDENCE_PATH=artifacts/radar_r11_verification_evidence.json python -m finco_radar.r12.live_proof             # live twin consuming that exact object
```
