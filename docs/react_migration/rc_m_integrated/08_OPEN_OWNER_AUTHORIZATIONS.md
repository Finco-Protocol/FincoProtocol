# Open owner authorizations and findings

Nothing below was bypassed. Each item is a recorded dependency, a governance successor that needs independent confirmation, or a
security finding. Nothing here claims an approval. Correction B (Financial Owner's standing authorization for in-scope corrections) is applied where noted; items that
depend on another PR or on a person's review remain open. Blobs are git blob SHA-1; re-verify with `git rev-parse <ref>:<path>`. The exact
head under review and its CI evidence are recorded in `09_EXACT_HEAD_EVIDENCE_AND_FINAL_REVIEW.md`.

## 1. Pinned paths changed under the task statement's presentation/adapter-layer authorization (relayed, not independently verified)

For each path: what changed, the reference blob it replaces, and who must confirm. "Owner authority" is the task statement's scope sentence
(presentation/adapter layer only); it was **relayed to this session, not independently verified**, and it is not an approval of any
protected financial path. None of these paths is a rate-contract, seed, Clone, Save or engine file owned by FIN-VAL F01.

| Path | Reference blob (main `cf7056de`) | Change | Confirmation needed from |
|---|---|---|---|
| `app/v2/react_workspace_router.py` | `db088accc730f3364dad347d1bb523e2463e1bbe` | one additive block importing and including the five adapter modules (no existing line changed) | React-surface owner |
| `frontend/src/app/WorkspaceView.tsx` | `eed73f37765f55ada26fe4bcb937c857d6e92dda` | Financing renders `FinancingStudio`; Analysis wraps the unchanged Last Run view in `AnalysisTools` | React-surface owner |
| `static/react/finco-react.js` / `.css` | `0f85e69fd9b3a398d82d61b95243ccfd46d4b9d2` / `adbc32f079ee5a77cf3bf1228a8b46d76f0245dd` | rebuilt from `frontend/` (a clean baseline build was first verified byte-identical) | React-surface owner |
| `app/v2/react_poc_router.py` | `895e201189882a847b18c24a4f074ec4282e2fd3` (original pin) | **only** `REACT_ASSET_VERSION` is derived from the SHA-256 of the shipped bundle bytes (item 4); a governance test proves that is the entire difference from `main` | React-surface owner |
| `tests/model_mutation_security_successor.py` | `4f5077c22b837e730ea0b2c2a57412eb1150d8a4` | additive `RC_M_SUCCESSORS` layer — now **six** paths (the four above + the asset router + the consolidation role file) | security-governance reviewer |
| `tests/test_model_workspace_consolidation_browser.py` | `6f91b8c9376ba65c27aab34ea39651cef351b2e9` (Overnight B state) | **import-only tail**: one shared fixture import and five star-imports of non-collected acceptance modules; no `def`, no skip | security-governance reviewer + CI owner |
| `tests/test_model_react_overnight_b_governance.py` | `2d381658…` | the strict equality `current == layer blob` is **kept**; it now reads `== RC_M_SUCCESSORS.get(path, blob)` (exactly the latest pinned state, never "either one") | security-governance reviewer |
| `tests/test_model_mutation_security_successor.py` | `9449a0d4…` | FIN-VAL / D-029 membership sets additionally admit the RC-M blob of the same path; the D-029 wrapper test now asserts **strict equality** with the RC-M blob of the role file | security-governance reviewer |
| `tools/ci_v3_production.py` + `docs/model_v2/d029/evidence/D029_CI_V3_OUTCOME_RECONCILIATION.json` | (D-029 reviewed set) | the Trust-scope reviewed set gains exactly one path, `tests/test_trust_readiness_controls.py`, **pinned to its exact blob**; negative tests for a drifted/missing blob and a dropped path | CI/security-governance reviewer |
| `tests/test_native_activation.py`, `tests/test_model_rc7_capex_binding_surfaces.py` | (existing inventories) | one exact entry each: `app/v2/react_analysis.py` (same `activated(run_matrix_points)` submission as the Legacy matrix router) and `app/v2/react_goal_seek.py` (BINDS the CAPEX profile) — each with a proof test | security-governance reviewer |
| `tests/test_trust_readiness_controls.py` | `635b95b5c9ac280153ae5933bc8d0c11fa80b8ec` | the CSRF-inventory test admits the two new CSRF-bound POST modules **only while** `tests/rcm_adapter_csrf_successor.py` holds (exact blob + AST structure, including the fence-then-claim-then-write order) | security-governance reviewer |

`tests/rcm_adapter_csrf_successor.py` is a **review proposal, not an approval**. Every historical pin line is still present (asserted by
`tests/test_rcm_governance.py`), and no path in `financial_engine/`, `finco_core/`, `app/input_adapter.py`, the projects repository,
`project_library_service`, `reference_seed_service`, `update_service`, the model-execution runtime, the D-029 ledger, `app/v2/router.py`,
golden fixtures, `main_web.py` or `.github/` changed (asserted against the merge base).

## 2. CI role for the Chromium acceptance — resolved without any CI governance change

The five Chromium suites are now **non-collected acceptance modules** (`tests/model_react_rcm_*_acceptance.py`, no module-level skip, no
Playwright import) imported at the tail of the **existing mandatory** `consolidation` role file. They therefore run inside that role's
fail-closed inventory / JUnit / screenshot verifier (`tools/ci_browser_job.py`), which is unchanged; `.github/` is untouched. In the plan
environment (no Playwright) the collection-skip counters are identical to `main` (66 and the same list of skipped modules, checked locally by
collecting both trees with Playwright blocked), so the CI-V3 reviewed-reconciliation contract is **not** triggered and no reconciliation
authority is requested. If the CI owner prefers a dedicated role instead, that is a `.github/` + verifier change this task does not authorize.

## 3. Atomic, exactly-once project creation — integrated after F01 (flag still default OFF)

FIN-VAL F01 (#389) is on `main` (`128bf0c2`), so the request-keyed creation prepared against its head is applied (details and proof in `atomic_create/README.md`): the request identity is committed by the
project row's own INSERT under a partial unique index; the project is `COMPLETE` only inside the transaction that writes its seed lines; keyed creates are INSERT-only; an interrupted create past its lease is archived
and its id stays consumed; same id with other inputs → 409; nothing is retried automatically. It runs through the canonical creation authority (no second project writer). The two F01-pinned creation files
(`projects_repository.py`, `project_library_service.py`) are admitted by `tests/finval_f01_scope.py` only as exact alternatives (`ATOMIC_CREATE_SUCCESSORS`). The interim adapter-level ledger is removed.
Remaining limits, stated plainly: the canonical seeded create is still several SQLite writes (now detectable and fenced, not one transaction); the unkeyed Legacy `/projects/create` is not keyed; the demo budget
is a read-then-create check. New Project remains behind `FINCO_MODEL_REACT_V1` (default OFF) and this is not a production authorization.

## 4. Stale-bundle cache — resolved by a content-derived version (nothing deployed)

`/static/` is served `Cache-Control: public, immutable` for 7 days (`deploy/nginx/app.conf`), so the URL is the only cache key. `REACT_ASSET_VERSION` in `app/v2/react_poc_router.py` is now
`rc-sec-mutation-v1-<first 12 hex of SHA-256(finco-react.js + finco-react.css bytes, file-name bound)>`, computed when the process starts. The host page (`no-store`) requests
`finco-react.js?v=<version>` and `finco-react.css?v=<version>`, so a changed bundle gets new URLs on the next page load and an obsolete cached bundle cannot be paired with the new backend
(`tests/test_rcm_asset_version.py`: version equals the hash of the committed bytes; any change to either file, or swapping their bytes, changes it; an unreadable file never collides; both
assets of host and fallback pages carry it; every template reference carries the query; nginx location stays immutable). A clean `npm run build` reproduces the committed bundle byte for byte.
**Operational note:** the version is computed at process start, so a deployment must restart the workers (as any code deploy does); a hot-swap of static files without a restart would keep serving
the old query for new pages.

## 5. Two-Senior facility editor in React — release-closed

Shown read-only with an explicit **NOT RELEASED** notice and a classic-workbook link. A React editor would have to author the proposal and the
digest-bound activation (`BIND_ON_SAVE`) — the highest-risk financing writer. **Request:** a design and authority decision, then acceptance by
Legacy-twin Run comparison. Storage/BESS creation and editing stay release-closed too.

## 6. Security finding — Legacy routes without a resource-bound token (pre-existing; separate from this PR)

* `POST /v2/workbook/goal-seek/apply` (Legacy, `app/v2/router.py`, protected) writes the Working Copy tariff with **session authentication only — no CSRF
  token and no purpose/resource binding**. A cross-site form post that rides the user's cookie could change the tariff (SameSite policy may mitigate; not verified).
* `POST /v2/workbook/goal-seek/run`, `POST /v2/workbook/scenarios/sensitivity/run` and `POST /v2/workbook/sensitivity/matrix/run` spend executor capacity on the
  same session-only basis.

This PR does **not** extend into the protected Legacy router. The React adapters bind their one write to a signed token over session + the exact offered
candidate (project, field, value, Working Copy identity, workbook version) and put the capacity-spending reads behind `X-Finco-React-Request: 1`.
**Request:** an owner decision whether to protect the Legacy routes (a one-line `validate_mutation_token` gate each, with the new operation names added to the
mutation inventory) — a separate, reviewed change.

## 7. F01 (interest-rate unit contract, PR #389) — integrated

`main` `128bf0c2` (F01 merged) was merged into this branch with an ordinary merge commit; the only conflicts were the three pinned-governance files, resolved by keeping BOTH the F01 successor layers and the RC-M layer.
No F01 source was overwritten and no rate conversion is implemented in React or in the adapters. Verified (`tests/test_model_react_rcm_f01_rate_matrix_v1.py`, 22 tests): a wizard-created Working Copy carries `human_percent_v1`;
Wizard → Create → Open → Financing → Save → Reload → Run for Solar, Wind, Data Center and EV Charging at 0.056 % → 0.00056, 0.56 % → 0.0056, 5.60 % → 0.056, 9.00 % → 0.09 (the effective rate reaching the canonical Run is read from F01's
`senior_rate_authority`); an honest model refusal is typed and leaves no history row; the Sensitivity strip/matrix (including the interest-rate driver, which moves the effective rate vector — preserved unchanged) and Goal Seek previews write
no Run, history or Working Copy change. Ambiguous historical copies stay fail-closed (F01's own suites pass on the integrated tree). D-029 (Run intent) is untouched.

## 8. Missing audit inputs

The two audit archives and `04_DETAILED_FUNCTIONAL_GAP_REGISTER.csv` were not available, so no previous baseline is promoted and GAP-R14…R28 not named in the task
text are marked BLOCKED in the register. No statement of "all gaps", a percentage, complete Legacy parity or production authorization is made anywhere in this set.

## 9. CI V3 hosted cold-start readiness (Correction D) — open, CI-owner decision only if it recurs

Two of five workers on head `9ac495c8` (run 40522709690) refused at the unchanged 0.600 s maximum-of-three cold-start gate (0.802 s / 0.704 s; exit 124, pytest never started). The probe's inputs are byte-identical to `main`; across 60 hosted worker starts on 12 heads the first-sample median is 0.318 s
and only these two exceed 0.6 s (`PR388_CALIBRATION_EVIDENCE.md`). This PR changes nothing in the gate and certifies nothing. **If a later wave on this PR refuses again, a separately reviewed CI performance-contract proposal is needed** (e.g. measure after the image load completes, or define the contract on a
percentile with a bounded retry that retains every raw sample). That is a CI-owner change; it is not requested here and not done here.

## 10. SQLite migration order — closed

The create-request unique index is created after the columns it reads; duplicate pre-existing identities fail closed with a diagnostic and are never recorded as migrated (`atomic_create/README.md`, `PR388_CORRECTION_D_ROOT_CAUSE.md`). Hosted worker-0 evidence on `9ac495c8`.

## 11. CI V3 calibration contract v2 (Correction F) — proposal under review

`docs/ci_v3/phase4/CALIBRATION_CONTRACT_V2.md`: threshold and statistic unchanged and applied to steady-state samples; a separate 1.8 s first-start ceiling; raw samples retained; verdict recomputed by the aggregate; negative tests prove slower start-up and forged receipts still fail.
Authorized by the Financial Owner's standing authorization for in-scope corrections; **not independently reviewed**. If the reviewer prefers the legacy rule, reverting `STEADY_STATE_CONTRACT` in `tools/ci_v3_production.py` restores it (the legacy contract remains approved in `tools/ci_v3_calibrate.py`).
