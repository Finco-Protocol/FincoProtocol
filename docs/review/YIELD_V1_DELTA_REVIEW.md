# FINCO Yield V1 Beta — Delta Review Dossier

Review target: PR #148 master Yield stream. This dossier does **not** authorize merge, deploy, mainnet signing or asset movement.

## A. Product purpose

FINCO Yield is an additive, non-custodial DeFi opportunity-analysis product with an execution-ready boundary:

`DISCOVER → UNDERWRITE → EVIDENCE → MONITOR → REVIEW TRANSACTION PLAN`

The user wallet remains the signer. FINCO does not custody, pool, auto-invest, rebalance, keep private keys or run a proprietary Yield vault.

## B. Architecture

Yield-specific logic stays under `finco_yield/**`. Yield-local runtime is mounted through the protocol shell without changing global Product Truth navigation/status surfaces owned by PR #147.

Key modules:
- `registry.py` exact-UID canonical opportunity registry;
- `freshness.py` source-aware freshness states;
- `ingestion.py` adapter isolation and sanitized failures;
- `onchain.py` explicit-block ERC-4626 reads, allowance and share balances;
- `underwriting.py` APY decomposition, net APY and bounded sensitivities;
- `evidence_v1.py` typed Yield evidence and deterministic hashing;
- `explore.py` filtering and side-by-side comparison with no winner/rank;
- `history.py` append-only observations with explicit superseding records;
- `monitor.py` read-only supported vault-share detection;
- `providers.py` typed normalized 0x/Enso provider inputs;
- `execution.py` canonical unsigned transaction planning;
- `web.py` feature-gated Explore/Detail/Compare/Evidence/Monitor/Enter Position review UI.

## C. Source authority model

Authority order:
1. `DIRECT_ONCHAIN` — exact chain + exact contract + explicit block identity;
2. `NATIVE_ENRICHED` — protocol-native/API/app observation with source timestamp;
3. `THIRD_PARTY_REFERENCE` — discovery/reference unless separately validated.

Provider route data does not automatically become Yield evidence authority.

The bundled 14 Morpho observations remain frozen `NATIVE_ENRICHED` research fixtures. They are **not** relabelled as current direct on-chain state. Freshness policy may mark them `STALE`; stale APY is not represented as current.

## D. Supported chains / protocols

Initial production-candidate scope remains Ethereum (1) and Base (8453), Morpho vault opportunities with ERC-4626-compatible direct identity semantics.

Current bundled candidate set: 14 exact Morpho observations. The count was not inflated merely to reach 20–50; evidence quality is preferred over breadth.

Aave is `DEFERRED BY DESIGN`. A future Aave adapter must model Aave-specific supply semantics rather than pretending Aave positions are ERC-4626 shares.

## E. Canonical identity

Opportunity identity binds exact:
- chain ID;
- protocol;
- product type;
- contract address;
- underlying address(es);
- share token.

Names, symbols and URL slugs are display-only. No ticker lookup, fuzzy matching, URL inference or LLM identity inference is authoritative.

Execution caller input is limited to exact opportunity UID, amount, connected wallet and optional funding token/method. Vault destination, underlying, share token and protocol are resolved server-side from the canonical registry.

## F. Underwriting math

Transparent outputs include Gross APY, Base APY, Reward APY, Intrinsic APY where source-supported, Organic Share, Reward Dependency and Reward-Off APY when the required semantics exist.

`Position Net APY` is emitted only when all explicit amount/horizon/cost assumptions are available. V1 uses a disclosed simple annualized one-time-cost adjustment; it is not a forecast.

Missing decomposition remains `COMPONENTS_UNAVAILABLE`; inconsistent components remain `COMPONENT_MISMATCH`; incomplete cost inputs remain `NET_APY_UNAVAILABLE`.

Scenarios are bounded sensitivities: `REWARDS_OFF`, `REWARDS_MINUS_50`, `EXIT_STRESS`, `GAS_SHOCK`. Protocol-causal scenarios such as utilization shift/depeg/liquidity compression remain `NOT_MODELLED` until explicit mechanics exist.

## G. Evidence model

`YIELD_EVIDENCE_V1` contains identity, source authority/time/block/adapter, normalized inputs, assumptions, outputs, schema/calculation versions and canonical hashes.

Canonicalization normalizes timezone-aware timestamps to UTC and Decimal semantics so `1.0` and `1.00` hash identically; object keys are deterministic and economically meaningful list order is preserved.

`YIELD_PRE_TRADE_EVIDENCE_V1` binds underwriting hashes to quote, route, approvals, receiver, destination, expected output, provider and fee/slippage state. It is evidence of what FINCO showed before signing; it is **not** FINCO Verify.

`YIELD_POST_TRADE_RECEIPT_V1` is a typed receipt design for tx hash/block/input/actual shares/quoted shares/slippage/timestamp. No real-money mainnet transaction is required for PR acceptance.

## H. Execution architecture

Execution remains independently gated by `FINCO_YIELD_EXECUTION_ENABLED`, default OFF.

Direct ERC-4626 authority reads verify chain ID, code existence, `asset()`, `totalAssets()`, `totalSupply()`, decimals, `convertToAssets()`, `convertToShares()`, exact-amount `previewDeposit()` and `previewRedeem()` at an explicit block.

