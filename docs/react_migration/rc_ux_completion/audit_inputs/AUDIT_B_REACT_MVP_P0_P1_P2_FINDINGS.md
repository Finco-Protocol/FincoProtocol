# FINCO React MVP — prioritized findings

Audit date: **27 October 2026, Europe/Zagreb**. Evidence timestamps use UTC. Target: latest reviewed main `6f10f3927b33a5715ac6313da200d0f96c023524`, tree `62e70c3bfda7a91280c8c16acc89eeef9f780d6b`.

**Verdict: REACT PILOT BLOCKED.** F01 is a financial unit-contract failure. F02 prevents trustworthy statement attribution. G01 and hosted deployment/access verification remain release gates. This verdict concerns pilot acceptance, not an assertion that every workflow fails.

Severity: P0 = financial/data integrity blocker; P1 = material trust or release blocker; P2 = usability/presentation correction. Recommendations and governance gaps are explicitly separated from confirmed product defects. No source changes, PR, merge or deployment were performed.

## Register

| ID | Priority | Classification | Finding |
|---|---|---|---|
| F01 | P0 | Confirmed financial/data defect | Financing percentage projection and Save disagree with typed debt authority |
| F02 | P1 | Confirmed presentation defect | Statements identify Data Center, Wind and EV projects as a placeholder Solar project |
| G01 | P1 | Confirmed governance gap; not a browser failure | D-029 remains release-closed despite executable integrated client paths |
| F03 | P2 | Confirmed traceability defect | Short Run identifiers collide within the same hour |
| F04 | P2 | Confirmed misleading product copy | Assumption grid says CAPEX/OPEX writer is out of scope while a live editor is directly below |
| U01 | P2 | UX recommendation supported by measured layout | Inputs are excessively long and repeat field/table scaffolding |
| U02 | P2 | UX recommendation supported by browser text | Engineering and governance implementation details dominate routine forms |
| U03 | P2 | UX recommendation supported by mobile capture | Mobile top navigation hides later destinations without a strong scroll cue |
| F05 | P2 | Confirmed label defect | Capacity labels duplicate their unit |
| F06 | P2 | Confirmed text-rendering defect | Results prints a literal Unicode escape in DSCR guidance |

## F01 — P0: Financing percentage projection and Save disagree with typed debt authority

**Classification:** Confirmed financial/data defect.

**Workflow and reproduction:** Open a disposable Solar Working Copy → Financing. Observe All-in Interest Rate (%) = 0.055 and API display_value = 5.50%. Enter 0.056, Save All-in Interest Rate, reload. Read the authorized debt projection and the disposable workspace typed schedule.

**Expected:** One explicit unit contract: 5.6 in a percent editor represents 5.6%; displayed, saved and typed engine rates agree. A genuine 0.056% rate must display as 0.056%, never 5.60%.

**Actual:** The editor begins at 0.055 beside a percent label. Saving 0.056 persists that value and reload preserves it. The API formats it as 5.60%, but ProjectInputSet.to_projectinputs() produces explicit_all_in_rates = 0.0005600000000000001, or 0.056%. Save succeeds and marks prior results STALE. This is a 100× disagreement between formatted evidence and typed pricing, not a statement-rounding issue.

**Evidence:** [solar-financing.png](REACT_MVP_BROWSER_EVIDENCE/solar-financing.png), [solar-api-fields-debt.json](REACT_MVP_BROWSER_EVIDENCE/solar-api-fields-debt.json), [interest-save-outcome.png](REACT_MVP_BROWSER_EVIDENCE/interest-save-outcome.png), [interest-after-reload.png](REACT_MVP_BROWSER_EVIDENCE/interest-after-reload.png), [interest-after-save.json](REACT_MVP_BROWSER_EVIDENCE/interest-after-save.json), [interest-typed-authority.json](REACT_MVP_BROWSER_EVIDENCE/interest-typed-authority.json).

**Reproducibility:** Reproduced through Save/reload; initial raw-versus-formatted discrepancy also appears across the four vertical debt projections. Direct typed conversion independently confirms the saved Solar rate. Financial output deltas were not separately attributed by running a paired 5.6% counterfactual.

**Likely affected source:** `app/v2/router.py:438–444 (magnitude-based percent formatting); frontend/src/app/workflow/SheetFieldsEditor.tsx:181–205 (raw editable value); app/input_adapter.py:_set_financing_interest_rate and snapshot-to-project conversion; app/persistence/projects_repository.py reference snapshot initializers storing fractional interest_rate_pct. Inspect seed/clone materialization as part of root-cause review.`

