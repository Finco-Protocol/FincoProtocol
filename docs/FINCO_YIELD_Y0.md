# FINCO Yield Y0 — Execution Architecture Spike

Status: limited working prototype; no merge, deploy, custody, signing, broadcasting, vault deployment or mainnet transfer.

## Boundary and authority
FINCO Yield is non-custodial, user-directed, evidence-backed and read-only by default. User wallet signs final transactions. Yield remains additive under `finco_yield/**`; Model/Radar/Verify authorities are unchanged.

Authority order is direct on-chain at explicit block > protocol-native API/subgraph > third-party discovery/reference > explicit manual override. Missing values remain unavailable, never synthetic zero.

Feature flags default off: `FINCO_YIELD_ENABLED=0` and `FINCO_YIELD_EXECUTION_ENABLED=0`.

## Y0 live sample
`finco_yield/data/live_opportunities.json` freezes 14 official-Morpho observations on Ethereum and Base with exact chain, vault contract, underlying address, share token, TVL/APY when surfaced, observed-at and provenance. Evidence is `NATIVE_ENRICHED`, not `DIRECT_ONCHAIN`, because this research pass did not bind the figures to a direct RPC block. APY decomposition components remain null where the captured source did not prove them.

## Underwriting and evidence
Y0 implements deterministic Gross APY/component reconciliation, Organic Share, Reward Dependency, Reward-Off APY, transparent Rewards Off / Rewards -50 / Exit Stress / Gas Shock behavior, `NOT_MODELLED` fallbacks, canonical JSON, SHA-256 input/output hashes and deterministic pre-trade evidence records.

## Execution
Direct ERC-4626 deposit calldata is generated only as an unsigned plan. The connected wallet must be the receiver. Quote fingerprints bind chain, opportunity, destination, input/output, amount and receiver; route hash and expiry are revalidated. Unlimited approvals fail closed in Y0.

Provider findings (checked 2026-09-30):
- Direct protocol call: preferred when the user already holds the underlying.
- Enso: current SDK/API exposes Route/Bundle, approval, receiver and calldata flows; bearer API key; SDK MIT. Y0 client generates/reads routing data only. Robinhood 4663 Enso support was not source-proven, so it remains UNCONFIRMED.
- 0x Swap API v2: current docs list Ethereum 1, Base 8453 and Robinhood 4663. API key + `0x-version: v2`; AllowanceHolder is the recommended flow. FINCO must use the API-provided approval target and never approve Settler.
- Official protocol links remain the fallback.

## Robinhood Chain 4663
`ROBINHOOD_YIELD_READY_NOW = PARTIAL`.

Proven: Robinhood documents EVM mainnet chain ID 4663, ETH gas and EVM-wallet support; Morpho API docs list 4663; official Morpho app shows a live Steakhouse USDG V2 vault at `0xBeEff033F34C046626B8D0A041844C5d1A5409dd`; 0x lists 4663 as supported.

Not yet proven: a 10–20 opportunity set on 4663, block-bound direct reads for the chosen vaults, authoritative Enso 4663 support, or end-to-end provider calldata on 4663. Keep Robinhood as Phase 1b.

## Security
No private-key API exists. No sign/broadcast API exists. No automatic investing/rebalancing exists. No FINCO vault exists. Receiver substitution, amount/chain/route changes and expired quotes fail closed. Mainnet transactions are out of scope.

## UI prototype
`finco_yield.web.router` exposes an isolated `/yield/prototype` drawer suitable for mounting later. It explicitly says `NO BROADCAST`, `Non-custodial · User-signed`, connected-wallet-only receiver and `COMPONENTS_UNAVAILABLE` when Reward-Off data cannot be proven.

## Tests and next chain
Focused Y0 test suite covers identity, missing != zero, APY reconciliation, scenarios, deterministic hashes, quote mutation/expiry/receiver attacks, unlimited approvals, default-off flags, 14 exact live sample identities, and UI safety copy.

Recommended sequence: Y0 spike -> Y1 Explore -> Y2 Underwrite/Compare/Evidence -> Y3 Monitor -> Y4 user-signed Act after security review.
