# FINCO V1 — Clean-Room Review Entry Point

## Repository

`Finco-Protocol/FincoProtocol`
https://github.com/Finco-Protocol/FincoProtocol

## Live Main SHA (at handoff)

```
0082e5bd27ffe166c1d80a177fae49670ed848f2
```

Merge commit: **R-LIVE V2 freshness/history/13-asset expansion** (PR #140, merged 2026-09-29)

Product base includes PR #136–#140 (R-LIVE V2 multi-asset authority, product shell, multi-asset
collector, freshness/history/13-asset expansion).

Previous main before PR #140: `226fe8d4ee15bfe60e441550f386e8985ae0c2f9` (PR #139 merge).
PR #140 full-suite evidence: 4703 passed, 38 skipped, 0 failed; 6/6 workflows SUCCESS.

This package describes the implemented repository state at this SHA.
It is not a marketing document. Limitations are disclosed in `05_KNOWN_LIMITATIONS.md`.

## Staging / Production URL

Not documented in the repository. The repository does not contain a live deployment
URL in its configuration files. Do not assume any URL — verify separately if needed.

## How to Run Locally

### Prerequisites

- Python 3.11+
- `pip install -r requirements.txt`

Dependencies include: `fastapi`, `uvicorn`, `pydantic`, `pandas`, `openpyxl`,
`bcrypt`, `itsdangerous`, `httpx`, `cryptography` (Ed25519), `pytest-asyncio`.

### Start the web application

```bash
uvicorn main_web:app --reload --port 8000
```

### Start the API server

```bash
uvicorn main_api:app --reload --port 8001
```

### Start the MCP server

```bash
FINCO_SESSION_TOKEN=<signed-token> python main_mcp.py --transport stdio
```

`FINCO_SESSION_TOKEN` must be a valid signed session token from
`app.auth.create_session_token()` (admin) or `app.auth.create_demo_session_token()` (demo).

### Run the test suite

```bash
# Full suite
pytest tests/

# Quick authority smoke — key authority files only, fast
pytest tests/test_b2_1_verified_authority.py \
       tests/test_b2_2_token_entitlement.py \
       tests/test_b2_3_usage_metering.py \
       tests/test_p3_run_certificate_v1.py \
       tests/test_p1_1_institutional_trust_pack.py \
       tests/test_p1_3_institutional_validation.py \
       tests/test_api_v1_1_institutional.py \
       tests/test_p0_4_capability_contract.py \
       tests/test_product_capability_consistency.py \
       tests/test_model_trust_pack_ux.py \
       tests/test_radar_r14_rlive_shell.py \
       tests/test_radar_r14_rlive_public_routes.py \
       tests/test_radar_r14_rlive_history_contract.py \
       tests/test_r_live_collector_batch.py \
       tests/test_r_live_collector_ops.py \
       -v --tb=short
```

The `tests/test_b2_2_token_entitlement.py` eth_account CI failure was resolved.
All authority tests in the suite are expected to run; no file-level exclusion required.

## CI Checks (4 required on every PR and main push)

| Check | Purpose |
|---|---|
| `safety-and-smoke` | public safety scan + full pytest |
| `compile-and-safety` | Python compilation check |
| `dependency-audit` | dependency vulnerability audit |
| `protocol-ui-browser` | browser/UI acceptance |

PR #140 CI result: **6/6 SUCCESS** at exact head `dd5bd09f6c1af303aa1b0d695828d8394f989de0`.
Full suite: 4703 passed, 38 skipped, 0 failed.

## Where to Find Key Capabilities

| Capability | Location |
|---|---|
| **FINCO Model (engine)** | `financial_engine/`, `finco_core/`, `domain/` |
| **Product capability registry** | `app/product_capability.py` |
| **API v1.1 (institutional)** | `app/api/v1_1/` |
| **MCP V1 server** | `app/mcp/v1/server.py`, entry: `main_mcp.py` |
| **FINCO Radar** | `finco_radar/`, `app/radar_rwa/`, `app/radar_crypto/` |
| **R-LIVE V2 authority** | `finco_radar/authority/r_live_policy.py`, `finco_radar/authority/r_live_onchain.py`, `app/radar_rwa/r_live_service.py` |
| **R-LIVE V2 public API** | `app/api/v1_1/r_live_public_router.py` (6 unauthenticated read-only routes) |
| **R-LIVE V2 UX shell** | `app/radar_ui/r_live_router.py`, templates `radar/r_live_landing.html`, `radar/r_live_detail.html` |
| **R-LIVE multi-asset collector (PR #139)** | `app/radar_rwa/r_live_collect.py` — no-arg = `collect_all_approved()` over full registry; `--asset-key` for single diagnostic |
| **FINCO VERIFY (B2.1)** | `app/verified/authority.py` |
| **Signed Run Certificate V1** | `app/services/run_certificate_service.py`, docs: `docs/SIGNED_RUN_CERTIFICATE_V1.md` |
| **Model Trust Pack UX V1** | `app/ui/trust_pack.py`, template: `app/templates/v2/partials/sheet_trust.html` |
| **B2.2 Token Entitlement** | `app/verified/token_entitlement.py` |
| **B2.3 Usage Metering** | `app/usage/ledger.py`, `app/usage/query.py` |

## Canonical Supported Today

Source of truth: `app/product_capability.py`
Consistency enforced by: `tests/test_p0_4_capability_contract.py`, `tests/test_product_capability_consistency.py`

| Vertical | Status |
|---|---|
| Solar | **LIVE** |
| Wind | **LIVE** |
| Data Center | **LIVE** |
| EV Charging | **LIVE** |
| Storage | **PREVIEW** (reference viewable; working-copy runtime not released) |

**BNB Tokenized Assets / Radar is a Radar capability — it is NOT a Model vertical.**
It must not be described as a model-runnable vertical. The FINCO Model vertical
list is Solar, Wind, Data Center, EV Charging, and Storage (PREVIEW).

## Authority Boundaries (summary)

| Boundary | Meaning |
|---|---|
| `financial_engine/**` | Frozen. Deterministic math. Zero diff allowed in product PRs. |
| `finco_core/**` | Frozen. Numeric primitives. Zero diff allowed. |
| `app/verified/**` | Frozen. Verification truth. Zero diff allowed. |
| `finco_radar/**` | Frozen. Radar authority. Zero diff allowed. |
| `session.user_id` | Only source of subject identity in B2.2 and B2.3. Caller cannot supply. |
| `wallet_address` | Resolved internally from `app.protocol.wallet_auth`. Never caller-supplied. |

## Authentication

FINCO sessions use **signed cookies** via `itsdangerous.URLSafeTimedSerializer`
(`app/auth.py`). This is NOT JWT. The implementation uses stateless signed
cookies with server-configured secret keys.

MCP V1 uses a server-configured `FINCO_SESSION_TOKEN` decoded through the same
signed session authority (`app.auth`). No caller-supplied identity is accepted.