**Financial/data impact:** Users can mistake a fractional raw value for the intended human percentage and commit materially different debt pricing. PASS integrity checks cannot validate the economic intent of an incorrectly scaled assumption. No hosted data was modified.

**Minimal correction:** Financial Owner must approve the authoritative percent contract and treatment of existing snapshots. Remove magnitude heuristics, emit explicit editable-unit metadata and normalize only at approved server boundaries. Review existing records before any migration. Do not multiply values in React as a speculative patch.

## F02 — P1: Statements identify Data Center, Wind and EV projects as a placeholder Solar project

**Classification:** Confirmed presentation defect.

**Workflow and reproduction:** Open /v2/model-react/disposable-audit-data-center#statements with no query-string project metadata after a committed Run. Compare the outer heading with the statement heading; reload. Repeat on another vertical.

**Expected:** Statements use the authorized project code/name/type from the same workspace as their persisted Run.

**Actual:** Outer heading correctly names the Data Center project. Inner statement heading says PRJ-0241 and FINCO Model project · Solar PV. The same placeholder survives direct-link reload and occurs in the other captured verticals.

**Evidence:** [data-center-postrun-statements.png](REACT_MVP_BROWSER_EVIDENCE/data-center-postrun-statements.png), [data-center-postrun-statements.txt](REACT_MVP_BROWSER_EVIDENCE/data-center-postrun-statements.txt), [confirmed-datacenter-wrong-statement-identity.png](REACT_MVP_BROWSER_EVIDENCE/confirmed-datacenter-wrong-statement-identity.png), [followup-observations.json](REACT_MVP_BROWSER_EVIDENCE/followup-observations.json).

**Reproducibility:** Confirmed on initial and independent follow-up Data Center reads; all vertical statement captures available.

**Likely affected source:** `frontend/src/finco/_workbook/StatementWorkbook.tsx:287,386–388; frontend/src/finco/_shared/FincoShell.tsx:39–58; frontend/src/app/WorkspaceView.tsx statement props.`

**Financial/data impact:** Wrong project/asset identity can contaminate screenshots and review conclusions. This audit did not observe cross-project numerical leakage: the defect is the displayed identity.

**Minimal correction:** Pass canonical workspace identity as required statement props. Eliminate query-string/demo fallback identity on the live component and show unavailable when canonical identity is absent.

## G01 — P1: D-029 remains release-closed despite executable integrated client paths

**Classification:** Confirmed governance gap; not a browser failure.

**Workflow and reproduction:** Read docs/model_v2/d029/D029_OWNER_DECISION_REGISTER.md and D029_EXECUTIVE_REVIEW.md at the audited SHA; inspect RunIntentPolicy and the integrated keyed POST route. Compare with successful local keyed Run/replay acceptance.

**Expected:** An owner-approved release disposition clearly states whether the deployed candidate may be used and which retention, recovery, shared-owner key-space and availability policies apply.

**Actual:** The decision register states RELEASE CLOSED and owner decisions PENDING. RunIntentPolicy.enabled is False, while latest-main clients submit intents and the local HTTP route executes/reconciles them. The policy object is not evidence of a runtime release gate. Documentation also retains pre-merge wording although PR #384 is merged. No owner approval or deployed policy disposition was available to this audit.

**Evidence:** [pr-384.json](REACT_MVP_BROWSER_EVIDENCE/pr-384.json), [acceptance.xml](REACT_MVP_BROWSER_EVIDENCE/acceptance.xml), [main-provenance.json](REACT_MVP_BROWSER_EVIDENCE/main-provenance.json).

**Reproducibility:** Source and documentation state confirmed; production activation and owner approval unverified. This is a release gate, not a claim that idempotency is broken.

**Likely affected source:** `docs/model_v2/d029/D029_OWNER_DECISION_REGISTER.md; docs/model_v2/d029/D029_EXECUTIVE_REVIEW.md; app/services/run_intent_service.py:33–44; app/v2/router.py:2996 onward; frontend/src/app/workflow/WorkflowBar.tsx.`

**Financial/data impact:** Unapproved retention/recovery and shared-project policies cannot be accepted merely because replay tests pass. Runtime activation requires governance evidence.

**Minimal correction:** Obtain an explicit owner disposition and accurate release matrix before enabling a pilot workflow. Keep financial/security policy approval separate from UI cleanup; do not silently change ledger retention, fencing, recovery or protected-reference rules.

## F03 — P2: Short Run identifiers collide within the same hour

**Classification:** Confirmed traceability defect.

**Workflow and reproduction:** Commit two resolved Runs within one hour, then inspect Results/Statements/Scenarios short snapshot labels and compare them with full runs API identities.

**Expected:** A visible Run label distinguishes the selected committed evidence without requiring raw API inspection.

