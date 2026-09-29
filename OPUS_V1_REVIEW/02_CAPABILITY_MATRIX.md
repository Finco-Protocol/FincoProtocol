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
| BNB Tokenized Assets | LIVE | ✓ | N/A | N/A | N/A | N/A | ✓ |

**Storage note:** Reference model is viewable. Working-copy runtime not released in V1.

## Cross-Cutting Capabilities

| Capability | Status | Notes |
|---|---|---|
| Institutional Trust Pack (P1.1) | LIVE | Methodology HTML, DSCR, XIRR ACT/365F docs |
| XLSX Export / Reconciliation (P1.2) | LIVE | Institutional workbook; export lineage tracked |
| Institutional Validation (P1.3) | LIVE | Same-run reconciliation, validation status contract |
| EV Institutional Reconciliation (P1.4) | LIVE | EV-specific reconciliation closure |
| Run Certificate / Signed Run (P3) | LIVE | `FINCO_RUN_CERTIFICATE_V1`; composite hash bound |
| FINCO Token Utility (P4) | LIVE | Holder entitlement rail |
| Verified Assets (P5) / B2.1 | LIVE | Model → Verify → Radar; explicit market binding |
| B2.2 Token Entitlement | LIVE | Fail-closed; `app/verified/token_entitlement.py` |
| B2.3 Usage Metering | LIVE | Append-only ledger; session-scoped identity |
| API v1 (model references + radar) | LIVE | `main_api.py` → `app/api/v1/` |
| API v1.1 (institutional) | LIVE | `app/api/v1_1/`; read-only |
| MCP V1 | LIVE | Read-only institutional agent; PR #129 |
| R-LIVE (Radar Live) | LIVE | On-chain snapshot collection; PR #126, #127 |
| P0 Release Integrity | LIVE | Canonical Supported Today contract (P0.4) |
| Jev / Reflex | **NOT V1** | Experimental; explicitly not part of V1 authority |

## What "LIVE" means

A LIVE capability is implemented, current, and intentionally exposed today.
It may carry documented known limitations (see `05_KNOWN_LIMITATIONS.md`).
LIVE does not mean "production-deployed to a public URL" — deployment status
is separate from capability status.

## What "PREVIEW" means

Implemented but intentionally limited in a documented way. Reference viewable;
runtime or cloning not released.
