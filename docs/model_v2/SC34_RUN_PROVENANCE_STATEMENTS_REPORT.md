# Safe Core V3.4 · Workstream C — Run provenance, historical evidence and Statements drill-down

Branch `feat/model-sc34-run-provenance-statements`, base `origin/main` `540e1f4bb54d53ad6d2c1628074b94fdb0c9eb06`.
Additive Run-evidence metadata and a read-only statements UX. No financial calculation, engine, domain, CI or governance change;
no Run repository, Statements engine or second calculation authority was created. Not merged, not deployed, no standalone PR.

## 1. What already existed (reused, not rebuilt)

| Existing authority | Used for |
|---|---|
| `runtime_authority.resolve_runtime_freshness` (NOT_RUN / CURRENT / STALE) | the **Inputs** dimension, unchanged |
| `last_runtime_identity.engine_version`, `replay_metadata.engine_version`, `run_history.engine_version` | the only sources of a Run's engine identity |
| `output_workspace_projection` / `statement_presentation` (persisted statement rows, annual view aggregated once) | every statement value |
| `workspace_destinations.DESTINATIONS` | every navigation destination |
| `workspace_nav` hash-per-tab history (`#opex`, `#outputs`) | Back/Forward context |
| Run History entries (immutable) | the historical Run |

## 2. SC-03 — independent Run status dimensions

`runtime_authority.resolve_run_status_dimensions` returns four facts, none derived from another:

| Dimension | Values | Source |
|---|---|---|
| Run context | `LAST_RUN`, `HISTORICAL_RUN` | the view that is rendered |
| Inputs | `NOT_RUN`, `CURRENT`, `STALE` (historical: `CURRENT`/`STALE` by hash equality, or *not evaluated*) | existing freshness authority |
| Engine | `CURRENT_ENGINE`, `ENGINE_SUPERSEDED`, `ENGINE_IDENTITY_UNKNOWN` | persisted engine identity vs the running engine's declared version |
| Integrity | `PASS`, `FAIL`, `INCOMPLETE`, `UNAVAILABLE` | the Run's own integrity verdict |

Rules: `ENGINE_SUPERSEDED` only when a persisted identity is known and differs; no persisted identity (or the legacy
`NOT_AVAILABLE`) → `ENGINE_IDENTITY_UNKNOWN`; two persisted identities that disagree → unknown (fail closed). Nothing is inferred from
timestamps or deployment versions. `CURRENT_ENGINE` means the Run carries the same *declared* engine version as the running engine; it is
not proof that code did not change without a version bump. `CURRENT` keeps meaning input freshness only. An Integrity FAIL is
displayed beside `CURRENT` inputs and a current engine. GET never runs the engine and never rewrites a Run.

Surfaces: the Statements toolbar (`outputs-status-dimensions`), the historical statements page and Model Home recent rows
(`engine_currency`, shown only as "Engine identity not recorded" when unknown).

### Forward-only provenance proposal (not implemented; needs an owner and the engine team)
Today `engine_version` is a single constant (`clean_senior_debt_v0`) that has not been bumped, so a historical Run can only ever prove
"same declared version" or "different declared version". To prove a *behavioural* supersession a Run would additionally need to persist
a forward-only `engine_provenance` block (for example `{schema, engine_version, build_digest, calculation_contract_digest}`) at commit.
Old Runs must stay as they are and render `ENGINE_IDENTITY_UNKNOWN`; no value may be back-filled. This is a persistence change in the
Run commit path and is therefore **out of scope** here.

## 3. SC-09 — Statements V2 drill-down

Opt-in "Drill-down" view per statement (the unchanged flat tables stay the default). Parent/child is an accounting grouping of rows the
Run persisted: `Net income ▸ Earnings before tax ▸ EBIT ▸ Revenues / Operating expenses / Depreciation`, the interest lines and CIT
accrual; cash flow `CFADS ▸ EBITDA cash ▸ revenue/opex cash, cash tax`, debt-service and distribution groups; balance sheet totals ▸ lines.
Parents show their own persisted values — **no child is ever summed into a parent**, no group header carries a number, unavailable
cells stay "—". Revenue-stream detail comes from the persisted `revenue_multistream_audit` and appears only in the model-period view
(the annual view would need re-aggregation, which is not done). OPEX/cost sub-lines are not persisted in the statements, so OPEX is a leaf.

