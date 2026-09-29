# FINCO V1 — Capability Matrix

Canonical source: `app/product_capability.py`
Consistency enforced by: `tests/test_p0_4_capability_contract.py`, `tests/test_product_capability_consistency.py`

## Model Verticals

| Vertical | Status | Reference | Runnable | Cloneable | Working Copy | Last Run | API |
|---|---|---|---|---|---|---|---|
| Solar | LIVE | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Wind | LIVE | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Data Center | LIVE | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| EV Charging | LIVE | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Storage | PREVIEW | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |

**Storage note:** Reference model is viewable. Working-copy runtime not released in V1.

**BNB Tokenized Assets is a Radar capability — it is NOT a Model vertical.** It is
not runnable, cloneable, or accessible as a model project. Do not include it in
the Model vertical list.

## Model Trust / Output Capabilities

| Capability | Status | Source |
|---|---|---|
| Canonical Last Run (COMMIT) | LIVE | `app/persistence/runs_repository.py` |
| Institutional XLSX Export (P1.2) | LIVE | `app/export/institutional_workbook.py`; requires committed Last Run |
| MODEL VALIDATION (P1.3) | LIVE | `app/model_validation/`; P1.3 reference reconciliation |
| EV Institutional Reconciliation (P1.4) | LIVE | EV-specific reconciliation closure |
| Institutional Trust Pack (P1.1) | LIVE | Methodology HTML, DSCR, XIRR ACT/365F docs |
| FINCO VERIFY / Verified Assets (B2.1) | LIVE | `app/verified/authority.py`; explicit market binding required |
| Signed Run Certificate V1 | LIVE | `app/services/run_certificate_service.py`; Ed25519; requires `FINCO_RUN_CERT_SIGNING_KEY` |
| Model Trust Pack UX V1 | LIVE | `app/ui/trust_pack.py`; 7-section read-only evidence surface in V2 workbook; PR #133 |

## Radar

