# FINCO V1 — Independent Clean-Room Review Prompt

You are performing a clean-room independent review of FINCO V1.
You have no prior context from the development history.

Use only the files in this `OPUS_V1_REVIEW/` package and the repository at
the SHA below. Do not assume anything about the system from any other source.

This package describes the implemented repository state. It is not a marketing
document. Do not treat this as an invitation to confirm its claims — your job
is to independently verify or challenge them.

---

## Entry Point

Repository: `Finco-Protocol/FincoProtocol`

**REVIEW PACKAGE PREPARED AGAINST PRODUCT BASE:**
`0082e5bd27ffe166c1d80a177fae49670ed848f2`

This is the post-PR#140 main. PR #140 merged at this SHA from accepted feature head
`dd5bd09f6c1af303aa1b0d695828d8394f989de0`. Previous main was `226fe8d4ee15bfe60e441550f386e8985ae0c2f9`.
PR #140 full-suite evidence: 4703 passed, 38 skipped, 0 failed; 6/6 workflows SUCCESS.

**DOCS PR HEAD:**
This review package was prepared in a docs PR. The docs PR head SHA is
recorded in `REVIEW_SNAPSHOT.json`. The product code at `0082e5bd` is
the authoritative product base.

**FINAL CLEAN-ROOM REVIEW TARGET:**
After the docs PR is reviewed and merged, verify the exact new live main SHA
and confirm it matches `REVIEW_SNAPSHOT.json` before beginning the review.
If in doubt, inspect the repository's HEAD at the time of your review.

Clone and review at the exact SHA confirmed above.

---

## What You Are Reviewing

FINCO V1 — an off-chain deterministic project-finance modelling and verification
platform with crypto/tokenized-asset intelligence, a signed run certificate,
a read-only institutional API, and a read-only MCP agent interface.

The product narrative is:

> **Model + Radar/R-LIVE + Verify + Signed Run + API/MCP + $FINCO**

Your job is to determine whether this narrative is internally coherent, whether
each component does what it claims, and whether any component contaminates
another in a way that breaks authority boundaries or makes a misleading claim.

---

## Review Dimensions

### A. Financial Model Correctness

This dimension IS in scope. Verify:

- **IRR / XIRR** — are equity return calculations correct? Which convention
  (ACT/365F vs ACT/ACT)? Is the compounding consistent with the period convention?
- **Project returns vs equity returns** — are they correctly separated?
- **DSCR** — numerator and denominator definition; period coverage vs annual;
  is there a sculpting / DSRA interaction?
- **Senior debt sizing** — amortisation schedule; balloon vs full amortisation;
  interest calculations (e.g. straight-line, annuity, bullet).
- **Shareholder loans (SHL)** — treatment of interest (PIK vs cash); interaction
  with equity returns.
- **Sponsor equity** — timing; how committed equity tranche interacts with SHL.
- **Corporate tax** — deferred tax, loss carryforward; timing of tax payment
  relative to profit period.
- **CAPEX and construction schedule** — timing of drawdowns; IDC / capitalised
  interest treatment.
- **OPEX and revenue timing** — beginning vs end of period; partial-period
  conventions on first/last years.
- **Cash waterfall** — order of priority; DSRA funding; distribution lock-up
  triggers.
- **Distributions** — how distributions reach equity holders; restrictions;
  cumulative tests.
- **Financial statements** — P&L, balance sheet, cash flow: do they reconcile?
  Opening/closing balance consistency?
- **DSCR minimum / cash sweep** — any interaction with the base debt schedule.
- **Period conventions** — are all metrics computed on consistent periods?
  Are partial periods handled consistently?
- **Vertical isolation** — do Solar, Wind, Data Center, EV Charging, and
  Storage share a common financial core? Are vertical-specific operating
  assumptions isolated from the shared engine?

For each: verify from code, not from documentation claims.

### B. Last Run / Working Copy / Export Authority

