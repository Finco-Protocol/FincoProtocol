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
and `.github/workflows/`. PR A infrastructure remains untouched.
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
