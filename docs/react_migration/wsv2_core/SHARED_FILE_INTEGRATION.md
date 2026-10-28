# Shared file integration ledger

| Path | Owner | Plan |
|---|---|---|
| frontend/src/app/WorkspaceView.tsx | WS1 | Sidebar, Overview mount, immutable Run refetch, optional WS2 extension slots |
| frontend/src/app/WorkspaceNav.tsx | WS1 | Existing compatibility navigation retained; new sidebar module composes released destinations |
| frontend/src/app/InputsGuide.tsx | WS1 | Layout labels only; writer semantics unchanged |
| frontend/src/app/workflow/WorkflowBar.tsx | WS1 | Pass confirmed Run identity to async refetch callback; no run/API authority changes |
| frontend/src/app/FinancialResults.tsx | WS1 | Export presentation-only selectors/chart for Overview; no finance calculation |
| frontend/src/app/newProject/NewProjectWizard.tsx | WS1 | Three-step flow; honest Blank constraint; existing creator retained |
| frontend/src/styles/wsv2-core.css | WS1 | New scoped responsive layout |
| static/react/finco-react.js and .css | WS1 generated | Build after all source changes; exact byte receipt |
| frontend/src/app/api.ts | no WS1 edits | Existing D-029/Save contracts stay authoritative |
| app/v2/router.py and react_workspace_router.py | no WS1 edits | Protected/read-only; no mount or writer changes |
| financial grids / PPA / pending-save modules | WS2 | No WS1 implementation changes |
| governance pin files/tests | Owner gate | Concrete additive successor proposal only; no weakening or replacement |

WS2 partner acknowledgement pending; no integration patch received. WS1 merges first only after separate Owner authorization. No self merge/deployment.

Predeclared additional essential API edit: WS1 owns the minimal `api.ts` error-code passthrough (`errorCode?: string` in failed RunModelResult, populated only from the existing typed outcome). No URL, request, CSRF, CAS, replay/UNKNOWN, identity verification or writer behavior changes. WS2 must keep this field when integrating; no concurrent partner branch exists at this preflight.

Display-precision addendum: WS1 additionally owns `frontend/src/app/units.ts` (display-only quantity metadata), `reportFormatting.ts`, `ReportPrecision.tsx`, App provider, StatementWorkbook and read-only financing/insights/comparison views. WS2 editing/** and PPAEditorView remain untouched. No formatter result can enter a Save payload. The existing exact-decimal unit formatter is reused; no second financial calculation authority is added.
