# FINCO Yield → Product Truth handoff (PR #147 owner)

Do not apply this as a global-nav/status edit from PR #148. This is the concise handoff requested by the Yield master workflow.

- Public status: **FINCO Yield V1 Beta — feature-gated; production mainnet execution not activated.**
- Candidate chains: Ethereum + Base.
- Candidate protocol: Morpho vaults / ERC-4626-compatible direct identity path.
- Bundled set: 14 frozen `NATIVE_ENRICHED` Morpho research observations; freshness may be stale and must be shown as such.
- Direct authority: block-bound adapter implemented; production live proof remains partial until configured runtime reads are captured.
- Explore / Detail / Compare / typed Evidence: implemented behind `FINCO_YIELD_ENABLED`.
- Wallet Monitor: read-only, reuses existing verified FINCO wallet identity; configured RPC chains only.
- Enter Position: canonical unsigned transaction-plan review behind separate `FINCO_YIELD_EXECUTION_ENABLED`; production signing/broadcast not activated.
- Custody: no.
- FINCO vault: no.
- Robinhood Chain 4663: `PARTIAL`; do not advertise READY.
- Known limitations: no fabricated history, no Aave adapter, no bare ERC-4626 min-shares guarantee, provider target allowlists required before routed activation.
- Feature flags: `FINCO_YIELD_ENABLED=0`, `FINCO_YIELD_EXECUTION_ENABLED=0` by default.
