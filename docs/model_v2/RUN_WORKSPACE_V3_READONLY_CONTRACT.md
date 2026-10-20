# Run & Scenario Workspace V3 — read-only comparison contract

Status: **feature candidate / Draft PR**. No financial release, Run writer change, Save, migration, engine modification or deployment is implied.

## V2 → V3 delta

| Existing authority | V3 addition |
|---|---|
| Run Intelligence / PR #209: append-only ledger, historical detail, LAST/CURRENT/STALE | Two- or three-Run picker including historical-vs-historical; exact source identities |
| Decision Support / PR #215: two-sided KPI variances | Three-column reference-driven KPI matrix; signed deltas and filters |
| RC-5A / PR #300: persisted input difference and missing-identity honesty | Pairwise lineage against selected reference without causal attribution |
| Credit Decision V4: committed date-exact Senior timeline and start/end safeguards | Multi-Run period grid, rejection of incompatible intervals and frequency |
| Statements V2: read-only model-period P&L, Cash Flow, Balance Sheet | Whitelisted statement cells joined only when Credit V4 independently validates the interval |

## Entry point

GET /v2/workbook/run-workspace-v3?project=PROJECT&run=last&run=HISTORY_ID&run=HISTORY_ID&reference=last

All operations use GET. No POST, Save, Run, mutation, migration, replay or side-effect route.

- A canonical Last Run may be selected by last. A Last Run without an immutable ledger row is not a fabricated history entry.
- History IDs are project- and owner-scoped by the existing Run History API. No project or scenario borrows unrelated results.
- A current Last Run and its history entry cannot occupy two columns; duplicate snapshots and Run IDs are refused.
- Only the canonical Last Run has CURRENT or STALE. Immutable history entries remain HISTORICAL.
- An opaque persisted identity is not a detailed historical input record.
- Output movement and assumption changes are observations, not causal attribution.

## Financial evidence

Every aggregate KPI passes through existing Decision Support metric and difference rules. Missing or malformed numbers remain unavailable, never zero. IRR variance is expressed in percentage points.

The period grid uses the persisted Senior/CFADS/DSRA/distribution timeline from Credit V4. A period is comparable only if every Run has the identical committed start and end dates and compatible frequency. No index alignment or inferred starts are permitted.

The existing Statements V2 adapter supplies whitelisted dated model-period P&L, Cash Flow and Balance Sheet lines. These cells join only to independently verified Credit V4 intervals. Invalid, duplicate, missing or non-ISO statement dates are excluded. No annual-to-quarterly conversion, stock summation or ratio aggregation.

**Limitation:** Runs without committed Credit V4 debt timeline start/end evidence cannot be date-joined, even if statement values exist. This is a deliberate fail-closed decision, not an assertion that the data is zero. No historical statement-axis reconstruction is performed.

Release-closed 3/3 is never activated or joined with 6/6. The released absence-of-policy contract is 6/6; unknown explicit policies fail closed.

## UI and ownership

The scoped HTMX partial is linked from Run History. Selectors, reference changes, filters and bounded pages use GET. Existing #v2-sheet-run-history swap semantics are preserved. CSS is additive, not a workbook shell redesign. Historical details, statements, Credit Decision, Model Checks and Trust are linked, not duplicated.

Existing modifications are limited to a router registration hook and a Run History navigation button. New files are the dedicated projection, router, partial, CSS, tests and this document.

Untouched: financial_engine, finco_core, domain, Run History repository, schema, formulas, Run writer, scenario Save, override binding, export, institutional reporting, Radar, V9 and quarterly activation.

This interface uses existing design tokens so a separate Replit visual redesign can restyle it without changing evidence semantics.

## Acceptance

Dedicated synthetic projection tests cover three-Run arithmetic and reference reversal, pp IRR, unavailable/zero/non-finite values, missing identity, no causal attribution, date and frequency refusal. Committed-Run route tests cover 2–3 real Runs, historical/historical, duplicate snapshots, owner isolation and no engine execution or Run mutation. Chromium tests cover desktop/mobile controls and Run History HTMX navigation.

Full exact-head GitHub CI and independent review are required before an owner-authorized normal merge.
