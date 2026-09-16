# FINCO Radar R6 — read-only terminal

R6 is the presentation and orchestration authority for the initial Radar cycle. It turns the typed R0–R5 authority chain into a compact terminal contract, JSON endpoint and isolated HTML surface. It does not recalculate economics, classify observations, recommend actions or execute transactions.

## Authority chain

| Phase | Authority |
|---|---|
| R0 | Executable quotes and size impact |
| R1 | Canonical asset identity and multiplier |
| R2 | Side-specific directional GAP |
| R3 | Executable liquidity and route evidence |
| R4 | Reference state and usability |
| R5 | Signals, evidence and comparable history changes |
| R6 | Formatting, grouping, rendering and read-only orchestration |

A successful snapshot discloses `R4_APPLIED`, `R5_APPLIED`, `R5_APPLIED` and `R6_APPLIED` for reference state, signals, history and terminal authority respectively. R6 binds to the exact R5 snapshot digest and computes a deterministic canonical-JSON SHA-256 terminal digest. These digests identify reproducible evidence; they are not on-chain commitments.

## How to read the terminal

Start with the canonical asset header, not the ticker alone. Check whether the reference is usable and inspect every typed blocking reason if it is not. The four market rows compare executable BUY prices with official ASK and executable SELL prices with official BID at $100 and $1,000. GAP is descriptive: `PREMIUM`, `DISCOUNT` and `WITHIN_THRESHOLD` are not trading recommendations.

The size cards preserve the independent BUY and SELL R5 states (`NO_MATERIAL_DISLOCATION`, `PERSISTS`, `DECAYS`, `EMERGES_AT_SIZE`, or `REVERSES`). The liquidity panel copies R3 spread, size-impact and route values. `CROSSED` means crossed executable quotes only; it does not establish arbitrage, profit or cost-complete economics.

The signal panel distinguishes active authority with no material event from `SIGNALS SUPPRESSED`. Suppression is a valid R4/R5 state, not an R6 error and not “no signal.” When reference authority is unusable, the exact R4 reasons remain visible. An `UNRESOLVED` market session is displayed as “Session authority unresolved”; R6 does not infer open or closed state from browser time.

The history panel renders only R5 `SignalChange` values. In particular, active-to-suppressed becomes `AUTHORITY_STATE_CHANGED`, never `SIGNAL_CLEARED`. Without supplied comparable history it says “No previous comparable observation available”; R6 invents no trend, chart or previous value.

## Panels and evidence

- Reference: official bid/ask, multiplier, token-equivalent prices, timestamp, factual age and all R4 classifications.
- Market: the four canonical side/notional observations with raw/formatted values, direction and timestamps.
- Size and liquidity: R5 persistence plus exact R3 spread, impact, route and cost-treatment evidence.
- Signals and history: exact R5 events, suppression reasons and typed changes.
- Evidence: canonical identity, full presentation contract, source and terminal digests, candidate audit and git head.

Presentation rounding never feeds classification. For example, an underlying `49.999` bps value may display as `50.00 bps` while retaining the upstream `WITHIN_THRESHOLD` state. Freshness changes only when a new R4 snapshot is evaluated; client code does not age a snapshot into another authoritative state.

## Read-only surface and boundaries

The isolated app exposes only `GET /radar`, `GET /radar/api/snapshot`, and `GET /radar/api/health`. Manual refresh performs a GET, prevents overlapping requests and leaves economic interpretation server-side. There are no write routes, wallet controls, swaps, signatures, custody or trading authority.

Provider cost inclusion remains explicitly unresolved where R3 records `COST_INCLUSION_UNRESOLVED`; no net-profit field is calculated. R4 interval-backed market-session authority, persistent production history, prediction, classic financial-model integration and token utility remain outside R6. This phase makes no recommendation, forecast or deployment change.
