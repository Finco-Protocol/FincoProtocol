# FINCO V1 — PR / SHA Ledger

All entries verified from `git log origin/main` at final live main SHA
`0082e5bd27ffe166c1d80a177fae49670ed848f2`.

Merge SHAs are the SHA on `main` after merge. Entries are newest-first within
each stream.

---

## R-LIVE V2 Freshness / History / 13-Asset Expansion (PR #140)

| PR | Capability | Accepted Feature HEAD | Merge SHA | State |
|---|---|---|---|---|
| #140 | R-LIVE V2: freshness/history semantics, 13-asset universe, source-component clocks, collected_at/evidence_at separation, 1h/24h ranges, STALE last-available UX, landing batch, candidate review | `dd5bd09f6c1af303aa1b0d695828d8394f989de0` | `0082e5bd27ffe166c1d80a177fae49670ed848f2` | MERGED |

Evidence: 4703 passed, 38 skipped, 0 failed (full Linux CI at PR #140 exact head); 6/6 workflows SUCCESS.

Key capabilities shipped:
- Expanded R-LIVE universe: 13 source-proven approved assets (AAPL, NVDA, AMZN, GOOGL, TSLA,
  AVGO, NFLX, AMD, DELL, SNAP, INTC, MSFT, META)
- SCAN_COMPLETE = NO (review environment egress policy blocked api.robinhood.com and
  rpc.mainnet.chain.robinhood.com; no authority standards weakened)
- Freshness distinction: market/pool activity age, oracle age, block age, effective
  evidence timestamp, FINCO collection timestamp (collected_at) — all structurally separate
- collected_at (FINCO collection timestamp) ≠ effective_evidence_at (on-chain observation time)
- 1h/24h range semantics: historical, collection-timestamp-selected, >=2 points, no interpolation
- STALE last-available UX: last canonical value shown with explicit HISTORICAL badge; badge stays STALE
- Landing batch: 1 current request + 1 range request (not 16)
- 6 public R-LIVE API routes (up from 3)
- New test files: test_r_live_onchain.py (22), test_r_live_v2_multi_asset.py (11),
  test_r_live_freshness_ranges.py (8), test_r_live_landing_batch.py (3),
  test_r_live_candidate_review.py (3)

Changed files: finco_radar/authority/r_live_policy.py, app/api/v1_1/r_live_public_router.py,
app/radar_rwa/r_live_service.py, docs/, tests/ (new R-LIVE test files), README.md.
Frozen namespaces: ZERO DIFF on financial_engine, finco_core, app, static, main_web.py,
.github/workflows (runtime code).

---

## R-LIVE V2 Multi-Asset Collector (PR #139)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #139 | R-LIVE V2: multi-asset collector and staging config contract | `226fe8d4ee15bfe60e441550f386e8985ae0c2f9` | MERGED |

No-arg invocation: `python -m app.radar_rwa.r_live_collect` iterates every key in
`APPROVED_BY_CANONICAL_ID` serially via `collect_all_approved()`. `--asset-key`
restricts a diagnostic run to one exact approved key.

Key behavioral guarantees (from `tests/test_r_live_collector_batch.py`):
- Serial iteration; one shared ledger; ledger always closed
- STALE/UNAVAILABLE per-asset market states are NOT process failures; exit 0 on mixed results
- Per-asset exception: asset recorded as UNAVAILABLE; remaining assets still attempted; exit 1
- Process failures (exit 1): `RPC_NOT_CONFIGURED`, `RPC_UNAVAILABLE`, `HISTORY_STORE_UNAVAILABLE`,
  `APPROVED_REGISTRY_UNAVAILABLE`, `COLLECTOR_RESULT_INVALID`, `R_LIVE_ACQUISITION_RUNTIME_UNAVAILABLE`
- RPC chain-id preflight (`eth_chainId` must return `4663`) gates all per-asset work
- Credentials never emitted in JSON output (`_safe_reason` sanitizes to typed uppercase identifiers)

Operational variables:
- `ROBINHOOD_RPC_URL` — required for both web current-read and the collector; never committed to Git
- `RADAR_BNB_INTELLIGENCE_DB_PATH` — shared durable B1.3 history ledger; web and collector must use
  the identical path; staging and production ledgers must be different files

Changed files (14): `app/radar_rwa/r_live_collect.py`, `.env.example`, `deploy/env.example`,
`deploy/r_live_collector_v1/README.md`, systemd unit files, staging env + collector units,
`tests/test_r_live_collector_batch.py`, `tests/test_r_live_collector_ops.py`.
Frozen namespaces: ZERO DIFF.

---

## R-LIVE V2 Product Shell (PR #137)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #137 | R-LIVE V2 product shell — registry-driven 8-asset surface, canonical history parity, public API wiring, UX shell | `9adf751cf3cb9fd087f99b433843cf8bdd9a7807` | MERGED |

Evidence: 27 R-LIVE shell tests, 25 public-routes tests, 20 history-contract tests (verified via `pytest --collect-only -q` at SHA `226fe8d4`); 4/4 CI SUCCESS.
Changed files (28): `app/api/v1_1/r_live_public_router.py`, `app/radar_ui/r_live_router.py`,
`app/radar_ui/router.py`, templates, tests.
Frozen namespaces: ZERO DIFF.

---

## R-LIVE V2 Multi-Asset Authority (PR #136)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #136 | R-LIVE V2 multi-asset authority — reviewed admission (AAPL, NVDA, AMZN, GOOGL, TSLA, AVGO, NFLX, AMD); freshness gate | `29afcf4f34b0407b716a55ba8b18edb572372d09` | MERGED |

Approved assets at PR #136 (8): AAPL, NVDA, AMZN, GOOGL, TSLA, AVGO, NFLX, AMD.
Rejected at PR #136 (4): MSFT (1 Swap at review time), META (0 Swaps at review time),
ORCL (no USDG pool), PLTR (1 Swap at review time).
Note: MSFT and META were subsequently re-reviewed and ADMITTED in PR #140. ORCL and PLTR remain excluded.
300-second freshness gate enforced. STALE/UNAVAILABLE suppress numeric output.

---

## B2.3 Concurrent Idempotency Fix (PR #135)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #135 | fix(usage): B2.3 SQLite concurrent idempotency — lock-safe duplicate delivery | `d71336680e6f7efdbb220501297c7b078b21dd0c` | MERGED |

Corrects: concurrent duplicate delivery no longer raises lock error to caller.
Invariant: `(subject_id, feature_key, idempotency_key)` unique constraint enforced
with no caller-visible error on duplicate. Exactly one event persisted.

---

## Opus Handoff Pack V1 (PR #131)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #131 | docs: FINCO V1 Opus clean-room handoff pack — final rebuild on main 8cd58ad | `1e86d61` | MERGED |

---

## Model Trust Pack UX V1 (PR #133)

| PR | Capability | Accepted Feature HEAD | Merge SHA | State |
|---|---|---|---|---|
| #133 | Model Trust Pack UX V1 — 7-section read-only evidence surface; Corrections A1–A4 (CSS, Section G certificate, fail-closed validation, labeling) | `ab8bd68fcde079a2bec685c258b0d593ee08819f` | `8cd58ad8f50108bbe9931751a4ef8d5b3feef797` | MERGED |

Evidence: 31/31 trust pack UX tests pass; 4/4 CI checks SUCCESS.
Changed files (7): `app/ui/trust_pack.py`, templates, router, tests.
Frozen namespaces: ZERO DIFF.

---

## Signed Run Certificate V1 (PR #132)

| PR | Capability | Accepted Feature HEAD | Merge SHA | State |
|---|---|---|---|---|
| #132 | Signed Run Certificate V1 — Ed25519, committed Last Run only, fail-closed identity | `e292442a9ddd0ff4703f8009e8bbabf9554946a8` | `c9abf435b62086c5a19ec7660fc78bc0653196df` | MERGED |

Key properties: Ed25519 (`cryptography` library), FINCO canonical JSON (sorted keys,
compact UTF-8), `FINCO_RUN_CERT_SIGNING_KEY` required, no fallback key,
no Working Copy values, legacy runs without workbook_version fail closed.

---

## V1 Product Truth Freeze (PR #130)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #130 | docs: V1 Product Truth Freeze — align product documentation with canonical implemented behavior | `cf67770504d4e07cda9094a76e4af3af5a48ce24` | MERGED |

---

## B2.3 Usage / Metering (PR #128)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #128 | B2.3 Correction A — subject-scoped idempotency, session identity, wallet canonical resolution, query failure distinction | `5b6abf71c7286db5e8fd172983f4505f7e3b18ce` | MERGED |
| (non-merge) | B2.3 V1 initial — append-only off-chain usage ledger | `1f53b8b` (direct push) | MERGED |

---

## MCP V1 (PR #129)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #129 | MCP V1 + Correction A — read-only institutional agent interface, dependency pin, version responses, exception boundary | `1f273d9` | MERGED |

MCP tools (9): `finco_supported_today`, `finco_projects`, `finco_last_run`,
`finco_run_identity`, `finco_kpis`, `finco_validation`, `finco_verify`,
`finco_r_live`, `finco_export_metadata`.

---

## R-LIVE Ops (PR #127)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #127 | R-LIVE collector timer — external R-LIVE collector operational package | `52aac6e` | MERGED |

---

## API v1.1 Institutional (PR #125)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #125 | API v1.1 Institutional Read-Only Surface — Correction A + B | `a94e77f` | MERGED |

---

## R-LIVE (PR #124, #126)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #126 | R-LIVE operational activation — read-only R-LIVE collection and surface | `13b86c8` | MERGED |
| #124 | R-LIVE token reference authority — exact on-chain AAPL token reference | `9ebb314` | MERGED |

---

## B2.2 Token Entitlement (PR #122)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #122 | B2.2 FINCO token entitlement — fail-closed FINCO token entitlement for Verified dossiers | `dfb8657` | MERGED |

---

## B2.1 Verified Assets / P5 (PR #120)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #120 | B2.1 first real Verified asset — fail-closed Verified provenance gate and dossier entitlement | `4100307` | MERGED |

---

## P1.4 EV Institutional Reconciliation (PR #123)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #123 | P1.4 EV institutional reconciliation closure | `b9c4d1a` | MERGED |

---

## P1.3 Institutional Validation (PR #121)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #121 | P1.3 Institutional Validation & Reconciliation Pack (+ Corrections A and B) | `412324c` | MERGED |

---

## P1.1 Institutional Model Trust Pack (PR #118)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #118 | P1.1 Trust Pack authority hardening (+ Corrections A, B, C) | `678fc8f` | MERGED |

---

## P0.4 Release Integrity / Supported Today (PR #115)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #115 | P0.4 Canonical Supported Today capability contract | `abbc4b0` | MERGED |

---

## P3 Run Certificate V1 — Initial (PR #101)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #101 | P3 Run Certificate V1 (initial hash-based) | `9f67d91` | MERGED |

**Note:** PR #101 established the initial run certificate framework (hash-based).
PR #132 upgraded it to Ed25519 asymmetric signing. The current canonical
implementation is in `app/services/run_certificate_service.py` (PR #132).

---

## Radar B1 (PR #114, #116, #117)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #117 | B1.3 BNB premium, execution gap, exact-identity history | `b6e4001` | MERGED |
| #116 | B1.2 cross-chain canonical identity | `ca8c0cd` | MERGED |
| #114 | B1.1 BNB RWA market intelligence | `93eda9a` | MERGED |

---

## Model Last Run P0.3 (PR #113)

| PR | Capability | Merge SHA | State |
|---|---|---|---|
| #113 | P0.3 Canonical Reference Model Last Run — EV Charging vertical | `8b24a15` | MERGED |

---

## Notes

- `#119` (Jev / Reflex) is NOT merged. It is experimental/shadow and outside V1 authority.
- No entries are fabricated. SHAs verified from `git log origin/main`.
- PRs merged as direct commits to main appear as regular commit SHAs.
- Inspect with:
  ```bash
  git log 0082e5bd27ffe166c1d80a177fae49670ed848f2 --oneline
  git log 0082e5bd27ffe166c1d80a177fae49670ed848f2 --oneline --merges
  ```
