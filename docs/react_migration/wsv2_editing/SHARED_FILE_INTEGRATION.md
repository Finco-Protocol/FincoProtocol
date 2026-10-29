# Shared-file integration ledger (WS-2)

| File | Touch in this PR | Owner / order |
|---|---|---|
| `frontend/src/app/WorkspaceView.tsx` | **none** | WS-1. After WS-1 merges, a 3-line patch (below) mounts the provider/drawer and swaps the CAPEX/OPEX view. |
| `frontend/src/app/api.ts` | **none** | WS-1/shared. WS-2 reuses `saveCostLinesBatch`/`fetchCostLines` unchanged; Save All will need its own adapter module once the endpoint exists. |
| `frontend/src/app/ux040506Views.tsx` | **none** (a re-export was tried and reverted: the pinned test `test_a_jump_request_older_than_the_mount_is_never_replayed` greps this file) | WS-1 |
| `app/v2/router.py`, `app/v2/react_workspace_router.py`, `app/v2/grid_router.py` | **none** | Owner-gated, see `PROTECTED_PATH_REQUEST_SAVE_ALL.md` |
| `frontend/src/app/workflow/PPAEditorView.tsx` | percent inputs, Advanced disclosure | WS-2 (editor file) |
| `frontend/src/app/workflow/workflowShared.tsx` | **none**; the existing `DirtyProvider` stays the leave-guard authority and `CostLinesGridView` keeps reporting into it | WS-1/shared |

## Integration patch for WS-1's shell (apply once, after WS-1 is merged)

```diff
- import { CostLinesView, DiagnosticsView, RunsView, TrustView } from "./ux040506Views";
+ import { DiagnosticsView, RunsView, TrustView } from "./ux040506Views";
+ import { CostLinesGridView as CostLinesView } from "./editing/CostLinesGridView";
+ import { ChangesProvider } from "./editing/ChangesProvider";
+ import { ChangesDrawer } from "./editing/ChangesDrawer";
  // wrap the section area in <ChangesProvider identity={editIdentity}> and place <ChangesDrawer capability={workspace.save_all} /> in the shell toolbar
```

`editIdentity` is built from `workspace.workbook.{version,composite_hash}`, the active scenario and `workspace.identity?.snapshot_id` (contract file). The removed `CostLinesView` body in `ux040506Views.tsx` must also drop its now-unused imports and keep the `useRef(requestNonce)` marker, or the pinned source test must be re-pinned by the Owner-authorised governance owner.
