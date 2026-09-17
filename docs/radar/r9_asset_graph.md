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
pytest -q tests/test_radar_r9_asset_graph.py   # 66 offline deterministic tests
python -m finco_radar.r9.live_proof            # live proof (re-runs the frozen
                                               # R1->R8 composition, adds no APIs)
```
