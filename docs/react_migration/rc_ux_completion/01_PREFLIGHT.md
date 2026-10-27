# RC-UX Completion V1 — live preflight (2026-10-27)

All values below were read from GitHub / the checked-out tree in this session, not copied from the handover.

## 1. main and #388
* `origin/main` HEAD = `f79e251903621c1a5c88501d51d6971960b612d3` ("Merge pull request #388 …").
* `git merge-base --is-ancestor f79e2519… origin/main` → true. The handover SHA equals the live main HEAD; GitHub had not advanced.
* Branch `integration/rc-ux-completion-v1` created from that commit. Source HEAD before any RC-UX change: `f79e251`.

## 2. Existing React workspace (verified in tree)
* `frontend/src/app/**` (9.6k lines): sections Inputs, Statements, Financing, Results, Scenarios, Analysis, Model checks, Trust (`WorkspaceNav.tsx`).
* #388 modules: `newProject/`, `analysis/` (Sensitivity, Goal Seek), `financing/` (Financing Studio, Investors).
* Adapters: `app/v2/react_*.py` mounted from `app/v2/react_workspace_router.py`; flag `FINCO_MODEL_REACT_V1` (default OFF).
* Build: `npm ci && npm run build` succeeds on main (102 modules). Bundle is committed under `static/react/` and version-hashed
  (`REACT_ASSET_VERSION`), so any frontend change requires rebuilding and committing the bundle.

## 3. Original audits — NOT AVAILABLE
* `FINCO_Legacy_React_Audit_2026-10-27.zip`, `04_DETAILED_FUNCTIONAL_GAP_REGISTER.csv` and the Audit B acceptance document are **not in the
  repository, not on the session filesystem and not retrievable through the GitHub tools** (searched file names and content for
  `Legacy_React_Audit`, `GAP-R14…R28`, `DETAILED_FUNCTIONAL_GAP`). The only trace is the RC-M register, which already records GAP-R14…R28 as BLOCKED.
* Consequence: GAP-R14…R28 and every Audit B P0/P1/P2 item remain **BLOCKED** in `RC_UX_MASTER_GAP_REGISTER.csv`. Nothing was reconstructed.
  **Required from the owner:** the two audit artifacts. Closure of "every audit gap" (Definition of Done §1) is impossible until they are supplied.
* Work proceeds on independently verifiable requirements from the RC-UX prompt (rows `RCUX-*`).

## 4. Feature flags / capability registry
* `FINCO_MODEL_REACT_V1` gates all `/v2/model-react/*` adapters. Vertical tiers: Solar, Wind = PILOT_CANDIDATE; Data Center, EV Charging = PREVIEW;
  Storage = RELEASE_CLOSED (`react_workspace_router._PILOT_TIER`). Two-Senior editing and Storage editing are release-closed.

## 5. FIN-V2 branches (parallel workstream)
| PR | Head | State | CI at check time |
|---|---|---|---|
| #391 FIN-V2-3 Integrated SHL, Sponsor Returns, Valuation, Goal Seek, Reporting | `482cc215` | open, draft | safety-and-smoke workers 1,2 failed; 0,3,4 in progress; browser, oracle, rate-contract green |
| #392 FIN-V2-D01+D02 Financial sensitivity truth | `f951174b` | open, draft | not inspected |
| #393 FIN-V2-R1 Reserve authority / forward coverage | `fbfcb017` | open, draft, based on `1f25903e` | not inspected |

None is merged → the Financing/Sponsor/Valuation/Reserve **binding** (C1 and the FIN-V2 parts of C2) is a recorded dependency (see `03_FINANCIAL_DEPENDENCY_MAP.md`).

## 6. Expected overlapping files with FIN-V2
#391 changes 74 files (financial_engine/, finco_core/inputs, app/services, app/export, app/workbook, app/api, app/input_adapter.py, app/v2/router.py, docs/financial_validation).
Only three can overlap RC-UX work: `tests/model_mutation_security_successor.py`, `tests/test_rcm_governance.py`, `app/v2/router.py`.
RC-UX therefore **never touches** `app/v2/router.py` and adds governance successors only as new, separate additive layers.

## 7. Protected rules honoured
No edits to `financial_engine/`, `finco_core/`, `app/api/project_runner.py`, `app/input_adapter.py`, policy modules. New code = React presentation + new `app/v2/react_*` adapters.

## 8. Governance defect found at preflight (fixed, narrowly)
`tests/test_rcm_governance.py::test_the_asset_router_differs_from_main_only_by_the_content_derived_cache_buster` compared `react_poc_router.py`
against the **merge-base with origin/main**. With #388 merged, the merge-base of any later branch already contains the content-derived
`REACT_ASSET_VERSION`, so the test fails on an unchanged tree (reproduced on `f79e251`). Fix: compare against the pinned pre-#388 reference commit
`cf7056de4078ca66afcf52265a9bacafe35586f7` (the baseline named in `08_OPEN_OWNER_AUTHORIZATIONS.md` item 1). The assertion body is unchanged; the pin is exact, not a
blanket allowance. This file is also touched by #391 → expected additive merge conflict at FIN-V2 sync.
