# FINCO Product Truth Release Matrix

Release-truth checklist for public product-status claims. One row per
surface × feature: the public status, the canonical source of truth, and
the merged authority behind it. **Only merged main is public truth — an
open PR (green or not) is not a shipped feature.**

Status vocabulary: `SHIPPED` · `PREVIEW` · `EXPERIMENTAL` ·
`IN DEVELOPMENT` · `NEXT` · `LATER` · `UNAVAILABLE`.

Last updated: PR #147 final cut (post-#146 sync). Canonical base:
main `77f29ae` (post-#146 JEV Intelligence V1) + #147 truth corrections.

| Surface | Feature | Public status | Source of truth | Merged authority | Known limitation |
| --- | --- | --- | --- | --- | --- |
| Model | Solar / Wind | SHIPPED | `app/product_capability.py`, capability contract tests | Model verticals (long-lived) | — |
| Model | Data Center | SHIPPED | `app/product_capability.py` | A3.1 / PR #88 lineage | — |
| Model | EV Charging | SHIPPED | `app/product_capability.py` | A3.2 lineage | runtime validation coverage narrower than Solar/Wind |
| Model | Storage | PREVIEW (reference view only) | `app/product_capability.py` (`ProductStatus.PREVIEW`) | Storage reference PR | working-copy runtime not released |
| Model | Product-run construction financing (IDC / commitment / structuring fees / initial DSRA / S&U) | SHIPPED | PR #144 (H-1 closed) | #144 | not a claim that all financing structures are supported |
| Model | DSCR sculpting fail-closed feasibility | SHIPPED | PR #144 (H-2 closed) | #144 | no "unconditionally institutional-grade" convergence claims |
| Model | Last Run authority | SHIPPED | runs/workspace persistence | canonical Last Run (COMMIT) | snapshot replaced by each subsequent committed run |
| Trust Pack | Model Trust Pack UX V1 | SHIPPED | `app/ui/trust_pack.py` | PR #133 + #143 | on-demand sections need a committed run |
| Run Integrity | Run Integrity Checks (H-4b) | SHIPPED | `app/run_integrity/` | #144 | internal consistency only — no external-assumption validation, not economic truth |
| Reference Regression | Reference Regression Check (P1.3) | SHIPPED | `app/model_validation/` (machine key `MODEL_VALIDATION`) | P1.3 + #143 terminology | regression protection only; never validates a user's Last Run |
| Signed Run | Certificate issuance (Ed25519) | SHIPPED (config-gated) | `app/services/run_certificate_service.py` | PR #132 + #143 truth | fails closed without `FINCO_RUN_CERT_SIGNING_KEY` |
| Signed Run | Public trust-key distribution / public verifier (M-2) | IN DEVELOPMENT (deferred at this release cut — no open PR at final cut) | M-2 master stream | **not merged** | do not mark shipped until merged; do not infer functionality from an open branch |
| FINCO Verify | Verified Assets authority | SHIPPED architecture; 0 production VERIFIED | `app/verified/` (`PRODUCTION_VERIFIED_ASSET_COUNT`) | B2.1 | records render MODEL_ONLY; MODEL_ONLY ≠ VERIFIED |
| Model ↔ Market | Source-proven model↔market bridge | NEXT / HIGH PRIORITY | missing-layer roadmap entry | **not implemented** | prerequisite for production VERIFIED assets |
| Radar | Stocks / Crypto / Economy | SHIPPED | radar UI surfaces | Radar PR series | — |
| Radar | R-LIVE V2 | SHIPPED (code/product surface) | `finco_radar/authority/r_live_*`, `app/radar_rwa/r_live_service.py` | PRs #127/#136/#137/#139/#140/#145 | operational activation requires deployment config (`ROBINHOOD_RPC_URL` + collector + ledger); repo assets are not proof of an active production collector |
| Radar | R-LIVE public API (6 routes) | SHIPPED | `app/api/v1.1/r_live_public_router.py` | #136/#137 | read-only; observations are not executable prices |
| JEV | JEV Radar Intelligence V1 | EXPERIMENTAL (merged) | `app/radar_rwa/jev_intelligence/` | PR #146 (merged 2026-09-30) | default OFF; enable-without-mode runs SHADOW (never silently VISIBLE); live provider smoke SKIPPED_NO_KEY at merge — external-provider validation not demonstrated; no accuracy/alpha/advice claims |
| $FINCO | Wallet identity / ownership verification | SHIPPED (foundation) | wallet/session/token-entitlement modules | B2.2 lineage | production token activation is future |
| $FINCO | Entitlement decision rail / utility registry | SHIPPED | B2.2 | B2.2 | token not launched; thresholds/economics not final |
| $FINCO | Usage metering (B2.3) | SHIPPED ledger; production coverage INCOMPLETE | B2.3 ledger | PRs #128/#135 | not wired into all production resource paths |
| $FINCO | Token launch / production metered utility (M-1) | NEXT | M-1 roadmap entry | **not merged** | candidate scarce resources only; economics not final |
| Yield | FINCO Yield (Y0 spike) | IN DEVELOPMENT / EXPERIMENTAL | `finco_yield/**` on PR #148 (OPEN — not merged) | **not merged** | flags default OFF; non-custodial; no mainnet execution; no FINCO-owned vault; Robinhood Chain PARTIAL; direction Explore → Underwrite → Evidence → Monitor → Act |
| API | Model reference API / Radar API (v1 beta) | SHIPPED (Beta contract) | `app/api/v1/` | A3–A5 series | stable SDK/GA policy later |
| API | R-LIVE public API | SHIPPED | `app/api/v1.1/r_live_public_router.py` | #136/#137 | — |
| MCP | MCP V1 read-only agent access | SHIPPED (single-session boundary) | `app/mcp/v1/` | MCP V1 | not yet a shared multi-user hosted transport |
| Anchoring | L2 / Merkle anchoring | LATER | roadmap | **not implemented** | nothing on-chain is claimed |

## Invariant reminders (enforced by contract tests)

- `Reference Regression Check ≠ Run Integrity ≠ FINCO Verify`; `Signed Run ≠ FINCO Verify`; `Signed Run ≠ economic truth`; `Reference price ≠ executable price`; `Working Copy ≠ Last Run`.
- `PRODUCTION_VERIFIED_ASSET_COUNT = 0`; MODEL_ONLY never implies VERIFIED.
- `$FINCO never touches the math; never determines whether evidence is true.` Balance never changes IRR / DSCR / valuation / market price / Verify state.
- Missing data is `UNAVAILABLE`, never zero.
- JEV and M-2 statuses above must be re-synced from merged main before the next release cut (open PR ≠ shipped).
