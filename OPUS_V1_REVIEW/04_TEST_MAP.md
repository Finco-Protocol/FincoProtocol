# FINCO V1 — Reviewer Test Map

All test files are in `tests/`. Run with `pytest tests/<file> -v`.

## Model Verticals

| Area | Test File | What it tests |
|---|---|---|
| Solar / Wind (reference models) | `tests/test_public_reference_models.py` | Public reference model integrity |
| Solar / Wind (engine smoke) | `tests/test_public_engine_smoke.py` | Engine runs without crash |
| Data Center | `tests/test_data_center_reference.py`, `test_data_center_vertical_integrity.py` | DC vertical integrity (A3.1) |
| EV Charging | `tests/test_ev_charging_reference.py`, `test_ev_charging_acceptance.py`, `test_ev_charging_a5_run.py` | EV canonical reference and model run |
| Capability contract | `tests/test_p0_4_capability_contract.py` | Supported Today registry consistency |
| Capability consistency | `tests/test_product_capability_consistency.py` | All surfaces agree with registry |

## Last Run / Run Certificate (P3 / Signed Run)

| Test File | What it tests |
|---|---|
| `tests/test_p3_run_certificate_v1.py` | Run Certificate V1: determinism, lineage, fail-closed gates |
| `tests/test_reference_canonical_last_run.py` | Canonical reference model Last Run integrity |
| `tests/test_storage_working_copy_contract.py` | Working Copy ≠ Last Run contract |
| `tests/test_f04_signing_secret_fail_closed.py` | Signing secret fail-closed behaviour |

## XLSX Export / Reconciliation (P1.2)

| Test File | What it tests |
|---|---|
| `tests/test_p1_2_xlsx_export_reconciliation.py` | XLSX numbers match committed Last Run |
| `tests/test_u2_1_v2_export.py` | V2 export surface |
| `tests/test_f07_export_lineage.py` | Export lineage tracking |
| `tests/test_f07b_canonical_export_authority.py` | Canonical export authority |

## Institutional Validation (P1.3)

| Test File | What it tests |
|---|---|
| `tests/test_p1_3_institutional_validation.py` | Same-run reconciliation, validation status contract |
| `tests/test_p1_1_institutional_trust_pack.py` | Trust Pack methodology, DSCR, XIRR ACT/365F |
| `tests/test_p1_4_ev_reconciliation.py` | EV institutional reconciliation |

## Verified Assets / B2.1

| Test File | What it tests |
|---|---|
| `tests/test_b2_1_verified_authority.py` | B2.1 market binding, evidence gate, dossier isolation |
| `tests/test_p5_verified_assets.py` | P5 Verified Assets composition (Model → Verify → Radar) |
| `tests/test_p5_browser_acceptance.py` | P5 browser acceptance |
| `tests/test_opus_a1_public_truth.py` | Public truth alignment (A1) |
| `tests/test_a2_public_verify.py` | A2 public reference verify + methodology reproducibility |

## B2.2 Token Entitlement

| Test File | What it tests |
|---|---|
| `tests/test_b2_2_token_entitlement.py` | FINCO token entitlement, fail-closed gate |
| `tests/test_p4_token_utility.py` | P4 holder entitlement rail |
| `tests/test_protocol_verification.py` | Protocol verification corpus |

## B2.3 Usage Metering

| Test File | What it tests |
|---|---|
| `tests/test_b2_3_usage_metering.py` | 29 tests: idempotency, identity, wallet, query failure |

Key markers in the test file:
- `test_B2_3_IDEMPOTENCY_SUBJECT_SCOPED` — scoped unique constraint
- `test_B2_3_CROSS_USER_IDEMPOTENCY_COLLISION_SAFE` — cross-user collision safety
- `test_B2_3_CROSS_FEATURE_IDEMPOTENCY_COLLISION_SAFE` — cross-feature collision safety
- `test_B2_3_QUERY_SIGNED_IDENTITY_ONLY` — no caller-supplied subject_id
- `test_B2_3_QUERY_CROSS_USER_SPOOF_IMPOSSIBLE` — spoof structural impossibility
- `test_B2_3_WALLET_NOT_CALLER_CONTROLLED` — wallet not in public API
- `test_B2_3_WALLET_CANONICAL_LINK_ONLY` — wallet resolved from auth only
- `test_B2_3_QUERY_FAILURE_NOT_ZERO` — UNAVAILABLE ≠ empty
- `test_B2_3_QUERY_ERROR_SECRET_SAFE` — no raw exception/SQL exposed
- `test_B2_3_CONCURRENT_DUPLICATE_SAFE_sqlite` — concurrent idempotency under SQLite

## API v1 / v1.1

| Test File | What it tests |
|---|---|
| `tests/test_api_v1_1_institutional.py` | API v1.1 institutional surface |
| `tests/test_api_v1_model_references.py` | v1 model reference endpoint |
| `tests/test_api_v1_model_reference_run.py` | v1 model reference run |
| `tests/test_api_v1_model_reference_preview.py` | v1 preview endpoint |
| `tests/test_api_v1_radar.py` | v1 Radar endpoints |
| `tests/test_api_v1_execution_simulation.py` | v1 execution simulation |
| `tests/test_protocol_api_beta.py` | protocol API beta surface |

## MCP V1

No dedicated MCP test file in `tests/` (MCP server is a stdio interface).
The institutional API v1.1 tests (`tests/test_api_v1_1_institutional.py`)
cover the underlying data surface the MCP server exposes.

## R-LIVE / Radar

| Test File | What it tests |
|---|---|
| `tests/test_r_live_onchain.py` | R-LIVE on-chain authority |
| `tests/test_radar_b1_authority.py` | Radar B1 authority baseline |
| `tests/test_radar_b1_2_cross_chain_identity.py` | Cross-chain canonical identity |
| `tests/test_radar_b1_3_intelligence.py` | BNB premium, execution, history |
| `tests/test_radar_r11_verification.py` | Radar R11 verification |
| `tests/test_radar_rwa.py`, `test_radar_rwa_bnb.py` | RWA market observations |
| `tests/test_radar_runtime_reliability.py` | Radar runtime reliability |

## Trust Pack

| Test File | What it tests |
|---|---|
| `tests/test_model_trust_pack.py` | Model Trust Pack content and authority |
| `tests/test_model_trust_pack_browser.py` | Trust Pack browser rendering |
| `tests/test_p1_1_institutional_trust_pack.py` | Institutional Trust Pack (methodology, DSCR, XIRR) |

## Golden Flows

| Test File | What it tests |
|---|---|
| `tests/test_golden_flow_correction_a.py` | Golden flow Correction A |
| `tests/test_golden_flow_correction_b.py` | Golden flow Correction B |
| `tests/test_correction_a_required_gates.py` | Required gate assertions for Correction A |
| `tests/test_correction_b_home_claims.py` | Correction B home surface claims |

## Quick Authority Smoke Command

```bash
pytest tests/test_b2_1_verified_authority.py \
       tests/test_b2_2_token_entitlement.py \
       tests/test_b2_3_usage_metering.py \
       tests/test_p3_run_certificate_v1.py \
       tests/test_p1_1_institutional_trust_pack.py \
       tests/test_p1_3_institutional_validation.py \
       tests/test_p0_4_capability_contract.py \
       tests/test_product_capability_consistency.py \
       -v --tb=short
```

Expected: all pass on `5b6abf71c7286db5e8fd172983f4505f7e3b18ce`.
