# FINCO Radar R11 — INDEPENDENT VERIFICATION AUTHORITY

## What R11 verifies

R11 is an independent, deterministic, fail-closed verification layer over
**serialized R10 evidence**:

```text
serialized R10 evidence
    → independent invariant verification
    → typed R11 verification result
    → content-addressed R11 evidence
```

R11 verifies that the evidence is: structurally valid; content-integrity
valid; lineage-consistent (R9/R8/R7); internally arithmetically consistent;
authority-bound according to the serialized evidence; deterministically
serializable; and explicit about unresolved authority.

**Verification means: "the serialized evidence satisfies the stated
deterministic contract and lineage."**

**It does NOT mean: "the valuation, reference price or market outcome is
objectively true."** R11 is not attestation, not notarization, not a blockchain-anchoring claim, and not a verification protocol in the cryptographic-trust sense.

## What R11 does NOT verify

R11 does not rerun or recreate the financial model, act as a second model
engine, reroute Radar quotes, recreate R0–R10 economics, invent missing
evidence, invent a model binding, invent FX authority, invent discount-rate
authority, claim price correctness or future outcomes, or claim investment
suitability.  R11 does not perform on-chain anchoring and carries no R12
Digital Twin authority (no streaming, no autonomous refresh, no persistent
twin state).

## Verification correctness vs economic truth

These are different claims.  R11 verifies the former only.  A snapshot whose
checks all pass is internally consistent and lineage-bound; that is a
statement about the evidence, not about the market.

## R10 PARTIAL vs R11 verification status

R11 status is independent of the R10 subject state.  The current live
subject is `MODEL_RADAR_PARTIAL` with exactly `MODEL_BINDING_UNAVAILABLE`
— an honest typed gap — and it **verifies `VERIFICATION_OK`**: the
serialized evidence correctly and consistently declares that state.  A
truthful partial subject is fully verifiable.  `VERIFICATION_PARTIAL` is
reserved for an explicitly optional verification authority being
unavailable; it is never a generic fallback.

## Frozen authority boundaries

R0–R10 are immutable authority (freeze anchor
`7ffaf3b1e67dabb728314948e2a4e4c7ef30047a`).  R11 consumes them read-only;
in particular `finco_radar/model_radar/**`, `finco_radar/r10/**` and
`finco_protocol/verification/**` are consumed, never modified.  The R11
boundaries are `modelAuthority = R10_APPLIED`,
`verificationAuthority = R11_APPLIED`,
`digitalTwinAuthority = R12_NOT_YET_APPLIED`.  The embedded subject keeps
its own historical `verificationAuthority = R11_NOT_YET_APPLIED` verbatim.

## Independent digest reconstruction

R11's primary reconstruction is implemented locally from the documented
canonical form (sorted keys, compact separators, UTF-8, SHA-256, excluding
only `r10SnapshotDigest`).  The frozen R10 verifier is used only as a
secondary cross-check, and the two must agree.  The same independent
rederivation applies to model input/output/run digests, the R9 source and
snapshot digests, the R8 source and snapshot digests, and the R7 provenance
digest carried through R8.

## Check inventory (22 deterministic checks)

SUBJECT_IDENTITY · R10_SNAPSHOT_DIGEST · R10_SNAPSHOT_DIGEST_FROZEN_CROSSCHECK ·
DETERMINISTIC_SERIALIZATION · R9_SOURCE_DIGEST · R9_SNAPSHOT_DIGEST ·
R9_IDENTITY_CONSISTENCY · R8_SOURCE_DIGEST · R8_SNAPSHOT_DIGEST ·
R8_DEPLOYMENT_LINEAGE · R7_PROVENANCE · SYNTHETIC_PROVENANCE ·
R10_BOUNDARY_CONTRACT · HONEST_MISSING_MODEL · SUBJECT_GAP_CONSISTENCY ·
MODEL_DIGESTS · MODEL_OBSERVATION_BINDINGS · COMPARABILITY_CONTRACT ·
REFERENCE_ARITHMETIC · EXECUTION_ARITHMETIC · EXECUTION_SOURCE_BINDING ·
HISTORICAL_TIMING.

