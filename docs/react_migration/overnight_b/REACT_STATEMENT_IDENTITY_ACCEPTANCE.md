# F02 — authoritative statement identity: root cause, fix, acceptance

## Reproduced (real Chromium, before the fix)

Disposable Working Copies of every vertical, opened directly at `/v2/model-react/{code}#statements` with no query:

| Vertical | Statement header (before) | Outer workspace (correct) |
|---|---|---|
| Solar | `PRJ-0241 · FINANCIAL STATEMENTS` / `FINCO Model project · Solar PV` | `Probe solar (Solar)` |
| Wind | `PRJ-0241 …` / `FINCO Model project · Solar PV` | `Probe wind (Wind)` |
| Data Center, EV Charging | header was correct in the same probe run, but only because the URL had already been rewritten before the statement first rendered (order-dependent) | correct |

With a hostile query (`?project=EVIL&projectId=PRJ-0241&technology=Solar%20PV`) the Data Center statement showed
`EVIL · Solar PV`. Screenshots: `screenshots/before-wind-statements.png`.

## Root cause (source)

`StatementWorkbook` (a harvested design component) read the project from `readProjectContext()` in
`frontend/src/finco/_shared/FincoShell.tsx`, which takes `projectId` / `project` / `technology` from `window.location.search`
and falls back to the demo values `PRJ-0241` / `FINCO Model project` / `Solar PV`. The live workspace tried to compensate by
**writing** the canonical name/code/type into the URL after the workspace loaded (`WorkspaceView` `replaceState` effect).
That made the URL an authority and the result order-dependent: whichever rendered first (the statement or the URL rewrite) decided what was shown.

## Fix

1. `StatementWorkbook` takes an explicit `projectIdentity {code, name, type}` prop (`statementContract.ts`). When
   `status.dataOrigin === "canonical-run"` the identity is taken **only** from that prop; `readProjectContext()` is reachable
   only for the non-live (design-harness) origins.
2. `WorkspaceView` passes `workspace.project` (the authorized, server-resolved identity of the opened project).
3. A canonical statement without a usable identity renders `data-statement-identity="missing"` (role `alert`,
   "Statement project identity unavailable") — never a Solar placeholder.
4. The statements payload now also carries `project.code` / `project.project_type`. If its `code` differs from the workspace's,
   Statements, Results and Analysis render `data-statement-identity="conflict"` and **no figures** (no cross-project data
   under the wrong identity).
5. The `replaceState` identity write was removed: the URL carries no project identity any more; a query string can still
   select a *view* (`?statement=cfads`) but never identity or mode.
6. `WorkspaceView` stays `key={project}`-mounted, so switching projects discards all previous state.

Financial values, unit conversion and Run History are untouched (same payload rows; only `status.runId`, a label, changed — see
`REACT_RUN_IDENTITY_ACCEPTANCE.md`).

## Permanent regressions (all in the mandatory consolidation browser role)

| Test node | Proves |
|---|---|
| `test_onb_statement_identity_is_the_authorized_project_in_every_vertical[solar|wind|data_center|ev_charging]` | direct link without query shows the project's own code, name and type; none of `PRJ-0241`, `FINCO Model project`, `Solar PV`; all six destinations (P&L, Balance Sheet, Cash Flow, CFADS, Debt, Distributions) keep it; reload keeps it |
| `test_onb_hostile_or_stale_query_cannot_change_the_statement_identity` | conflicting `project`, `projectId`, `technology`, `mode=reference`, `parentReferenceId` change nothing; `?statement=cfads` still selects the view; Results/Analysis unaffected |
| `test_onb_switching_projects_never_carries_the_previous_statement_identity` | Solar → Library → Data Center: no trace of the first project's name/code; Back/Forward safe |
| `test_onb_missing_or_conflicting_identity_fails_visibly` | statements naming another project → conflict alert, zero statement cells, zero metric cards; nameless workspace → visible failure, no placeholder |

Counts and run IDs: `REACT_BROWSER_ACCEPTANCE.md`. Negative control: the same four nodes (`[solar]` … ) **fail** against the
original `main` bundle (`REACT_BROWSER_ACCEPTANCE.md`, "negative control").

## Limits

* The design harness (`/__mockup`, `ModelWorkspace`, `ResultsAnalysisView`) still uses `readProjectContext()` by design; it
  never shows live data and is labelled as a prototype.
* Identity correctness depends on the server's `/workspace` response; this PR does not change that authority.
