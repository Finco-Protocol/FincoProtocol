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

## 3. Atomic, exactly-once project creation — prepared and tested; applied after #389 merges (release gate closed)

**Live in this PR (interim).** The React create is fenced across server processes by a durable claim ledger (`app/v2/react_request_claims.py`, table created lazily by that new
module, one atomic `INSERT OR IGNORE` on `(user_id, request_id, purpose)` decided *before* the canonical creator runs). Proven with separate OS processes
(`tests/test_model_react_rcm_new_project_multiprocess_v1.py`). It is **not exactly-once**: the project rows and the claim are two writes, a crash between them orphans a project and the id
stays "unknown", and the canonical seeded creation itself is several writes (also true of Legacy `/projects/create`, which is unkeyed). **New Project is therefore not production-ready**
and the flag `FINCO_MODEL_REACT_V1` stays default OFF.

**Prepared, not applied (`atomic_create/`).** The durable, transactional guarantee is implemented *through the canonical creation authority* (no second project writer): the request identity is
committed by the same single INSERT as the project row under a partial unique index; the project is `COMPLETE` only inside the transaction that writes its seed lines; keyed creates are
INSERT-only (the pre-existing upsert in `save_project` let two concurrent same-name creates overwrite each other); an interrupted create past its lease is archived and its id stays
consumed. It is tested single-process with a crash injected at every step, with three real server processes (`os._exit` after the row, inside the seed transaction and after completion),
with mutation checks, and on the **#389 head** (patch applies cleanly; RC-M merged onto it conflicts only in the three pinned-governance files; F01's own suites still pass). It is held back
because `projects_repository.py` and `project_library_service.py` are changed by #389 and pinned by blob in `tests/finval_f01_scope.py`; applying now would race that branch. The post-merge
steps (merge main, `git apply`, admit the two new blobs as exact alternatives in the F01 scope pin, re-pin the adapter, re-run the F01/rate-unit acceptance) are in `atomic_create/README.md`.
`tests/test_rcm_atomic_create_patch.py` keeps the preparation from rotting. **The release gate stays closed until the patch is applied and its tests pass on the merged tree.**

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

## 7. F01 (interest-rate unit contract, PR #389) — separate gate; **not integrated**

#389 is an open Draft (head `d53400a634bbaed8013c545dfa74b35991b9f436`, not merged) and owns `human_percent_v1` and its persistence. RC-M does **not** reimplement it: no rate default, no
unit conversion and no schedule override exists in the React code, and no rate-dependent parity (Sensitivity or Goal Seek against a rate-bearing financing authority, 0.056 % / 0.56 % /
5.60 % / 9.00 % Wizard → Financing → Save → Reload → Run) is claimed. A trial merge of the RC-M branch onto the #389 head conflicts only in three pinned-governance files (see
`atomic_create/README.md`); the React sources auto-merge. After #389 merges: synchronize with the verified new `main`, preserve all React changes, adopt `human_percent_v1`, run the four-rate matrix
through the wizard-created Working Copy, then revalidate Sensitivity and Goal Seek. D-029 (Run intent) is likewise untouched and separately gated.

## 8. Missing audit inputs

The two audit archives and `04_DETAILED_FUNCTIONAL_GAP_REGISTER.csv` were not available, so no previous baseline is promoted and GAP-R14…R28 not named in the task
text are marked BLOCKED in the register. No statement of "all gaps", a percentage, complete Legacy parity or production authorization is made anywhere in this set.
