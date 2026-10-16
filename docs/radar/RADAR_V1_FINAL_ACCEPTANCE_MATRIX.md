# Radar V1 — Final Staging Acceptance Matrix

Status: **PREPARED / NOT EXECUTED**. This file is a test plan, not an assertion that staging, collector, or real-market evidence has passed. The deployment build SHA must be independently supplied and correlated with the final approved Git HEAD.

## Preconditions

1. Independent GitHub exact-head source/merge-tree and frozen-namespace review is complete.
2. Full unsharded Public Safety process reports child rc=0 and mandatory evidence PASS.
3. Security/Compile, Governance Full History, Radar gates and applicable Browser roles all PASS for exact final head.
4. Operations supplies staging deployed SHA and independently confirms matching artifact/manifest.
5. Read-only operator audit runs on an existing consistent, checkpointed observation-store copy. An active WAL, missing DB or failed SQLite integrity check is a blocker, **not** an empty successful run.
6. Collector cycles and health are observed without any audit-triggered provider calls. Do not interpret the audit's TEMPORARY copy as production data.
7. Entitlement accounts and project/test identities are provisioned with no live-wallet secrets exposed to screenshots.
8. Workstream A R6 Signal Feed must be integrated and exact-head approved before its own rows can be marked tested.

## Evidence capture conventions

Each row requires: tested SHA, UTC timestamp, operator, account role, exact URL/route, screenshot identifier where UI applies, API response status/body redacted, original source evidence timestamps, collector health sample, and PASS/FAIL/BLOCKED/N/A with reason. Capture HTTP logs and screenshot evidence only on authorized staging.

