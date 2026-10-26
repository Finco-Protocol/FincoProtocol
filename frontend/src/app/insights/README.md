# WF-REACT-3 isolated analytical components

These components are **not connected to the served React workspace**. Forward integration with PR #378 owns that connection. There is no alternate navigation or application shell here, and no generated asset change.

`FinancialInsights({ project })` is the optional read-only data container. It fetches history from `/v2/model-react/insights/history?project=…`, requires explicit one-to-three Run selection, then reads `/v2/model-react/insights?project=…&run=…`. Fetches use GET, same-origin credentials, no-store caching, abortable requests, and fail closed on redirects. Local selection never selects the workspace scenario or performs Save/Run.

`FinancialInsightsView({ history, payload, selected, onSelection, onRead, busy?, error? })` is the controlled surface for integration and an isolated browser acceptance harness. Types come from `types.ts`. Project/Run selection and metric binding must match before evidence renders. Reusable components are exported from `index.ts`.

All finance values, interpretation, flags and comparison deltas come from approved server projections. Monetary formatting reuses the shared exact-decimal numeric formatter at two display decimals. Ratio and percentage display retains canonical server precision. SVG arithmetic positions persisted numeric values only, includes zero/negative values, and breaks at missing intervals. Every timeline also has a keyboard-accessible full data table. Annual presentation, unsupported PLCR and absent evidence remain unavailable.

Sponsor schedule tables select only explicit kEUR fields and never aggregate them. Project, Pure Equity and Total Sponsor returns remain separate. Evidence disclosures preserve actual immutable scenario/history/snapshot/composite/engine/workbook identity and local canonical statement/history links.

Validation (from repository root):

```sh
npm --prefix frontend run typecheck
node frontend/src/app/insights/__tests__/insights.test.mjs
```

The focused Node suite bundles only into a temporary directory, renders components against explicitly test-only fixtures, and removes its output. It does not write shipped static assets or alter the authoritative pytest collection inventory. Financial/browser acceptance should additionally use actual API payloads from persisted Solar and Wind Runs in an isolated environment.
