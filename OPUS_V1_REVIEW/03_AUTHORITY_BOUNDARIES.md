# FINCO V1 — Security and Authority Boundaries

## 1. Signed Session Identity

**Module:** `app/auth.py`

- All user sessions use **signed cookies** via `itsdangerous.URLSafeTimedSerializer`.
  This is NOT JWT. The implementation is stateless signed cookies with a
  server-configured `FINCO_SECRET_KEY`.
- `session.user_id` is the sole source of subject identity for B2.2 and B2.3.
- No public method in B2.2 (`app/verified/token_entitlement.py`) or B2.3
  (`app/usage/query.py`, `app/usage/ledger.py`) accepts a caller-supplied
  `subject_id` or `user_id` string.
- Demo sessions are structurally separate (`DEMO_COOKIE_NAME`); they do not
  share identity with authenticated sessions.

**MCP V1:** Uses a server-configured `FINCO_SESSION_TOKEN` decoded through the
same signed session authority (`app.auth`). No caller-supplied identity is accepted.
Current deployment model uses server-configured signed session identity — it is
not reviewed as a shared arbitrary multi-user hosted transport. This is a
deployment/isolation boundary, not a security defect in the codebase.

**Invariant:** `subject_id = session.user_id` — this derivation cannot be
overridden by any caller.

## 2. Exact Market Identity

**Module:** `app/verified/authority.py`, `finco_radar/authority/cross_chain.py`

- A `ModelMarketRunBinding` requires source-attested evidence with an explicit
  `evidence_id`, `source`, and timezone-aware `observed_at` timestamp.
- Name matching, symbol matching, and CoinGecko data alone do not establish identity.
- The binding joins one immutable Last Run (by `composite_hash`) to one market
  asset (by canonical cross-chain identity).

**Invariant:** No production binding is created without explicit, source-attested
on-chain evidence.

## 3. Missing != Zero

**Module:** `app/usage/query.py` (`UsageQueryResult`)

- A storage failure returns `UsageQueryResult(state=UNAVAILABLE, reason=USAGE_QUERY_UNAVAILABLE)`.
- An empty result is `UsageQueryResult(state=AVAILABLE, summaries=())`.
- These are structurally distinct. A failure never returns an empty list.

**Module:** `finco_radar/` (R-LIVE, gap engine)

- Missing on-chain observations are surfaced as gaps, not as zero values.
- `finco_radar/gap/` models the observation gap explicitly.

**Invariant:** Absence of data is never silently treated as zero.

## 4. No Hidden Fallback

**Module:** `app/verified/token_entitlement.py` (B2.2)

- If FINCO token verification fails, access is denied. There is no hidden fallback
  that grants access on exception. Fail-closed.

**Module:** `app/usage/ledger.py` (B2.3)

- Wallet address resolution (`app.protocol.wallet_auth.get_verified_wallet`) is
  fail-open: if unavailable, the event is recorded without wallet identity.
  This is intentional — usage recording must not fail because wallet auth is
  temporarily unavailable.

**Module:** `app/services/run_certificate_service.py` (Signed Run Certificate)

- Incomplete Last Run identity fails closed with `LAST_RUN_IDENTITY_INCOMPLETE`.
- Legacy runs without persisted workbook_version fail closed — they must be rerun
  before a certificate can be issued. The current workbook version is never
  substituted at issuance.
- Absent `FINCO_RUN_CERT_SIGNING_KEY`: `SigningKeyUnavailable` is raised; no
  fallback production key exists.

## 5. Working Copy != Last Run

**Module:** `app/persistence/runs_repository.py`, `app/persistence/records.py`

- The Working Copy is the current editable project state.
- The Last Run is the most recently committed calculation snapshot.
- They can differ. A model edit after the last run produces a Working Copy that
  diverges from the Last Run.
- The Signed Run Certificate (`app/services/run_certificate_service.py`) is issued
  from the Last Run only — never from the Working Copy.

**Invariant:** Certificate issued from persisted Last Run only — never re-runs
the engine, never accepts Working Copy state.

## 6. Reference Regression Check != FINCO VERIFY

**Module:** `app/model_validation/` (Regression Check), `app/verified/` (Verify)

- **Reference Regression Check (H-4A)** re-runs canonical reference-model
  KPIs against pinned expected values (P1.3 vertical reconciliation). It
  runs against the canonical reference, NOT the user's committed Last Run;
  it is regression protection for the reference library and does NOT
  independently validate a user's model or establish accounting/debt/cash
  integrity of the Last Run. (Historical note: H-2 — the DSCR sculpting
  false-CONVERGED finding — was CLOSED by PR #144; a regression-check PASS
  was never evidence of model soundness and still is not.)
- **Verification** establishes a source-attested market binding. Requires
  explicit on-chain evidence with confirmed `evidence_id`.
- A "Validated" project has passed structural checks. It has not been verified
  against a real-world asset.
- Neither Validation nor Verification asserts that the model inputs reflect
  economic reality.
- The Model Trust Pack UX V1 presents both sections separately, with explicit
  labeling that they are distinct authorities.

**Invariant:** `MODEL_VALIDATION ≠ FINCO_VERIFY`

## 7. Reference != Executable Price

**Module:** `finco_radar/`, `app/radar_rwa/`

- Radar provides reference market intelligence (prices, liquidity, identity evidence).
- Radar data does not flow into the financial engine.
- A reference price from R-LIVE or Radar is not an executable quote; it is observational.
- R-LIVE 300-second TWAP with USDG/USD Chainlink adjustment is a reference, not a trade price.

## 8. Token != Math / Truth

**Module:** `app/verified/token_entitlement.py` (B2.2), `app/protocol/token_balance.py`

- The FINCO token is used for access control (entitlement) to Verified dossiers.
- Token balance or entitlement has no effect on the financial engine, validation
  results, or verification outputs.
- Holding a token does not change what the model calculates.

**Invariant:** `$FINCO NEVER TOUCHES THE MATH. $FINCO NEVER DETERMINES WHETHER EVIDENCE IS TRUE.`

## 9. Signing != Verify, Signing != Truth

**Module:** `app/services/run_certificate_service.py`

- A Signed Run Certificate proves provenance and integrity: WHAT was computed
  (composite hash, engine version, workbook version, KPIs) and WHEN (issued_at).
- **SIGNED RUN ≠ FINCO VERIFY** — completely separate systems.
  The certificate carries no synthetic FINCO Verify observation.
- **SIGNED RUN ≠ economic truth** — does not prove that model assumptions were correct.
- **SIGNED RUN ≠ model correctness** — does not validate model structure.
- **SIGNED RUN ≠ executable market price.**
- Ed25519 asymmetric signing (PR #132) provides cryptographic integrity and
  provenance IF AND ONLY IF the verifier independently trusted/pinned the public key.
  A self-supplied key or key identifier alone does not establish the issuer's identity.

## 10. Frozen Namespaces

The following packages must show zero diff in any product PR:

```
financial_engine/**    — deterministic financial math
finco_core/**          — numeric primitives
app/verified/**        — verification truth
finco_radar/**         — radar authority
app/model_validation/**— validation authority
app/api/v1_1/**        — (for API v1.1 stream PRs)
app/mcp/**             — MCP implementation
```

Any PR that touches these namespaces without a documented reason should be
treated as a potential regression and reviewed independently.
