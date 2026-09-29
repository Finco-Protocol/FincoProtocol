# FINCO V1 — Known Limitations

This document states limitations explicitly. None are hidden. A reviewer should
treat any undisclosed deviation from these as a potential finding.

---

## 1. Jev / Reflex — Experimental, Not V1

- Issue #119 (Jev / Reflex) is experimental.
- It is explicitly NOT part of FINCO V1 authority.
- Its existence in the repository does not constitute a supported V1 capability.
- Do not assess Jev / Reflex as part of the V1 scope.

---

## 2. Production Deployment Status

- The repository does not document a live production URL.
- The FINCO Protocol may not be deployed to a publicly accessible production
  environment at the time of this review.
- `app/product_capability.py` and the test suite describe WHAT is implemented
  in the codebase; they do not assert WHERE it is deployed.
- Reviewers should not assume any public URL is available without independent
  verification.

---

## 3. No Fabricated Model ↔ Market RWA Binding

- No FINCO V1 run is bound to a real-world asset by a production
  `ModelMarketRunBinding` with a confirmed live on-chain observation.
- The B2.1 binding architecture is implemented and tested.
- A concrete production binding requires: an operator supplying source-attested
  on-chain evidence with a confirmed `evidence_id`. This is an operational step,
  not a code step.
- Reference: `app/verified/authority.py`, `tests/test_b2_1_verified_authority.py`.

---

## 4. Storage Vertical — PREVIEW Only

- The Storage vertical is `ProductStatus.PREVIEW`.
- Reference model is viewable.
- Working-copy runtime is NOT released in V1.
- Cloning and working-copy editing are not available for Storage.

---

## 5. Cryptographic Signing — Hash-Based Only in V1

- Run Certificates use composite SHA-256 hash binding in V1.
- Asymmetric key signing (e.g., Ed25519 or secp256k1) is not implemented in V1.
- The Run Certificate proves computational integrity (what was run, engine version,
  digests) but does not carry a cryptographic signature that can be verified by
  a third party without access to the FINCO system.

---

## 6. MCP V1 — Read-Only Interface Only

- The FINCO MCP V1 server is read-only.
- It surfaces model references, run metadata, and Radar snapshots.
- It does not execute model runs, modify projects, or write any state.
- MCP tool-call usage metering (`FEATURE_MCP_TOOL_CALL`) is defined as a
  hook interface in V1 — it is not wired to live MCP traffic in V1.

---

## 7. R-LIVE Collector — Timer-Based, External Dependency

- R-LIVE snapshot collection requires configured external API keys
  (see `app/radar_rwa/r_live_collect.py`).
- Without valid API keys, R-LIVE collection fails gracefully (no crash,
  but no live snapshots).
- The collector timer is implemented (`PR #127`) but requires operational
  configuration to produce live data.

---

## 8. Radar Data Sources — External Dependencies

- Radar modules depend on external APIs: CoinGecko, Hyperliquid, FRED,
  DeFiLlama, BNB chain RPC.
- Without configured API keys or live network access, Radar data returns
  gracefully degraded (empty or cached) responses.
- Tests that require live external data are skipped in CI via scope gates
  (`tests/test_radar_ci_scope_gate.py`).

---

## 9. XLSX Export — Requires Committed Last Run

- Institutional XLSX export is only available for projects with a committed
  Last Run.
- A project in Working Copy state (no committed run) cannot produce an
  institutional export.

---

## 10. Demo Sessions — Not Entitled

- Demo sessions (`DEMO_COOKIE_NAME`) do not carry FINCO token entitlement.
- They have read access to public reference models but not to Verified dossiers
  or institutional exports.

---

## 11. No Fiat / Token Price in Usage Metering

- B2.3 Usage Metering records usage events.
- There is no billing engine, no fiat price per event, and no token price
  per event in V1.
- Usage data is observability only.
