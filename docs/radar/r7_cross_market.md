# FINCO Radar R7 — CROSS-MARKET INTELLIGENCE

## Objective

R7 builds a deterministic, evidence-backed cross-market intelligence layer answering:

> For the same economic asset, how do the underlying market, tokenized representation, oracle/reference source, DEX/venue observation, FX conversion and settlement context relate to each other — and at which layer does an observed price dislocation originate?

R7 makes the complete observable price path inspectable and attributes observed dislocations to layers:

```text
UNDERLYING MARKET → FX / normalization → ORACLE / REFERENCE
→ TOKENIZED REPRESENTATION → VENUE / DEX → SETTLEMENT CONTEXT
```

Core boundary:

- **R7** — theoretical/observed dislocation + dislocation attribution ("what is different, where, and how large?");
- **R8** — theoretical edge → executable edge (explicitly out of scope here).

## Authority ownership

R7 consumes and never duplicates or redefines frozen R0–R6 authority:

| Phase | Authority R7 consumes | R7 must not do |
|---|---|---|
| R0 | execution quote acquisition/provenance | duplicate quote acquisition logic |
| R1 | canonical identity `chain_id + contract_address` | treat ticker equality as identity |
| R2 | GAP semantics (BUY=ASK-based, SELL=BID-based) | introduce a competing GAP formula |
| R3 | size/side/route/execution/liquidity evidence | perform R8 executable-edge simulation |
| R4 | reference usability, reference price, multiplier, halt/state | manufacture reference authority |
| R5 | deterministic signals and history semantics | redefine signal states |
| R6 | read-only terminal | redesign the terminal |

Reproduction commands:

```bash
pytest -q tests/test_radar_r7_cross_market.py
python -m finco_radar.r7.live_proof   # writes evidence + .sha256 + manifest
python -m compileall -q .
python tools/public_safety_scan.py
```

## Economic identity

`EconomicIdentityBinding` introduces economic identity separate from token contract identity:

- `economic_asset_uid` — e.g. `AAPL` (validated `[A-Z0-9._-]{1,32}`);
- explicit `canonical_keys` — one or more `AssetKey(chain_id, contract_address)`;
- `reference_identifiers` and a declared `source` for provenance.

Rules: binding fails closed on duplicate keys, empty keys, or an unknown UID shape; membership of every venue/token/oracle observation is checked against the binding; **ticker equality is never sufficient identity**; a venue row carrying an unbound deployment fails closed (`CROSS_MARKET_EVIDENCE_MISMATCH`). In the live proof the binding source is the official R1 registry (which itself binds UID↔symbol↔deployments), not ticker inference.

## Layer definitions

`LayerType`: `UNDERLYING`, `FX`, `ORACLE_REFERENCE`, `TOKEN`, `VENUE`, `SETTLEMENT`.

- **Underlying market observation** (`LayerObservation`) — economic uid, source, instrument, price, quote currency, `observed_at`, provenance. Unavailable layers carry `SOURCE_UNAVAILABLE` with a named reason and never carry a price.
- **FX normalization** (`FxObservation`) — source/target currency, rate, source, `observed_at`. Stablecoin parity is never assumed (`USD ≠ USDC` without explicit policy authority). Stale FX (older than the stale-layer window) is treated as unavailable; comparisons requiring missing FX become unavailable with `FX_UNAVAILABLE`.
- **Oracle/reference** — the canonical layer comes from frozen R4 authority. A hypothetical *observed external oracle* would be modeled as a separate observation and could be compared against, never silently substituted for, R4 canonical authority. The live oracle price is the canonical midpoint `(raw_bid + raw_ask) / 2 × currentMultiplier` computed from R4 evidence.
- **Token representation** (`TokenRepresentation`) — economic uid, canonical key, symbol, multiplier, representation status, R4 usability, and an *optional* independent token-layer price observation. Without one, the TOKEN layer carries no price and the price path connects `ORACLE_REFERENCE → VENUE` directly.
- **Venue/DEX** (`VenueObservation`) — canonical identity, venue/route identity, side, notional, executable observation, timestamp, R2 GAP, R3 route/liquidity lineage. Extracted live from the frozen R3 liquidity authority.
- **Settlement context** (`SettlementContext`) — settlement asset, chain, currency, transfer requirement (if explicitly known), availability, authority status (`CONTEXT_ONLY_R8_PENDING`). R7 does NOT compute bridge fees, gas, execution fees, settlement loss, net PnL or realized return — all reserved for R8. If settlement prevents comparison, that is exposed as a comparability limitation.

