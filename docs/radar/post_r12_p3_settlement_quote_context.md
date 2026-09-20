# FINCO Radar Post-R12 P3 — Settlement Reference + Read-Only Quote Context

Closes the P2 composition limitation `SETTLEMENT_RESOLVER_NOT_WIRED` and
activates the existing read-only `$100 / $1,000` BUY/SELL flow against
the frozen R0 execution-quote authority and the frozen R2 directional
GAP authority — when all required quote context is genuinely configured.

Not R13.  No deploy.  No signing/custody/trade submission.  LI.FI stays
quote-only; any transaction payload fields remain inert evidence.

## Discovered authority situation (P1/P2 inspection)

- The ONLY frozen settlement parser (`_discover_settlement`, LiFi token
  metadata) lives inside the private proof modules — deliberately NOT
  called from product composition and NOT duplicated.
- No public canonical settlement configuration existed.  Per the P2/P3
  contract, settlement identity and value are therefore **operator
  configuration**: nothing is invented, and `1 token = 1 USD` is never
  assumed.  Missing configuration fails closed.

## Architecture

- **`app/radar_ui/quote_context.py`** — `resolve_quote_context()` reads
  the operator configuration into an immutable `QuoteContext`;
  `build_settlement_reference()` constructs the FROZEN
  `SettlementReference` from the bound context with typed fail-closed
  reasons; `quote_taker_address()` validates the public taker routing
  address.
- **P5/P6 fingerprint binding** — `build_request()` binds the context's
  safe identity (settlement chain/contract/symbol/decimals, state, USD
  reference, source id, taker address, fail-closed problems) into the P1
  `AcquisitionRequest.provider_config`; the provider callable
  reconstructs its context from THAT SAME material — one ownership path,
  and any context change changes the acquisition fingerprint (so cached
  snapshots from other contexts are never reused).
- **P7 frozen QuoteRequest** — constructed with ALL required arguments
  including `taker_address=<validated public routing address>`; SELL
  keeps the frozen sizing reference (`R8_BOUND_REFERENCE_MIDPOINT_
  SIZING_ONLY`) semantics; the frozen same-chain and positive-notional
  validations remain in force.
- **P9/P10** — the snapshot evidence gains a settlement section
  (configured/state/source/identity/usd value or the stable fail-closed
  reason) and the Execution panel activates only from `QUOTE_OK`
  evidence; GAP is fed to the frozen `compute_directional_gap` only when
  execution and reference are both genuinely available.

## Configuration (all operator-provided; missing → fail closed)

| Variable | Meaning |
| --- | --- |
| `RADAR_V1_QUOTE_TAKER_ADDRESS` | public, non-secret read-only quote routing address (20-byte EVM hex) |
| `RADAR_V1_SETTLEMENT_ADDRESS` | settlement token deployment (20-byte EVM hex) |
| `RADAR_V1_SETTLEMENT_CHAIN_ID` | settlement chain (defaults to the target asset chain) |
| `RADAR_V1_SETTLEMENT_SYMBOL` | settlement symbol (display) |
| `RADAR_V1_SETTLEMENT_DECIMALS` | settlement decimals (0–255) |
| `RADAR_V1_SETTLEMENT_STATE` | frozen `SettlementReferenceState` value (e.g. `REFERENCE_CURRENT`) |
| `RADAR_V1_SETTLEMENT_USD_PER_ASSET` | positive finite USD value per settlement unit, from the operator's stated authority |
| `RADAR_V1_SETTLEMENT_SOURCE` | source/methodology label recorded with the settlement reference |

Fail-closed reasons: `SETTLEMENT_NOT_CONFIGURED`,
`SETTLEMENT_IDENTITY_INVALID`, `SETTLEMENT_CHAIN_MISMATCH`,
`SETTLEMENT_REFERENCE_INVALID`, `SETTLEMENT_REFERENCE_UNUSABLE`,
`QUOTE_TAKER_ADDRESS_NOT_CONFIGURED`, `QUOTE_TAKER_ADDRESS_INVALID`.

## Safety (P4/P8/P13)

The taker address is public, non-secret quote-routing context — not a
connected wallet, not custody, not authorization, not a signing
identity.  No private key, seed phrase, signature, approval or
transaction submission exists anywhere in this flow; the Radar surface
remains visibly `READ-ONLY`.  Future provider API credentials (if any)
must stay server-side and outside fingerprint material and UI evidence.

## Governance (P14/P15)

CI gates: zero diff on frozen R0–R12 authority vs `1045a34…`; zero diff
on the P1 runtime core vs `d8c471b…`; focused P3 tests; P2 + P1
regressions; frozen R0/R2/R6 regressions; full repository suite;
compileall; public safety.
