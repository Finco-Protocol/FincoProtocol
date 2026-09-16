# FINCO Radar R5 — Signals, Evidence and History

R5 is a deterministic interpretation layer over frozen R2 GAP observations, R3 executable-liquidity evidence and R4 reference usability. It emits descriptive typed market states, reconstructible evidence and policy-consistent change history. It does not recommend trades, rank assets, forecast prices or claim profit.

## Authority boundaries

- R2 GAP is a directional measurement, not an R5 signal.
- R3 liquidity metrics qualify execution context, but are not R5 signals.
- R4 usability means the official reference can be interpreted; it does not mean a dislocation exists.
- R5 signal means a caller-defined threshold was crossed; it is not a trade recommendation or arbitrage claim.
- History change is descriptive and is not predictive authority.
- R6 terminal/presentation authority is not applied.

R5 binds R3 and R4 only when `asset_uid + chain_id + contract_address` agree. Ticker is metadata and cannot repair identity. Every embedded R2 observation must use the exact R4 reference timestamp and halt flag. BUY reference prices reconstruct as `raw ask × current multiplier`; SELL reconstructs as `raw bid × current multiplier`.

## Mandatory SignalPolicy

The engine has no defaults. Callers must provide finite policy values:

- `min_abs_gap_bps`: inclusive positive/negative material GAP boundary.
- `max_execution_spread_bps`: inclusive upper boundary for a normal executable spread.
- `max_adverse_size_impact_bps`: strictly exceeded only by positive R0 size impact. Negative impact is not adverse merely because its magnitude is large.
- `max_input_skew_seconds`: maximum R3 production-time versus R4 `as_of` skew.
- `material_history_change_bps`: inclusive minimum absolute GAP change recorded as `MAGNITUDE_CHANGED`.

These are caller policy, not universal market truth. History generated under different policies is not comparable and fails closed.

## Side and size semantics

Positive GAP is `PREMIUM`, negative GAP is `DISCOUNT`, and values strictly between `−min_abs_gap_bps` and `+min_abs_gap_bps` are `WITHIN_THRESHOLD`. Equality at either boundary is material. BUY remains a comparison with official ASK; SELL remains a comparison with official BID. The labels never imply an action.

For each side, `$100 → $1,000` becomes `NO_MATERIAL_DISLOCATION`, `PERSISTS`, `DECAYS`, `EMERGES_AT_SIZE`, or `REVERSES`. Both exact GAPs and their R2 delta remain in evidence; they are never averaged into a score.

R3 executable spreads are consumed without recomputation: negative is `CROSSED`, zero through policy maximum is `WITHIN_POLICY`, and above policy is `WIDE`. `CROSSED` remains an observation—not a profit or free-money assertion. Route changes retain both signatures as context and never automatically suppress or penalize a signal.

Provider fee/gas treatment remains `COST_INCLUSION_UNRESOLVED` whenever R3 reports `EVIDENCE_ONLY_INCLUSION_UNRESOLVED`. R5 therefore does not calculate all-in edge or net economics.

## Reference suppression

When R4 says `reference_usable=false`, R5 succeeds with `SUPPRESSED_REFERENCE_UNUSABLE`, `signalsActive=false`, no signal events, and the exact ordered R4 blocking reasons. This state is deliberately distinct from `NO_MATERIAL_DISLOCATION`.

## Deterministic history

Each immutable R5 snapshot is serialized as canonical sorted JSON and identified by a SHA-256 evidence digest. Every history entry must exactly bind its duplicated identity, symbol, observation time and policy metadata to that embedded snapshot. A comparable series requires identical canonical asset identity and SignalPolicy, timezone-aware strictly increasing times, deterministic ordering and reconstructible digests. Change types include `AUTHORITY_STATE_CHANGED`, `SIGNAL_APPEARED`, `SIGNAL_CLEARED`, `DIRECTION_CHANGED`, `SIZE_STATE_CHANGED`, `LIQUIDITY_CONTEXT_CHANGED`, `MAGNITUDE_CHANGED`, and `UNCHANGED`. Economic change labels require comparable active authority at both endpoints; becoming suppressed never asserts that a signal cleared.

The live proof never invents a prior observation. Until a runtime supplies one, it records `previousObservationAvailable=false`, the current entry and an empty change list. Persistence storage, scheduling and terminal UX remain later runtime/R6 work. R4's future market-session authority requirement also remains explicit.
