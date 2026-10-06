# Model V2 UX Foundation Contract

Status: UX-implementation contract for the finance-native Model V2 UX
foundation (Model Home + Workspace Shell + Overview/Smart Panel), delivered
on `feat/model-v2-ux-foundation` from epic head `c0e2543`. Design authority:
the completed FINCO Model V2 UI/UX harvest. This document is product truth —
implementation, tests and this contract must agree.

## 1. Model entry semantics

- **Library-first.** Clicking Model opens Model Home (the Project Library).
  The previously opened project is NEVER auto-reopened.
- Model Home is a product home, not an admin catalog:
  `FINCO MODEL` hero → one-line purpose → **+ New Project** (primary CTA) →
  **Recent Projects** (when populated) → **Reference Models**.
- Search/filter stays fully functional (same form id, HTMX contract,
  pagination) but is visually subordinate to project content.

## 2. Empty state

- With zero working projects the empty Recent block collapses to a single
  onboarding line ("No working projects yet — create a new project above, or
  start from a reference model below").
- Reference Models are immediately visible; no giant empty-state artwork.

## 3. Populated Recent Projects

- Compact decision rows: name, technology, role badge (Working copy /
  My project), **Last Run** (`Last run · YYYY-MM-DD` from the persisted
  workspace record, or a typed `Not run` — never a fabricated timestamp),
  updated date, Open action.
- Data sources: `ProjectRecord` + the per-project persisted
  `WorkspaceStateRecord` (Workflow 07). No engine execution, no
  recalculation, no metrics invented for visual symmetry. Country/capacity
  are NOT shown on Model Home rows — no cheap persisted authority exists at
  list scale today (documented gap, not an omission of shipped data).

## 4. Reference Models

- Product semantics renamed from "Reference Templates" to "Reference Models"
  (they are inspectable canonical models). "View Reference" is now
  **Open model**.
- Cards may show compact headline evidence — Project IRR, Senior Debt,
  Min DSCR — ONLY from the persisted canonical Last Run summary, formatted
  through the shared KPI catalog. Evidence that is absent is omitted;
  unavailable is never rendered as zero. A legitimate persisted 0.0 renders.
- Protected references remain read-only until **Create working copy**.

## 5. Preview state

- Storage (and any vertical without an editable runtime) renders an explicit
  `PREVIEW` chip and "Reference model available. Editable runtime not yet
  supported." — never a peer card, never ambiguous "coming soon".

## 6. Working Copy vs Last Run (hard product contract)

The workspace header shows ONE compact state row with exactly four states:

| State | Meaning | Presentation |
|---|---|---|
| `NOT RUN` | Working Copy, no successful run yet | `NOT RUN · No successful run yet` |
| `CURRENT` | Last Run successful and matches current Working Copy identity | `CURRENT · Last Run · Successful · <timestamp>` |
| `STALE` | Working Copy changed since the Last Run | `STALE · Working Copy · changes not run — Last Run · Successful · <timestamp>` |
| failed rerun | the previous successful Last Run stays visible; the failure surfaces through the existing run-error presentation | never destroys Last Run values |

- Classification comes from the CANONICAL freshness authority
  (`resolve_runtime_freshness`, composite-identity based) — never from
  timestamps. A stale flag without persisted runtime degrades to NOT RUN.
- **Saving is not running.** Working Copy saves never recompute outputs;
  after a causal save every Last-Run surface is classified STALE in the same
  response (one post-save authority refresh), values remain readable.
- **Run Model is explicit.** The header Run button binds the EXISTING
  canonical run form (`#v2-canonical-run-form`) — there is no second run
  authority, no auto-run on open/tab-change/focus.
- Failed attempts: the last successful run is never destroyed; persistent
  "latest attempt failed" classification requires a persistence seam that
  does not exist yet — documented gap, not silently approximated.

## 7. Workspace navigation

Persistent left navigation, finance-native groups, desktop-first density
(32–40 px rows, small chips, subtle borders):

- **Overview** — Overview
- **Model** — Project · Timeline & Discounting* · Escalation* · Revenue ·
  Development · Operations
- **Financing** — Senior Debt · Investor · Tax
- **Outputs** — Statements · Returns · Analytics*
- **Analysis** — Scenarios · Sensitivity · Compare
- **Trust** — Assumptions · Calculation Trace
- **Delivery** — Exports* · Run History*

`*` = future capability: rendered disabled with a truthful "not yet
available" title, never as a shipped page. Every AVAILABLE item activates an
EXISTING sheet tab (one economic field = one edit authority — navigation
never duplicates editable surfaces). Deep links: `#<section>` hash is kept
in sync and activates the matching tab on load where the existing
architecture supports it.

## 8. Overview (decision screen)

- KPIs grouped **Returns** (Project IRR, Pure Equity IRR, Total Sponsor IRR,
  Project NPV, Total Sponsor MOIC) / **Debt & Coverage** (Senior Debt,
  Min DSCR, Avg DSCR, Min LLCR) / **Operating** (Revenue, EBITDA, CFADS,
  CAPEX).
- Authority: `OutputMetricProjection` pass-through from the persisted Last
  Run only. Presentation may format; it must not recompute XIRR/MOIC/DSCR/
  LLCR, infer missing values, or replace unavailable with zero. A tile
  renders only when its metric is AVAILABLE — absent metrics are omitted.
  Documented raw gaps (Senior Debt, CFADS, pure-equity MOIC) stay typed
  gaps until upstream persists them.
- Stale quarantine: the state strip classifies the whole output context;
  stale tiles carry `v2-kpi-tile--stale`; stale values stay readable but
  never resemble current outputs.
- Charts reuse persisted canonical chart series only.

## 9. Smart Panel

- Right-side contextual panel; sections **Checks / Assumptions / Trace**.
- NOT a second Assumption Register and not an analytics engine: it renders
  availability + navigation rows over existing authorities:
  - Checks: the repository's own validation-tier authority
    (`app.validation_status`) with its OWN tone vocabulary (pass/warn/fail —
    no invented lender rules, no remapping), ordered blocking-first
    (fail → warn → pass); Trust Pack section availability (Last Run
    identity, reference regression — which always loads on demand, never on
    render).
  - Assumptions: availability + "Review assumptions" → the Trust Pack sheet
    (the register stays THE authority).
  - Trace: available only with a persisted run; typed empty state otherwise.
- **Go to field**: rendered ONLY where evidence carries an existing reliable
  field/sheet identity (stable `data-field-id`). No such persisted check
  evidence exists yet, so no Go-to-field action is rendered — a fake action
  is worse than no action.
- Empty states are explicit (no checks yet / no run / stale / failed) — no
  giant blank panels.
- The panel refreshes through the ONE post-run/post-save authority
  (`build_post_run_ui_state` / `build_post_save_ui_state`) — same
  single-workspace-read contract as every other runtime surface.

## 10. Post-run / post-save coherence

One successful Run → one coherent persisted workspace read → one coherent UI
refresh. `post_run_ui.py` remains the SINGLE post-run presentation authority;
the UX foundation extends its fragment set (workspace header, Smart Panel)
instead of adding parallel refresh paths.

## 11. Protected reference models

References open in the same workspace; read-only state is obvious (badge in
the header); the header offers no Run CTA for read-only models; Last Run
evidence is inspectable; **Create working copy** is the editing path.

## 12. Explicit out of scope (honest gaps)

- Developer Economics, Goal Seek/Tender, new sensitivity/Compare economics,
  Working Capital, Debt Service Frequency, new tax jurisdictions, CPI/PPI
  authorities, new Revenue Runtime semantics, Storage economics, true
  quarterly engine, API productization, XLSX redesign, version restore,
  full Run History backend, advanced revenue editor.
- Persistent "latest attempt failed" state (needs a Workflow 07 seam).
- Per-project change COUNT in the stale banner (needs a change-log
  authority; the banner states "changes not run" without a count).
- Timeline & Discounting / Escalation / Analytics / Exports / Run History
  surfaces (declared future navigation, no fake pages).
- Model Home row country/capacity columns (no list-scale persisted
  authority; shown inside the workspace instead).
