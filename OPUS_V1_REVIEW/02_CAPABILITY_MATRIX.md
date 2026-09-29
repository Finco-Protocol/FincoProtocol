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
| R-LIVE — AAPL on-chain reference (Robinhood chain 4663) | LIVE | `finco_radar/authority/r_live_onchain.py`, `app/radar_rwa/r_live_service.py` |
| R-LIVE history store (B1.3) | LIVE | Durable B1.3 history; external collector is sole writer |
| R-LIVE operational collector package (PR #127) | LIVE | External systemd operational package; requires deployment configuration |

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
- R-LIVE collector operational package exists but requires deployment configuration.
  Repository-ready does not prove VPS collector activation.