- Is the Working Copy / Last Run separation correctly enforced everywhere?
  Can any surface return Working Copy values labeled as Last Run outputs?
- Is `PRODUCTION_VERIFIED_ASSET_COUNT` accurate? Are any MODEL_ONLY records
  presented as VERIFIED?
- Does institutional XLSX export read persisted outputs and never re-run the
  financial engine?
- Can the Trust Pack UX surface return Working Copy values in any section?
- Does `app/services/run_certificate_service.py` fail closed for incomplete
  Last Run identity? Does it ever substitute current values?

### C. Model Trust Pack

- Does `app/ui/trust_pack.py:build_trust_pack()` correctly distinguish its
  7 sections (A: Last Run Identity, B: Core KPIs, C: MODEL VALIDATION [DEFERRED],
  D: FINCO VERIFY, E: Institutional Export, F: Methodology, G: Signed Run
  Certificate [DEFERRED])?
- Does it correctly present MODEL VALIDATION ≠ FINCO VERIFY?
- Does it correctly present Signed Run Certificate ≠ FINCO VERIFY?
- Are DEFERRED sections (C, G) correctly guarded — no actionable load URL
  without a committed Last Run?
- Does the CSS presentation correctly restrict green/verified status to
  VERIFIED only?
- Does the Trust Pack rendering ever issue a certificate or run the model
  at page render time?

### D. FINCO Verify

- Can any code path in `app/model_validation/` create or update a VERIFIED
  record in `app/verified/`?
- Can any code path convert a validation PASS into VERIFIED status?
- Does `app/verified/token_entitlement.py` have any fallback that grants
  access when the token check fails?
- Does B2.2 accept a caller-supplied `subject_id` or bypass session identity?
- What is the exact production `PRODUCTION_VERIFIED_ASSET_COUNT`?

### E. Signed Run Certificate

- Is the Ed25519 signing in `app/services/run_certificate_service.py`
  correctly implemented?
- Does it ever call the financial engine or accept Working Copy inputs?
- Can a caller obtain a certificate without a configured `FINCO_RUN_CERT_SIGNING_KEY`?
- Does issuing a Signed Run Certificate create or update any record in
  `app/verified/`?
- Is the private key ever logged, returned in responses, or exposed?

### F. R-LIVE V2 Identity / Pools / Freshness / Premium / History

**Post-PR#140 R-LIVE architecture — verify all of the following independently:**

