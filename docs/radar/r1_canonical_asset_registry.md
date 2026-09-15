# FINCO Radar R1 — Canonical Asset Registry

## Scope

R1 establishes a fail-closed canonical identity layer for tokenized assets. It remains read-only and isolated from `financial_engine/` and `finco_core/`.

## Canonical identity

The canonical deployment key is:

`chain_id + contract_address`

Ticker/symbol is never a primary key. Symbols are allowed only for discovery, display and provider endpoint selection after the symbol has been bound back to a canonical deployment. Symbols are validated as a single safe provider path segment before use in a reference request.

The official Stock Token asset UID is stored as the cross-chain asset identity. One UID may have deployments on multiple chains, while each deployment key must belong to exactly one UID.

## Official source mapping

R1 consumes the official Robinhood Stock Token `/assets` registry and preserves:

- onchain asset UID;
- token symbol/name as metadata;
- per-chain contract deployments;
- current multiplier;
- pending multiplier and effective time when present;
- asset status;
- trading-capability metadata;
- raw source evidence.

`currentMultiplier` is mandatory and must be positive and finite. R1 never defaults a missing multiplier to `1`.

## Collision rules

R1 fails closed on:

- the same canonical deployment key owned by two asset UIDs;
- duplicate asset UIDs in one snapshot;
- more than one deployment for one asset on the same chain;
- malformed UID/address/symbol fields;
- unknown asset status values;
- invalid or inconsistent multiplier metadata.

Duplicate symbols are **not** treated as a registry conflict. They are explicitly allowed as metadata collisions; symbol discovery must return all matches and must never silently choose one.

## Reference binding

Robinhood's `/prices/{symbol}` endpoint is symbol-addressed, so R1 creates a typed `ReferenceBinding` from a canonical asset record before calling it. The adapter's bound-reference surface fetches the symbol-addressed payload and immediately validates it. A returned price row is accepted only if its deployment list contains the exact bound `chain_id + contract_address` exactly once and its symbol metadata agrees with the bound record.

Live evidence records both the requested canonical key and the canonical key reconstructed from the returned reference deployment evidence. CI requires those keys to be identical; it does not rely on a hardcoded success flag.

This prevents a same-ticker/wrong-contract row from becoming a valid reference mapping.

R1 does not yet decide whether a reference is current, stale, halted or paused for a corporate action. Those semantics belong to R4 — Reference State Engine.

## Official UID handshake boundary

R1 can re-validate an **official registry UID** against one or more exact canonical deployments. This is not a generic multi-provider external-identity registry. Provider-namespaced external identifiers, provenance and conflict policy belong to the later Reference State / cross-market authority workstream.

## Multiplier boundary

R1 stores `currentMultiplier`, `pendingMultiplier` and the pending effective timestamp as registry metadata. It does not apply trading-state semantics to those fields. R2/R4 may consume them through the canonical asset record rather than rediscovering them by ticker.

## R0 boundary

R0 remains the frozen execution-authority proof and is not rewritten as part of R1. R1 becomes the canonical identity authority for subsequent Radar phases. The R1 live gate reruns both the R0 network proof and the original R0 size-aware economics acceptance criterion, so registry work cannot silently break the execution-quote layer.

## R1 acceptance

The live proof must establish that:

1. the official registry returns at least one asset;
2. all asset UIDs are unique;
3. all canonical deployment keys are unique;
4. at least one active deployment exists on Robinhood Chain (`4663`);
5. a symbol-addressed reference response can be bound back to one exact canonical deployment with reconstructed deployment evidence;
6. the existing R0 execution-quote proof and size-aware acceptance criterion still pass as a regression check;
7. `financial_engine/` and `finco_core/` remain unchanged.