Allowance is read separately; insufficient allowance creates an exact/minimal approval plan before deposit. Unlimited approvals fail closed.

Bare ERC-4626 `deposit(uint256,address)` has no universal min-shares argument. Therefore direct plans are deliberately `UNPROTECTED_PREVIEW_ONLY` and `user_signable=False` in this PR. Expected shares are not described as guaranteed. Production signing requires an approved vault-specific protected route/router/official flow.

## I. Provider contracts

Provider review refreshed 2026-09-30 against current official documentation.

### 0x v2
Official references reviewed:
- https://docs.0x.org/docs/developer-resources/supported-chains
- https://docs.0x.org/docs/upgrading/upgrading_to_swap_v2
- https://docs.0x.org/docs/developer-resources/contract-addresses

V1 uses the Swap API v2 AllowanceHolder quote shape. Provider response is normalized into FINCO-owned types. Approval and transaction targets must appear in explicit server-side chain-specific allowlists; unknown targets fail closed. Settler is not treated as an arbitrary ERC-20 approval target. 0x remains swap infrastructure, not FINCO authority.

### Enso
Official API reviewed:
- https://api.enso.build/api

Route responses are normalized and require a server-side chain-specific transaction-target allowlist. Raw provider JSON is not canonical Yield evidence. Authoritative Enso support for Robinhood Chain 4663 was not proven and remains `UNCONFIRMED`.

### Morpho
Official references reviewed:
- https://docs.morpho.org/developers/api/get-started/
- https://docs.morpho.org/developers/api/morpho-api/
- https://docs.morpho.org/get-started/resources/data/

Morpho native data is suitable for discovery/enrichment; direct contract reads are preferred for execution identity at an explicit block.

## J. Wallet boundary

Yield reuses `app.protocol.wallet_auth.get_verified_wallet`; it does not create a second wallet identity system. The verified wallet is used only for read-only position context and the canonical economic receiver.

Wallet ownership ≠ transaction signing ≠ `$FINCO` entitlement.

## K. Security / threat model

Fail-closed controls cover unknown UID, destination substitution, underlying/funding-token substitution, share-token substitution, receiver substitution, chain/amount/route/calldata mutation, quote expiry, approval mutation, unlimited approvals, unexpected provider targets and direct RPC chain/contract/asset/share mismatch.

Adapter failures are isolated and browser-safe; secrets, Authorization headers, signed URLs, provider internals and stack traces are not exposed as public error text.

No private-key API, server-side signing, auto-broadcast, auto-invest or rebalance API exists.

## L. Custody boundary

`CUSTODY = NO`.

Out of V1 scope: proprietary FINCO vault, allocator, keeper, rebalancer, pooled user funds, custody and automated portfolio management.

## M. Feature flags

- `FINCO_YIELD_ENABLED=0` default;
- `FINCO_YIELD_EXECUTION_ENABLED=0` default.

Optional runtime settings:
- `FINCO_YIELD_RPC_<chain_id>`;
- `FINCO_YIELD_HISTORY_PATH`;
- `ZERO_X_API_KEY`, `ENSO_API_KEY`;
- `FINCO_YIELD_0X_APPROVAL_TARGETS_<chain_id>`;
- `FINCO_YIELD_0X_TRANSACTION_TARGETS_<chain_id>`;
- `FINCO_YIELD_ENSO_TRANSACTION_TARGETS_<chain_id>`.

## N. Robinhood readiness

`ROBINHOOD_CHAIN_4663 = PARTIAL` as of 2026-09-30.

Source-proven during review: Robinhood chain identity/EVM compatibility, Morpho API chain listing, and 0x supported-chain listing.

Not yet proven to FINCO production standard: maintainable FINCO-supported opportunity set, block-bound reads for selected vaults, authoritative Enso 4663 support, and end-to-end FINCO routed execution on 4663.

## O. Current limitations

1. The 14 bundled opportunities are frozen research observations, not a live current-state feed.
2. The direct adapter is implemented but this implementation environment did not have a configured live RPC proof; production direct authority remains `PARTIAL` until runtime evidence is captured.
3. Bare direct ERC-4626 signing is not activated because `previewDeposit()` is not a min-shares guarantee.
4. 0x/Enso production routing remains review-only until deployment allowlists/credentials and current provider contracts are independently reviewed.
5. No fabricated 7d/30d history is backfilled; windows appear only after sufficient real immutable observations exist.
6. Wallet Monitor only reads configured Yield RPC chains; position value/earned amount remain unavailable without source-bound valuation methodology.
7. Aave is deferred rather than forced into the wrong semantics.
8. Mainnet transaction signing/broadcast is not activated.

## P. Production activation requirements

Before mainnet execution activation: independent security review, live contract-semantic verification for enabled opportunities, reviewed provider target allowlists, vault-specific deposit-protection decision, browser wallet-handoff review, exact-head CI, independent PR review and explicit human approval.

No production activation is part of this PR acceptance.

## Q. Explicit authority separation

PR #148 does not authorize Yield to become authority for `financial_engine/**`, `finco_core/**`, `finco_radar/authority/**`, `app/model_validation/**`, `app/verified/**`, Signed Run or token entitlement.

`$FINCO` must not alter APY, evidence confidence, opportunity ordering, route economics or Yield calculation/evidence state. Future utility may gate convenience/intelligence depth, not economic authority.
