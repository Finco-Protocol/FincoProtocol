# UX-01 — Full-React Architecture PoC: implementation record

Branch: `feat/ux01-full-react-poc-v1` (based on `epic/model-react-frontend-v1`
at `b28a05723967df590f6a684c64504d845e576508` = verified `main` HEAD).
Draft PR target: the epic branch — never `main`.

## 1. What exists after this PoC

One isolated, feature-flagged React slice proving the target architecture:
**React 18 + TypeScript + Vite** application shell served same-origin by the
existing FastAPI app, with

- ONE real editable canonical input: `tax.assumptions.cit_rate_pct`
  (registry-bound, `editable=True`, PCT 0–100, `app/workbook/registry.py`),
- ONE real persisted financial statement: the Profit & Loss table,
- full loading / unavailable / error states, keyboard operability,
- zero financial computation in the browser.

Legacy Jinja2/HTMX remains the default experience for ordinary users; no
navigation, template, route or behaviour of the legacy surface was modified.

## 2. Changed-file inventory (see PR for the exact list)

Backend (additive):
- `app/v2/react_poc_router.py` — new router: page shell, fallback page, bootstrap
  JSON. Read-only; persists nothing; authorizes nothing on its own.
- `app/templates/v2/react_poc.html`, `app/templates/v2/react_poc_fallback.html`.
- `main_web.py` — one `include_router(..., prefix="/v2")` line.

Frontend (new tree):
- `frontend/` — package.json, tsconfig, vite config, `src/` (api client +
  typed view models, App shell, input/status/statement components, styles).
- `static/react/finco-react.js`, `static/react/finco-react.css` — committed
  Vite build output served by the existing `/static` mount (same-origin, no CDN;
  the bundle contains no non-same-origin URL besides W3C namespace constants and
  React's inert error-decoder doc strings).

Tests (new; no existing test modified):
- `tests/test_model_react_poc_v1.py` (16 contract tests, TestClient).
- `tests/test_model_react_poc_browser_acceptance.py` (3 real-Chromium checks;
  `pytest.importorskip("playwright")`; deliberately NOT wired into any CI
  selection — adding it to `tools/ci_browser_job.py` SELECTIONS is a one-line
  governance decision for the reviewer).

Docs: this directory (`docs/react_migration/`).

## 3. Canonical contracts actually used (no parallel authority anywhere)

| Concern | Authority reused by the PoC |
|---|---|
| Page authorization | `resolve_request_session` + `resolve_accessible_project` (identical to `GET /workbook/outputs`) |
| Coherent snapshot | `PostRunRequestContext.capture` + `validate_current` (503 `WORKSPACE_UNAVAILABLE` on concurrent change) |
| Composite identity | `assemble_consistent_for_get` / `WORKBOOK.version`; bootstrap returns the same hash the legacy grid renders (asserted by test) |
| Editability | registry `FieldSpec` + protected-reference gate (`is_protected_reference`) — project-level; per-field typing stays with the canonical validator |
| Save (the only mutation) | existing `POST /v2/workbook/grid/save` — C0 atomic batch writer, composite CAS, CSRF, owner checks; success returns the NEW authoritative composite hash + `run_state` |
| Freshness | `resolve_runtime_freshness` (NOT_RUN / CURRENT / STALE + basis) |
| Statements | `statement_presentation.financial_statement_tables` over `context.projection.fs` (persisted RuntimeResult); unavailable cells are `v:null` + "—" |
| Run status dimensions | `resolve_run_status_dimensions` (input freshness, Run Integrity, engine currency, run context — four independent facts) |

## 4. Save/Run behaviour implemented

- Save updates the actual Working Copy and returns the new composite hash; the
  React client adopts the server-returned hash + canonical display value.
- A Save never alters the persisted Last Run and never triggers a Run
  (`model_executed:false`, `run_state` reclassification only — pinned by tests).
- STALE is shown as a badge plus an explicit banner.
- Stale CAS conflict (409) → explicit "Reload required" state; no blind retry;
  the typed value is preserved on every failed Save.
- **Run button deliberately deferred**: the canonical `POST /workbook/run`
  answers HTMX fragments (200 + `X-Finco-Run-Outcome`) or 303 redirects. A thin
  read-only JSON outcome adapter (or form-post + redirect-follow + bootstrap
  re-fetch) is required before a React Run button can exist without inventing a
  second Run authority. Documented for UX-01B; nothing in the PoC runs the model.

## 5. CAPEX/OPEX batch contracts documented for later migration (not extended)

- Scalar field batches: `POST /v2/workbook/grid/save` →
  `WorkbookUpdateService.apply_batch_draft_update` → `v2_atomic_batch_draft_update`
  (single `BEGIN EXCLUSIVE`, composite CAS, ≤50 cells, ≤64 chars/value,
  duplicate-field rejection, all-or-nothing).
- Cost lines: `POST /v2/workbook/grid/cost-lines/save` →
  `app.v2.cost_batch_commands.update_cost_lines_batch` — separate atomic writer
  over the row-versioned CAPEX/OPEX repositories (one `BEGIN EXCLUSIVE` around
  all rows, per-line verdicts, `CostBatchConflictError`/`CostBatchInvalidError`
  semantics, HTMX partial + OOB response on success). The PoC does NOT touch
  this surface; the React cost-grid migration must consume it (or its eventual
  JSON twin) rather than the scalar writer.

## 6. Replit React Design prototype — separate reuse gate (not passed)

The FINCO Model React Design prototype lives in the separate Replit
"GoldenNiceConsultant" project. **Its TSX/CSS source has not been inspected in
this environment — no reuse claim is made.** This PoC uses only small
temporary React components to establish the backend/build architecture.
The structure is prepared for transfer without another technology migration:

- plain Vite + React + TS workspace (`frontend/`), no framework lock-in;
- design tokens consumed from the existing `static/tokens.css` (`--fo-*`);
- presentational components segregated (`src/components/`) from API adapters
  (`src/api/`), so Replit screens can replace the PoC views one domain at a
  time behind the same typed adapters;
- stable bundle entry (`static/react/finco-react.js`) + host data-attribute
  contract, so swapping components never changes the server surface.

**Missing source access to record for UX-01B:** export/access to the Replit
project's `src/` (TSX + CSS), its component inventory, and any asset licences;
then the §7 gate (inspect → map → port per domain) can run.

## 7. Build & governance notes

- `npm run build` (tsc --noEmit + vite build) produces the committed bundle;
  `frontend/node_modules/` and `frontend/dist/` are git-ignored.
- No new CI workflow, no runner requirement, no existing test weakened: the PR
  gate (`compileall`, safety scan, CI V2 contract tests) covers the Python
  side; the committed bundle is byte-audited by a test for non-same-origin URLs.
