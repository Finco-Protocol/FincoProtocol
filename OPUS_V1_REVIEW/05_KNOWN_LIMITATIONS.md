# FINCO V1 — Known Limitations

This document states limitations explicitly. None are hidden. A reviewer should
treat any undisclosed deviation from these as a potential finding.

---

## 1. Jev / Reflex — Experimental, Not V1

- Issue #119 (Jev / Reflex) is experimental / shadow.
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
- Current MODEL_ONLY records must not be described as VERIFIED.
- Validation PASS is not evidence of VERIFIED status.
- Reference: `app/verified/authority.py`, `tests/test_b2_1_verified_authority.py`.

---

## 4. Storage Vertical — PREVIEW Only

- The Storage vertical is `ProductStatus.PREVIEW`.
- Reference model is viewable.
- Working-copy runtime is NOT released in V1.
- Cloning and working-copy editing are not available for Storage.

---

## 5. Signed Run Certificate — Production Signing Key Required

- Signed Run Certificate V1 uses Ed25519 asymmetric signing (`app/services/run_certificate_service.py`).
- Issuance requires `FINCO_RUN_CERT_SIGNING_KEY` (base64-encoded, 32-byte Ed25519
  seed) in deployment configuration. There is no fallback production key.
- Without a configured signing key, issuance raises `SigningKeyUnavailable` and
  fails closed.
- Meaningful issuer trust requires that the verifier independently trusted and
  pinned the public key. A self-supplied key or key identifier alone does not
  establish the issuer's identity.

---

## 6. Legacy Runs — Workbook Version Required for Signed Run

- Legacy Last Runs without a persisted `workbook_version` cannot be signed.
- Issuance fails closed with `LAST_RUN_IDENTITY_INCOMPLETE` for such runs.
- The current workbook version is never substituted at issuance.
- Affected projects must perform a new calculation run before a Signed Run
  Certificate can be issued.

---

## 7. MCP V1 — Server-Session Deployment Boundary

- The FINCO MCP V1 server is read-only.
- Current deployment model uses a server-configured `FINCO_SESSION_TOKEN` decoded
  through the existing signed session authority.
- MCP V1 is not yet reviewed as a shared arbitrary multi-user hosted transport.
  Its current deployment boundary is single-session, server-configured identity.
- This is a deployment/isolation boundary, not a security defect in the codebase.

---

## 8. B2.3 Usage Metering — Hook Coverage

- B2.3 Usage Metering records usage events in an append-only ledger.
- MCP tool-call (`FEATURE_MCP_TOOL_CALL`) and Trust Pack interaction metering
  hooks may exist in the codebase but are not necessarily wired into all
  production traffic paths.
- Do not claim complete production metering coverage unless source proves it.
- `TOKEN_CONFIGURATION_UNAVAILABLE` remains truthful where applicable.

---

## 9. R-LIVE Collector and Operational Configuration