| ID | Surface/journey | Required expected state | Evidence screenshot/record | Status |
|---|---|---|---|---|
| RDA-01 | Tokenized landing, 1440px | Canonical asset IDs and stated MARKET / REFERENCE provenance only; no synthetic live claims | RDA-01-DESKTOP | NOT RUN |
| RDA-02 | Tokenized landing, 390px | No horizontal page overflow; source timestamps remain legible | RDA-02-MOBILE | NOT RUN |
| RDA-03 | Primary Market view | Eligible current market price only if exact active representation and MARKET evidence | RDA-03-PRIMARY | NOT RUN |
| RDA-04 | Catalog | Registry identity, active/inactive/quarantine disagreements not silently collapsed | RDA-04-CATALOG | NOT RUN |
| RDA-05 | Audit / provenance | Original chain/contract and source identities; no field implies unproved oracle bindings | RDA-05-AUDIT | NOT RUN |
| RDA-06 | Missing observation store | Clear DATA_NOT_READY / unavailable; no database creation during GET or audit | RDA-06-MISSING | NOT RUN |
| RDA-07 | Partially populated store | Row-level partial/missing reason, never a fabricated zero | RDA-07-PARTIAL | NOT RUN |
| RDA-08 | Last canonical price | Real last persisted price labelled historical with original age, never relabelled current | RDA-08-LAST-PRICE | NOT RUN |
| RDA-09 | Current price | AVAILABLE only if canonical freshness requirements pass for MARKET and source-specific oracle where applicable | RDA-09-CURRENT | NOT RUN |
| RDA-10 | Stale price | Age, original clocks and STALE state remain; historical distribution not upgraded to current basis | RDA-10-STALE | NOT RUN |
| RDA-11 | Missing REFERENCE | Basis null/UNAVAILABLE with canonical missing-reference reason | RDA-11-REFERENCE | NOT RUN |
| RDA-12 | Clock mismatch | MARKET, oracle normalization and official REFERENCE clocks distinct; 300-second basis skew never bypassed | RDA-12-CLOCKS | NOT RUN |
| RDA-13 | Relative Value detail | Existing canonical basis, venue, instrument and exact source provenance; no alternative calculator | RDA-13-RELATIVE | NOT RUN |
| RDA-14 | Own-history distribution | >=8 usable original observations and >=3600s eligible span; percentile only when current evidence supports it | RDA-14-HISTORY | NOT RUN |
| RDA-15 | Insufficient history | INSUFFICIENT_HISTORY with unavailable percentile; missing points not filled | RDA-15-INSUFFICIENT | NOT RUN |
| RDA-16 | Dislocation persistence | Proven crossing/sign reversal only; missing continuation or unknown prehistory shows no fabricated start time | RDA-16-PERSISTENCE | NOT RUN |
| RDA-17 | Deepstate | Historical executed NVDA/USDG evidence, original USDG/NVDA unit; current executable / current cross-venue unavailable | RDA-17-DEEPSTATE | NOT RUN |
| RDA-18 | Crypto API envelopes | Stable route shape, explicit unsupported states, tenant isolation and no protected fields in unauthorized response | RDA-18-API-REDACTED | NOT RUN |
| RDA-19 | Entitlement: anonymous | Only public information; protected history and signal evidence never leaked | RDA-19-ANON | NOT RUN |
| RDA-20 | Entitlement: basic | Premium projections appropriately redacted, no premium data serialized for hidden sections | RDA-20-BASIC | NOT RUN |
| RDA-21 | Entitlement: history only | Own-history only where permitted; dislocation/other premium sections remain gated | RDA-21-HISTORY-ONLY | NOT RUN |
| RDA-22 | Entitlement: dislocation only | Dislocation granted without leaking unentitled history points | RDA-22-DISLOCATION-ONLY | NOT RUN |
| RDA-23 | Entitlement: full | Both approved premium projections visible; still no delivery/execution claims | RDA-23-FULL | NOT RUN |
| RDA-24 | Collector health | Real last attempt/success, LIVE/STALE/STOPPED with original observed and collected clocks | RDA-24-HEALTH | NOT RUN |
| RDA-25 | No acquisition on page load | Instrument GET calls/logs show zero new provider RPC/HTTP acquisition | RDA-25-NETWORK-TRACE | NOT RUN |
| RDA-26 | R-LIVE live table/detail | Current/last canonical price distinction, repolling and first paint preserve truthful clock/age | RDA-26-RLIVE | NOT RUN |
| RDA-27 | Workstream A R6 Signal Feed | Exact-head integrated deployment only: event lifecycle, explicit alert readiness != delivery, gaps and no trade recommendations | RDA-27-SIGNAL | BLOCKED: A NOT VERIFIED IN THIS WORKSTREAM |
| RDA-28 | No unauthorized write | Audit leaves original DB, indexes, directory and source SHA/metadata unchanged; no checkpoint reset | RDA-28-ZERO-WRITE | NOT RUN |
| RDA-29 | UI/API error states | Invalid IDs, corrupted JSON, missing evidence, expired entitlement and protected route access fail closed | RDA-29-ERROR | NOT RUN |
| RDA-30 | Repeated fixed-as-of read | Identical result/evidence hashes on unchanged snapshot, no artificial new observation | RDA-30-REPEAT | NOT RUN |

## Read-only operator audit

Execute on an authorized **offline checkpointed copy**, never an uncheckpointed live WAL:

    python -m tools.radar_tokenized_closeout_audit --db-path /approved/offline-copy/venues.db --as-of 2026-10-16T09:00:00+00:00 > radar-closeout.json

Expected semantics:

- Exit 0: audit executed and observation DB had persisted rows. **Not staging PASS**.
- Exit 2: DATA_NOT_READY, no existing source data or empty store.
- Exit 3: BLOCKED on unsafe, changed or corrupt store; cannot claim evidence readiness.
- The report's original source file must remain unchanged.
- Missing/malformed market prices never become zero.
- Evidence clock contract version and source-vs-transport counts are reported separately.
- A historical distribution can exist while the current market is stale. Never let one upgrade the other.

## Acceptance ownership

- **Security/Trust:** access redaction, integrity, exact-content and deployment correlation.
- **Radar evidence reviewer:** clock/freshness, source identity, basis, history and Deepstate authority.
- **Operations:** actual staging SHA, real collector liveness, DB audit snapshot provenance, screenshots and reproducibility.
- **Financial/market authority:** no new calculator/source authorizations; explicitly approve any future market authority separately.

Freeze requires **all mandatory gates PASS and no unresolved blocker**. This matrix is not itself approval, and no staging was run while preparing it.
