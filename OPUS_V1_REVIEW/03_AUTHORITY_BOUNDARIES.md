# FINCO V1 — Security and Authority Boundaries

## 1. Signed Session Identity

**Module:** `app/auth.py`

- All user sessions are signed JWTs (`itsdangerous`).
- `session.user_id` is the sole source of subject identity for B2.2 and B2.3.
- No public method in B2.2 (`app/verified/token_entitlement.py`) or B2.3
  (`app/usage/query.py`, `app/usage/ledger.py`) accepts a caller-supplied
  `subject_id` or `user_id` string.
- Demo sessions are structurally separate (`DEMO_COOKIE_NAME`); they do not
  share identity with authenticated sessions.

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
  that grants access on exception.
- Fail-closed: `app/auth.py` rate-limiting, `app/protocol/access_decision.py`.

**Module:** `app/usage/ledger.py` (B2.3)

- Wallet address resolution (`app.protocol.wallet_auth.get_verified_wallet`) is
  fail-open: if unavailable, the event is recorded without wallet identity.
  Wallet resolution failure does NOT prevent recording the usage event.
- The fail-open direction is documented and intentional: usage recording must
  not fail because wallet auth is unavailable.

## 5. Working Copy != Last Run

**Module:** `app/persistence/runs_repository.py`, `app/persistence/records.py`

- The Working Copy is the current editable project state.
- The Last Run is the most recently committed calculation snapshot.
- They can differ. A model edit after the last run produces a Working Copy that
  diverges from the Last Run.
- The Run Certificate (`app/verify/run_certificate.py`) is issued from the
  Last Run only — never from the Working Copy.

**Invariant:** `RUN_CERTIFICATE_FROM_PERSISTED_LAST_RUN_ONLY` — the certificate
never re-runs the engine.

## 6. Validation != Verify

**Module:** `app/model_validation/` (Validation), `app/verify/` (Verify)

- **Validation** checks model structure and numeric tolerances against the
  committed Last Run outputs.
- **Verification** issues a Run Certificate binding the immutable run record
  (composite hash, engine version, digests).
- A "Validated" project has passed structural checks. It has not been verified
  against a real-world asset.
- Neither Validation nor Verification asserts that the model inputs reflect
  economic reality.

## 7. Reference != Executable Price

**Module:** `finco_radar/`, `app/radar_rwa/`

- Radar provides reference market intelligence (prices, liquidity, identity evidence).
- Radar data does not flow into the financial engine.
- A reference price from Radar is not an executable quote; it is observational.
- `finco_radar/quotes/normalization.py` normalizes observable data; it does not
  price trades.

## 8. Token != Math / Truth

**Module:** `app/verified/token_entitlement.py` (B2.2), `app/protocol/token_balance.py`

- The FINCO token is used for access control (entitlement) to Verified dossiers.
- Token balance or entitlement has no effect on the financial engine, validation
  results, or verification outputs.
- Holding a token does not change what the model calculates.

**Invariant:** `$FINCO NEVER TOUCHES THE MATH. $FINCO NEVER DETERMINES WHETHER EVIDENCE IS TRUE.`

## 9. Signing != Truth

**Module:** `app/verify/run_certificate.py`

- A Run Certificate proves WHAT was computed (inputs, engine version, outputs)
  and WHEN (run timestamp).
- It does NOT prove that the assumptions were correct.
- It does NOT prove that the outputs match any real-world asset performance.
- In V1, signing is SHA-256 hash-based (composite hash); no asymmetric key
  signing is included in V1.

## 10. Frozen Namespaces

The following packages must show zero diff in any product PR:

```
financial_engine/**    — deterministic financial math
finco_core/**          — numeric primitives
app/verified/**        — verification truth
finco_radar/**         — radar authority
app/api/v1_1/**        — (for the API v1.1 stream PRs)
app/mcp/**             — MCP implementation
```

Any PR that touches these namespaces without a documented reason should be
treated as a potential regression and reviewed independently.
