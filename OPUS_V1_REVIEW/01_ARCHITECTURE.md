# FINCO V1 — Architecture: Eight-Step Pipeline

Each step identifies the canonical module, exact purpose, what it proves, and
what it does NOT prove.

The pipeline is linear for a model run. Radar and Verified operate on parallel
authority lanes.

---

## 1. CALCULATE

**Canonical module:** `financial_engine/`, `finco_core/`, `domain/`

**Purpose:** Deterministic FINCO project-finance engine. Computes cash flows,
returns, financial statements, and credit metrics from project inputs.

**What it proves:**
- Given a set of project inputs (capacity, production, pricing, debt, tax, etc.),
  deterministically produces financial outputs.
- All arithmetic is performed in these namespaces. No other module executes
  financial math.

**What it does NOT prove:**
- Nothing about real-world asset performance or market prices.
- The inputs are assumed by the modeller; the engine does not verify them.
- No on-chain state is consumed here.
- A calculation result is not a verified record until it is COMMITTED and SIGNED.

---

## 2. COMMIT

**Canonical module:** `app/persistence/runs_repository.py`, `app/persistence/records.py`

**Purpose:** Canonical immutable Last Run identity — one persisted snapshot of
the committed calculation.

**What it proves:**
- One immutable Last Run snapshot is persisted: engine version, composite hash,
  assumption digest, output digest, run timestamp, workbook version, scenario id,
  run origin.
- Working Copy exists (current editable state). **Working Copy ≠ Last Run.**
- `last_runtime_composite_hash` is the integrity anchor for this committed run.

**What it does NOT prove:**
- That the inputs were correct or market-validated.
- That the outputs match any on-chain asset state.
- A committed run is not a verification.

---

## 3. VALIDATE

**Canonical module:** `app/model_validation/runner.py`, `app/model_validation/contracts.py`

**Purpose:** Reference Regression Check (H-4A) — pinned reference-model regression evidence.

**What it does:** The Reference Regression Check executes against the canonical
reference model for the vertical, not against the user's project data. It compares
the reference model's outputs / KPIs with pinned expected reference values and
tolerances. It is regression protection for the reference library.

**What it proves:**
- Specific numeric tolerances are declared in `app/model_validation/tolerances.py`.
- The canonical reference model still reproduces its pinned expected values within
  those tolerances.
- The result is surfaced on the Trust Pack; it always describes the canonical
  reference, never the user's own Last Run.

**What it does NOT prove:**
- It does **not** validate the user's committed Last Run.
- It does **not** establish accounting, debt, cash-flow or financing integrity of
  that Last Run. Regression protection for the reference library is its whole
  scope; it is not a model-soundness guarantee.
- **Reference Regression Check ≠ FINCO VERIFY.** It does not establish a market
  identity or run binding.
- A passing check does not mean any real-world asset has been verified.

**Read/write boundary:** The Reference Regression Check runs the P1.3 reference reconciliation.
From the Trust Pack UX, it is a DEFERRED / explicit user-action path — never
triggered at page render time.

---

## 4. VERIFY

**Canonical module:** `app/verified/authority.py`, `app/verified/contracts.py`

**Purpose:** FINCO VERIFY — source-proven evidence and binding authority.

**What it proves:**
- A `ModelMarketRunBinding` (`app/verified/authority.py`) establishes an explicit
  attestation joining one FINCO Last Run (by composite hash), one market asset
  (by canonical cross-chain identity), and source-attested evidence.
- No production binding is created by name, symbol, or CoinGecko data alone.
- The binding requires explicit, source-attested evidence with a timezone-aware
  `observed_at` timestamp and confirmed `evidence_id`.

**What it does NOT prove:**
- VERIFY does not assert that the model IRR equals the asset's market return.
- The binding does not claim mathematical equivalence between model and market.
- **FINCO VERIFY ≠ Reference Regression Check** (separate systems, separate authorities).
- **FINCO VERIFY ≠ Signed Run Certificate** (separate systems, separate authorities).

---

## 5. OBSERVE

**Canonical module:** `finco_radar/authority/`, `app/radar_rwa/r_live_service.py`,
`finco_radar/authority/r_live_onchain.py`

**Purpose:** Radar / R-LIVE — market observation and reference authority.

**What it proves:**
- R-LIVE: on-chain reference price for AAPL (Robinhood chain 4663) via an approved
  independent AAPL/USDG Uniswap V3 pool. 300-second TWAP. USDG/USD Chainlink
  adjustment. Never hardcodes USDG = $1.
- History writes are structurally separated from reads. External one-shot collector
  (`PR #127`) is the sole history writer. Read paths never write history.
- Only AVAILABLE observations persist. STALE / UNAVAILABLE do not append numeric
  history.
- Cross-chain canonical identity (`finco_radar/authority/cross_chain.py`) uses
  source-attested evidence, not name/symbol matching.

**What it does NOT prove:**
- A reference price is not an executable quote. Radar data is reference intelligence.
- Missing observations are surfaced as gaps, not as zero values.
- Market observations do not flow into the financial engine.
- Repository-ready deployment assets do not prove production collection is active.

---

## 6. SIGN

**Canonical module:** `app/services/run_certificate_service.py`

