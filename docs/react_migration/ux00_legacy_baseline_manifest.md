# UX-00 — FINCO Model Legacy Baseline Manifest

Status: **baselined on the verified live `main` head** recorded below.
Purpose: acceptance reference for the React migration. The Jinja2/HTMX frontend
is a *temporary, complete legacy fallback* for the whole migration; nothing in
this manifest authorizes any change to it, to staging, or to `main`.

## 1. Source baseline

| Item | Value |
|---|---|
| Verified `main` HEAD (live, 2026-10-21) | `b28a05723967df590f6a684c64504d845e576508` — "Merge pull request #334 — Public Safety CI 200-minute budget" |
| Prior architecture-audit reference SHA | `b28a05723967df590f6a684c64504d845e576508` — identical; `main` has not advanced since the audit |
| Epic branch | `epic/model-react-frontend-v1` created at exactly the SHA above (recorded on the branch; no rebase/force policy applies) |
| Repo state at baseline | 539 `tests/test_*` modules; Workbook V2 flag `FINCO_WORKBOOK_V2` default-ON; React PoC flag does not exist at this SHA |

## 2. Staging deployment baseline — PENDING (not frozen)

`main` and the deployed staging environment are **not** assumed to be the same
commit. The actual staging deployment identity, its change controls and its
writable-database isolation were **not verifiable from this assignment's
environment** (no staging host access was available).

Therefore:

- Staging baseline status: **PENDING — NOT VERIFIED, NOT FROZEN.** No claim of a
  frozen legacy staging environment is made.
- No staging change is authorized or performed by UX-00/UX-01 work.
- Required before any legacy-baseline or React-preview environment is stood up:
  isolated writable databases, safe synthetic test datasets only, and explicit
  deployment-identity capture (commit SHA + release channel) recorded here.

## 3. Legacy architecture at baseline

- Server: FastAPI (`main_web.py`) serving Jinja2 templates (`app/templates/`)
  with HTMX partials; static assets under `static/` (same-origin; vendored
  vendor JS under `static/vendor/`; design tokens in `static/tokens.css`).
- Model workspace shell: `GET /v2/workbook` (`app/v2/router.py` +
  `app/templates/v2/workbook.html`), hybrid nav groups
  inputs / scenarios / outputs / analysis / diagnostics / trust.
- Input editing: per-field updates via `POST /v2/workbook/update` and the
  Excel-like hybrid grid via `POST /v2/workbook/grid/validate`,
  `POST /v2/workbook/grid/save` (scalar batch, C0 atomic writer, composite CAS)
  and `POST /v2/workbook/grid/cost-lines/save` (separate atomic batch writer for
  CAPEX/OPEX cost lines, row-versioned repositories).
- Run: `POST /v2/workbook/run` — canonical engine orchestration; HTMX clients
  receive 200 + HTML fragments with an `X-Finco-Run-Outcome` header; non-HTMX
  clients receive 303 redirects (success) or `?v2_err=` redirects (failure).
- Statements & outputs: `GET /v2/workbook/outputs` over
  `PostRunRequestContext` + `build_output_workspace_safe`; run history drill-downs
  under `GET /v2/workbook/run-history*`.
- Feature flags: `FINCO_WORKBOOK_V2` and `FINCO_INPUTS_SLICE1_ENABLED`
  (absent/empty → ACTIVE; canonical truthy/falsy sets in
  `app/utils/workbook_flag.py`).

## 4. Route inventory at baseline (Model V2 surface, 68 routes)

Key groups (full list via `grep -hoE "@router.(get|post)\(\"[^\"]+\"" app/v2/*.py`):

- Workbook shell & sheets: `/v2/workbook`, `/v2/workbook/grid/{sheet,panel}`,
  inputs / revenue / capex / opex / project-setup / tax / financing / fs /
  returns / trust / run-history tabs (all tabs asserted present by
  `tests/test_model_hybrid_inputs_grid_routes.py`).
- Mutations: `/v2/workbook/update`, `/v2/workbook/grid/save`,
  `/v2/workbook/grid/cost-lines/save`, `/v2/workbook/run`,
  scenario CRUD + override routes, goal-seek, whatif apply, revenue
  contracts/stress, investor agreement/export, calendar operating-frequency,
  import workflow (preview→assess→review→confirm), BESS candidate,
  valuation-acquisition, developer/credit decision configuration.
- Reads: outputs, diagnostics, run-compare, run-history (+detail/compare/
  statements/export), scenario compare, financing trace/integrity/investor,
  trust certificate/validation, decision surfaces, portfolio, kpi/smart-panel
  fragments.

## 5. Important flags & in-flight work at preflight (2026-10-21)

Open PRs to avoid conflicting with: V9 performance line (#327, #328, #332),
RC-7 institutional acceptance drafts (#336, #337), CI performance
`perf/ci-p0-sequential-runtime-v1` (#335), RC-7 integration (#318, conflicting
with `main` at preflight). None of them touches the UX-01 PoC surface.

## 6. Save / Run / output semantics pinned at baseline (acceptance reference)

1. Save = Working Copy only. It never alters a persisted Last Run and never
   executes the engine; a persisted economic change classifies the existing
   Last Run STALE through `resolve_runtime_freshness` (composite CAS identity).
2. Run = server-authoritative only (`POST /v2/workbook/run`, fail-closed
   pipeline, atomic commit with final CAS).
3. Statements always originate from persisted RuntimeResult evidence via the
   canonical statement services; unavailable values render "—", never 0
   (`_cell`/`fmt_number`); NOT_RUN / CURRENT / STALE are distinct states;
   input freshness, Run Integrity and engine currency are independent
   dimensions (SC-03).
4. Authorization: session via `resolve_request_session`; project access via
   `resolve_accessible_project`; protected references read-only; CSRF tokens on
   every mutation; foreign-project access denied (404).

## 7. Reference datasets for later parity testing

- Synthetic reference seeds: `create_reference_seeded_project` with
  `generic_solar_reference`, `generic_wind_reference`, `generic_storage_reference`,
  `generic_data_center_reference`, `generic_ev_charging_reference` (used by the
  existing browser acceptance suites).
- Canonical expected values for parity checks come only from persisted
  RuntimeResult payloads (`financial_statements`, `runtime_summary`,
  `debt_schedule`) thawed via `thaw_runtime_payload`, never from UI text.
- Protected reference project: seeded `generic_solar_reference-reference`
  (read-only acceptance target).

## 8. Existing browser acceptance coverage at baseline

Real-Chromium suites (pytest + playwright, explicit CI selections in
`tools/ci_browser_job.py`): workspace consolidation, hybrid inputs grid,
workflow C navigation, cost grid editing/batch save, import workflows, Q4,
diagnostics V1/V2, protocol shell, yield, crypto, EV charging. The UX-01 PoC
adds a separate, skippable module (`tests/test_model_react_poc_browser_acceptance.py`)
and does not modify any existing suite.
