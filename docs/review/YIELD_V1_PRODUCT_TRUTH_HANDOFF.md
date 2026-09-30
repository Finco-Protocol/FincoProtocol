# FINCO Yield → Product Truth alignment

PR #147 Product Truth is **merged**. PR #148 does not rewrite global navigation,
global status, or canonical Product Truth surfaces.

Until PR #148 itself merges, FINCO Yield must be described as:

**IN DEVELOPMENT / EXPERIMENTAL — feature-gated; production mainnet execution is not activated.**

Current #148 product truth:
- Candidate chains: Ethereum + Base.
- Candidate protocol: Morpho vaults / ERC-4626-compatible direct identity path.
- Bundled set: 14 frozen `NATIVE_ENRICHED` Morpho research observations; freshness may be stale and must be shown as such.
- `NATIVE_ENRICHED` is `READ_ONLY_RESEARCH`; it does not authorize execution.
- Direct planning requires a fresh explicit block-bound ERC-4626 revalidation of chain, contract bytecode, asset, share token and exact preview amount.
- Explore / Detail / Compare / typed Evidence: implemented behind `FINCO_YIELD_ENABLED`.
- Wallet Monitor: read-only, reuses existing verified FINCO wallet identity; configured RPC chains only.
- Enter Position: canonical unsigned transaction-plan review behind separate `FINCO_YIELD_EXECUTION_ENABLED`; production signing/broadcast is not activated.
- Direct bare ERC-4626 remains `UNPROTECTED_PREVIEW_ONLY` and `user_signable=False`.
- Custody: no.
- FINCO vault: no.
- Robinhood Chain 4663: `PARTIAL`; do not advertise READY.
- Feature flags: `FINCO_YIELD_ENABLED=0`, `FINCO_YIELD_EXECUTION_ENABLED=0` by default.

Do not claim Yield is shipped until PR #148 merges. Do not claim production execution,
custody, a FINCO vault, or mainnet money movement.