Two independent controls per line: a chevron `<button>` (expand/collapse) and the label `<a>` (navigate). Destinations:

| Line family | Destination | Kind |
|---|---|---|
| Revenues / revenue cash | Revenue | input |
| Operating expenses / OPEX cash | OPEX | input |
| Depreciation, net fixed assets | CAPEX | input |
| Senior interest, debt service, DSRA, Senior balance | Senior debt | input |
| CIT accrual, cash tax | Tax assumptions | input |
| Net dividends, cash for distribution | Returns | explanation |
| Derived totals, SHL lines, share capital, retained earnings, cash | Trust (read-only Run provenance) | provenance — "no one-to-one editable input" |

### Historical Run and input context
Links always lead to the **current Working Copy** and say so. The context note is `RUN_MATCHES_WORKING_COPY` (inputs CURRENT, no
warning), `WORKING_COPY_DIFFERS` (inputs STALE, scenario switched…) or `HISTORICAL_RUN`; a Base Run is never presented as an
alternative scenario's Run (a scenario with no Run shows NOT_RUN and no links). Immutable historical *assumptions* are not shown: the
history entry stores the composite identity, not a re-renderable input snapshot, so that is stated rather than simulated.

### Back/Forward
The reading context (view, expanded lines, selected period, focused line, region scroll, window scroll, Run identity) is saved into
`history.state` immediately before a link navigates (the link is a native `#tab` anchor, so the browser records the entry). On Back the
nav re-opens `#outputs`, the sheet reloads, and the context is restored only if project, snapshot and scenario still match. Verified in
Chromium: expand Net income → EBT → EBIT, select a period, scroll, follow *Operating expenses* → OPEX, Back → same statement, expansion,
period, focused line and scroll offset.

## 4. SC-11 — accessibility
`treegrid` with `aria-level`/`aria-expanded`/`aria-controls`; chevron has a state-following accessible name; roving tab stop (row +
its chevron + link); Up/Down, Home/End, Right (expand, then into first child), Left (collapse, then to parent), Enter on a line,
Enter/Space on the chevron; ordinary table keyboard use is untouched (header buttons, the scroll region's own arrow keys, the existing
OPEX/CAPEX editors). Scrolling is contained per statement region at 1440 / 768 / 390 px (page overflow 0). Without JavaScript every line
stays visible. The drill-down markup deliberately avoids `<caption>`/`role="region"` so the existing table-accessibility contract
(`test_tables_are_keyboard_and_screen_reader_accessible`) keeps counting the flat tables only.

## 5. D2 decision requests (owner approval required; shipped disabled / evidence-only)
1. **D2-a** Product treatment of a proven `ENGINE_SUPERSEDED` Run (badge wording, banner, re-run call to action). Currently
   `ENGINE_SUPERSEDED_GOVERNED_DISPLAY_ENABLED = False`: the evidence is in `data-*` attributes and a neutral "Recorded engine X" text.
2. **D2-b** Whether the header/Library/Run-History "CURRENT" chip should be renamed "Inputs current" once the other dimensions are
   visible everywhere (header and Run History are outside this workstream).
3. **D2-c** Whether the drill-down becomes the default statements view (flat is default today to protect existing tests/behaviour).
4. **D2-d** The forward-only `engine_provenance` persistence field (section 2).

