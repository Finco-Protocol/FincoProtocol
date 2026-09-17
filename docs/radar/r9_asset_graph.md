# FINCO Radar R9 — FINCO ASSET GRAPH

## Objective

R9 connects the financial and market identities already proven by R0–R8 into a
deterministic, typed, evidence-backed relationship graph. It introduces no new
market data, no new economics, and no new APIs of its own: every node and edge
is derived from frozen upstream evidence (R1 registry, R4 reference state,
R7 cross-market, R8 execution simulator) that is carried by digest and must
reconstruct before anything is derived from it.

Missing relationships are first-class evidence: where no upstream authority
proves a relationship (official underlying market, external oracle, corporate
actions, a second venue), R9 records a typed graph gap — never a synthetic
edge, never an interpolation, never an AI/LLM inference.

## Authority map (frozen R0–R8, consumed — never redefined)

| Upstream | Authority consumed by R9 |
| --- | --- |
| R1 registry | token deployment identity `AssetKey(chain_id, contract_address)` |
| R4 reference state | reference instrument + reference source |
| R7 cross-market | economic identity binding, venue observations, settlement context, layer availability |
| R8 execution simulator | per-scenario execution evidence bound to the R8 snapshot digest |

R7's economic UID namespace and R3's `assetUid` namespace are different
identifiers and are never compared or merged.

## Node and edge vocabulary

Node types: `ECONOMIC_ASSET`, `TOKEN_DEPLOYMENT`, `UNDERLYING_INSTRUMENT`,
`REFERENCE_INSTRUMENT`, `REFERENCE_SOURCE`, `VENUE`, `SETTLEMENT_CONTEXT`.

Relationship types: `REPRESENTED_BY` (economic asset → deployment, R7
authority), `HAS_UNDERLYING` (reserved; requires an official underlying
authority that does not exist today), `REFERENCED_BY`/`OBSERVED_BY` (R4
authority), `QUOTED_ON` (R7 venue observations), `SETTLES_VIA` (R0 settlement
reference carried through R7), `HAS_EXECUTION_EVIDENCE` (R8 scenarios).

Node identity is derived from canonical identity, never from display ticker:
`economic:{uid}` and `deployment:{chain_id}:{contract_address}`. Edge identity
is the SHA-256 of `relationship|from|to` — and for execution evidence of
`relationship|from|to|side|notional`, because each R8 scenario is distinct
evidence, never a duplicate edge.

## Graph gaps (explicit absence of authority)

`UNDERLYING_RELATIONSHIP_UNAVAILABLE`, `REFERENCE_INSTRUMENT_UNAVAILABLE`,
`REFERENCE_SOURCE_UNAVAILABLE`, `SETTLEMENT_IDENTITY_UNRESOLVED`,
`SECOND_VENUE_UNAVAILABLE`, `EXTERNAL_ORACLE_UNAVAILABLE`,
`CORPORATE_ACTION_AUTHORITY_UNAVAILABLE`, `UPSTREAM_EVIDENCE_UNAVAILABLE`.

A snapshot with at least one gap is `ASSET_GRAPH_PARTIAL`; a gapless snapshot
is `ASSET_GRAPH_OK`. The live proof always yields `ASSET_GRAPH_PARTIAL`
because the underlying-market, external-oracle and corporate-action
authorities do not exist yet.

## Determinism and lineage

- Deep immutability: snapshots are frozen dataclasses over `MappingProxyType`
  and tuples; mutating callers cannot mutate a published graph.
- Canonical digests: `json.dumps(sort_keys=True, separators=(",", ":"),
  ensure_ascii=False)`; `r9SnapshotDigest` covers everything including the
  embedded upstream evidence.
- Fail-closed lineage: `build_graph_from_upstream` refuses to derive anything
  unless the embedded R8 and R7 evidence reconstruct their own recorded
  snapshot digests (`ASSET_GRAPH_LINEAGE_MISMATCH`) and the payload shape is
  usable (`ASSET_GRAPH_INPUT_INVALID`).
