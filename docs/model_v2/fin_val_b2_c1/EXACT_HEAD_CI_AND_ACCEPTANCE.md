# Exact-head CI and acceptance

Status: **BLOCKED — EXACT-PATH FINANCIAL OWNER AUTHORIZATION REQUIRED** and **BLOCKED — MATERIAL ATOMICITY FINDING** (for a full-R-1-closure claim). No merge, no deploy, no activation.

## Identity
* main `8944aca351ef89c81a8a9bf715ab352629c35624` (tree `3448aeb245ff118fde0907541dfe40ace42a86d8`) — unchanged since the PR was opened.
* PR #383 head at the time of the audit: `8422adbeca843ada3fb6f476ce06b1ef7b519e99` (tree `81bac6a0acf33e6dd6e8a9c7098619ed1ead6ca5`); merge-base = main; 1 ahead / 0 behind; Draft; no reviews, no review threads.

## Exact-head CI at `8422adbe` (run 40339048467 and siblings)
| Workflow / job | Result |
|---|---|
| Q4 Focused (`q4-canonical-financial`), atomic-batch, PR Compile and Safety (`compile-and-safety`, bundle identity), Governance Full History (`authoritative-history`), Dependency Security Audit, `source-safety`, `route` | success |
| Public Safety and Model Smoke `plan` | **failure** — see below |
| `worker-*` | skipped (downstream of plan); `aggregate`, `tests`, `mandatory-evidence` | failure (downstream of plan only; **not** independent evidence of a regression) |
| Protocol UI Browser Acceptance (`mandatory-browser-evidence`) | still running at the last observation; result not inferred |

### Plan failure — genuine, caused by this PR
`tools.ci_v3_schema.ContractError: original nodes removed; reviewed reconciliation authority required: ['tests/test_fin_val_b1_capex_save_integrity.py::test_residual_capacity_overflow_never_yields_a_plausible_value']`.
Cause: the PR renamed that original B1 test. Local reproduction (full `pytest --collect-only tests`, pristine main vs branch): 20,379 original nodes, 20,449 on the branch (+71 added); the **only** original node missing is exactly that one. `tools.ci_v3_production plan` itself needs the Docker runtime image build and an authenticated `GH_TOKEN` baseline and was not run locally.
Required correction (**protected path, not applied**): restore the exact node name; patch kept at `docs/model_v2/fin_val_b2_c1/PROPOSED_B1_NODE_RESTORE.patch`.

## Local results (focused, non-skipped)
* `tests/test_fin_val_b2_c1_recovery_finite_opex.py` — 70 tests pass (68 + 2 added for the gate stand-down below).
* `tests/test_fin_val_b1_capex_save_integrity.py` — 77 pass at the pushed head.
* RC-7B family (`production_acceptance`, `run_workspace`, `axis_production`, `funding_statements`) — all pass after the fix below.
* Regression shards: 333 + 200 pass (before the B1 fixes listed above); full non-browser sweep (4 shards, 15,000+ tests) classified against pristine main:
  * identical failures on main and branch (environmental / history-depth): 9 failed + 20 errors in the CI-V3 tooling tests (Docker/GitHub-token dependent), 6 historical CSRF-successor/known-gap tests (`rc_sec`, `rc7b_quarterly`, `wf09`, `trust_readiness`), 4 Chromium render tests (`rc6_opex_profiles_ui`, `credit_decision_v4_render`);
  * **new on the branch**: the two SEC-02 successor tests (unreviewed blobs — governance item) and four `test_rc7b_quarterly_production_acceptance` tests (a regression of this PR, fixed — next section).

## New defect found by this audit and fixed (unprotected file)
My Working Copy recovery gate (`diagnose_draft`) also fired for the **typed RC-7B 3/3-selection refusal** (`QUARTERLY_*`), which the pages already render in place ("Invalid saved 3/3 selection") and the Run refuses. That replaced a handled page with the recovery page (4 failing tests). Fix: `app/workbook/draft_recovery.py` stands down for `QUARTERLY_*` typed refusals; two additive tests cover both directions. Not a protected path.

## SEC-02 successor — owner-gated (not applied)
Two tests fail only because six pinned blobs changed:
| Path | main blob | current blob |
|---|---|---|
| `app/v2/router.py` | `cbff734453400269589d9fcc5cec702cbc239b55` | `f92bdd593406ab1c04d343af75fba86d80055414` |
| `app/v2/react_workspace_router.py` | `84a41c2e95975a4ab77e31da8b4428651bbfd462` | `aee8e13815cc02f3e7ae43c57925aa6679515719` |
| `app/templates/v2/partials/sheet_opex.html` | `8a84abaa862abbd9400cec2ce1813297fab69f0b` | `3220115c7565420b03694def6a8d8ad3a0ec042e` |
| `frontend/src/app/WorkspaceView.tsx` | `19614dd386d76b3bf4edbe929c8e045bfe41bd2c` | `5e14876224a9444151aa57b243291dbb98b2891e` |
| `frontend/src/app/types.ts` | `57af23a933828889583765243e347b9739875b48` | `d5077405dd2c316fe3ee006250287d11835382f4` |
| `static/react/finco-react.js` | `c5a8a5ed17326a4ec275ba9e4f573bd47f630486` | `4b74bb50f43c665136e8fcac11e0a9beead08f8b` |

## Browser / bundle
Live-server Chromium check of both recovery surfaces (desktop and 390 px): passed. `npm run typecheck` and `npm run build` pass; the copied bundle equals the committed bundle (`git diff --exit-code -- static/react` clean, CI `compile-and-safety` green).

## Not yet done (gated)
Fresh exact-head full CI after the corrections, the Protocol UI Browser role matrix result, and the SEC-02 successor tests green: all depend on the approvals requested in `SECURITY_GOVERNANCE_AND_D029_CONFLICT_MATRIX.md` and below.
