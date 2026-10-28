# Governance pin request (WS-2 Save All) — NOT APPLIED, awaiting Financial Owner approval

The Owner authorised the eight `app/` paths for Save All and required an exact path list and minimal diff **before** any protected test, golden or governance pin is changed. Nothing below has been applied.

## 1. Evidence (reproduced locally and in exact-head CI)

* Only these governance tests fail because of this PR (all "unreviewed blob" / exact-source): `tests/test_finval_rate_successor.py`, `tests/test_finval_f01_scope.py`, `tests/test_finval_f01_fixture_integrity.py` (the F01 layers re-check every pinned source), and the `compile-and-safety` bundle-reproducibility step (PPA source changed, committed bundle not rebuilt).
* 31 other failures/errors in the 35 test files touching the refactored code fail **identically on a clean `main` worktree** (shallow-history sandbox) — none is introduced here. 637 pass.
* Green on the latest head: authoritative-history, source-safety, independent-oracle, atomic-batch, dependency-audit.

## 2. Pinned sources this PR changes

| Path | Blob on `main` | Pinned in |
|---|---|---|
| `app/v2/grid_router.py` | `0d1ab6c05b7d4f53f9d4a341818e107969bcccc0` | `tests/model_mutation_security_successor.py` (`BLOBS`, `FINVAL_F01_COMPLETE_SUCCESSORS`), `tests/finval_f01_scope.py`, F01 `scope-blobs.json` + `FINANCIAL_OWNER_SCOPE_MANIFEST.md` (historical) |
| `app/v2/react_workspace_router.py` | `4cb4d0e211fb536bc15a5a0c29a67d5bd2b9fa76` | `tests/model_mutation_security_successor.py` (`RC_UX_SUCCESSORS`), `docs/react_migration/rc_ux_completion/SOURCE_SUCCESSOR.json` |
| `static/react/finco-react.js`, `.css` | `7fdf827d…`, `0966ea1d…` | `tests/model_mutation_security_successor.py` (`RC_UX_SUCCESSORS`) |

Not pinned by any layer (admitted only by the new cohort below): `app/persistence/db.py`, `app/persistence/workspace_repository.py`, `app/v2/capex_commands.py`, `app/v2/cost_batch_commands.py`, `app/v2/save_all_commands.py` (new), `app/workbook/revenue_contracts_service.py`.

## 3. Proposed minimal change (additive; no historical pin is edited or weakened)

1. **New exact-source cohort** `tests/fin_v2_wsv2_scope.py` + manifest `docs/react_migration/wsv2_editing/SOURCE_SUCCESSOR.json`, modelled on `tests/fin_v2_pr394_corr_scope.py`: it owns exactly the eight authorised `app/` paths (blob-pinned), the new Save All test file, the WS-2 frontend files and this document set, with negative controls (one-byte drift, extra `app/` path, deletion, unauthorised route, missing history). Registered by one line in `tests/fin_v2_cohorts.py`.
2. **One additive successor layer** `WSV2_SAVE_ALL_SUCCESSORS` in `tests/model_mutation_security_successor.py` admitting the new blobs of `app/v2/grid_router.py` and `app/v2/react_workspace_router.py` (and the rebuilt bundle blobs) **in addition to** the existing ones. Historical layers stay byte-identical, as `test_finval_rate_successor` already requires.
3. **Cascade re-pins only**, performed by the repository's own tool (`docs/react_migration/rc_ux_completion/handover/tools/refresh_pins.py`): the four `docs/financial_validation/*/SOURCE_SUCCESSOR.json` and the RC-UX manifest re-pin the *changed governance test files* (`tests/model_mutation_security_successor.py`, `tests/fin_v2_cohorts.py`) exactly as PR #396 did.
4. **Bundle**: `static/react/finco-react.{js,css}` rebuilt once through that tool, at integration after WS-1, so it contains both sides.

Files that would change: `tests/fin_v2_wsv2_scope.py` (new), `tests/fin_v2_cohorts.py`, `tests/model_mutation_security_successor.py`, the four `SOURCE_SUCCESSOR.json` manifests above, `docs/react_migration/rc_ux_completion/SOURCE_SUCCESSOR.json`, `docs/react_migration/wsv2_editing/SOURCE_SUCCESSOR.json` (new), `static/react/finco-react.js`, `static/react/finco-react.css`.

Not touched: any financial formula, golden, native gate, Run Integrity rule, F01 historical pin, workflow file.

## 4. Decision requested

Approve the file list in §3 (or amend it). Until then CI on this PR stays red on exactly the checks in §1, and nothing is merged or deployed.

---
## Status update — Owner approval received (2026-10-28, verified HEAD `cb00721`)

Approved: §3 items 1–5, additive only, with the condition that **shared manifests and the final JS/CSS bundle are re-pinned once, after WS-1 (PR #398) merges**, and that the two byte-pinned PPA browser acceptance modules are **not** edited without a separate path-and-diff approval.

Applied now (WS-2-only, no shared blob): `tests/fin_v2_wsv2_scope.py`, `tests/test_fin_v2_wsv2_scope.py`, `docs/react_migration/wsv2_editing/SOURCE_SUCCESSOR.json`, the one-line registration in `tests/fin_v2_cohorts.py`, and the additive `WSV2_SAVE_ALL_SUCCESSORS` layer in `tests/model_mutation_security_successor.py`.

Deferred to the single post-WS-1 integration: the four `docs/financial_validation/*/SOURCE_SUCCESSOR.json` manifests, `docs/react_migration/rc_ux_completion/SOURCE_SUCCESSOR.json`, and `static/react/finco-react.{js,css}`.

Verification already done (throwaway worktree, not committed): running the repository's own `refresh_pins.py --no-build` on this branch changes exactly five files (`tests/model_mutation_security_successor.py` plus the four manifests above — `fin_v2_ci` is unchanged) and then **137 governance tests pass** (new cohort + negative controls, `test_finval_rate_successor`, `test_finval_f01_scope`, `test_finval_f01_fixture_integrity`, RC-UX cohort, PR #394 cohort, composite). Until the integration the composite cohort and the bundle-reproducibility step stay red by design.

Separate approval still requested (not applied): the two pinned PPA browser acceptance modules. Paths: `tests/model_react_wf2_browser_acceptance.py` (pin `a0c509ed…`), `tests/model_react_mvp_acceptance.py` (pin `525dce2c…`). Minimal diff: in the PPA step only, `get_by_label("Contracted volume share").fill("0.8"|"1")` → `fill("80"|"100")` and `get_by_label("Indexation rate").fill("0.02")` → `fill("2")`, the post-save readback `to_have_value("0.02")` → `to_have_value("2")`, the `Source reference` fill becomes optional (moved under Advanced); label text changes to "Contracted volume" / "Annual indexation". No other assertion changes. Re-pinned by the same tool afterwards.