Checks whose optional subject authority is absent (model digests,
comparability, arithmetic) are `UNAVAILABLE` — explicitly not applicable,
never a failure.  Subject gaps are preserved verbatim; `R11 gap kinds are
R11-owned` and never reuse R10's vocabulary.

## Arithmetic verification

Reference and execution deviations are independently recomputed in exact
Decimal (`referencePrice - modelValue`,
`(referencePrice / modelValue - 1) × 10000`, and the execution analogues)
with identical BUY/SELL sign semantics, positive finite denominators, and
no re-subtraction of any R8 cost.  Every execution row must trace to its
embedded R8 scenario (identity, price, USD execution currency, timestamp,
net-edge state verbatim).  Timing is historical: R11 verifies the subject's
serialized timestamps were internally consistent at production time; no new
freshness policy is applied.

## Content-addressed envelope

The optional envelope uses the frozen
`finco_protocol.verification.EvidenceEnvelope` read-only, bound to the
subject payload (`payloadSha256 == subjectEvidenceDigest`).  It is
content-addressed only — **not a blockchain-anchoring claim** — and the R11 snapshot
digest remains the primary R11 authority.

## Synthetic provenance

R11 synthetic state is DERIVED as the OR of the verified causal chain
(R10/R9/R8/R7).  Every causal flag must be an exact boolean; laundering
synthetic evidence into a non-synthetic verification result is impossible,
and no caller override exists.

## Correction A (verification trust-boundary closure)

- **A1** — the R0–R10 freeze authority (`R10_FREEZE_ANCHOR` / `R10_FREEZE_TREE`) is pinned as an immutable contract constant; caller freeze values are claims verified by the `FREEZE_IDENTITY` check, and the evidence records verified canonical values.
- **A2** — `HONEST_MISSING_MODEL` is evaluated on every subject: the no-model state must declare `MODEL_BINDING_UNAVAILABLE`; `MODEL_RADAR_OK` cannot carry gaps; `MODEL_RADAR_PARTIAL` requires at least one.
- **A3** — strict nested-shape validation (`_mapping_or_fail` / `_sequence_or_fail`, no falsy-swap defaults): malformed gaps, sourceDigests, R9 nodes, R8 scenarios or upstream containers produce `VERIFICATION_INPUT_INVALID`, never raw exceptions.
- **A4** — the complete serialized `ModelEvidence` authority contract is mirrored: exact typed engine-authority vocabulary, exact-boolean synthetic, non-empty identity fields bound to the subject, all five output-observation bindings, and the full multiplier policy (input authority required when declared; output-only or input-dropped claims rejected).
- **A5** — the comparability contract additionally requires exact-boolean `ok` values, `ok`↔gap pairing, and serialized `comparability.gaps` to mirror the failed dimensions.
- **A6** — reference verification binds `modelValue`, reference price, source and `referenceObservedAt` exactly to the embedded R7 oracle observation and `modelObservedAt` to the valuation timestamp.
- **A7** — execution rows bind `r8ScenarioIndex` to the canonical `(side, notional, venue)` ordering; duplicate scenario identities are detected; `quoteObservedAt` existence and exact timestamp binding are enforced; scenario deployment identity must match the canonical R8 deployment.
- **A8** — R9 identity is proven from the actual graph: exactly one canonical `ECONOMIC_ASSET` node.
- **A9** — exact-boolean outer contracts (type identity, not int aliasing), typed status enum, tz-aware `generatedAt`, SHA-256 digest shapes, and `verify_serialized_r11_evidence` validating outer invariants before digest comparison.
- **A10** — `CONTENT_ENVELOPE_BINDING` (24th check): frozen schema/canonicalization/surface/evidenceType/authorityRefs, `payloadSha256 == subjectEvidenceDigest`, `contentAddress = sha256:<payloadSha256>`; optional and secondary.
- **A11** — PR metadata/provenance corrected.

## Reproduction commands

```bash
pytest -q tests/test_radar_r11_verification.py   # 90 offline deterministic tests
python -m finco_radar.r11.live_proof             # live subject + verification
```
