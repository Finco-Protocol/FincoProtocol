# Open owner authorizations and findings

Nothing below was bypassed. Each item is a recorded dependency, a governance successor that needs independent confirmation, or a
security finding. Nothing here claims an approval. Blobs are git blob SHA-1; re-verify with `git rev-parse <ref>:<path>`. The exact
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
| `tests/model_mutation_security_successor.py` | `4f5077c22b837e730ea0b2c2a57412eb1150d8a4` | additive `RC_M_SUCCESSORS` layer — now **five** paths (the four above + the consolidation role file) | security-governance reviewer |
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

## 3. Atomic, exactly-once project creation — owner-gated; adapter-level fence in place

**What this PR does.** The React create is fenced across server processes by a durable claim ledger (`app/v2/react_request_claims.py`, a
table created lazily by that new module, one atomic `INSERT OR IGNORE` on `(user_id, request_id, purpose)`) decided *before* the canonical
creator runs. Proven with separate OS processes (`tests/test_model_react_rcm_new_project_multiprocess_v1.py`): simultaneous same-id POSTs
create one project; a process that dies after the write and before finishing the claim leaves the claim `CLAIMED` and every later request
reports an unknown outcome (503) and creates nothing; replay after a lost response returns the same project; users are isolated; the demo
budget holds across workers. A claim is never reclaimed, overwritten, expired or retried automatically.

**What it cannot do (so New Project is NOT labelled production-ready).**
* The project rows and the claim are two writes in one SQLite file, not one transaction. A crash in between orphans a project (visible in the
  Library) and the request id is then permanently "unknown" — safe against duplicates, not exactly-once.
* The canonical seeded creation itself is several writes (`create_working_copy`, then `update_project_record` with the seeded snapshot, …); a
  crash inside it can leave a partially seeded working copy. That is pre-existing and also affects Legacy `/projects/create`, which is not fenced.
* The in-process demo limiter counts per process; the durable budget above covers only the React create.

**Exact minimal owner-gated patch request** (paths owned by the creation authority; **not** applied here):

| Path | Reference blob (`HEAD`) | Change |
|---|---|---|
| `app/persistence/db.py` | `0d7bbb67f5ea6524f8a902d555b1e715ade8da0a` | `_ensure_column(conn, "projects", "create_request_id", "TEXT")` and `CREATE UNIQUE INDEX IF NOT EXISTS projects_user_create_request_uq ON projects(user_id, create_request_id) WHERE create_request_id IS NOT NULL` |
| `app/persistence/projects_repository.py` | `1fe389fe6bb2abf5eb0edb01fb3026924e77a243` | the project-row insert accepts an optional `create_request_id`; a unique-index conflict returns the existing record instead of inserting |
| `app/services/project_library_service.py` | `b93c23b427c1d24d3a3ea3e65a4e42128dba06c0` | `create_working_copy(..., create_request_id=None)` forwards it and performs the row, workspace state and base-case scenario in the same transaction as the insert |
| `app/services/reference_seed_service.py` | `9f8dbe73093fc02831873a9a06d08641119ba821` | `create_reference_seeded_project(..., create_request_id=None)` applies the seeded snapshot **inside the same transaction** as the project row; **F01 owns this file** — this request needs the F01 owner's exact-path authorization and must follow the F01 merge |

Once merged, the adapter passes `request_id` to the writer and the ledger becomes redundant; until then this item stays open. Required owner
decisions: (a) approval of those four exact paths and the F01 owner's sequencing, (b) whether Legacy `/projects/create` receives the same key.

## 4. Stale-bundle cache prerequisite (deployment)

`REACT_ASSET_VERSION = "rc-sec-mutation-v1"` in `app/v2/react_poc_router.py` (protected) is the bundle cache-buster and nginx serves the assets as immutable.
The bundle changed in this PR, so a version bump is a **deployment prerequisite**: without it clients can keep running the previous bundle against the new
adapters. Not changed here; nothing was deployed.

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

## 7. F01 (interest-rate contract) — separate gate

No F01 change is integrated here. Interest-rate defaults, seed/clone rate persistence and any **rate-dependent parity** are not claimed. The wizard shows no rate
and the bankability editor edits only what the canonical contract already carries. D-029 (Run intent) is likewise untouched and separately gated.

## 8. Missing audit inputs

The two audit archives and `04_DETAILED_FUNCTIONAL_GAP_REGISTER.csv` were not available, so no previous baseline is promoted and GAP-R14…R28 not named in the task
text are marked BLOCKED in the register. No statement of "all gaps", a percentage, complete Legacy parity or production authorization is made anywhere in this set.
