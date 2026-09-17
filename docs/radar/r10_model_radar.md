# FINCO Radar R10 — FINCO MODEL × RADAR

## Objective

R10 builds a deterministic, typed, evidence-backed bridge between frozen
FINCO model authority, the R9 asset graph, and Radar reference/execution
state:

```text
FINCO deterministic financial model authority
                    ↓
             FINCO Asset Graph (R9)
                    ↓
        Radar reference/execution state (R4/R7/R8)
```

The canonical R10 question: *what model-derived value belongs to this exact
economic asset, is that model output actually comparable with the market
unit Radar observes, and what is the signed difference when comparison is
valid?*

**A FINCO model value is model evidence, not market truth.**

**R10 compares model evidence with market evidence only when economic
identity, value kind, unit basis, currency and timing are source-proven
compatible.**

**R10 does not infer a valuation from ticker similarity.**

## Existing model authority consumed (inventory)

R10 consumes, and never reimplements, the frozen model authority:

| Entrypoint | Authority |
| --- | --- |
| `finco_core.sponsor.xnpv.xnpv` | date-based XNPV (Excel-compatible, float boundary) |
| `finco_core.sponsor.xirr.xirr` | XIRR return metric |
| `financial_engine.orchestrator.run_operating_model` | project operating model |
| `financial_engine.orchestrator.run_tax_cfads_model` | tax/CFADS model |
| `financial_engine.orchestrator.run_senior_debt_model` | senior-debt model |

R10 owns only the binding, evidence, comparability, comparison and digest
layers — not the model mathematics.  No discount rate is ever invented: a
missing discount-rate authority is `MODEL_DISCOUNT_RATE_AUTHORITY_UNAVAILABLE`.

## Model vs market authority distinction

```text
MODEL VALUE  ≠  REFERENCE PRICE  ≠  EXECUTION PRICE  ≠  R2 GAP  ≠  R7 DISLOCATION  ≠  R8 EDGE
```

R10 may compare them; it never overwrites or merges them.  XIRR/IRR/DSCR/
LLCR/EBITDA are `NON_PRICE_METRIC` evidence — never prices, never
"undervaluation percentages".

## Economic UID binding

`ModelBinding` derives its identity from the canonical pair
(`economicAssetUid`, `economic:<UID>` node in R9) plus model identity.
Tickers, symbols and display names carry zero binding authority.  The token
deployment `AssetKey(chain_id, contract_address)` remains a separate
representation; the model belongs to the economic asset.

## Model evidence

`ModelEvidence` records model id/version, engine authority, valuation
timestamp, value kind, Decimal value, currency, unit basis, optional
source-proven unit multiplier, input/output digests, the derived
`modelRunDigest`, and the original upstream value representation.  Frozen
model functions may return `float`: values cross the R10 boundary through
their canonical textual representation (`Decimal(repr(x))`), never
`Decimal(binary_float)`.

## Value kinds and unit basis

Closed enums: `VALUE_PER_ECONOMIC_UNIT`, `EQUITY_VALUE_TOTAL`,
`ENTERPRISE_VALUE_TOTAL`, `NAV_TOTAL`, `PROJECT_NPV_TOTAL`,
`NON_PRICE_METRIC`; `PER_SHARE`, `PER_TOKEN_CLAIM`, `PER_ECONOMIC_UNIT`,
`TOTAL_EQUITY`, `TOTAL_ENTERPRISE`, `TOTAL_PROJECT`.  The denominator is
never inferred.  A TOTAL-kind value is normalized only with a
source-proven unit multiplier; the multiplier is never assumed to be 1 and
never derived from token supply.

## Currency semantics

Same-currency comparison only.  No implicit FX conversion, no
stablecoin==USD assumption, no missing-FX-equals-1.  R10 v1 consumes no new
FX authority; a currency mismatch is `CURRENCY_MISMATCH` +
`FX_AUTHORITY_UNAVAILABLE`.

## Timing

`ModelRadarTimingPolicy(maxModelAgeSeconds, maxModelMarketSkewSeconds)`.
The valuation timestamp is required, timezone-aware, never in the future
(hard `MODEL_RADAR_TIMING_INVALID`).  A stale model is `MODEL_STALE` and is
never relabeled current; excessive model-market skew is
`TIMING_SKEW_INVALID`.

## Comparability

Seven explicit dimensions: economic identity, value kind, unit basis,
currency, multiplier, timing, reference availability.  States:
`COMPARABLE`, `PARTIALLY_COMPARABLE`, `NOT_COMPARABLE` with typed gap kinds
(no free-text state as authority).

## Reference comparison (descriptive)

```text
referenceMinusModelValue = referencePrice − modelValuePerUnit
referenceVsModelBps      = (referencePrice / modelValuePerUnit − 1) × 10000
```

Decimal-only, strictly positive model basis required.  Field names are
deliberately neutral — never upside/downside/profit/opportunity.

## Execution comparison

Consumes the exact R8-observed execution price per token
(`r2GapEvidence.executionPriceUsdPerToken`) with side, notional, venue and
the R8 `netEdgeState` preserved verbatim.  Identical sign semantics for BUY
and SELL — this is descriptive deviation, **not** the R8 favorable
executable edge.

## R8 no-double-count rule

R10 never subtracts provider fees, gas, settlement adjustments, size
impact, slippage or route costs — R8 owns execution economics.  Diagnostic
mutation of R8 cost/size evidence cannot change an R10 comparison (regression
tested).

## Digest lineage

Distinct digests, never collapsed: `r9AssetGraphDigest` (canonical SHA-256
of the COMPLETE embedded R9 evidence) vs `r9SnapshotDigest` (internal,
frozen R9 verifier); `r8ExecutionSimulatorDigest` vs `r8SnapshotDigest`;
`modelInputDigest`, `modelOutputDigest`, `modelRunDigest`; and
`r10SnapshotDigest` over canonical JSON excluding itself.  Any semantic
model-input change alters the run digest.

## Immutability and determinism

Deep-frozen snapshots; caller mutation cannot change published evidence;
serialization returns fresh structures.  Execution comparisons are ordered
by `(side, notional, venue)`; gaps are sorted; equivalent input ordering
produces identical canonical bytes and digest.

## Live limitations

The repository contains no source-proven model binding for the live Radar
economic asset.  The live proof therefore reports
`MODEL_RADAR_PARTIAL` + `MODEL_BINDING_UNAVAILABLE` with verified R9
lineage — the honest, PASSING outcome.  R10 never fabricates model evidence
to appear complete, never backfills a missing market reference with model
value, and never converts an unavailable model into zero or last-known.

## Synthetic proof

The offline synthetic fully-comparable proof (`synthetic = true`) validates
the complete path — binding, comparability, reference bps, four execution
comparisons, digest reconstruction.  It is never live market evidence.

## R11/R12 boundaries

R10 digests are evidence-integrity hashes — not attestation, notarization,
on-chain proof, or verification protocol (R11 owns those).  No streaming
model updates, autonomous refresh, event bus, or digital-twin state (R12
owns those).

## Reproduction commands

```bash
pytest -q tests/test_radar_r10_model_radar.py   # 84 offline deterministic tests
python -m finco_radar.r10.live_proof            # live proof (re-runs the frozen
                                                # R1->R9 chain, adds no APIs)
```