## Timing policy

Every layer retains its own `observed_at`. `CrossMarketPolicy` (mandatory, caller-supplied, no engine defaults) declares `comparison_currency`, `material_dislocation_bps`, `max_layer_skew_seconds` and `stale_layer_seconds`. Timing diagnostics expose oldest/newest observations, total stack skew, per-component pairwise skew, the policy values and a state:

- `ALIGNED` — all available timestamps within the skew window, none stale;
- `SKEWED` — total skew exceeds `max_layer_skew_seconds` (reason `TIMING_SKEW`);
- `STALE_LAYER` — any available layer older than `stale_layer_seconds` (reason `STALE_LAYER`, stale layers named);
- `TIMING_UNRESOLVED` — fewer than two timestamps available.

Asynchronously observed markets are never treated as simultaneous; a stale observation never becomes current because another layer is current.

## Price-path formulas

For each adjacent comparable layer pair, a `DislocationComponent` is computed deterministically:

```text
delta      = to_price − from_price
delta_bps  = (to_price / from_price − 1) × 10,000
material   = |delta_bps| ≥ material_dislocation_bps   (exact boundary is material)
```

Every component records both endpoint authorities (layer type, source, timestamp), the applied FX conversion (if any), the pairwise timing skew, the policy threshold, and its timing validity. Component pairs: `UNDERLYING→UNDERLYING[fx]`, `UNDERLYING→ORACLE_REFERENCE`, `ORACLE_REFERENCE→TOKEN`, `TOKEN→VENUE` (or `ORACLE_REFERENCE→VENUE` when the token layer has no independent price), `VENUE→VENUE` (cross-venue dispersion), `TOKEN→TOKEN` (cross-deployment via `compare_cross_deployments()` over two stacks binding the same economic asset to disjoint canonical deployments — ticker match is insufficient; matching quote currencies required).

**Cross-venue comparisons are currency-safe (Correction A):** every member price is first normalized into the comparison currency with the same explicit FX authority rules used elsewhere; raw cross-currency prices are never compared. Members whose conversion is unavailable or stale are dropped with `FX_UNAVAILABLE`. The dispersion component binds each endpoint to the EXACT normalized member that produced the low/high price — price, source, timestamp and venue identity — selected by a deterministic order (normalized price, venue, side, notional, canonical key, observed_at, route signature) independent of caller input order; equal normalized prices break deterministically by venue name.

**Component timing authority (Correction A):** a component is timing-valid only when both endpoint observations are fresh within the staleness window (a future observation is never fresh) and their pairwise skew is inside the skew window. Timing-invalid components are retained as evidence but are excluded from attribution: material differences with invalid timing yield `ATTRIBUTION_UNAVAILABLE` (with `TIMING_SKEW`/`STALE_LAYER` reasons), never a normal material attribution. `STALE_LAYER` remains distinguishable from `TIMING_SKEW` and `TIMING_UNRESOLVED`; future observations are never normalized into fresh data.

## Attribution semantics

Group attribution is a deterministic fold over material components:

- comparability `UNAVAILABLE`/`SUPPRESSED`, or reference unavailable → `ATTRIBUTION_UNAVAILABLE`;
- zero material components → `NO_MATERIAL_DISLOCATION`;
- exactly one → the component's mapped state (`UNDERLYING_REFERENCE_DISLOCATION`, `FX_NORMALIZATION_DISLOCATION`, `REFERENCE_TOKEN_DISLOCATION`, `TOKEN_VENUE_DISLOCATION`, `CROSS_VENUE_DISLOCATION`, `CROSS_DEPLOYMENT_DISLOCATION`);
- more than one → `MULTI_LAYER_DISLOCATION` — component-level evidence is preserved, never collapsed.

No LLM classification, no opaque score.

## Comparability states

`COMPARABLE` / `PARTIALLY_COMPARABLE` / `SUPPRESSED` / `UNAVAILABLE` with typed reasons (`IDENTITY_UNRESOLVED`, `FX_UNAVAILABLE`, `REFERENCE_UNAVAILABLE`, `TIMING_SKEW`, `STALE_LAYER`, `SETTLEMENT_CONTEXT_UNRESOLVED`, `MULTIPLIER_UNRESOLVED`, `UPSTREAM_EVIDENCE_MISMATCH`, `INSUFFICIENT_MEMBERS`, `UNDERLYING_SOURCE_UNAVAILABLE`). Suppressed (authority says the reference is not usable) is deliberately distinct from `NO_MATERIAL_DISLOCATION` (prices agree) — a halted/inactive reference is unusable even when every price agrees, and an authority-state change is never reported as a market-price change. Unavailable layers are never silently discarded to manufacture a clean comparison.

