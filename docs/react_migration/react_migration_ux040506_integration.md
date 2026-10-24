# UX-04/05/06 — Inputs, Financing, Run/History, Diagnostics & Trust Integration

**Status:** Draft PR over the merged UX-03 Epic (`b2e78b3f`). Feature flag `FINCO_MODEL_REACT_V1` stays OFF. No merge/activation performed by this PR.

## 1. Architecture

Read-only JSON projections over the SAME canonical authorities the legacy workbook uses, plus mutations exclusively on the EXISTING canonical writer routes. No new persistence, no computed financial values, no fabricated endpoints. New projections in `app/v2/react_workspace_router.py` (all gated by the same per-request `FINCO_MODEL_REACT_V1` flag, same authorization order `resolve_request_session` → `resolve_accessible_project`, same `_json` no-store envelope):

| Endpoint | Source (canonical) | Mutation contract (existing route) |
| --- | --- | --- |
| `GET /model-react/fields/{project_setup\|debt\|revenue\|tax}` | `_build_sheet_fields` over the canonical PIS (registry FieldSpecs with `binding_label` bound/partial/display-only/template-locked + validation metadata) | `POST /v2/workbook/update` (composite CAS; financing-sheet fields authenticate with the BOUND `financing_csrf.issue_token` token, exactly like the legacy financing form) |
| `GET /model-react/costlines?sheet=capex\|opex` | the same loaders the atomic batch writer verifies row versions against (`_list_capex`/`_list_opex`) | `POST /v2/workbook/grid/cost-lines/save` (atomic batch; row-version CAS; 409 conflict/422 invalid; success carries `X-Cost-Batch-Saved`) |
| `GET /model-react/revenue` | `_build_revenue_contract_editor` (the legacy revenue form's state, incl. scenario override scope) | **read-only in React** — the guided contract editor keeps its canonical legacy form; the Save contract (`POST /v2/workbook/revenue/contracts`, bound CSRF + composite CAS) is projected for the next increment |
| `GET /model-react/runs` | `run_history_repository.get_run_history` (immutable committed evidence) | Run initiation stays on `POST /v2/workbook/run` (form contract: 303 success / `?v2_err=` failure) — **no new Run authority** |
| `GET /model-react/diagnostics` | `build_quality_insight_safe` (canonical fail-closed evaluator) + `diagnostics_client_payload` | read-only |
| `GET /model-react/trust` | `app.ui.trust_pack` certificate/validation builders | read-only |

## 2. React surfaces

- `frontend/src/app/ux040506Views.tsx` — `FinancingView` (per-field atomic save through `/v2/workbook/update`; display-only/template-locked values rendered read-only), `CostLinesView` (CAPEX/OPEX toggle; staged edits; ONE atomic batch; UNKNOWN-outcome classification on transport loss, never blind-retried), `RevenueView` (read-only canonical contract state + truthful gated note), `RunsView` (canonical Run button + immutable history table; NOT RUN stays NOT RUN), `DiagnosticsView` + `TrustView` (canonical evidence; UNAVAILABLE never shown as a pass).
- `WorkspaceView.tsx` — financing / model-checks / trust nav sections ACTIVATED over the projections; cost-lines + revenue live in the Inputs section; Run + history live in Results. Scenarios and Analysis (sensitivity / goal-seek / what-if) remain **visibly gated** — their backend admission for React is not verified yet.
- All views style with the existing `fm-*` classes so the three B/D/G themes apply unchanged (`data-fm-theme` scoping untouched).

## 3. Invariants preserved

- Save never triggers a Run (grid/save, cost-lines/save and update all end with `model_executed: false` semantics; the Run is a separate explicit user action).
- Current Working Copy and persisted Run stay separate: statements/results still come from the persisted evidence; STALE banners unchanged.
- Stale inputs never erase the Last Successful Run; historical Run identity is immutable (history is read-only).
- No automatic retry of ambiguous mutations: transport-loss on save/run answers UNKNOWN and demands a reload/reconcile, matching the Correction-A semantics.
- Synthetic-data quarantine: the served bundle was rebuilt and re-verified free of every forbidden marker; `FORBIDDEN_PRODUCTION_MODULES` unchanged (no new demo modules were introduced).

## 4. Known gaps (documented, gated)

1. Revenue contract editing (guided form) — legacy only; contract projected.
2. Scenarios (create/select/compare) — legacy only; nav section gated.
3. Sensitivity / goal-seek / what-if — legacy only; nav section gated.
4. Financing structured facilities (multi-row schedules beyond the registry field grid) — legacy only.
5. Merchant revenue, workbook import, exports — intentionally unavailable in the design.

## 5. Local acceptance (Windows, Python 3.12, Node 24)

- Both TS programs clean; production build clean; served bundle re-published and marker-free; transfer build clean.
- pytest: new `tests/test_model_react_ux040506_v1.py` **15/15**; full React batch (ux02 + poc + harvest + rc5 + ux040506) **66/66**.
- Boot check: 13 `/v2/model-react/*` routes registered in the production app, workspace routes before the PoC catch-all.
- Boundary declaration: no `financial_engine/`, `finco_core/` or `domain/` file authored; no governance recognizer touched; one normal two-parent merge of current `origin/main` included solely for the live ancestry guard.

## 6. UX-07/08 addendum (this PR)

**Correction A (outcome integrity, P0):** the client mutation classifiers no longer treat a followed redirect's 200 as success. `classifyFormPostOutcome` (URL-parsed, no substring matching) classifies login redirects, `?v2_err=` error redirects, clean canonical redirects and unexpected destinations; `saveWorkbookField` reconciles a clean redirect through a fresh authorized projection (value comparison) before success; `runModel` requires the persisted Run History to GROW after a clean redirect (an unreadable or unchanged history is UNKNOWN, never success, and transport loss is never retried); `saveCostLinesBatch` requires the `X-Cost-Batch-Saved` header. Regression evidence: `tests/test_model_react_outcome_integrity_v1.py` (10 real-endpoint pins incl. expired-session 302→/login, stale CAS → `?v2_err=`, bound-token 403, protected-reference refusal with non-persistence) and `frontend/transfer/scripts/outcomeIntegrity.test.mjs` (18 fetch-level cases). A real projection bug found during testing (`_jsonable` could not serialize date/Decimal/UUID values → 503 on date-carrying sheets) was fixed.

**UX-07 (scenarios + compare + revenue editor):**
- `GET /model-react/scenarios` — canonical scenario records + active scenario; mutations stay on the canonical form routes (create/select/rename/archive; a selection NEVER starts a Run).
- `GET /model-react/scenario-compare` — ASSUMPTION-level differences (override keys/values) between the Working Copy and one scenario, each side's persisted Run identity; KPI deltas deliberately NOT computed in the browser (`kpi_compare.available=false` with reason).
- `ScenarioView`/`ScenarioCompareView` — management UI (create/select/rename/archive, compare disclosure) over those projections.
- `RevenueEditorView` — edits the canonical contracts payload (streams & products JSON) and saves atomically through `POST /v2/workbook/revenue/contracts` (bound CSRF, composite CAS; canonical typed validation errors surfaced verbatim; guided PPA form remains on legacy).

**UX-08 (completion pass):** every new view ships loading / error / empty / unavailable states (fail-closed 503 projections surface as retryable banners); native select/button/input elements with aria-labels throughout (keyboard-first); responsive behaviour via the existing `fm-*` media queries (top-bar wrap below 760px from UX-03B); the three B/D/G themes apply unchanged through the scoped token layer; direct-URL/reload/Back-Forward continue through the hash-section router. Sensitivity / goal-seek / what-if remain gated: their canonical endpoints are HTML solvers whose JSON admission for React is not established — documented as the next increment's contract work.