| Capability | Status | Source |
|---|---|---|
| Radar B1.1 — BNB RWA market intelligence | LIVE | `finco_radar/`, `app/radar_rwa/` |
| Radar B1.2 — Cross-chain canonical identity | LIVE | `finco_radar/authority/cross_chain.py` |
| Radar B1.3 — BNB premium, execution gap, exact-identity history | LIVE | `finco_radar/` |
| R-LIVE V2 — 8-asset registry (AAPL, NVDA, AMZN, GOOGL, TSLA, AVGO, NFLX, AMD) | LIVE | `finco_radar/authority/r_live_policy.py`, `finco_radar/authority/r_live_onchain.py`, `app/radar_rwa/r_live_service.py` |
| R-LIVE V2 public API (3 read-only routes) | LIVE | `app/api/v1_1/r_live_public_router.py`; unauthenticated; exact canonical_id only |
| R-LIVE V2 UX shell — landing table + per-asset detail | LIVE | `app/radar_ui/r_live_router.py`; `/radar/r-live`, `/radar/r-live/{canonical_id}` |
| R-LIVE history store (B1.3) | LIVE | Durable B1.3 history; external collector is sole writer; read paths write zero history |
| R-LIVE multi-asset collector (PR #139) | LIVE | `app/radar_rwa/r_live_collect.py`; no-arg = full approved registry batch (`collect_all_approved`); `--asset-key` = single diagnostic; requires `ROBINHOOD_RPC_URL` + `RADAR_BNB_INTELLIGENCE_DB_PATH` |
| R-LIVE operational collector package (PR #127, updated PR #139) | LIVE | External systemd operational package; staging config contract; `ROBINHOOD_RPC_URL` + `RADAR_BNB_INTELLIGENCE_DB_PATH` required; staging/production ledgers must be separate |

**R-LIVE code status vs operational status:**
- Code/product surface: SHIPPED (implemented, tested, in repository)
- Operational current-data activation: REQUIRES DEPLOYMENT CONFIGURATION — NOT PROVEN BY REPO
  (`ROBINHOOD_RPC_URL` + active VPS collector + `RADAR_BNB_INTELLIGENCE_DB_PATH` must be configured)
- "LIVE" in this table means the capability is implemented and exposed in the codebase.
  It does NOT mean "staging/production RPC and collector are currently proven active."

**R-LIVE V2 public API routes (exact):**
- `GET /api/v1.1/radar/r-live/assets` — list approved identities (no auth required)
- `GET /api/v1.1/radar/r-live/{canonical_id}` — current reference for exact identity
- `GET /api/v1.1/radar/r-live/{canonical_id}/history` — historical evidence (read-only, zero writes)

**R-LIVE identity semantics:** UID is the `canonical_id` from `APPROVED_RLIVE_ASSETS`
(e.g. `4663:0xaf3d76f...`). No ticker/symbol/fuzzy lookup. Unapproved identity
returns `UNAVAILABLE` / `ASSET_NOT_IN_REGISTRY`.

**R-LIVE critical invariants:**
- 300-second TWAP freshness gate; no Swap in window → STALE
- USDG/USD conversion from canonical Chainlink oracle (never assumed 1:1)
- STALE and UNAVAILABLE suppress current numeric observations
- Read paths perform zero history writes; collector is sole writer
- Reference is indicative and non-executable; does NOT create FINCO VERIFIED status
- Approved pool at review time ≠ guarantee of current AVAILABLE observation

## Distribution

| Capability | Status | Source |
|---|---|---|
| API v1 (model references + Radar) | LIVE | `main_api.py` → `app/api/v1/` |
| API v1.1 (institutional, read-only) | LIVE | `app/api/v1_1/`; read-only |
| MCP V1 (read-only institutional agent) | LIVE | `app/mcp/v1/server.py`; 9 tools; signed session identity |

## Token / Access

| Capability | Status | Source |
|---|---|---|
| B2.2 Token Entitlement | LIVE | `app/verified/token_entitlement.py`; fail-closed |
| B2.3 Usage / Metering | LIVE | `app/usage/ledger.py`; append-only; session-scoped identity |
| P0.4 Release Integrity / Supported Today | LIVE | `app/product_capability.py` |

## Experimental (NOT V1 scope)

| Capability | Status | Notes |
|---|---|---|
| Jev / Reflex (#119) | **NOT V1** | Experimental shadow; explicitly not part of V1 authority |

## What "LIVE" means

A LIVE capability is implemented, current, and intentionally exposed today.
It may carry documented known limitations (see `05_KNOWN_LIMITATIONS.md`).
LIVE does not mean "production-deployed to a public URL" — deployment status
is separate from capability status.

## What "PREVIEW" means

Implemented but intentionally limited in a documented way. Reference viewable;
runtime or cloning not released.

## Critical capability boundaries

- No production `ModelMarketRunBinding` with confirmed live on-chain observation exists.
  The binding architecture is implemented and tested; activating it requires an
  operator supplying source-attested on-chain evidence.
- Signed Run Certificate V1 requires `FINCO_RUN_CERT_SIGNING_KEY` deployment
  configuration. Without it, issuance fails closed.
- R-LIVE collector requires both `ROBINHOOD_RPC_URL` (private, never committed) and
  `RADAR_BNB_INTELLIGENCE_DB_PATH` (shared durable B1.3 ledger). Web and collector must
  use the identical ledger path. Staging and production must be different files.
  Repository-ready does not prove VPS collector activation.
- No-arg collector batch: STALE/UNAVAILABLE/AVAILABLE per-asset are canonical market states,
  not process failures. Exit 0 when the batch ran with no process-level error (mixed market
  states are expected).
- Pre-batch process failures (no per-asset work): RPC_NOT_CONFIGURED, RPC_UNAVAILABLE
  (chain preflight fails), HISTORY_STORE_UNAVAILABLE (ledger init fails),
  APPROVED_REGISTRY_UNAVAILABLE → exit 1, results empty.
- Per-asset acquisition exception: asset recorded as UNAVAILABLE; remaining approved assets
  still attempted; after full batch: process_error = R_LIVE_ACQUISITION_RUNTIME_UNAVAILABLE,
  exit 1. Exceptions never abort the remaining batch.
- Post/in-batch persistence failure: HISTORY_PERSISTENCE_UNAVAILABLE per-asset or ledger
  close exception → HISTORY_STORE_UNAVAILABLE after batch, exit 1.