## Evidence contract

`CrossMarketSnapshot` is deeply immutable: frozen dataclasses plus recursive deep-freezing of every nested evidence mapping (`MappingProxyType` over a private deep-frozen copy — no aliases to caller-owned objects survive construction). Caller mutations to `upstream_evidence`, `source_digests`, `live_disclosures` or any observation `raw_evidence` after build have no effect on the snapshot; direct and nested mutation attempts raise. Serialized evidence (`to_evidence_dict()`) is canonical JSON (sorted keys, compact separators, UTF-8), freshly built on every call (serialization mutation never mutates the source), deterministically ordered (venues canonicalized at construction), and carries `r7SnapshotDigest` — a SHA-256 over the canonical encoding of the evidence without the digest field itself. `verify_serialized_evidence()` recomputes that digest and fails closed on any tampering. Live venue rows additionally embed canonical asset identity (`chainId`, `contractAddress`) and their raw evidence, so each row is independently attributable to one canonical deployment. The evidence includes `schemaVersion`, `phase`, `gitHead`, `generatedAt`, `economicAssetUid`, `identityBinding`, `layers`, `timing`, `comparabilityState/Reasons`, `pricePath`, `dislocationComponents`, `attributionState`, `events`, `upstreamEvidence`, `sourceDigests`, `liveDataDisclosures` and the R5/R8/R9 boundary declarations (`signalAuthority=R5_APPLIED`, `executableEdgeAuthority=R8_NOT_YET_APPLIED`, `assetGraphAuthority=R9_NOT_YET_APPLIED`). No secrets or credentials are ever embedded.

## Events

`derive_events(previous, current)` produces deterministic descriptive events — `DISLOCATION_APPEARED/WIDENED/NARROWED/CLEARED`, `ATTRIBUTION_CHANGED`, `REFERENCE_DIVERGENCE`, `VENUE_DIVERGENCE`, `TIMING_ALIGNMENT_LOST/RESTORED`. Dislocation width is the **magnitude** of the signed delta: `+100 → +200` and `−100 → −200` are both `DISLOCATION_WIDENED`; `+200 → +100` and `−200 → −100` are both `DISLOCATION_NARROWED`; a sign flip with unchanged magnitude (`+100 → −100`) emits neither — direction remains observable on the component itself. Events describe observed changes between two snapshots; they never imply future market movement and never emit BUY/SELL recommendations. A snapshot built without a `previous` carries no events.

## R8 boundary (enforced)

R7 may expose "observed theoretical dislocation: +85 bps". R7 must not claim "executable edge: +42 bps" — fees, gas, bridge costs, settlement loss and net executable PnL belong to the R8 Execution Simulator. The evidence declares `executableEdgeAuthority = R8_NOT_YET_APPLIED`, and the CI gate rejects forbidden profit language ("net edge", "arbitrage", "guaranteed", "risk-free") anywhere in the artifact. Cost-treatment uncertainty upstream stays unresolved; venue differences are worded as observed dislocation/price difference, never as net profit.

## R9 boundary

R7 defines the minimum typed relationships needed for deterministic comparison (one economic asset → deployments → layers). The general FINCO Asset Graph — generalized traversal engines, relationship schemas, graph databases — belongs to R9 and is intentionally not built here.

## Live-data limitations

The frozen R0–R6 source set provides no official underlying-market source and no FX authority. The live proof therefore declares, honestly and in the artifact:

- `UNDERLYING_SOURCE_UNAVAILABLE` — the UNDERLYING layer is explicitly missing;
- `FX_AUTHORITY_UNAVAILABLE` — no FX normalization authority exists (all live prices are USD-quoted, so no comparison currently requires conversion);
- `ORACLE_REFERENCE` — canonical, from live R4 authority;
- `TOKEN` — representation from live R1/R4 authority (no independent token price source yet);
- `VENUE` — live R0/R3 execution observations for the selected candidate;
- `SETTLEMENT` — context only (`CONTEXT_ONLY_R8_PENDING`).

The live snapshot is therefore `PARTIALLY_COMPARABLE` — an honest state, never silently completed with assumptions. Synthetic deterministic fixtures (marked `synthetic: true`) prove the full-stack semantics, including `EXPECTED`-style paths that live data cannot exercise yet.