**Actual:** Timestamp snapshot IDs such as 20261026T233127.272989+0000 and 20261026T233344.504536+0000 both shorten to 20261026T233. The full identity exists in API/history evidence, but several high-level labels are identical.

**Evidence:** [solar-postrun-results.png](REACT_MVP_BROWSER_EVIDENCE/solar-postrun-results.png), [rapid-repeat-run.png](REACT_MVP_BROWSER_EVIDENCE/rapid-repeat-run.png), [scenario-followup-history.json](REACT_MVP_BROWSER_EVIDENCE/scenario-followup-history.json), [scenario-followup-reconciled.png](REACT_MVP_BROWSER_EVIDENCE/scenario-followup-reconciled.png).

**Reproducibility:** Confirmed distinct full snapshots with colliding 12-character prefixes. Other displayed timestamps can help disambiguate but do not repair the short label.

**Likely affected source:** `frontend/src/app/WorkspaceView.tsx StatusRow; frontend/src/app/workflow/ScenarioWorkspace.tsx:164; ModelExportView.tsx; FinancialResults.tsx identity rendering; statement status adapter.`

**Financial/data impact:** Increases risk of comparing or citing the wrong historical Run; no incorrect API binding observed.

**Minimal correction:** Use a server-provided short unique Run reference, or show timestamp through seconds with full identity on focus/copy. Reuse one identity presentation across surfaces.

## F04 — P2: Assumption grid says CAPEX/OPEX writer is out of scope while a live editor is directly below

**Classification:** Confirmed misleading product copy.

**Workflow and reproduction:** Open Inputs and scroll from Assumption grid Save to the CAPEX construction plan.

**Expected:** One clear save-scope explanation tells users where each group is saved.

**Actual:** The grid states the canonical cost-line writer is “out of this PR’s scope,” while the same page renders editable CAPEX/OPEX rows and an atomic Save action. The grid boundary itself is valid; the product explanation is obsolete.

**Evidence:** [solar-inputs.png](REACT_MVP_BROWSER_EVIDENCE/solar-inputs.png), [solar-inputs.txt](REACT_MVP_BROWSER_EVIDENCE/solar-inputs.txt).

**Reproducibility:** Confirmed in four vertical input captures.

**Likely affected source:** `app/v2/react_workspace_router.py:557–559; frontend/src/app/CanonicalInputGrid.tsx:247; frontend/src/app/ux040506Views.tsx CostLinesView.`

**Financial/data impact:** Users may incorrectly conclude that cost edits are unavailable or covered by the scalar Save. No failed cost persistence inferred from copy alone.

**Minimal correction:** Replace with “Save assumptions here; save CAPEX/OPEX in the line-item editor below.” Remove PR references.

## U01 — P2: Inputs are excessively long and repeat field/table scaffolding

**Classification:** UX recommendation supported by measured layout.

**Workflow and reproduction:** Open Solar Inputs at 1440px and 390px. Scroll from Project setup through the grid, costs and revenue.

**Expected:** A modeler can find and edit a coherent assumption group without repeatedly scanning duplicate controls and headers.

**Actual:** Full-page captures measure 11,889px high at 1440px and 15,199px at 390px. The grid repeats Field/Value/Unit/Status tables for many single-row categories; setup fields appear again as grid references. Multiple independent Save scopes share one long page.

**Evidence:** [solar-inputs.png](REACT_MVP_BROWSER_EVIDENCE/solar-inputs.png), [responsive-390-inputs.png](REACT_MVP_BROWSER_EVIDENCE/responsive-390-inputs.png), [solar-inputs.txt](REACT_MVP_BROWSER_EVIDENCE/solar-inputs.txt).

**Reproducibility:** Measured in actual Chromium captures; usability impact is an auditor recommendation, not a failed user study.

**Likely affected source:** `frontend/src/app/WorkspaceView.tsx input groups; frontend/src/app/CanonicalInputGrid.tsx section/category mapping; frontend/src/styles/rc-react-mvp.css.`

**Financial/data impact:** Increases missed assumptions and save-scope confusion. No unsaved data loss demonstrated by page length.

**Minimal correction:** Consolidate rows into one table per meaningful group; retain group anchors and a single clear Save scope per editor. Remove repeated table headers and duplicate explanations before adding new components.

## U02 — P2: Engineering and governance implementation details dominate routine forms

**Classification:** UX recommendation supported by browser text.

**Workflow and reproduction:** Open Financing and Results; read help text and KPI captions as an ordinary financial modeler.

**Expected:** Concise financial definitions and actionable reasons for read-only controls; implementation provenance remains available on demand.

