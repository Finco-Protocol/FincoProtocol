# FINCO Radar R8 — EXECUTION SIMULATOR

## Objective

R8 is a deterministic, evidence-backed **pre-trade execution simulator**. It converts R7 observed theoretical dislocation into the economics actually supported by executable quote evidence:

> At this exact executable size, what portion of the observed difference survives the execution economics that are actually known — without guessing?

Core distinction (never interchangeable):

- `THEORETICAL_DISLOCATION` — comes from R7 (cross-market attribution);
- `GROSS_EXECUTION_EDGE` — comes from actual R0/R2 execution economics at a specific side and notional;
- `NET_EXECUTABLE_EDGE` — exists only after every economically additive cost required by the scenario has explicit treatment authority. If any required treatment is unresolved, the net edge stays unavailable. **Never guess zero.**

R8 is a READ-ONLY pre-trade simulation. It never places or prepares a transaction, never signs, never holds custody, never emits recommendations, scores, ranks or probabilities.

## Authority map (frozen R0–R7, consumed — never redefined)

| Phase | Authority R8 consumes |
|---|---|
| R0 | executable quotes at exact sizes, normalized amounts, fee/gas evidence, settlement reference, timestamps |
| R1 | canonical identity `chain_id + contract_address` (never ticker alone) |
| R2 | side-correct GAP semantics: BUY → ASK, SELL → BID; `gap_bps = (exec/ref − 1) × 10,000` |
| R3 | size comparison, quote-pair timing, routes, cost treatment, execution spread |
| R4 | reference state/usability (a suppressed reference is never resurrected) |
| R5/R6 | signal/history and terminal authority untouched |
| R7 | economic identity, cross-market attribution, comparability, causal timing, evidence lineage — consumed by digest |

## Theoretical vs gross vs net edge

- `THEORETICAL_DISLOCATION` — the R7 component's observed cross-layer difference (`theoretical_dislocation_bps`).
- `GROSS_EXECUTION_EDGE` — exact USD economics of the actual R0 quote vs the matched official reference side.
- `NET_EXECUTABLE_EDGE` — gross minus source-proven incremental provider and settlement costs, only when every adjustment is resolved. Otherwise `PARTIAL` (gross available, net value null) or `UNAVAILABLE`.

## BUY/SELL formulas (exact USD, spec §6)

```text
benchmark_value_usd = token_amount × reference_price_usd_per_token

BUY:  gross_execution_edge_usd = benchmark_value_usd − settlement_amount_usd
SELL: gross_execution_edge_usd = settlement_amount_usd − benchmark_value_usd

gross_execution_edge_bps = gross_execution_edge_usd / benchmark_value_usd × 10,000
```

## Mandatory R2 handshake

The computed bps must equal the side-correct transformation of the frozen R2 gap:

```text
BUY:  gross_execution_edge_bps = −r2_gap_bps
SELL: gross_execution_edge_bps = +r2_gap_bps
```

within exact Decimal arithmetic (pure reconstruction tolerance `0.000001` bps absorbs division-rounding residuals only). Any larger deviation fails closed with `UPSTREAM_ECONOMICS_MISMATCH`.

## No-double-count principle (critical)

**R0 size impact is diagnostic evidence and is not deducted again from the exact R2/R0 execution economics.** The $100 and $1,000 quotes each carry their own complete execution economics; their gross-edge difference is the observed size sensitivity (descriptive only). Subtracting the size impact from the side-adjusted gap would double-count execution economics — a dedicated regression test (`test_r8_does_not_double_count_r0_size_impact`) fails if that ever happens. Similarly, route changes carry no penalty: `ROUTE_ECONOMICS_EMBEDDED_IN_EXECUTION_QUOTE`.

## Size semantics — no interpolation

R8 simulates only sizes with exact executable quote evidence ($100 / $1,000 live; arbitrary exact quotes via the frozen R0 authority). A requested size without an exact quote is `EXECUTION_QUOTE_UNAVAILABLE` — never interpolated, extrapolated or estimated from nearby sizes. Each scenario produces an independent result; size sensitivity (`grossEdgeChangeBps`, `netEdgeChangeBps` only when both nets are COMPLETE, `routeChanged`) is descriptive.

## Cost-treatment rules

- `SOURCE_PROVEN_INCLUDED` — the cost is already inside the normalized quote amounts: `provider_incremental_cost_usd = 0`; never subtracted again.
- `SOURCE_PROVEN_EXCLUDED` — proven outside the quote economics: deducted exactly once (`fee + gas`, both required).
- `EVIDENCE_ONLY_INCLUSION_UNRESOLVED` — never added, never subtracted, never treated as zero: net executable edge stays null with `COST_TREATMENT_UNRESOLVED`.
- A missing fee is not zero; a missing gas is not zero: incomplete pairs yield `COST_EVIDENCE_INCOMPLETE` (`PARTIAL` net).
- An explicit source-proven zero works exactly as zero.

## Settlement semantics