- Digest reconstruction is order-independent: nodes, edges and gaps are sorted
  before the digest is computed.

### Correction A — lineage digest semantics (F1)

Two different R7 checks coexist and must never be conflated:

- `sourceDigests["r7CrossMarketDigest"]` = canonical SHA-256 of the COMPLETE
  embedded `r7CrossMarketEvidence`, required to equal the digest declared by
  the embedded R8 snapshot under `sourceDigests["r7CrossMarketDigest"]`;
- the embedded R7 internal `r7SnapshotDigest` is verified independently with
  the frozen R7 verifier.

`sourceDigests["r8ExecutionSimulatorDigest"]` binds the embedded R8
`r8SnapshotDigest` explicitly and is verified with the frozen R8 verifier.
The R3 digest declared by R8 must also reconstruct over the embedded R3
evidence.

### Correction A — evidence lineage on edges (F2)

Topology identity and evidence lineage are separate: `edge_id` is graph
identity; `evidenceDigest` is the canonical digest of the exact upstream
record proving the relationship — the R7 `identityBinding` for
`REPRESENTED_BY`, the venue's exact observation rows for `QUOTED_ON`, the R7
settlement block for `SETTLES_VIA`, the oracle observation for
`REFERENCED_BY`/`OBSERVED_BY`, and the parent R8 snapshot digest (with the
scenario identity retained in metadata) for `HAS_EXECUTION_EVIDENCE`.
Changing only a source record preserves node and edge IDs but changes the
`evidenceDigest` and the `r9SnapshotDigest`.

### Correction A — canonical paths (F3)

Every source-proven venue emits a real topology path
`[economic, deployment, venue]` bound by `[REPRESENTED_BY, QUOTED_ON]`
edges; the generic validator enforces `len(edge_ids) == len(node_ids) - 1`
and exact consecutive connectivity, failing with
`ASSET_GRAPH_TOPOLOGY_INVALID`. Serialized snapshot paths and the
`canonical_asset_path()` query helper agree.

### Correction A — duplicate/conflict rules (F4)

Duplicate nodes with identical canonical semantics are idempotent (evidence
references merge deterministically); any identity/authority conflict raises
`ASSET_GRAPH_IDENTITY_MISMATCH`. Duplicate edges with equivalent semantics
are idempotent; any conflict (relationship, endpoints, authority phase,
source, evidence digest, metadata) raises `ASSET_GRAPH_TOPOLOGY_INVALID`.
No first-write-wins, no last-write-wins.

### Correction A — semantic R7/R8 binding (F5)

After both frozen digest verifiers pass, R9 additionally requires: R8 and R7
economic UIDs to be identical; the R8 canonical deployment to equal the R9
deployment and to appear exactly once in the R7 `identityBinding`; the R7
token layer to agree with the same `AssetKey`; and every R8 scenario to carry
the canonical UID, the canonical deployment, and a `quoteSource` proven by
the embedded R7 venue observations. Individually digest-valid but
semantically incompatible snapshots are rejected with
`ASSET_GRAPH_LINEAGE_MISMATCH`.

## Boundaries (what R9 is not)

- No graph database, no generic arbitrary graph traversal — the graph is the
  typed evidence itself plus six read-only query helpers.
- No AI/LLM inference, no wallet tracking, no execution or transaction
  submission.
- Model authority remains `R10_NOT_YET_APPLIED`; verification remains
  `R11_NOT_YET_APPLIED`; digital twin remains `R12_NOT_YET_APPLIED`.
- The R8 no-double-count discipline is preserved untouched: R9 re-displays
  evidence; it never recomputes or re-deducts R2/R8 economics.

## Reproduction commands

```bash
pytest -q tests/test_radar_r9_asset_graph.py   # 96 offline deterministic tests
python -m finco_radar.r9.live_proof            # live proof (re-runs the frozen
                                               # R1->R8 composition, adds no APIs)
```
