# WSV2 interface contract (WS-2 side) — to be agreed with WS-1

Status: **proposed by WS-2, no WS-1 PR existed at P00**. Nothing here is a second source of truth: the canonical workbook state remains the server projection the shell already fetches.

## Ownership

| Area | Owner |
|---|---|
| `WorkspaceView.tsx`, navigation/sidebar, global layout/CSS, Overview/Results, Run UX and post-Run refresh | WS-1 (GPT-6) |
| `frontend/src/app/editing/**`, `styles/ws2-editing.css`, CAPEX/OPEX grid, `PPAEditorView.tsx`, Save All client | WS-2 |
| `api.ts`, `app/v2/router.py`, `app/v2/react_workspace_router.py` | shared-risk, see `SHARED_FILE_INTEGRATION.md` |

## Read-only canonical identity the shell passes to WS-2

```ts
interface EditIdentity {            // frontend/src/app/editing/pendingEdits.ts
  projectId: string;                // project code
  workbookVersion: string;          // workspace.workbook.version
  contentHash: string;              // workspace.workbook.composite_hash (the CAS token)
  activeScenario: string | null;    // active scenario id, null = Base case
  lastRunSnapshotId: string | null; // workspace.identity?.snapshot_id
}
```

## Exports WS-1 mounts (no other coupling)

```ts
<ChangesProvider identity={EditIdentity | null}>   // once, around the section editors
<ChangesDrawer capability={SaveAllCapability|null} onSaveAll={() => void} saving={boolean} />   // any slot in the shell
useChanges(): { total, bySection, blocking, discardAll, rebase(identity, baselines), committed(ids, identity), ... }
CostLinesGridView  // drop-in for CostLinesView (same props)
```

* **Pending count / badge:** `useChanges().total` and `bySection`. The drawer renders its own badge.
* **Draft preservation:** drafts live in the provider, so they survive switching Inputs/PPA/CAPEX/OPEX/Financing. They are in memory only; `beforeunload` warns while any exist. There is no silent storage restore.
* **Refetch:** after any committed change the shell re-reads the projection and calls `rebase(identity, baselines)`. A baseline that moved becomes a *conflict marker*, never a silent rebase. A different project/scenario marks every draft `SCOPE_CHANGED`.
* **After a Run** the shell does not need to touch drafts; a Run does not change the working copy.
* **Save != Run:** nothing in WS-2 calls the Run route. A saved financially relevant change leaves the Last Run `STALE` through the existing canonical freshness authority.

## Save All wire contract (proposed, server side gated)

`SaveAllCapability = { available, url?, csrf_token?, sections?, reason? }` is published by the server inside the workspace projection. While `available !== true` the client shows **BLOCKED** and never loops over per-section writers. Request: `SaveAllRequest` in `editing/saveAll.ts` (single `content_hash` + `workbook_version` + `scenario_id`, one operation-bound CSRF token, a client `request_id` for idempotent replay, `cells`, `contracts_json`, `cost_lines`).

## Events

Save != Run · stale Last Run after changed inputs · second tab (CAS conflict → drafts kept, marked) · wrong project/owner (server 404/403, drafts untouched) · failed Save restores nothing and discards nothing.