**Actual:** Always-visible text includes inputs_section, data-grid-source, PARTIAL path, FLAT/CALIBRATED vectors, R8/N02, composite CAS and RuntimeResult property paths. Dense small help text occupies much of the financing screen.

**Evidence:** [solar-financing.png](REACT_MVP_BROWSER_EVIDENCE/solar-financing.png), [responsive-390-financing.png](REACT_MVP_BROWSER_EVIDENCE/responsive-390-financing.png), [data-center-postrun-results.png](REACT_MVP_BROWSER_EVIDENCE/data-center-postrun-results.png).

**Reproducibility:** Confirmed visible copy; comprehension impact is a recommendation.

**Likely affected source:** `app/workbook/registry.py descriptions; app/v2/router.py field projection; frontend/src/app/workflow/SheetFieldsEditor.tsx; FinancialResults.tsx source captions; ux040506Views.tsx.`

**Financial/data impact:** Obscures the business meaning of inputs and unavailable features. Provenance itself is useful and should remain accessible.

**Minimal correction:** Use short financial hints; move technical provenance into an existing details disclosure. Say “Another change was saved; reload before saving” instead of explaining CAS to a modeler.

## U03 — P2: Mobile top navigation hides later destinations without a strong scroll cue

**Classification:** UX recommendation supported by mobile capture.

**Workflow and reproduction:** At 390px open Financing. Observe the initial primary nav strip; try to locate Scenarios, Analysis and Model checks.

**Expected:** All primary destinations are discoverable and keyboard reachable in the narrow layout.

**Actual:** The visible strip initially shows Inputs, Statements, Financing and Results; later destinations require horizontal navigation. The page fits without document overflow, but the initial strip does not clearly signal the hidden destinations.

**Evidence:** [responsive-390-financing.png](REACT_MVP_BROWSER_EVIDENCE/responsive-390-financing.png), [responsive-320-financing.png](REACT_MVP_BROWSER_EVIDENCE/responsive-320-financing.png).

**Reproducibility:** Visible layout confirmed; no claim that hidden links are inaccessible or broken.

**Likely affected source:** `frontend/src/app/WorkspaceNav.tsx; frontend/src/styles/rc-react-mvp.css navigation overflow rules.`

**Financial/data impact:** Discovery and efficiency impact; no data integrity impact demonstrated.

**Minimal correction:** Keep the existing strip and add a modest overflow affordance or wrap labels. Verify focus scrolling and active-item visibility without adding another navigation hierarchy.

## F05 — P2: Capacity labels duplicate their unit

**Classification:** Confirmed label defect.

**Workflow and reproduction:** Open Project setup for Data Center or EV Charging.

**Expected:** IT Capacity (MW) and Installed Charging Capacity (MW), each with one unit suffix.

**Actual:** Labels render IT Capacity (MW) (MW) and Installed Charging Capacity (MW) (MW). The projection label already contains the unit and the Field component appends it again.

**Evidence:** [data_center-inputs.png](REACT_MVP_BROWSER_EVIDENCE/data_center-inputs.png), [data_center-inputs.txt](REACT_MVP_BROWSER_EVIDENCE/data_center-inputs.txt), [ev_charging-inputs.txt](REACT_MVP_BROWSER_EVIDENCE/ev_charging-inputs.txt).

**Reproducibility:** Confirmed across two verticals.

**Likely affected source:** `app/v2/router.py:_build_sheet_fields vertical field_label; frontend/src/app/workflow/workflowShared.tsx Field; SheetFieldsEditor.tsx.`

**Financial/data impact:** Presentation inconsistency, no numerical conversion defect demonstrated for capacity.

**Minimal correction:** Keep labels unit-free and supply the unit once through metadata.

## F06 — P2: Results prints a literal Unicode escape in DSCR guidance

**Classification:** Confirmed text-rendering defect.

**Workflow and reproduction:** Open Results with a committed Run and read the minimum/average DSCR guidance below KPI cards.

**Expected:** “Analysis → Financial intelligence” or plain words.

**Actual:** The rendered text says “Analysis \u2192 Financial intelligence”.

**Evidence:** [solar-postrun-results.png](REACT_MVP_BROWSER_EVIDENCE/solar-postrun-results.png), [solar-postrun-results.txt](REACT_MVP_BROWSER_EVIDENCE/solar-postrun-results.txt).

**Reproducibility:** Confirmed browser text; literal JSX source corroborates.

**Likely affected source:** `frontend/src/app/FinancialResults.tsx:514.`

**Financial/data impact:** Minor credibility/navigation-copy defect; no numeric impact.

**Minimal correction:** Use the actual arrow character or “under Analysis, Financial intelligence”.