## 6. Production wiring (PR #292 Correction A)
1. `app/v2/router.py` now registers the historical route (`router.include_router(statements_drilldown_router)`) beside the other isolated
   routers: `GET /v2/workbook/run-history/statements`. No other line of that file changed except the one context key below. Shared-file
   note: the only concurrently open model branch (`feat/revenue-index-series-v1`, #289) touches `domain/revenue`, a cost doc and a test —
   no overlap with `app/v2/router.py`, Run History templates or CI tooling.
2. `v2_run_history_detail` passes `statements_drilldown_available`, computed from the mounted routes (`_statements_drilldown_registered()`),
   so the link exists only while the route does.
3. CI: the established `outputs` browser role (one of the SIX mandatory roles) now runs **both** `tests.model_outputs_workspace_acceptance`
   and `tests.model_statements_tree_acceptance` through `tools/ci_outputs_role.py` (each in its own process, both always executed, exit
   status recorded in `artifacts/outputs-role.json`). `tools/ci_browser_job.py` validates, fail-closed: the role record names exactly the two
   modules with normal zero exits; each module's `browser-results.json` has the right schema, `all_pass`, `passed == total == len(checks)`,
   a minimum check count and (for Statements V2) ten named required checks; every screenshot is listed, hash-matched and a valid PNG. HEAD/tree
   provenance is the existing per-role `process.json` check. No workflow file was edited; the other five roles and every selection are unchanged.
4. Defects found by the new browser checks and fixed: (a) the historical fragment reused `id="v2-sheet-outputs"` and several section/row ids
   that the Outputs sheet already owns, so both could be in the document at once — the fragment now uses `#v2-run-statements` and an
   `hst-` id prefix, the shared CSS/JS bind to either root; (b) the cells' absolutely positioned screen-reader text escaped the scroll region and
   widened the page (1151 px at 768 px) — `.st-region` is now a positioned containing block.

### Run History navigation contract
Detail → "Open this Run's financial statements" records one history entry; browser Back returns to the Run detail, Forward to the statements;
"Back to Run detail" drives that same Back; focus returns to the opener; reopening the same Run restores expansion, selected period and focused
line (session storage keyed by project + Run); a different Run opens its own evidence; following a line link to the Working Copy and pressing
Back returns to the same statements view. The Outputs sheet and its state are untouched.

### Response safety
Failure responses are fixed generic texts (no exception text, payload or id is echoed or logged); persisted values are auto-escaped
(tested with a `<script>` snapshot id and a sentinel in malformed evidence); unauthenticated and foreign-owner/foreign-project requests get no content.

## 6b. Remaining integration notes
* Optional: show the four dimensions in the workspace header projection and the Run History list rows (outside this correction).
* `tests/model_statements_tree_acceptance.py` is now part of the mandatory `outputs` role; the optional `ci_contract_inventory` lists it.

## 7. Files
New: `app/v2/statement_drilldown.py`, `app/v2/historical_statements.py`, `app/v2/statements_drilldown_router.py`,
`app/templates/v2/partials/_statement_tree.html`, `app/templates/v2/partials/run_history_statements.html`,
`static/js/model_statements_tree.js`, `static/css/model_statements_tree.css`, tests `test_sc34_*.py`,
`tests/model_statements_tree_acceptance.py`. Modified (additive): `app/workbook/runtime_authority.py`,
`app/v2/output_workspace_projection.py`, `app/library/model_home.py`, `app/templates/v2/partials/sheet_outputs.html`,
`app/templates/v2/partials/run_history_detail.html` (link, now active), `app/templates/library/project_library_list.html`, and in Correction A:
`app/v2/router.py` (registration + one context key), `static/js/model_outputs_workspace.js` (binds both roots), `static/css/model_outputs_workspace.css`
(`:is(#v2-sheet-outputs, #v2-run-statements)`), `static/js/model_run_history_statements_nav.js` (new), `tools/ci_browser_job.py`, `tools/ci_outputs_role.py` (new),
`tools/ci_contract_inventory.py`, tests `test_sc34_historical_production_wiring.py`, `test_sc34_ci_outputs_role.py` and the outputs-role fixture in
`test_model_workspace_consolidation.py`.

## 8. Known limitations
* The outputs fragment grows (drill-down tables are server-rendered for both bases); it is not lazy-loaded.
* Historical assumptions are not reconstructed (labelled link to the Working Copy instead).
* Statement lines that persist no revenue-stream or OPEX sub-line detail cannot be expanded further.

## 9. Verification (local, this branch)
| Check | Result |
|---|---|
| `test_sc34_run_status_dimensions.py` | 22 passed |
| `test_sc34_statements_drilldown.py` | 19 passed |
| `test_sc34_model_home_engine_identity.py` | 2 passed |
| Real Chromium `tests.model_statements_tree_acceptance` (1440 / 768 / 700 / 390 px) | 31 / 31 |
| Existing `tests.model_outputs_workspace_acceptance` (CI browser script) | 79 / 79 |
| Existing outputs/statements, workspace UX, trust, library, RC-2/RC-3 inventory, M3 boundary, run-history and workspace browser suites | 722 passed + 106 passed, 0 failed |
Financial values and canonical Run outputs are unchanged: tests assert node cells equal the flat statement cells, the committed Run and
history entry are byte-identical after GETs, and the engine is never called on GET.