- The R-LIVE collector (PR #127, updated PR #139) is an external systemd
  operational package. The no-arg command `python -m app.radar_rwa.r_live_collect`
  iterates every key in `APPROVED_BY_CANONICAL_ID` serially (`collect_all_approved`).
  `--asset-key` restricts a diagnostic run to one exact approved AssetKey.
- Collection requires `ROBINHOOD_RPC_URL` (Robinhood Chain 4663 HTTPS RPC, private,
  never committed to Git) and `RADAR_BNB_INTELLIGENCE_DB_PATH` (durable B1.3 history
  ledger shared between the web service and collector). Missing `ROBINHOOD_RPC_URL`
  produces `RPC_NOT_CONFIGURED` and exits 1 before any per-asset work.
- The web current-read path (`GET /api/v1.1/radar/r-live/{uid}`) also requires
  `ROBINHOOD_RPC_URL` at request time; it never reads or writes the history ledger.
  Current observation and history are architecturally separate surfaces.
- The web history read path (`GET /api/v1.1/radar/r-live/{uid}/history`) reads from
  the shared B1.3 ledger (`RADAR_BNB_INTELLIGENCE_DB_PATH`); it never writes. The
  collector is the sole history writer.
- Web process and collector must be configured with the identical
  `RADAR_BNB_INTELLIGENCE_DB_PATH`. Staging and production must be different files;
  a shared path between environments silently cross-contaminates history.
- Canonical market states (AVAILABLE, STALE, UNAVAILABLE from authority) are not process
  failures. Exit 0 means the batch ran without process-level error; mixed market states
  are expected and healthy.
- Pre-batch process failures (abort before any per-asset work): `RPC_NOT_CONFIGURED`,
  `RPC_UNAVAILABLE` (chain preflight fails), `HISTORY_STORE_UNAVAILABLE` (ledger
  initialization fails), `APPROVED_REGISTRY_UNAVAILABLE`.
- Per-asset acquisition exception: that asset is recorded as UNAVAILABLE; remaining
  approved assets are still attempted; after the complete batch:
  `process_error = R_LIVE_ACQUISITION_RUNTIME_UNAVAILABLE`, exit 1. Exceptions do not
  abort the remaining batch.
- Post/in-batch persistence failure: `HISTORY_PERSISTENCE_UNAVAILABLE` per-asset, or
  ledger close exception → `HISTORY_STORE_UNAVAILABLE` after batch, exit 1.
- Repository-ready deployment assets do not prove that a production VPS collector
  is currently active. Do not claim production collection is active without
  actual deployment evidence.

---

## 10. Reference Prices — Not Executable Prices

- R-LIVE provides reference market intelligence: on-chain TWAP with Chainlink
  adjustment.
- A reference price is not an executable quote. It is observational.
- Radar data does not flow into the financial engine.

---

## 11. Radar Data Sources — External Dependencies

- Radar modules depend on external APIs: CoinGecko, Hyperliquid, FRED,
  DeFiLlama, BNB chain RPC.
- Without configured API keys or live network access, Radar data returns
  gracefully degraded (empty or cached) responses.
- Tests that require live external data are skipped in CI via scope gates
  (`tests/test_radar_ci_scope_gate.py`).

---

## 12. XLSX Export — Requires Committed Last Run

- Institutional XLSX export is only available for projects with a committed
  Last Run.
- A project in Working Copy state (no committed run) cannot produce an
  institutional export.

---

## 13. Demo Sessions — Not Entitled

- Demo sessions (`DEMO_COOKIE_NAME`) do not carry FINCO token entitlement.
- They have read access to public reference models but not to Verified dossiers
  or institutional exports.

---

## 14. No Fiat / Token Price in Usage Metering

- B2.3 Usage Metering records usage events.
- There is no billing engine, no fiat price per event, and no token price
  per event in V1.
- Usage data is observability only.

---

## 15. R-LIVE V2 — Approved Pool ≠ Current Availability; SCAN_COMPLETE = NO

- R-LIVE V2 reviewed and approved 13 assets (AAPL, NVDA, AMZN, GOOGL, TSLA,
  AVGO, NFLX, AMD, DELL, SNAP, INTC, MSFT, META) based on on-chain authority
  reviews at blocks 75507992 (initial 8 assets, PR #136, 2026-09-29) and
  75763398 (5 additional assets: DELL, SNAP, INTC, MSFT, META, PR #140, 2026-09-29).
- MSFT and META were REJECTED at PR #136 (insufficient Swap activity at that time)
  and ADMITTED at PR #140 following a new source-proven review. ORCL and PLTR
  remain excluded.
- **SCAN_COMPLETE = NO**: the review environment's egress policy blocked
  api.robinhood.com and rpc.mainnet.chain.robinhood.com (HTTP 403), preventing
  a registry-wide exhaustive scan of all candidates. This does not weaken the 13
  admitted assets — each has individually source-proven admission evidence. It means
  additional assets may be admissible once the scan environment permits wider access.
  No authority standards were weakened to compensate for the blocked scan.
- Pool approval at review time does not guarantee that a current observation
  is AVAILABLE at any later time.
- Runtime re-validates freshness: the last qualifying Swap must be within 300
  seconds at the pinned head. No Swap in that window returns STALE.
- USDG is never assumed to equal USD 1; the Chainlink USDG/USD proxy is
  re-read at each acquisition.
- REJECTED assets (ORCL, PLTR) are excluded from the registry. They cannot be
  queried via the public API. Their exclusion is permanent until a new review.
- The R-LIVE public API is unauthenticated (reference surface). This is
  intentional: it is read-only and does not expose any user or project data.

---

## 16. R-LIVE V2 — Collection-Time History and Range Semantics (PR #140)

- 1h/24h ranges are selected by `collected_at` (FINCO collection timestamp), not by
  on-chain observation time (`effective_evidence_at`). This is intentional: ranges
  reflect the collection cadence, not on-chain block time.
- A range window requires >=2 collected points to produce a summary. Fewer points returns
  an appropriate empty or insufficient-data response. There is no price interpolation.
- `collected_at` and `effective_evidence_at` are structurally separate fields. Do not
  assume they are equal.
- STALE last-available UX shows the last canonical AVAILABLE value with an explicit
  HISTORICAL label when the current reading is STALE. This value is not a current
  observation. The STALE badge is never promoted to AVAILABLE when a historical fallback
  is displayed.
- Landing page batch: the R-LIVE landing uses 2 total API requests (1 current + 1 ranges),
  not one request per asset. Landing batch optimization is code-proven.

---

## 17. B2.3 Concurrent Idempotency — Correctness Fixed, Scale Not Guaranteed

- PR #135 fixed a SQLite lock-error on concurrent duplicate delivery
  (`(subject_id, feature_key, idempotency_key)` constraint).
- The fix ensures: no lock error to caller; successful canonical response;
  exactly one persisted usage event under concurrent duplicate delivery.
- This correctness fix does not claim unlimited production-scale concurrency.
  High-throughput production deployments should evaluate SQLite concurrency
  limits independently.

---

## 18. $FINCO Token Not Yet Launched

- The protocol access and service-entitlement layer is implemented.
- The $FINCO token is not yet launched. Token economics, access thresholds,
  network deployment, and smart-contract design are not final.
- Token utility does not imply that a token contract, token sale, staking system,
  or token-gated production service is currently live.
