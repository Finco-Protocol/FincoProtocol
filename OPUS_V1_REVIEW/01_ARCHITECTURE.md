# FINCO V1 — Architecture: Eight-Step Pipeline

Each step below identifies the canonical module, what it proves, and what it
explicitly does NOT prove. The pipeline is linear for a model run; Radar and
Verified operate on parallel authority lanes.

---

## 1. CALCULATE

**Canonical module:** `financial_engine/`, `finco_core/`, `domain/`

**What it proves:**
- Given a set of project inputs (capacity, production, pricing, debt, tax, etc.),
  deterministically computes cash flows, returns, financial statements, and
  credit metrics over a model period.
- All arithmetic is performed in these namespaces; no other module executes
  financial math.

**What it does NOT prove:**
- Nothing about real-world asset performance or market prices.
- The inputs are assumed by the modeller; the engine does not verify them.
- No on-chain state is consumed here.
- A calculation result is not a verified record until it is COMMITTED and SIGNED.

---

## 2. COMMIT

**Canonical module:** `app/persistence/runs_repository.py`, `app/persistence/records.py`

**What it proves:**
- One immutable Last Run snapshot is persisted: engine version, composite hash,
  assumption digest, output digest, and run timestamp.
- A Working Copy exists (the current editable state). Working Copy ≠ Last Run.
- `last_runtime_composite_hash` is the integrity anchor for this committed run.

**What it does NOT prove:**
- That the inputs were correct or market-validated.
- That the outputs match any on-chain asset state.
- A committed run is not a verification.

---

## 3. VALIDATE

**Canonical module:** `app/model_validation/runner.py`, `app/model_validation/contracts.py`

**What it proves:**
- Structural and tolerance checks run against the committed Last Run outputs.
- Specific numeric tolerances are declared in `app/model_validation/tolerances.py`.
- Validation status is stored and surfaced per-project.

**What it does NOT prove:**
- Validation is NOT Verify. Validation checks model structure; it does not
  establish a market identity or run binding.
- A "Validated" status badge on a project does not certify economic accuracy
  against real-world assets.

---

## 4. VERIFY

**Canonical module:** `app/verify/run_certificate.py`, `app/verify/issuer.py`

**What it proves:**
- A Run Certificate (`FINCO_RUN_CERTIFICATE_V1`) is generated from the
  persisted Last Run only — never by re-running the engine.
- The certificate binds: `composite_hash`, `engine_version`, `assumption_digest`,
  `output_digest`, `run_id`, and headline metrics.
- Certificate ID is deterministic (`frc_` prefix + 16 hex chars of SHA-256).
- The certificate is immutable once issued; a new run changes all digests.

**What it does NOT prove:**
- The certificate does not assert that the underlying model assumptions are
  correct or verified against any external data source.
- It proves WHAT was run and WHEN; not WHETHER the assumptions were right.
- Signing in V1 is hash-based; no cryptographic key signing is in V1.

---

## 5. OBSERVE

**Canonical module:** `app/observability.py`, `app/radar_rwa/r_live_service.py`,
`finco_radar/authority/`

**What it proves:**
- Radar collects and caches observable market data: on-chain token prices,
  liquidity, cross-chain identity, and R-LIVE (reference live) snapshots.
- R-LIVE snapshots are read-only; their provenance and staleness are
  surfaced explicitly.
- BNB RWA canonical identity is established via cross-chain evidence
  (`finco_radar/authority/cross_chain.py`).

**What it does NOT prove:**
- Observed data does not backfill missing on-chain data.
- A gap in observations is surfaced as a gap, not zero.
- Radar data is reference intelligence; it is not the model's inputs.

---

## 6. SIGN

**Canonical module:** `app/verify/run_certificate.py` (composite hash binding),
`app/verified/authority.py` (B2.1 model-market binding)

**What it proves:**
- A `ModelMarketRunBinding` (`app/verified/authority.py`) establishes an explicit
  attestation joining: one FINCO Last Run certificate (by composite hash), one
  market asset (by canonical cross-chain identity), and source-attested evidence.
- No production binding is created by name, symbol, or CoinGecko data alone.
- The binding requires explicit, source-attested evidence with a timezone-aware
  observation timestamp.

**What it does NOT prove:**
- A binding does not assert that the model IRR equals the asset's market return.
- Signing is not cryptographic key-signing in V1.
- The binding does not claim mathematical equivalence between model and market.

---

## 7. DISTRIBUTE

**Canonical module:** `app/export/institutional_workbook.py`,
`app/export/runtime_summary.py`, `app/export_metadata.py`, `app/excel_export.py`

**What it proves:**
- XLSX institutional export packages the Last Run outputs, run lineage,
  validation status, and methodology notes into a controlled workbook.
- Export lineage is tracked; exports reference the committed run's composite hash.
- `P1.2` XLSX reconciliation tests (`tests/test_p1_2_xlsx_export_reconciliation.py`)
  verify that exported numbers match the committed Last Run.

**What it does NOT prove:**
- An exported workbook is not a live pricing document.
- Export does not re-run the engine; it reads persisted outputs.

---

## 8. METER

**Canonical module:** `app/usage/ledger.py`, `app/usage/query.py`,
`app/usage/contracts.py`, `app/usage/hooks.py`

**What it proves:**
- Usage events are recorded in an append-only SQLite ledger after the B2.2
  access decision is made. Recording never affects the access decision.
- Subject identity is always derived from the signed session (`session.user_id`);
  callers cannot supply it.
- Idempotency is scoped: `UNIQUE(subject_id, feature_key, idempotency_key)`.
- Query failures return `UsageQueryResult(state=UNAVAILABLE)` — never an empty
  list indistinguishable from genuine zero usage.
- Wallet address is resolved internally from `app.protocol.wallet_auth`
  (fail-open); callers cannot supply it.

**What it does NOT prove:**
- Usage recording has no effect on financial math or verification truth.
- No billing engine, no fiat/token price, no entitlement decision in B2.3.
- Usage data is observability only.

---

## Radar Authority Lane (parallel)

**Modules:** `finco_radar/`, `app/radar_rwa/`, `app/radar_crypto/`,
`app/radar_economy/`, `app/radar_derivatives/`, `app/radar_stablecoins/`

**Key invariants:**
- R-LIVE (`finco_radar/authority/r_live_onchain.py`, `r_live_policy.py`):
  reads on-chain token reference data for AAPL and similar RWA tokens.
  Snapshots are read-only; history writes are structurally separated from reads.
- Cross-chain canonical identity (`finco_radar/authority/cross_chain.py`):
  established via source-attested evidence, not by name/symbol matching.
- Market observations do not flow into the financial engine.

## MCP Lane (parallel)

**Module:** institutional API v1.1 in stdio mode (committed as part of PR #129)

Read-only. Surfaces model references, run metadata, and Radar snapshots.
Does NOT execute model runs or modify any data.