**Universe (PR #140): 13 source-proven approved assets**
AAPL, NVDA, AMZN, GOOGL, TSLA, AVGO, NFLX, AMD, DELL, SNAP, INTC, MSFT, META.
Note: MSFT and META were REJECTED at PR #136 (insufficient Swap activity at that time) and
ADMITTED at PR #140 (source-proven at wider review). ORCL and PLTR remain excluded.
SCAN_COMPLETE = NO: the review environment's egress policy blocked api.robinhood.com and
rpc.mainnet.chain.robinhood.com (HTTP 403), preventing a registry-wide exhaustive scan.
This does not weaken the 13 admitted assets — their admission evidence was acquired and is
source-proven. It means the universe may grow when environment permits wider scanning.

**Identity and registry:**
- Does the R-LIVE authority correctly reject all unapproved identities?
  (`APPROVED_RLIVE_ASSETS` in `finco_radar/authority/r_live_policy.py`)
- Is there any ticker/symbol/fuzzy/LLM identity path? There must not be.
- Verify the approved canonical_id list (13 assets) against `docs/radar/r_live_v2_admission.md`
  and the deployed registry in `finco_radar/authority/r_live_policy.py`.
- Are ORCL and PLTR still correctly excluded?

**Freshness (multiple independent clocks — post-PR#140):**
- Is the 300-second TWAP freshness gate enforced? What happens if no Swap occurred in the window?
- Is USDG/USD conversion computed from the canonical Chainlink oracle? Is USDG ever assumed = USD 1?
- Are STALE and UNAVAILABLE structurally distinct from empty/zero?
- Does the codebase distinguish at least the following independent freshness signals:
  (a) market/pool activity age (time since last qualifying on-chain Swap),
  (b) oracle age (Chainlink USDG/USD feed staleness),
  (c) block age (age of the pinned observation block),
  (d) effective evidence timestamp (on-chain time of the observation, `effective_evidence_at`),
  (e) FINCO collection timestamp (`collected_at`, time the collector persisted the result)?
- Are `collected_at` and `effective_evidence_at` structurally separate fields? Verify that
  `collected_at` is never substituted for `effective_evidence_at` in any output.

**1h/24h ranges (PR #140):**
- Do 1h/24h range windows use `collected_at` (FINCO collection timestamp) as the selection clock,
  not `effective_evidence_at` or `observed_at`?
- Are ranges explicitly HISTORICAL (not live/streaming)?
- Do ranges require >=2 data points? What is returned for <2 points?
- Is there any price interpolation within ranges? There must not be.

**STALE last-available UX (PR #140):**
- When the most recent observation is STALE, does the UX show the last canonical available value
  with an explicit HISTORICAL label?
- Does the STALE badge remain STALE (never green) when showing a last-available value?
- Is the displayed value clearly labeled as HISTORICAL and explicitly not a current reading?

**Landing batch (PR #140):**
- Does the landing page use 2 total API requests (1 current batch + 1 ranges batch) rather than
  one per-asset pair (which would be 13×2 = 26 requests)?
- Verify in `app/radar_ui/r_live_router.py` and the corresponding landing template.

**Read/write boundary:**
- Do read paths (`app/radar_rwa/r_live_service.py`) perform zero history writes?
- Is the collector the sole approved history writer?
- Does any surface imply an R-LIVE observation is a tradeable or executable price?

**Public API routes (6 routes — verify all):**
```
GET /api/v1.1/radar/r-live/assets                   — list approved identities
GET /api/v1.1/radar/r-live/current                  — stream current results for all approved (NDJSON)
GET /api/v1.1/radar/r-live/history/ranges            — landing summary: all approved 1h/24h ranges
GET /api/v1.1/radar/r-live/{uid}                    — current reference (exact identity only)
GET /api/v1.1/radar/r-live/{uid}/history             — historical evidence (read-only)
GET /api/v1.1/radar/r-live/{uid}/history/ranges      — 1h/24h ranges for exact identity
```
- Are all 6 routes unauthenticated and read-only?
- Does any route write history? (`persist_history=False` must be enforced on all read routes.)
- Are all routes exact-canonical_id-only — no ticker/fuzzy lookup?

**Multi-asset collector (PR #139) — verify independently:**
- Does `python -m app.radar_rwa.r_live_collect` (no-arg) call `collect_all_approved()`
  over the full `APPROVED_BY_CANONICAL_ID` registry? (`main([])` in `r_live_collect.py`)
- Does `--asset-key` correctly restrict to one diagnostic run?
- Does `collect_all_approved` use a single shared ledger for all assets and close it
  exactly once, regardless of per-asset outcomes?
- Are STALE/UNAVAILABLE per-asset market states correctly treated as non-process-failures
  (exit 0 for mixed market states)?
- Does a per-asset acquisition exception leave that asset as UNAVAILABLE while continuing
  the batch over remaining assets?
- Do pre-batch process failures (RPC_NOT_CONFIGURED, RPC_UNAVAILABLE, HISTORY_STORE_UNAVAILABLE
  from ledger init, APPROVED_REGISTRY_UNAVAILABLE) correctly exit 1 with no per-asset work?
- Does a per-asset acquisition exception leave that asset as UNAVAILABLE, continue the batch
  for all remaining assets, and produce `R_LIVE_ACQUISITION_RUNTIME_UNAVAILABLE` after the
  full batch (exit 1)?
- Does a post/in-batch persistence failure (HISTORY_PERSISTENCE_UNAVAILABLE per-asset or ledger
  close exception) produce `HISTORY_STORE_UNAVAILABLE` after batch work (exit 1)?
- Does `_safe_reason` ensure no raw exception text or credential appears in JSON output?
- Is `ROBINHOOD_RPC_URL` the sole source for both the web current-read path and the
  collector? Is it never committed to Git or emitted in collector output?
- Is `RADAR_BNB_INTELLIGENCE_DB_PATH` the shared durable B1.3 history ledger used by
  both the web history read surface and the collector? Are staging and production
  ledgers documented as required to be separate?
- Does the RPC preflight (`_check_rpc_health` / `eth_chainId` → 4663) gate all
  per-asset work and close the transport regardless of outcome?

### G. Radar UX / R-LIVE / Stocks / Crypto / Economy

- Does `/radar` redirect to `/radar/r-live`? Is R-LIVE the default Radar domain?
- Does `/radar/stocks` still serve the Stocks surface correctly?
- Do the 4 Radar navigation domains (R-LIVE, Stocks, Crypto, Economy) all
  correctly route and render?
- Does `app/radar_ui/r_live_router.py` fabricate any numeric values server-side?
- Is the per-asset detail shell loaded from the canonical API only (client-side)?
- Is any Radar reference observation presented without an adequate disclosure
  that it is not executable?

### H. API

- Are all 6 R-LIVE public API routes (assets, current, history/ranges [all],
  /{uid}, /{uid}/history, /{uid}/history/ranges) correctly unauthenticated and read-only?
- Does any R-LIVE API route write history? (`persist_history=False` must be
  enforced on all read routes.)
- Does the `/radar/r-live/current` streaming route (NDJSON) correctly fan out only to
  approved exact identities and never write to history?
- Does the `/radar/r-live/history/ranges` all-assets landing route correctly read
  from the shared ledger without writing?
- Does the institutional API v1.1 expose any project data through the R-LIVE
  routes?
- Are all API v1 and v1.1 endpoints correctly access-controlled?
- Can any API endpoint return another user's usage data, Verified dossier,
  or run certificate?

### I. MCP

- Are all 9 MCP tools (`finco_supported_today`, `finco_projects`,
  `finco_last_run`, `finco_run_identity`, `finco_kpis`, `finco_validation`,
  `finco_verify`, `finco_r_live`, `finco_export_metadata`) truly read-only?
- Does any MCP tool perform state mutation, trigger model runs, or expose
  internal exceptions?
- Is MCP session identity correctly derived from `FINCO_SESSION_TOKEN` and not
  from caller-supplied arguments?
- Is the server-session deployment boundary correctly disclosed?

### J. Authentication / Multi-tenancy / Security

- Are sessions correctly implemented as signed cookies via
  `itsdangerous.URLSafeTimedSerializer`? No JWT claimed?
- Is `session.user_id` the sole source of subject identity in B2.2 and B2.3?
- Can a caller supply `subject_id`, `wallet_address`, or bypass session
  identity in B2.2 or B2.3?
- Is B2.3 idempotency correctly scoped by `(subject_id, feature_key, idempotency_key)`?
  Does concurrent duplicate delivery fail gracefully post-PR #135?
- Are demo sessions structurally separate from authenticated sessions?
- Is there adequate multi-tenant data isolation for a controlled institutional pilot?

### K. Deployment / Operational Readiness

- What is the gap between "IMPLEMENTED" and "OPERATIONALLY CONFIGURED" for
  each claimed LIVE capability?
- Specifically: R-LIVE web current-read requires `ROBINHOOD_RPC_URL`; R-LIVE
  collector requires both `ROBINHOOD_RPC_URL` + `RADAR_BNB_INTELLIGENCE_DB_PATH`;
  Signed Run Certificate requires `FINCO_RUN_CERT_SIGNING_KEY`; MCP requires
  `FINCO_SESSION_TOKEN`. Are all deployment requirements disclosed?
- Is `RADAR_BNB_INTELLIGENCE_DB_PATH` correctly documented as shared between web
  and collector, with staging/production separation required?
- Does the staging config contract (`deploy/r_live_collector_v1/staging/`) correctly
  isolate staging from production paths, DB, and environment files?
- Is there any claimed LIVE capability that is not reliably deployable given
  the documented limitations?
- Persistent storage: are DB paths, SQLite file locations, and migration
  requirements clearly defined?

### L. Product Capability Truth

- Run `pytest tests/test_p0_4_capability_contract.py tests/test_product_capability_consistency.py -v`
  and verify all pass.
- Is every claimed LIVE capability in `02_CAPABILITY_MATRIX.md` accurately
  described?
- Is Storage correctly described as PREVIEW only?
- Is BNB Tokenized Assets correctly kept as Radar-only (not a Model vertical)?

### M. Full Crypto / RWA Product Assessment

This is a required standalone assessment. Evaluate:

**M.1 Product coherence**

Given the combined product: Model + Radar/R-LIVE + Verify + Signed Run +
API/MCP + $FINCO — does this form:

a. A coherent crypto-native RWA product?
b. A hybrid institutional/crypto product?
c. A conventional SaaS with a token attached?

Explain your reasoning with specific evidence from the codebase.

**M.2 Token necessity analysis**

Evaluate each component:

1. What currently genuinely requires $FINCO holding/entitlement to function?
2. What requires only standard auth/payment that could be any currency/token?
3. What disappears entirely if the token is removed?
4. Is the token necessary, optional, or primarily narrative?
5. What minimum real crypto-native functionality would make the token necessity
   defensible? Propose it concretely.

**M.3 Strongest next crypto-native feature**

Propose ONE strongest next feature that:
- reuses the current architecture (Model + R-LIVE + Verify + Signed Run);
- gives visible user value;
- strengthens the RWA thesis;
- avoids a financial-engine rewrite;
- does not contaminate Verify, math, or evidence authority;
- is bounded enough to implement in a single focused PR stream.

Do not tell us what conclusion to reach. Do not propose features already
implemented. Identify specifically which current capability it builds on.

---

## Specific Historical Problem Areas — Verify These Independently

1. **Working Copy vs Last Run** — confirm no API endpoint or export surface
   returns Working Copy values labeled as Last Run outputs.

2. **Export-time rerun** — confirm institutional XLSX export reads persisted
   outputs and never re-runs the financial engine.

3. **Last Run identity completeness** — confirm `app/services/run_certificate_service.py`
   fails closed for incomplete identity and refuses to substitute current values.

4. **Validation vs Verify** — confirm no code path in `app/model_validation/`
   sets a VERIFIED status or updates `app/verified/`.

5. **Verify fail-closed behavior** — confirm `app/verified/token_entitlement.py`
   has no access-granting fallback on exception.

6. **Market identity authority** — confirm `finco_radar/authority/cross_chain.py`
   requires source-attested evidence and cannot be satisfied by name/symbol alone.

7. **Independent reference provenance** — confirm R-LIVE reference prices never
   flow into `financial_engine/` as inputs.

8. **Reference vs executable price** — confirm no R-LIVE observation is
   presented as a tradeable or executable price in any API response.

9. **R-LIVE writer/read boundary** — confirm read paths in
   `app/radar_rwa/r_live_service.py` perform zero history writes.

10. **Signed Run vs Verify separation** — confirm issuing a Signed Run
    Certificate does not create or update any record in `app/verified/`.

11. **Token/access vs truth/math separation** — confirm B2.2 entitlement
    and B2.3 usage recording have no effect on any financial calculation
    or verification outcome.

12. **Missing != zero** — confirm `app/usage/query.py` and `finco_radar/gap/`
    structurally distinguish storage failures from empty/zero results.

13. **Supported Today consistency** — run
    `pytest tests/test_p0_4_capability_contract.py tests/test_product_capability_consistency.py -v`
    and verify all pass.

14. **Trust Pack render guard** — confirm `app/ui/trust_pack.py:build_trust_pack()`
    never calls `issue_run_certificate()`. Certificate issuance must only occur
    via an explicit user-triggered endpoint.

15. **R-LIVE V2 freshness gate** — confirm that no numeric R-LIVE output is
    returned when the last Swap is older than 300 seconds (STALE state). Verify
    that STALE ≠ UNAVAILABLE ≠ empty.

16. **R-LIVE V2 no history write** — confirm `GET /api/v1.1/radar/r-live/{uid}/history`
    passes `persist_history=False` and makes no write to the history store.

17. **R-LIVE V2 identity enforcement** — confirm that an unapproved `uid` on any
    R-LIVE public API route returns a typed error, never a fabricated response.

18. **B2.3 concurrent fix** — confirm that PR #135 correctly handles concurrent
    duplicate delivery: no lock error to caller, exactly one event persisted.

19. **R-LIVE current observation vs history separation** — confirm that the web
    current-read path (`GET /api/v1.1/radar/r-live/{uid}`) acquires a fresh
    on-chain observation at request time and does NOT depend on the history ledger.
    UNAVAILABLE from the current-read path means the on-chain acquisition failed
    or ROBINHOOD_RPC_URL is not configured — not that no history exists.

20. **Multi-asset collector batch semantics** — confirm that `collect_all_approved`
    in `app/radar_rwa/r_live_collect.py`:
    (a) Pre-batch: RPC_NOT_CONFIGURED, RPC_UNAVAILABLE, HISTORY_STORE_UNAVAILABLE
        (ledger init), APPROVED_REGISTRY_UNAVAILABLE each abort before any per-asset
        work and exit 1.
    (b) Per-asset: acquisition exceptions are caught per-asset; that asset becomes
        UNAVAILABLE; remaining assets are always attempted; after the full batch
        `R_LIVE_ACQUISITION_RUNTIME_UNAVAILABLE` is set and exit 1 is returned.
    (c) Post/in-batch: HISTORY_PERSISTENCE_UNAVAILABLE per-asset or ledger close
        exception produces HISTORY_STORE_UNAVAILABLE after batch work, exit 1.
    (d) STALE/UNAVAILABLE/AVAILABLE market states (no exception) are not process
        failures; exit 0 for mixed market states with no process-level error.

21. **Collector credential safety** — confirm that `_safe_reason` in
    `app/radar_rwa/r_live_collect.py` filters all typed output to
    `[A-Z][A-Z0-9_]{0,95}`, ensuring no raw exception text, RPC URL, or other
    credential appears in JSON stdout captured by journald.

22. **collected_at vs effective_evidence_at separation (PR #140)** — confirm that
    `collected_at` (FINCO collection timestamp) and `effective_evidence_at` (on-chain
    observation time) are structurally distinct fields in the history schema.
    `collected_at` must never be substituted for `effective_evidence_at` or vice versa.
    The 1h/24h range selection clock must use `collected_at`, not `effective_evidence_at`.

23. **1h/24h range semantics (PR #140)** — confirm that:
    (a) ranges are selected by `collected_at` (collection timestamp), not by on-chain time;
    (b) ranges require >=2 collected points; fewer returns an appropriate empty/unavailable
        response, never interpolated values;
    (c) no price interpolation exists anywhere in the ranges computation;
    (d) ranges always carry `history_kind: "HISTORICAL"` in the API response.

24. **STALE last-available UX (PR #140)** — confirm that when the current reading is STALE,
    any last-known canonical available value shown:
    (a) carries an explicit HISTORICAL label in the UI and API response;
    (b) never appears as a current reading;
    (c) the STALE freshness badge is never promoted to AVAILABLE or green when a
        historical fallback value is displayed.

25. **Landing batch optimization (PR #140)** — confirm that the R-LIVE landing page
    (`app/radar_ui/r_live_router.py` or the landing template) issues at most 2 API
    requests: one to `/radar/r-live/current` (or current batch) and one to
    `/radar/r-live/history/ranges` (all-assets ranges summary). It must NOT issue
    one request per asset (which would be 26+ requests for 13 assets).

26. **SCAN_COMPLETE = NO (PR #140)** — confirm that:
    (a) the repository's admission documentation correctly notes that the wide
        registry scan was environment-blocked (egress to api.robinhood.com and
        rpc.mainnet.chain.robinhood.com blocked at HTTP 403);
    (b) no authority standards were weakened to compensate for the blocked scan;
    (c) the 13 admitted assets have individually source-proven admission evidence;
    (d) assets not yet scanned (due to environment block) are correctly excluded,
        not assumed admitted.

27. **13-asset universe completeness (PR #140)** — confirm that all 13 canonical
    identities in `APPROVED_RLIVE_ASSETS` (AAPL, NVDA, AMZN, GOOGL, TSLA, AVGO,
    NFLX, AMD, DELL, SNAP, INTC, MSFT, META) have individually distinct `canonical_id`
    and `economic_asset_uid` values. No two assets may share a pool address.
    ORCL and PLTR must remain excluded.

28. **MSFT and META re-admission (PR #140)** — these were REJECTED in PR #136 (MSFT: 1 Swap;
    META: 0 Swaps at review time) and ADMITTED in PR #140 following a new source-proven
    review. Confirm that their PR #140 admission evidence satisfies the same admission
    standards as all other approved assets (pair authority, fee, decimals, 300s observe,
    liquidity, cardinality, bounded Swap, USDG/USD oracle check).

29. **Freshness clock independence (PR #140)** — confirm that the five freshness signals
    (market activity age, oracle age, block age, effective_evidence_at, collected_at)
    cannot be conflated in any API response or UX state calculation. Specifically:
    (a) STALE is triggered by market activity age (no Swap in 300s window), not by
        collection age or oracle age alone;
    (b) a stale Chainlink oracle produces a separate error, not a STALE market state;
    (c) `collected_at` is always >= `effective_evidence_at` (collection happens after
        observation); verify no code path inverts this.

30. **No numerical score** — this review must not produce an overall numerical score,
    grade, or pass/fail verdict for FINCO V1 as a whole. Each finding must be graded
    individually by severity. A Final Launch Blocker Table (Section C) is required
    as the structured summary — not a single verdict.

---

## What NOT to Review

- `domain/**` — not a standalone authority surface, but inspect any domain model
  that materially participates in a reviewed calculation or authority path.
- Jev / Reflex (issue #119) — experimental shadow, explicitly not V1 scope.

---

## Format for Findings

```
FINDING [n]: <file:line or surface> — <one sentence>
SEVERITY: BLOCKER | HIGH | MEDIUM | LOW | INFORMATIONAL
EVIDENCE: <specific code path, test, or API call that demonstrates the issue>
WHY IT MATTERS: <why this is a problem for a public/institutional launch>
RECOMMENDED CORRECTION: <specific fix>
BLOCKS PUBLIC LAUNCH: YES / NO / CONDITIONAL
```

Severity definitions:
- **BLOCKER**: must be fixed before any controlled institutional exposure
- **HIGH**: serious issue; fix before public launch
- **MEDIUM**: should be fixed; workaround may exist
- **LOW**: improvement; not a launch blocker
- **INFORMATIONAL**: observation only; no required action

If no findings in a dimension: `NO FINDINGS — invariants hold as described.`

---

## Instructions

- Do NOT assign an overall score.
- Do NOT fabricate findings. Verify from code, not from intent.
- Do NOT tell us FINCO is enterprise-ready or expected to pass.
- Do NOT tell us specific gaps are "already solved" unless you have verified them.
- Verify each historical problem area independently.
- Cross-check the Known Limitations in `05_KNOWN_LIMITATIONS.md` — if any is
  understated or overstated, say so as a finding.
- If a LIVE capability in `02_CAPABILITY_MATRIX.md` is not reliably deployable
  given documented limitations, flag it.
- Report your findings ordered by severity (BLOCKER first).
- Complete ALL review dimensions. Do not skip financial model correctness.
- Complete the Crypto / RWA Product Assessment (Dimension M) in full.
- Complete the three required final sections A, B, and C below in full.
  Do not abbreviate or skip any question in any section.

---

## A. Enterprise Product Assessment

Answer each question explicitly. Do not skip.

1. **Strongest enterprise capability** — which single V1 capability is most
   credible to an institutional buyer today, and why?
2. **Weakest enterprise capability** — which single V1 capability would most
   likely cause an institutional buyer to pause or reject deployment, and why?
3. **Financial model risk** — is the financial engine (IRR/XIRR/DSCR/debt/SHL/
   CAPEX/OPEX/distributions) ready for institutional reliance? State the
   highest-risk formula or output path you found.
4. **Security / tenancy risk** — does the session and authentication model
   adequately isolate tenant data? State the highest-risk isolation gap you found.
5. **Operational risk** — which V1 operational dependency (key management,
   RPC config, ledger path, environment variable) carries the highest deployment
   risk? What happens if it is misconfigured in production?
6. **Support level** — for each of: (a) local/self-hosted, (b) controlled pilot,
   (c) multi-tenant SaaS — state whether the current codebase supports it and
   what the primary gap is.
7. **Enterprise launch blockers** — list up to three specific blockers (not
   covered elsewhere) that would prevent a controlled institutional launch.

---

## B. Crypto / RWA Product Assessment

Answer each question explicitly. Do not skip.

1. **Strongest crypto-native component** — which V1 crypto or RWA component
   (R-LIVE, B2.1 Verify, B2.2 Token Entitlement, B2.3 Metering, cross-chain
   identity) is most technically sound, and why?
2. **Weakest crypto-native component** — which component has the most significant
   gap relative to its stated purpose, and why?
3. **$FINCO token justification** — does the current codebase support a credible
   on-chain utility argument for $FINCO? What is currently missing?
4. **Missing token utility** — which token utility function is most notably absent
   from the V1 codebase that would be expected for a credible protocol launch?
5. **Missing RWA capability** — what RWA capability gap (not already listed in
   Known Limitations) would most weaken the protocol's RWA thesis?
6. **R-LIVE thesis strength** — does R-LIVE V2 strengthen or weaken the on-chain
   RWA intelligence thesis? State your specific reasoning from the code.
7. **Next feature** — if you could add one feature to V1 to most strengthen the
   crypto/RWA thesis, what would it be?
8. **Thesis verdict** — is the FINCO V1 codebase backed by a credible on-chain
   RWA narrative, or is the crypto layer primarily a narrative wrapper? State
   your specific evidence either way.

---

## C. Final Launch Blocker Table

Produce a single table. One row per area. Do not omit any area.

| AREA | CURRENT STATE | BLOCKER? | REQUIRED ACTION |
|------|--------------|----------|-----------------|
| Financial model (IRR/XIRR/DSCR/debt/SHL/CAPEX/OPEX/distributions) | | | |
| Last Run / XLSX export | | | |
| Trust Pack UX V1 | | | |
| FINCO VERIFY (B2.1) | | | |
| Signed Run Certificate V1 | | | |
| R-LIVE V2 (code surface) | | | |
| R-LIVE operational (collector + RPC + ledger config) | | | |
| Radar / BNB market intelligence | | | |
| API v1 / v1.1 | | | |
| MCP V1 | | | |
| Auth / tenant isolation | | | |
| Token entitlement (B2.2) | | | |
| Usage / metering (B2.3) | | | |
| Deployment / operations (key management, env config) | | | |
| Docs / product truth | | | |
| Crypto / token thesis | | | |

BLOCKER values: **YES** (must fix before any institutional exposure) /
**CONDITIONAL** (blocker under stated condition) / **NO** (not a blocker).
