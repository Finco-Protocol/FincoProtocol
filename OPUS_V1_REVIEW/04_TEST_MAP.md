# FINCO V1 — Reviewer Test Map

All test files are in `tests/`. Run with `pytest tests/<file> -v`.

Verified counts are accurate at main SHA `226fe8d4ee15bfe60e441550f386e8985ae0c2f9`.

The `eth_account` CI failure in `tests/test_b2_2_token_entitlement.py` was fixed.
All test files listed here run without infrastructure exclusion.

---

## Model Verticals

| Area | Test File | What it tests |
|---|---|---|
| Solar / Wind (reference models) | `tests/test_public_reference_models.py` | Public reference model integrity |
| Solar / Wind (engine smoke) | `tests/test_public_engine_smoke.py` | Engine runs without crash |
| Data Center | `tests/test_data_center_reference.py`, `test_data_center_vertical_integrity.py` | DC vertical integrity (A3.1) |
| EV Charging | `tests/test_ev_charging_reference.py`, `test_ev_charging_acceptance.py`, `test_ev_charging_a5_run.py` | EV canonical reference and model run |
| Capability contract | `tests/test_p0_4_capability_contract.py` | Supported Today registry consistency |
| Capability consistency | `tests/test_product_capability_consistency.py` | All surfaces agree with registry |

---

## Canonical Last Run / COMMIT

| Test File | What it tests |
|---|---|
| `tests/test_reference_canonical_last_run.py` | Canonical reference model Last Run integrity |
| `tests/test_storage_working_copy_contract.py` | Working Copy ≠ Last Run contract |

---

## Signed Run Certificate V1 (PR #132)

| Test File | Count | What it tests |
|---|---|---|
| `tests/test_p3_run_certificate_v1.py` | 40 | Ed25519 signing, Last Run only, fail-closed gates, identity completeness, frozen namespace check |
| `tests/test_p3_route_integration.py` | — | Route integration for certificate endpoint |
| `tests/test_p3_browser_acceptance.py` | — | Browser rendering of certificate surface |
| `tests/test_f04_signing_secret_fail_closed.py` | — | Signing secret fail-closed behaviour |

Key markers in `test_p3_run_certificate_v1.py`:
- Ed25519 signing verified
- Issued from Last Run only (never Working Copy)
- Incomplete identity fails closed
- Legacy run without workbook_version fails closed
- Frozen namespace assertions (`financial_engine` not modified)

---

## XLSX Export / Reconciliation (P1.2)

| Test File | What it tests |
|---|---|
| `tests/test_p1_2_xlsx_export_reconciliation.py` | XLSX numbers match committed Last Run |
| `tests/test_u2_1_v2_export.py` | V2 export surface |
| `tests/test_f07_export_lineage.py` | Export lineage tracking |
| `tests/test_f07b_canonical_export_authority.py` | Canonical export authority |

---

## Institutional Validation (P1.3)

| Test File | Count | What it tests |
|---|---|---|
| `tests/test_p1_3_institutional_validation.py` | 50 | Same-run reconciliation, validation status contract |
| `tests/test_p1_1_institutional_trust_pack.py` | — | Trust Pack methodology, DSCR, XIRR ACT/365F |
| `tests/test_p1_4_ev_reconciliation.py` | — | EV institutional reconciliation |

---

## Model Trust Pack UX V1 (PR #133)

| Test File | Count | What it tests |
|---|---|---|
| `tests/test_model_trust_pack_ux.py` | 31 | UX acceptance: all 7 sections, DEFERRED pattern, CSS classes, authority separation |
| `tests/test_model_trust_pack.py` | — | Model Trust Pack content and authority |
| `tests/test_model_trust_pack_browser.py` | — | Trust Pack browser rendering |

Key markers in `test_model_trust_pack_ux.py`:
- `TRUST_PACK_VERIFIED_STYLE_ONLY_FOR_VERIFIED` — only verified status gets green CSS
- `TRUST_PACK_CERTIFICATE_SEPARATE_FROM_VERIFY` — section G ≠ FINCO VERIFY
- `TRUST_PACK_SIGNING_NEVER_IMPLIES_VERIFIED` — certificate cannot imply VERIFIED
- `TRUST_PACK_RENDER_DOES_NOT_SIGN` — page render never issues a certificate
- `TRUST_PACK_GLOBAL_FAILURE_NO_ACTIONABLE_DEFERRED_STATE` — without committed run, no actionable load URL

---

## FINCO VERIFY / Verified Assets (B2.1)

| Test File | What it tests |
|---|---|
| `tests/test_b2_1_verified_authority.py` | B2.1 market binding, evidence gate, dossier isolation |
| `tests/test_p5_verified_assets.py` | P5 Verified Assets composition (Model → Verify → Radar) |
| `tests/test_p5_browser_acceptance.py` | P5 browser acceptance |
| `tests/test_opus_a1_public_truth.py` | Public truth alignment (A1) |
| `tests/test_a2_public_verify.py` | A2 public reference verify + methodology reproducibility |

---

## B2.2 Token Entitlement

| Test File | What it tests |
|---|---|
| `tests/test_b2_2_token_entitlement.py` | FINCO token entitlement, fail-closed gate |
| `tests/test_p4_token_utility.py` | P4 holder entitlement rail |
| `tests/test_protocol_verification.py` | Protocol verification corpus |

---

## B2.3 Usage Metering

| Test File | Count | What it tests |
|---|---|---|
| `tests/test_b2_3_usage_metering.py` | 29 | Idempotency, identity, wallet, query failure |

