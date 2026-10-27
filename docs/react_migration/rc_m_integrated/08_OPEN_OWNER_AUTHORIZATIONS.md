# Open owner authorizations and findings

Nothing below was bypassed; each item is either a recorded dependency, a governance successor that needs independent confirmation, or a
security finding. Blobs are git blob SHA-1 at the PR head recorded in `09_…`; re-verify with `git rev-parse <ref>:<path>`.

## 1. Pinned paths changed under the task statement's presentation/adapter-layer authorization (relayed, not independently verified)

| Path | Blob on main | Blob in this PR | Change | Risk / effect |
|---|---|---|---|---|
| `app/v2/react_workspace_router.py` | `db088accc730f3364dad347d1bb523e2463e1bbe` | see `09` | one additive block that imports and includes five new adapter modules (no existing line changed) | none to existing routes; new routes are GET reads plus the two CSRF-bound POSTs |
| `frontend/src/app/WorkspaceView.tsx` | `eed73f37765f55ada26fe4bcb937c857d6e92dda` | see `09` | Financing section renders `FinancingStudio`; Analysis section wraps the unchanged Last Run view in `AnalysisTools` | presentation only |
| `static/react/finco-react.js` / `.css` | `0f85e69fd9b3a398d82d61b95243ccfd46d4b9d2` / `adbc32f079ee5a77cf3bf1228a8b46d76f0245dd` | see `09` | rebuilt from `frontend/` (`npm ci` + `npm run build`; a clean baseline build was first verified byte-identical) | bundle replaced |
| `tests/model_mutation_security_successor.py` | `4f5077c22b837e730ea0b2c2a57412eb1150d8a4` | see `09` | additive `RC_M_SUCCESSORS` layer (four pinned paths) | every earlier layer stays immutable and individually admitted (tested) |
| `tests/test_model_react_overnight_b_governance.py`, `tests/test_model_mutation_security_successor.py` | `2d381658…`, `9449a0d4…` | see `09` | assertions "current source is this layer's blob" widened to "…or the later RC-M successor" | governance tests edited (additive membership only) — **needs reviewer confirmation** |
| `tests/test_trust_readiness_controls.py` | `635b95b5c9ac280153ae5933bc8d0c11fa80b8ec` | see `09` | CSRF-inventory test admits the two new CSRF-bound POST modules only while `tests/rcm_adapter_csrf_successor.py` holds (exact blob + AST structure) | the successor is a **review proposal, not an approval** |

No path in `financial_engine/`, `finco_core/`, `app/input_adapter.py`, the projects repository, `project_library_service`, `update_service`, the model-execution
runtime, the D-029 ledger, `app/v2/router.py`, golden fixtures or `.github/` changed (`tests/test_rcm_governance.py` asserts this against the merge base).

## 2. CI role for the new Chromium acceptance files — decision needed

The CI browser roles are fixed in `.github/workflows/protocol_ui_browser.yml` (`protocol import grid q4 outputs consolidation`). The new files
(`tests/test_model_react_rcm_*_browser.py`) run in the **public pytest job only if Playwright/Chromium are present there**; they are not in a
mandatory browser role. Adding a role changes CI governance, which this task does not authorize. **Request:** add a role (or fold the files into
`consolidation`) with the execution-inventory verifier updated.

## 3. Atomic idempotent project creation

The Create idempotency stamp is a second canonical write after the project exists (see `03_…`). A crash between the two leaves an unstamped project that
the UI reports as *unknown*, never *not created*. A fully atomic create needs `request_id` support in `create_working_copy` / `create_reference_seeded_project`
(protected: `app/services/project_library_service.py`, `app/persistence/projects_repository.py`). **Request:** exact-path approval and a minimal diff plan
(add an optional `request_id` column or replay-metadata key written inside the same transaction as the project row).

## 4. Stale-bundle cache prerequisite

`REACT_ASSET_VERSION = "rc-sec-mutation-v1"` in `app/v2/react_poc_router.py` (protected) is the bundle cache-buster, and nginx serves the assets as immutable. The bundle changed, so a
version bump is a **deployment prerequisite** or users may keep the old bundle. Not changed here.

## 5. Two-Senior facility editor in React

Shown read-only with an explicit **NOT RELEASED** notice and a classic-workbook link. A React editor would have to author the proposal and the digest-bound activation
(`BIND_ON_SAVE`) — the highest-risk financing writer — and needs a design and authority review. **Request:** decision on whether to build it, and the acceptance (Legacy-twin Run comparison).

## 6. Security finding (pre-existing, not introduced here)

`POST /v2/workbook/goal-seek/apply` (Legacy) writes the Working Copy tariff with session authentication only — no CSRF token — and `POST /v2/workbook/scenarios/sensitivity/run`,
`/v2/workbook/goal-seek/run` and `/v2/workbook/sensitivity/matrix/run` spend executor capacity the same way. The React adapters bind the one write to a signed, project-bound
token and put the CPU-spending reads behind a header a cross-site page cannot send. **Request:** decide whether to protect the Legacy routes (they are pinned/protected). Cookie `SameSite`
policy may mitigate cross-site POSTs; that was not verified here.

## 7. F01 (interest-rate contract)

No F01 PR exists on the remote. Interest-rate defaults, project seed/clone rate persistence and rate-dependent parity cannot be finalized until it merges. The wizard shows no rate and the bankability editor
only edits what the canonical contract already carries.

## 8. Missing audit inputs

The two audit archives and `04_DETAILED_FUNCTIONAL_GAP_REGISTER.csv` were not available, so the previous "27/43" baseline is **not** promoted, and GAP-R14…R28 not named in the task text are marked BLOCKED in the register.