`QUOTE_SETTLEMENT_REFERENCE` (the R0 valuation conversion) is never deducted again as a "settlement cost". Only explicitly evidenced post-trade adjustments (`SettlementAdjustmentEvidence`: bridge/withdrawal/service fees, destination gas) may be applied, and only with known source and treatment: `NOT_REQUIRED`/`SOURCE_PROVEN_INCLUDED` → 0; `SOURCE_PROVEN_EXCLUDED` → amount deducted once; `UNAVAILABLE`/`UNRESOLVED`/`STALE` → net stays partial with `SETTLEMENT_ADJUSTMENT_UNRESOLVED`. Stale or future settlement evidence fails closed (`TIMING_INVALID`).

## Timing

R0 quote timestamps, R2 reference timestamps, R0 settlement-reference timestamps, R7 component timing dependencies and any cost/settlement evidence timestamps are preserved. R8-only cost/settlement evidence is governed by the mandatory caller-supplied `SimulationTimingPolicy` (`max_cost_evidence_age_seconds`, `max_settlement_evidence_age_seconds` — no hidden defaults). Timing-invalid evidence stays serialized but cannot resolve a net value (`TIMING_INVALID` blocker).

## Lineage

Canonical R8 evidence cryptographically binds everything it consumed: `r7CrossMarketDigest`, `r3LiquidityDigest` (required), plus `r2GapEvidenceDigest` and `r0QuoteEvidenceDigest` when those layers are separately represented. Embedded evidence must reconstruct its recorded digest (canonical JSON: `sort_keys=True, separators=(",", ":"), ensure_ascii=False`); any mismatch, one-sided pair or missing core binding fails typed closed. A valid outer `r8SnapshotDigest` never legitimizes inconsistent embedded upstream evidence.

**Semantic upstream binding (Correction B):** cryptographic validity alone is insufficient. The embedded R7 snapshot must belong to THIS economic asset: its `economicAssetUid` must equal the R8 UID, and its `identityBinding.canonicalKeys` must contain the R8 canonical deployment (`chainId + contractAddress`) exactly once — a cryptographically valid R7 snapshot belonging to another economic asset or deployment is rejected (`R7_LINEAGE_MISMATCH`). The theoretical dislocation value is likewise DERIVED from the embedded R7 `dislocationComponents` (`label -> deltaBps` mapping): a caller-supplied `theoretical_dislocations` value is accepted only as redundant evidence requiring exact Decimal equality, so a valid label plus an invented bps value can never produce a valid snapshot. The embedded R3 evidence must also belong to THIS deployment (`chainId`/`contractAddress`, and `canonicalKey` if present must agree) — R3 `assetUid` uses a different namespace than the economic UID and is never compared to it (`R3_LINEAGE_MISMATCH`).

## Closed-loop limitation

R8 v1 models `REFERENCE_RELATIVE` execution only. A favorable reference-relative edge is never labeled realized/guaranteed/risk-free profit: `closedLoopState = CLOSED_LOOP_NOT_PROVEN`. A closed-loop claim would require executable BUY and SELL legs, quantity compatibility, timing coherence, full cost treatment and settlement evidence for every leg — none of which is fabricated. `CLOSED_LOOP` scenarios fail typed closed (`CLOSED_LOOP_NOT_PROVEN`), and equal USD notionals never imply matched token quantities.

## Fail-closed states

`EXECUTION_SIMULATION_OK` · `EXECUTION_QUOTE_UNAVAILABLE` · `REFERENCE_UNAVAILABLE` · `IDENTITY_MISMATCH` · `R7_LINEAGE_MISMATCH` · `R3_LINEAGE_MISMATCH` · `R2_ECONOMICS_MISMATCH` · `UPSTREAM_ECONOMICS_MISMATCH` · `TIMING_INVALID` · `COST_TREATMENT_UNRESOLVED` · `COST_EVIDENCE_INCOMPLETE` · `SETTLEMENT_ADJUSTMENT_UNAVAILABLE` · `SETTLEMENT_ADJUSTMENT_UNRESOLVED` · `CLOSED_LOOP_NOT_PROVEN` · `NON_FINITE_ECONOMICS` · `INPUT_INVALID`. A scenario may successfully produce gross execution evidence while its net edge remains unresolved — that distinction is modeled explicitly (`NetEdgeState`: `COMPLETE`/`PARTIAL`/`UNAVAILABLE` with typed `NetEdgeBlocker`s).

## Live-data limitations

The live LiFi provider cost treatment is `EVIDENCE_ONLY_INCLUSION_UNRESOLVED`, so the live artifact legitimately reports: gross execution economics available, `netEdgeState = PARTIAL`, `netExecutableEdge = null`, reason `COST_TREATMENT_UNRESOLVED`. That is a successful R8 state — the phase succeeds by modeling the boundary honestly, not by forcing a net number. No underlying, FX, second-venue or external-oracle data is invented.

## R9 boundary / Model boundary

No asset graph, graph DB, generic edge schema or traversal engine: `assetGraphAuthority = R9_NOT_YET_APPLIED`. No classic FINCO Model valuation (DCF/NAV/intrinsic value) — that belongs to R10; R8's benchmark is the existing Radar authority only: `modelAuthority = MODEL_NOT_YET_APPLIED`.

## Reproduction commands

```bash
pytest -q tests/test_radar_r8_execution_simulator.py
python -m finco_radar.r8.live_proof   # writes evidence + .sha256 + manifest
python -m compileall -q .
python tools/public_safety_scan.py
```
