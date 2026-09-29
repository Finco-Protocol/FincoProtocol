# FINCO V1 — Clean-Room Review Entry Point

## Repository

`Finco-Protocol/FincoProtocol`
https://github.com/Finco-Protocol/FincoProtocol

## Live Main SHA (at handoff)

```
5b6abf71c7286db5e8fd172983f4505f7e3b18ce
```

Merge commit: **B2.3 Usage/Metering — Correction A** (PR #128, merged 2026-09-28)

## Staging / Production URL

Not documented in the repository. The repository does not contain a live deployment
URL in its configuration files. Do not assume any URL — verify separately if needed.

## How to Run Locally

### Prerequisites

- Python 3.11+
- `pip install -r requirements.txt`

Dependencies include: `fastapi`, `uvicorn`, `pydantic`, `eth-account>=0.11,<0.14`, `pandas`, `openpyxl`, `bcrypt`, `itsdangerous`, `httpx`, `pytest-asyncio`.

### Start the web application

```bash
uvicorn main_web:app --reload --port 8000
```

### Start the API server

```bash
uvicorn main_api:app --reload --port 8001
```

### Run the test suite

```bash
# Full suite (runs ~25 min in CI due to browser/integration tests)
pytest tests/

# Fast smoke — skips browser and slow integration tests
pytest tests/ -m "not browser and not slow" -x

# Key authority test files (fast, no browser required)
pytest tests/test_b2_1_verified_authority.py \
       tests/test_b2_2_token_entitlement.py \
       tests/test_b2_3_usage_metering.py \
       tests/test_p1_1_institutional_trust_pack.py \
       tests/test_p1_2_xlsx_export_reconciliation.py \
       tests/test_p1_3_institutional_validation.py \
       tests/test_p3_run_certificate_v1.py \
       tests/test_api_v1_1_institutional.py \
       -v
```

## CI Checks

Four required checks run on every PR and main push:

| Check | File |
|---|---|
| `safety-and-smoke` | `.github/workflows/public_safety_and_smoke.yml` |
| `compile-and-safety` | `.github/workflows/...` |
| `dependency-audit` | `.github/workflows/dependency_security_audit.yml` |
| `protocol-ui-browser` | `.github/workflows/protocol_verification.yml` |

## Canonical Architecture Map

```
User Session (signed JWT)
        │
        ▼
  app/auth.py — session identity, CSRF, rate-limit
        │
        ├──► FINCO Model (main_web.py + app/ + financial_engine/ + finco_core/)
        │         │
        │         ├── CALCULATE  → financial_engine/*, finco_core/*
        │         ├── COMMIT     → app/persistence/runs_repository.py
        │         ├── VALIDATE   → app/model_validation/
        │         ├── VERIFY     → app/verify/ (run_certificate.py, issuer.py)
        │         ├── OBSERVE    → app/observability.py
        │         ├── SIGN       → app/verify/run_certificate.py (composite hash)
        │         ├── DISTRIBUTE → app/export/ (XLSX, institutional workbook)
        │         └── METER      → app/usage/ (B2.3)
        │
        ├──► FINCO Radar (app/radar_*/*, finco_radar/*)
        │         └── R-LIVE  → finco_radar/authority/, app/radar_rwa/r_live_*
        │
        ├──► FINCO Verified (app/verified/)
        │         └── B2.1 asset dossier, B2.2 token entitlement
        │
        ├──► API v1 (main_api.py → app/api/v1/)
        │         └── model references, radar, run endpoint
        │
        ├──► API v1.1 (app/api/v1_1/)
        │         └── institutional read-only surface
        │
        └──► MCP Server (app/api/v1_1/ — stdio-mode institutional agent)
```

## Authority Boundaries (summary)

| Boundary | What it means |
|---|---|
| `financial_engine/**` | Frozen. Deterministic math. Zero diff allowed in product PRs. |
| `finco_core/**` | Frozen. Numeric primitives. Zero diff allowed. |
| `app/verified/**` | Frozen. Verification truth. Zero diff allowed. |
| `finco_radar/**` | Frozen. Radar authority. Zero diff allowed. |
| `app/api/v1_1/**` | Frozen for this stream. |
| session.user_id | Only source of subject identity in B2.2 and B2.3. Caller cannot supply. |
| wallet_address | Resolved internally from `app.protocol.wallet_auth`. Never caller-supplied. |

## Supported Today Contract

Canonical source: `app/product_capability.py`

LIVE verticals: Solar, Wind, Data Center, EV Charging, BNB Tokenized Assets
PREVIEW: Storage (reference viewable; working-copy runtime not released)

The product capability registry is the single source of truth. Public surfaces
(Roadmap, Docs, API, UI) must match it. Consistency is enforced by
`tests/test_p0_4_capability_contract.py` and `tests/test_product_capability_consistency.py`.