**Purpose:** Signed Run Certificate V1 — cryptographic provenance and integrity
of the committed Last Run.

**What it proves:**
- Ed25519 signature over a FINCO canonical JSON payload.
- Issued from committed Last Run only — never re-runs the engine.
- Never accepts Working Copy values.
- Payload includes: explicit issuer, timezone-aware `issued_at`, snapshot_id,
  composite_hash, persisted workbook_version, engine_version, scenario_id,
  run_origin, KPI digest, key_id, payload_digest, signature_algorithm.
- Incomplete identity fails closed (`LAST_RUN_IDENTITY_INCOMPLETE`).
- Legacy runs without persisted workbook_version must be rerun before issuance.
- Requires configured `FINCO_RUN_CERT_SIGNING_KEY` (base64-encoded 32-byte Ed25519
  seed). No fallback production key.
- Independently trusted/pinned public key required for meaningful issuer trust.

**What it does NOT prove:**
- **SIGNED RUN ≠ FINCO VERIFY** — completely separate authorities.
- **SIGNED RUN ≠ economic truth.**
- **SIGNED RUN ≠ model correctness.**
- **SIGNED RUN ≠ executable market price.**
- The certificate carries no synthetic FINCO Verify observation.
- Issuer trust requires that the verifier independently pin/trust the public key.
  A self-supplied key does not establish identity.

**From the Trust Pack UX:** Signed Run Certificate is a DEFERRED / explicit
user-action path — never issued at page render time.

**Authority separation:** `TRUST_PACK_RENDER_DOES_NOT_SIGN`

---

## 7. DISTRIBUTE

**Canonical module:** `app/api/v1_1/` (API v1.1), `app/mcp/v1/server.py` (MCP V1),
`app/export/institutional_workbook.py`

**Purpose:** API v1.1 + MCP V1 — read-only institutional and agent access to
canonical authorities.

**API v1.1 endpoints (read-only):**
- `/projects/{id}/run-identity` — committed Last Run identity
- `/projects/{id}/kpis` — canonical KPIs from Last Run
- `/projects/{id}/validation` — Reference Regression Check evidence (machine authority key `MODEL_VALIDATION`)
- `/projects/{id}/verify` — FINCO VERIFY state
- `/projects/{id}/export` — institutional export metadata
- `/projects/{id}/run-certificate` — Signed Run Certificate V1 (explicit action)

**MCP V1 tools (read-only, 9 tools):**
`finco_supported_today`, `finco_projects`, `finco_last_run`, `finco_run_identity`,
`finco_kpis`, `finco_validation`, `finco_verify`, `finco_r_live`, `finco_export_metadata`

No duplicate financial or Verify logic. No trusted caller-controlled user_id.
Signed session identity only. R-LIVE reads perform zero history writes.

**Institutional XLSX export:**
- Packages Last Run outputs, run lineage, Reference Regression Check status, and methodology notes.
- Never re-runs the engine; reads persisted outputs only.
- Requires a committed Last Run.

**Model Trust Pack UX V1 (`app/ui/trust_pack.py`):**
Read-only composition of seven canonical evidence sections. Sections C (Reference
Regression Check) and G (Signed Run Certificate) are DEFERRED — loaded only by explicit
user action. Never runs the model and never silently issues a certificate.

---

## 8. METER

**Canonical module:** `app/usage/ledger.py`, `app/usage/query.py`,
`app/usage/contracts.py`

**Purpose:** B2.3 — off-chain usage ledger downstream of access.

**What it proves:**
- Usage events are recorded in an append-only SQLite ledger after the B2.2
  access decision. Recording never affects the access decision.
- Subject identity always derives from the signed session (`session.user_id`);
  callers cannot supply it.
- Idempotency is scoped: `UNIQUE(subject_id, feature_key, idempotency_key)`.
- Query failures return `UsageQueryResult(state=UNAVAILABLE)` — structurally
  distinct from empty/zero usage.
- Wallet address resolved internally from `app.protocol.wallet_auth` (fail-open
  direction: usage recorded even if wallet unavailable).

**What it does NOT prove:**
- Usage recording has no effect on financial math or verification truth.
- No billing engine, no fiat/token price, no entitlement decision in B2.3.
- MCP tool-call and Trust Pack metering hooks may exist but are not necessarily
  wired into all production traffic paths.

---

## Radar Authority Lane (parallel)

**Modules:** `finco_radar/`, `app/radar_rwa/`, `app/radar_crypto/`,
`app/radar_economy/`, `app/radar_derivatives/`, `app/radar_stablecoins/`

**Key invariants:**
- R-LIVE reads are structurally separated from history writes.
- Cross-chain canonical identity uses source-attested evidence.
- Market observations do not flow into the financial engine.
- BNB Tokenized Assets is a Radar capability, not a Model vertical.

## Critical Invariants

```
Reference Regression Check ≠ FINCO VERIFY
SIGNED RUN ≠ FINCO VERIFY
SIGNED RUN ≠ economic truth
SIGNED RUN ≠ model correctness
SIGNED RUN ≠ executable market price
MARKET REFERENCE ≠ executable price
$FINCO NEVER TOUCHES THE MATH.
$FINCO NEVER DETERMINES WHETHER EVIDENCE IS TRUE.
```