Key markers:
- `test_B2_3_IDEMPOTENCY_SUBJECT_SCOPED` — scoped unique constraint
- `test_B2_3_CROSS_USER_IDEMPOTENCY_COLLISION_SAFE` — cross-user collision safety
- `test_B2_3_QUERY_SIGNED_IDENTITY_ONLY` — no caller-supplied subject_id
- `test_B2_3_QUERY_CROSS_USER_SPOOF_IMPOSSIBLE` — spoof structural impossibility
- `test_B2_3_WALLET_NOT_CALLER_CONTROLLED` — wallet not in public API
- `test_B2_3_QUERY_FAILURE_NOT_ZERO` — UNAVAILABLE ≠ empty
- `test_B2_3_QUERY_ERROR_SECRET_SAFE` — no raw exception/SQL exposed
- `test_B2_3_CONCURRENT_DUPLICATE_SAFE_sqlite` — concurrent idempotency under SQLite (PR #135 fix)

---

## API v1 / v1.1

| Test File | Count | What it tests |
|---|---|---|
| `tests/test_api_v1_1_institutional.py` | 31 | API v1.1 institutional surface; covers data the MCP server exposes |
| `tests/test_api_v1_model_references.py` | — | v1 model reference endpoint |
| `tests/test_api_v1_model_reference_run.py` | — | v1 model reference run |
| `tests/test_api_v1_model_reference_preview.py` | — | v1 preview endpoint |
| `tests/test_api_v1_radar.py` | — | v1 Radar endpoints |
| `tests/test_api_v1_execution_simulation.py` | — | v1 execution simulation |
| `tests/test_protocol_api_beta.py` | — | protocol API beta surface |

---

## MCP V1

No dedicated MCP test file. The MCP server is a stdio interface; the institutional
API v1.1 tests (`tests/test_api_v1_1_institutional.py`) cover the underlying data
surface that the MCP server exposes.

---

## R-LIVE V2 (PR #136 / #137)

| Test File | Count | What it tests |
|---|---|---|
| `tests/test_radar_r14_rlive_shell.py` | 504 | R-LIVE V2 product shell: registry-driven rows, identity enforcement, no-write contract, approved/unapproved routing |
| `tests/test_radar_r14_rlive_public_routes.py` | 238 | R-LIVE public API routes: assets list, exact-identity detail, unapproved fails closed, no history write |
| `tests/test_radar_r14_rlive_history_contract.py` | 459 | R-LIVE history contract: read-only, STALE/UNAVAILABLE distinct from empty, canonical schema parity |
| `tests/test_radar_robinhood_multi_asset.py` | — | Multi-asset Robinhood authority and freshness gate |

Key invariants tested:
- Unapproved identity → `ASSET_NOT_IN_REGISTRY` (never fabricated response)
- Read paths → zero history writes (`persist_history=False`)
- STALE / UNAVAILABLE structurally distinct from empty/zero
- 300-second freshness gate: no current numeric if no recent Swap
- Public API is unauthenticated; no project list, no exports

## R-LIVE Multi-Asset Collector (PR #139)

| Test File | Count | What it tests |
|---|---|---|
| `tests/test_r_live_collector_batch.py` | 241 | Batch orchestration, per-asset independence, process/market state distinction, credential redaction, RPC preflight |
| `tests/test_r_live_collector_ops.py` | 40 | Collector operational semantics, single-asset diagnostic path, unapproved key rejection |

Key invariants tested:
- `test_no_arg_main_uses_batch_and_prints_safe_json` — no-arg `main([])` calls `collect_all_approved`
- `test_no_arg_batch_uses_complete_registry_and_one_serial_ledger` — full registry, single shared ledger
- `test_batch_registry_count_is_derived_and_not_hardcoded` — count derived from policy, not literal
- `test_explicit_exact_key_collects_only_one_and_unapproved_fails_closed` — `--asset-key` diagnostic; unapproved → `ASSETKEY_NOT_APPROVED`
- `test_batch_config_and_ledger_failures_are_nonzero_and_redacted` — `RPC_NOT_CONFIGURED`, `HISTORY_STORE_UNAVAILABLE`
- `test_configured_but_unreachable_rpc_is_process_failure_without_secret` — `RPC_UNAVAILABLE`; no credential in output
- `test_individual_exception_does_not_abort_batch_or_leak_secret` — exception → UNAVAILABLE for that asset; batch continues; no raw exception in output
- `test_every_acquisition_exception_attempts_every_asset_and_exits_nonzero` — all assets attempted regardless of exceptions
- `test_one_canonical_nonavailable_state_is_healthy_batch` — STALE/UNAVAILABLE market state ≠ process failure; exit 0
- `test_history_persistence_failure_is_process_failure` — AVAILABLE result with no digest → `HISTORY_STORE_UNAVAILABLE`

---

## R-LIVE V1 / Radar BNB

| Test File | What it tests |
|---|---|
| `tests/test_r_live_onchain.py` | R-LIVE on-chain authority (AAPL V1) |
| `tests/test_radar_b1_authority.py` | Radar B1 authority baseline |
| `tests/test_radar_b1_2_cross_chain_identity.py` | Cross-chain canonical identity |
| `tests/test_radar_b1_3_intelligence.py` | BNB premium, execution, history |
| `tests/test_radar_r11_verification.py` | Radar R11 verification |
| `tests/test_radar_rwa.py`, `test_radar_rwa_bnb.py` | RWA market observations |
| `tests/test_radar_runtime_reliability.py` | Radar runtime reliability |

---

## Quick Authority Smoke Command

```bash
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
       -v --tb=short
```

Handoff SHA: `226fe8d4ee15bfe60e441550f386e8985ae0c2f9`.

## Full Suite Command

```bash
pytest tests/ -q
```
