# PR B — Model workspace consolidation V1

## Scope and provenance

Presentation-only Option C implementation. One implementation agent; one Draft PR.
Starting main: `5dbfd2a2fb1c6c777b7eb26d93a7090820acce23` (#245 and #246 merged).
PR A #247 owns CI infrastructure; this PR does not modify its branch or workflows.

Required sources read and reconciled:

- `FINCO_COORDINATOR_SOURCE_ARCHITECTURE_CI_AUDIT_V1.md`
- `PR_B_ARCHITECTURE_CODE_CONSOLIDATION_V1_AGENT_PROMPT.md`
- `FINCO_UIUX_STAGING_AUDIT_V1.md`, `FINCO_NAVIGATION_BEFORE_AFTER.md`
- `FINCO_UIUX_CONSOLIDATION_BLUEPRINT.md`, `FINCO_UIUX_FINDINGS.csv`
- Original staging screenshots and DOM evidence in the UI/UX handover.

Required source ZIP SHA-256:
`8da10d7a536d318c67b35dbe7334e364bc72984d2e422b18b2a416328a9fc167`.
Staging's deployed SHA was not confirmed. No shared staging project was mutated.
Authenticated staging mutation acceptance is **NOT TESTED**; local tests use isolated synthetic projects.

## A. Old → new navigation

`app/v2/workspace_destinations.py` is the typed destination authority for presentation.
Server-side contextual groups and browser primary group membership derive from it.
The hidden old activation buttons/panels remain compatibility and HTMX/OOB contracts, not a second visible nav.

| Retained tab ID / old destination | New visible destination |
| --- | --- |
| overview | Overview, accessible project landing |
| input-grid | Inputs → All assumptions |
| project-setup | Inputs → Project & Technical |
| inputs | Inputs → Technical assumptions (specialist retained) |
| revenue | Inputs → Revenue |
| capex / Development | Inputs → CAPEX |
| opex / Operations | Inputs → OPEX |
| debt | Inputs → Financing · Senior Debt |
| investor | Inputs → Financing · Investor |
| tax | Inputs → Tax assumptions |
| scenarios | Scenarios → Selection & overrides |
| outputs | Outputs → Financial Outputs |
| fs | Compatibility alias to Financial Outputs; no duplicate visible entry |
| returns | Outputs → Returns (unique specialist details retained) |
| run-history | Outputs → Run History |
| sensitivity | Analysis → Sensitivity |
| goal-seek | Analysis → Goal Seek / Tender Pricing |
| compare | Analysis → Compare committed runs |
| trust | Trust → identity, assumptions & available lineage |

Export Last Run remains the existing toolbar action; the misleading disabled nav duplicate is removed.
Smart Panel actions and Overview drilldowns continue through existing tab IDs.
Mobile Sections and Insight controls use `aria-controls`/`aria-expanded`; contextual sections close on selection.
Overview is not a competing sixth primary editing area.

## B. Duplication removed

- Removed the manually maintained JS group/default arrays and server nav destination list.
- Removed the competing visible all-sheet strip; preserved physical IDs for existing consumers.
- Removed duplicate Financial Statements table markup and the Outputs statement assembly adapter.
- Both consumers now use `statement_presentation.py` and `_statement_table.html`.
- Route-based Outputs reuses its existing PostRunContext statement projection.
- Annual values come from the existing canonical annual projection, not another aggregator.

Separate Project/Technical and Returns specialists are intentionally retained rather than collapsing their
distinct write contracts or removing unique functionality. No persistence/editor redesign is included.

## C. Statement capabilities

| Capability | Preservation |
| --- | --- |
| Annual / model periods | Canonical annual view plus complete model-period view, display-only selector |
| Dates / full tenor / Year 0 | Existing persisted period/date metadata and Year 0 display toggle |
| P&L / Balance Sheet / PF waterfall | Same canonical projected rows, every persisted period |
| CFADS / Senior facilities / construction | Existing Outputs schedules, no new accounting |
| Sponsor returns / distributions | Existing Outputs sections; supplemental Returns editor retained |
| CIT | Working Copy assumption explicitly separate from unchanged historical accrual |
| kEUR / EUR / precision | Existing formatting over `data-raw`; no changes to persisted amounts |
| Missing / signed values | Missing remains unavailable, not zero; negatives retained |
| Reconciliation / integrity / freshness | Independent existing authorities; STALE names prior Last Run |
| Compatibility | `#fs`, `?sheet=fs` resolve Outputs; FS wrappers/test IDs/OOB targets retained |

The shared renderer isolates Outputs data attributes from the hidden compatibility tables, avoiding ambiguous
document selectors. Assistive captions are contained inside the horizontal scroll region on mobile.
No financial formula, aggregation helper, numeric tolerance or financial golden was modified.

## D. Findings disposition

| Finding | Status | Implemented boundary / remaining limitation |
| --- | --- | --- |
| F01 | FIXED | Missing scalar override remains blank/editable; separate canonical subtotal note. Protected reference displays known subtotal read-only. |
| F02 | FIXED | One five-area hierarchy and contextual sections; old strip not visible. |
| F03 | FIXED | One visible Financial Outputs destination and shared statement projection/renderer. |
| F04 | FIXED | Main sheet first; Insight collapsed and explicitly expandable. |
| F05 | FIXED | Protected cost/technical/merchant affordances distinguish read-only permission from binding. |
| F06 | FIXED | Legacy Last Run, scenario evidence, immutable ledger and unavailable Trust identity explained separately; no fabricated records. |
| F07 | RETAINED BY DESIGN | Missing assumptions labelled honestly; no reverse derivation from valid historical results. |
| F08 | FIXED | P50 help no longer appears on Data Center/EV. Specialist section structure retained. |
| F09 | FIXED | Working commercial/Tax assumptions explicitly separate from Last Run results. |
| F10 | FIXED | OPEX Y1 labelled as including applied contingency; authority unchanged. |
| F11 | FIXED | CAPEX/OPEX/Financing contextual labels. |
| F12 | FIXED | Working CIT assumption versus historical accrual explicit. |
| F13 | FIXED | Persisted model/date-phase versus operating-period labels; no calendar rewrite. |
| F14 | FIXED | Existing toolbar export retained; disabled competing Export nav removed. |
| F15 | DEFERRED | New Project default synchronization is outside this consolidation. |
| F16 | FIXED | Reproduced Investor HTMX eval filter removed in favor of explicit read-only POST-success listener. CSP unchanged. Strict-CSP acceptance must remain green. |
| F17 | DEFERRED | Search, new structured persistence and density preferences belong to UX V2. |
| F18 | FIXED | Trust shortcut states available lineage, not a complete Calculation Trace. |

## E. Input and authority evidence

Real canonical protected reference fixtures confirm Solar C.01 = **3,000 kEUR** and Wind C.01 = **30,000 kEUR**.
The Input Grid never writes those category totals into an absent scalar override.
All reference grid rows remain non-editable. An actual scalar zero remains zero, even with a non-zero category subtotal.
Working Copy cost-line editors and their existing writers remain available.

## F–H. Acceptance evidence and commands

Local Python 3.12 / Chromium, isolated databases and synthetic projects. Local pytest disables the unrelated
globally installed web3 pytest entrypoint; `pytest_asyncio.plugin` is loaded explicitly. No test is skipped to hide
a failure. Runtime tests use supported thread mode. Existing browser helpers with CSP bypass are not F16 evidence.

Observed during implementation:

- Statement/characterization suite: **52 passed**, including four-sector all-row/all-period persisted financial parity.
- Outputs browser acceptance: **79/79 PASS**, normal exit 0. Four sectors, F3 A/B and aggregate Senior, formatting,
  Year 0, CURRENT → STALE → CURRENT, committed scenario identity and owner isolation.
- Broader route/CAS/Revenue/F3/precision set: **233 passed** before correcting four shared-label presentation failures;
  the affected statement suite was then rerun successfully. This is not claimed as a fresh all-green combined run.
- Last Run/Trust/P1.3/export set: **253 passed** plus one obsolete hidden-tab browser selector failure; its migration
  is tested separately and final CI remains required.
- New real-browser coverage: four sectors × desktop/light and mobile/dark, all 19 hash/query destinations,
  Back/Forward, keyboard focus, immediate main surface and strict CSP: **11 passed** including two consecutive
  atomic Saves, explicit Runs and CURRENT → STALE → CURRENT, with persisted Run identity assertions.
- Existing mobile financial, Trust, Hybrid grid, AI Import and Q4 browser contracts are migrated to visible controls,
  not forced clicks on hidden compatibility buttons. Their economic assertions are retained.
- Fresh focused/governance set: **177 passed, 1 existing retired-scope skip**. Exact application-commit browser set:
  **20 passed** (new strict-CSP matrix and canonical protected-reference/Working Copy journeys), plus **8 passed**
  Protocol/Workflow C journeys. Specialist cost-line suites: **38 passed**; a combined local run also hit a shared
  fixed-port collision, so Workflow C was rerun independently rather than treating network failures as passes.
- F3/Q3 expanded evidence: **45/45 PASS**, normal exit 0, after explicitly opening the new Insight control.
  The first GitHub browser workflow was green overall but its pre-existing non-gating F3 evidence step had exit 1;
  this is not accepted as clean evidence. The test-navigation correction requires fresh exact-head CI.

Representative commands:

```text
python -m pytest -q tests/test_model_workspace_consolidation.py tests/test_model_outputs_workspace.py
python -m pytest -q tests/test_model_workspace_consolidation_browser.py tests/test_workflow_c_browser_v1.py
python -m pytest -q tests/test_model_hybrid_inputs_grid_browser.py tests/test_model_ai_import_browser_c.py tests/test_model_q4_browser.py
python -m tests.model_outputs_workspace_acceptance --out artifacts/prb-outputs
python tools/public_safety_scan.py
git diff --check
```

New synthetic screenshots are emitted under `artifacts/model-workspace-consolidation` (or
`WF05_SCREENSHOT_DIR`). Outputs acceptance emits screenshots, route/browser logs and `browser-results.json`.
Artifacts contain synthetic data only and are not substituted for authenticated staging mutation proof.
Compatibility IDs are characterized before consolidation; ordinary hash/query routes and OOB targets are retained.

## I–J. Integration gates and limitations

Exact commit, latest main, ahead/behind, workflow URLs/artifact IDs and fresh Linux full-suite results belong in
the PR body after push. Do not reuse historic audit suite counts or another branch's CI as final evidence.
Until all mandatory exact-head gates and full Linux supervisor/evidence upload finish successfully, this is
**MODEL_CONSOLIDATION_V1_PARTIAL_OR_BLOCKED**, not a readiness assertion.

Zero diff required: `financial_engine/`, `finco_core/`, `domain/`, canonical `app/workbook/` writers and contracts,
`app/persistence/`, financial export authorities, accepted goldens/tolerances/pins, security/auth/CSRF/CAS,
and all workflow infrastructure except the explicitly authorized additive Correction A browser step
in `.github/workflows/protocol_ui_browser.yml`. PR #247's branch/infrastructure remains untouched.
If main advances, integrate it with a normal merge and rerun relevant exact-head gates. No rebase/force push.
Any protected-authority or reviewed-scope guard failure requires an explicit reviewed exception, not a weakened guard.
The local changed-file public-safety scan passes. The complete Windows checkout scan rejects the unchanged
Swagger vendor bundle because Git CRLF conversion changes its exact-byte exemption hash. Read-only comparison
proves the normalized bytes equal the accepted blob (`fd76294e…`). No vendor exemption, line-ending policy or
scanner is changed; the authoritative Linux scan remains a required fresh CI gate.

## K. Rollback

Revert this presentation commit in a separately reviewed PR. No DB migration, history rewrite, input change,
Run identity rewrite or export change is necessary. Legacy IDs and canonical writer/runtime authorities remain
in place. Existing committed Last Runs are unchanged; reopening a page never runs the engine.

No self-approval. No merge. No deployment.

## Correction A — exact-head browser acceptance and refresh race

The 2026-10-11 live refresh confirmed main `5dbfd2a2fb1c6c777b7eb26d93a7090820acce23`,
PR HEAD `7bdee280219f93227c2f1fd3696b41b6e4eea74c`, merge-base equal to main, 2 ahead / 0 behind,
OPEN/DRAFT/MERGEABLE and no comments, submitted reviews or review threads.
These are checkpoint observations, not final acceptance of a later commit.

### Coverage ownership and fail-closed integration

Browser run `38137255958` did **not** execute the new consolidation module. Its original mandatory
pytest selections executed 101 Protocol/Yield nodes (one pre-existing API-B04 deselection),
11 AI Import nodes, 34 WF-05 nodes and 2 Q4 nodes. The Outputs CLI passed 79 checks.
PR #247 HEAD `2b71e29262040c5eea33810cfa40bbc8f2b025b8` also omitted the new module from
`tools/ci_browser_job.py` selections. The full-suite workflow installs neither Playwright nor
Chromium; an import-time browser skip cannot substitute for this missing mandatory execution.

The user explicitly authorized a narrow additive change in #248: a separate **gating** step in
the existing Protocol UI Browser Acceptance workflow, plus a mandatory artifact upload.
All existing selections and controls are retained. Collection failure, test failure, incomplete
node execution, skips/xfails/errors, missing screenshot evidence or missing upload files fail closed.
The evidence includes collected node IDs, executed JUnit cases, synthetic screenshots and actual
tested SHA/tree. Eight deterministic negative/positive controls exercise the exact workflow validator.

**PR #247 integration requirement:** after #248 is independently reviewed and merged, #247 must
normally sync new main and preserve every consolidation node, JUnit/screenshot evidence and its
fail-closed validation in the parallel browser architecture **and mandatory aggregate gate**.
It must freshly prove complete browser coverage; replacing this step with the old selections is
not acceptable. #247's branch was not modified or force-pushed by this task.

### Browser node inventory (17; no added skips, xfails or deselections)

All nodes are under `tests/test_model_workspace_consolidation_browser.py::`:

- `test_four_sector_navigation_mobile_insight_and_csp`: eight exact parametrizations, four
  canonical templates × `[1440-light]` / `[390-dark]`; all five areas, Sections, Insight and unique IDs.
- `test_four_sector_statements_match_persisted_projection_with_csp`: four canonical templates;
  real Run, exact full Annual/Model vectors, missing versus zero, signed values, existing Balance Check
  CSS/title classification, Year 0, full column axis and immutable Last Run across read/format controls.
- `test_legacy_links_context_navigation_history_and_keyboard`: all 19 hash routes, Back/Forward and focus.
- `test_query_aliases_use_canonical_outputs_without_duplicate_table_ids`: all 19 query routes, including fs.
- `test_consecutive_atomic_save_run_stale_current_with_csp_enabled`: real atomic saves/runs and persisted identity.
- `test_consecutive_htmx_workbook_saves_refresh_investor_once_each`: two real Slice 1 saves, exactly one Investor
  GET per successful workbook POST; engine entrypoint forbidden during reads; no Last Run synthesized.
- `test_investor_delayed_response_cannot_restore_pre_scenario_evidence`: a real pre-switch CURRENT GET delayed
  across a real scenario create/select and newer NOT RUN response; old response must not swap or emit errors.

Every browser context in this module keeps CSP enabled. Existing protected-reference/Working Copy and
cost-grid suites retain their financial assertions; the scalar-input/category-subtotal characterization
uses real canonical Solar/Wind reference values and read-only permissions.

### Source-proven Investor race correction

Before correction, the delayed real GET caused an HTMX `swapError` / detached-target TypeError after
scenario replacement (an earlier schedule also left the newer state unresolved). The test is retained;
the failure is not accepted as a harmless transport issue. Normal sequential workbook saves already
produced exactly one refresh each, so no debounce, cache, scheduler or new authority was introduced.

The narrow plain-JavaScript correction invalidates only superseded **presentation responses** when
a workbook POST starts. A listener on the original request source prevents `beforeOnLoad` even when
that source was detached by OOB replacement; a document-only listener would miss that event.
Completed writes temporarily withhold old Investor evidence behind a neutral refresh message until
the existing read-only GET renders it. Listeners are removed on request completion. No GET runs the
engine, no writer/CAS/scenario persistence contract changes, and no `unsafe-eval` relaxation is added.

### Evidence attribution and frozen scope

At checkpoint `7bdee28…`, optional F3 evidence run `38137255958` was independently inspected:
legacy equivalence, financial reconciliation and Chromium all exited 0; all 32 manifest file hashes
match. Artifact `11701501478` records tested merge-ref `7b14a06f769b5c8c80b62412c4c39b90ab825642`,
whose tree `d0ae0674b113e96dd5f406b9fddd869ba653fb79` equals the PR HEAD tree. The pre-existing tool's
textual `pull_request: 240` label is stale; it is not used as current PR attribution. Fresh final-head
F3 evidence, full pytest/supervisor exit and every mandatory workflow remain required after this commit.

Correction A changes only the authorized workflow, Investor presentation JavaScript, the two
consolidation test modules and this report. Financial engine/core/domain/workbook/persistence,
financial goldens/tolerances, Revenue V2/F3 contracts, canonical writers, Run History, governance pins
and authentication/security policy remain zero diff. Final run IDs/results/artifacts belong in PR
metadata after exact-head CI completes. Keep PR OPEN/DRAFT; no self-approval, merge or deployment.
