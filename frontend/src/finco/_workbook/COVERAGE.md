# FINCO isolated design — workbook coverage

> Acceptance evidence: [`BROWSER_ACCEPTANCE.md`](./BROWSER_ACCEPTANCE.md). Production-integration concept map: [`INTEGRATION_READINESS.md`](./INTEGRATION_READINESS.md) and [`UI_COMPONENT_HANDOFF.md`](./UI_COMPONENT_HANDOFF.md).

## Authority and isolation

Benchmark: user-supplied description of FINCO main at `5996453b8d5bbfaa48bc06922fc6963cf94d2f84`. This sandbox did not access or verify that repository. “Listed on main” below is an inventory attribution, **not independent proof of release, activation or production support**. No original app, API, engine, database, deployment or integration is connected.

All figures, traces, statements, historical runs and scenario comparisons are fixed synthetic examples. Drafts and local Save acknowledgements use browser-tab session storage only; they are not backend persistence and can be reset from the workspace. No engine formulas, automatic Run, computed statement reconciliation, model-specific output or real provenance.

## Coverage matrix

| Canonical family / module | Design destination | State implemented here | Authority / deliberate limits |
|---|---|---|---|
| Project Library | `ProjectLibrary.tsx` → Model Workspace | Five synthetic Solar PV, wind and Solar + BESS contexts; local search/filter/add/open; project ID and technology carry through; Storage visibly preview-gated | Draft session keys are isolated by project ID, but use the same synthetic seed and fixed shared Results; project identity is not a model record |
| Overview | Workspace → Overview | Example-filled visual overview; navigation to grid/statements | Supplied main inventory; release unknown |
| Model Diagnostics | Workspace → Model Diagnostics; shared Model Checks section | Dynamic scalar error count, field-level validation and blocking scalar Save/Run | Financial integrity checks **not evaluated** |
| Scenarios | Workspace → Scenarios; Results → Scenarios panel | Three independently editable local assumption drafts; selection can open fixed Results context | No scenario execution; results stay fixed and unchanged |
| Scenario Compare | Workspace → Scenario Compare | Fixed Base / Downside / Upside matrix with an explicit difference/status column | No deltas or outcomes are calculated from assumptions |
| Run Compare | Workspace → Run Compare | Select up to three fixed illustrative Run records and compare displayed fields | No runs are created; period alignment and input snapshots unavailable |
| Sensitivity | Workspace → Sensitivity | Fixed pre-authored examples selectable by driver and displayed outcome | No live solver; fixtures are partial and synthetic |
| Goal Seek | Workspace → Goal Seek | Target, driver, bounds and solver-state design fields | Solver unavailable; inputs do not reach the model |
| Project Setup / Inputs | Workspace → Project Setup / Inputs | Preserved validated forms, dates and PPA/debt sections | 21 authorized scalar examples, not full real schema |
| Hybrid Input Grid | Workspace default → Hybrid Input Grid | Editable scalar draft + locked saved/reference columns; frozen labels/header; Enter/Shift+Enter, Tab/Shift+Tab, Esc, arrows, undo; atomic validated scalar TSV paste; distinct Save/Run | Formula bar is display-only; locked IRR never changes |
| Revenue / multi-contract PPA | Workspace → Revenue / multi-PPA | Independent local drafts for PPA-A Fixed, PPA-B Indexed and PPA-C Scheduled; mode-specific fields, dates, tariff, share, counterparty and schedule markers | Merchant residual is not derived; no contract overlap, allocation, settlement, P50/P90 or availability engine |
| CAPEX sublines / spending | Workspace → CAPEX / spending | 18 monthly columns, period-end headers, grouped EPC/civil/owner leaf rows, ISO milestone-date markers, separate local period-batch Save; Front-/Back-loaded, S-curve and Milestone profile selectors | Profile choices only change explanatory copy. Fixed synthetic total/debt/equity reference rows are never recalculated or reconciled; not a full project-life schedule |
| OPEX lines / step profiles | Workspace → OPEX / profiles | Default 12 editable quarterly columns and six separately authored locked semiannual references; optional 60-quarter / 30-half-year UX horizon; fixed escalation/step annotations; separate quarterly line Save | Extended quarter cells after the authored 12-period sample are zero placeholders; extended half-year values are dashes, not aggregates. No generated escalation, step-up or forecast |
| Investor / Equity | Workspace → Investor / Equity; Equity tranche | Local commitment, maturity and equity instrument fields; local Save | Multi-investor classes, distribution waterfall, IRR/MOIC calculation unavailable |
| Senior Debt / bankability / multi-facility | Workspace → Senior Debt / facilities; Sources & Uses / reserves | Five separate local drafts: Senior A, Senior B, Junior/Mezzanine, SHL, Sponsor Equity; terms, margin, maturity, grace, repayment, P50/P90, DSCR and PIK examples | Sizing, sculpting, covenant tests, cash sweep, DSRA/DSRF sizing, intercreditor and bankability unavailable |
| Tax and timing | Workspace → Tax & timing | Local date sequence with basic order validation; cash/accrual view, tax rate, loss carryforward, depreciation, VAT, withholding and payment-label fields | Tax computation, tax-loss utilization, depreciation, VAT recovery and cash timing unavailable |
| Financial Statements / P&L | Results → P&L sheet | Fixed annual/model-period snapshots, expand/collapse all, unit/precision formatting, keyboard cell focus and contextual source trace navigation | Partial rows; trace navigation is not calculation lineage or input dependency |
| Balance Sheet | Results → Balance sheet | Separate fixed rows and expandable groups | Fixed balance-check example is not a performed integrity check |
| Cash-flow waterfall | Results → Cash flow | Operating/investing/financing sections and detail groups | No formula evaluation or cross-sheet reconciliation |
| CFADS | Results → CFADS | Fixed EBITDA-to-CFADS / debt-service bridge, DSCR row | No actual covenant test |
| Statements & Debt | Results → Debt schedule | Senior/Mezzanine fixed schedules including construction draws, IDC, fees, opening, interest, principal, service, closing | Partial synthetic facility snapshots; not linked to editor |
| Returns / Sponsor Returns | Results → Sponsor returns | Fixed contributions, distributions, IRR, MOIC | No returns calculation |
| Trust Pack | Workspace → Trust Pack | Assumption/provenance/run/integrity register and linked coverage matrix | No certified Trust Pack, source proof, engine provenance or export |
| Run History | Workspace → Run History; Results → Run History panel | Three fixed illustrative records with links to fixed outputs | No real timestamp, input hash, engine version, append, persistence or execution audit |
| Excel migration | Workspace → Excel migration | Disabled upload/mapping/unsupported-structure/reconciliation/Run-first workflow preview | No workbook parsing, macro/formula import or actual file handling; scalar paste only |
| Exports | Workspace → Exports | Disabled Excel/PDF content and destination controls | No file generation, storage or download |
| Sources & Uses / reserves | Workspace → Sources & Uses / reserves | Fixed €104.8m illustrative sources/uses example, period snapshot and DSRA/DSRF rows | Totals are not linked to facility or cost drafts; no reconciliation, sizing or reserve calculation |
| Financing trace | Workspace → Financing trace; statement/KPI trace panels | Associated input destination, period, Run identity and explicit no-lineage disclosure | Navigation is a design pointer; no verified engine lineage |
| Lender / credit decision | Workspace → Lender / credit decision | Fixed lender-review matrix and facility/case/period selectors; period-level credit rows | No automated sizing, covenant compliance, bankability decision or approval |
| Advanced project / technology modules | Workspace → Advanced project / technology | Explicit gated capability list | Adjacent main inventory; release authority unknown/closed |
| Developer Economics / Decision | Workspace → gated capability sheets | Explicit destinations and unavailable states | No release or calculation authority asserted |
| Acquisition / Investor waterfall | Workspace → gated capability sheets | Explicit destinations and unavailable states | Acquisition underwriting and distribution waterfall unavailable |
| Advanced revenue / BESS / Storage | Workspace → gated capability sheets | Explicit destinations and unavailable states | Merchant settlement, dispatch, degradation and allocation unavailable |
| Data Center / EV Charging / other technology | Workspace → gated capability sheets | Explicit destinations and unavailable states | Technology-specific workspaces are not implemented |
| Construction monthly / operation 3M / 6M choices | Workspace view-only candidates; Results model-period snapshots | Selection/display controls and explicitly partial static samples | Candidate only; no activated frequency policy claimed |

## State semantics

- Scalar `Save` acknowledges the entire valid scalar draft in memory; it never saves cost lines or runs a model.
- CAPEX and OPEX saves acknowledge their own valid line batches independently.
- Period planners use a focused editable-cell grid: arrows skip locked cells; Enter/Shift+Enter and Tab/Shift+Tab stage then move; Esc cancels a live cell edit; Ctrl/Cmd+Z undoes a staged local batch; Shift-click marks a range.
- Rectangular period TSV paste validates all target cells before staging. Ragged/out-of-bounds rectangles, group/summary cells, negative or non-numeric amount cells, and malformed/invalid ISO dates reject atomically. A rejected range leaves every draft cell unchanged and is visible in the workspace; demo Run remains blocked until the paste error is resolved.
- CAPEX has an 18-month illustrative window. OPEX offers a 12-quarter edit grid and an independent six-period read-only semiannual snapshot. These are fixed, partial examples, not activated production frequency policy.
- Scalar, line, Revenue, financing, tax/timing and scenario drafts have per-project browser-tab session scopes and per-record local acknowledgements. Switching sample projects does not reuse another project's draft; contract/facility/scenario records remain separately selectable. Closing the tab or using Reset clears the demo state. This is not backend persistence; all projects still share common synthetic seed values and fixed Results.
- PPA share values, sources/uses, debt/reserve snapshots, tax schedules and scenario outcomes never feed one another. Fixed Results remain DEMO-FIXED-018 regardless of edits.
- Period planner states distinguish **WORKING COPY**, **LOCAL DEMO SAVE · NOT RUN**, and fixed synthetic **LAST RUN** references. Save only acknowledges the relevant browser-tab session line batch; it never recalculates outputs. Closing the tab or using Reset clears demo drafts; none are backend-persisted.
- Dirty scalar/line drafts block the demo Run affordance until their separate saves are acknowledged.
- Invalid scalar assumptions block scalar Save and demo Run. Invalid cost lines block their line Save, remain dirty and therefore block demo Run.
- `NOT RUN` / `STALE DEMO REFERENCE` are UI states, not engine status. Opening the preset demo produces `CURRENT DEMO SNAPSHOT` **only as a UI viewing state**. Financial freshness stays **UNKNOWN / no input linkage**, integrity **NOT EVALUATED**, engine/version **NOT CONNECTED**.
- Main workbook presence, production release authority and prototype interactivity are intentionally separate.

## Iteration 7 design coverage

- Credit Decision is a read-only fixed fixture: lender matrix states use `OBSERVED`, `REVIEW REQUIRED`, `NOT EVALUATED` and `UNAVAILABLE`; no covenant row is marked compliant. Facility and period selectors only choose display context.
- Statement and KPI source traces show the selected metric/value/period, associated design section and `DEMO-FIXED-018`. Opening an input page and returning can restore the statement sheet, view, trace row and horizontal/vertical scroll position. Trace destinations do not prove numerical dependency.
- Statement grids add expand/collapse all, fixed unit display conversion, precision selection, selected cell focus and arrow-key movement. These are presentation/navigation controls only; model outputs remain fixed.
- Scenario Compare, Run Compare, Sensitivity and Goal Seek have separate destinations. Run comparison accepts up to three pre-authored records; unmatched period dates and unavailable input hashes are disclosed rather than inferred.
- Diagnostics separate editable input validation from construction funding, Sources & Uses, debt maturity/DSCR, statement integrity, scenario and provenance states. Financial checks remain `NOT EVALUATED` or `UNAVAILABLE`.
- Import/Export screens are disabled workflow designs. No workbook file, macro, formula, Excel/PDF output or external storage is processed.
- Gated product families are individually listed so navigation coverage does not imply release or implementation.

## Deliberately not implemented

Full production input schema; independent model persistence; contract overlap, merchant residual, P50/P90 and availability allocation; full period generation; debt sizing/sculpting, DSRA/DSRF sizing, Sources & Uses reconciliation; tax/depreciation/VAT calculation; real scenario execution, sensitivity and goal seek; financial integrity checks; lender/credit decision; audited Trust Pack and engine provenance; Excel workbook import/export; BESS/hybrid dispatch and other technology workflows. These are unavailable or explicitly gated design scope, not asserted as released production features.

## Iteration 8 workbook productivity and workflow context

| Area | Current design behavior | State boundary |
|---|---|---|
| CAPEX / OPEX display controls | Both planners offer 0–3 display decimals; category rows can collapse/expand. OPEX's 3M/6M choice retains the default 12Q/6H sample; a separate horizon selector opens the 60Q/30H long UX fixture. | Display-only; no profile, conversion, totals or financial outputs are calculated. |
| Period-grid interaction | Arrows, Enter/F2, Tab/Shift+Tab, Esc, direct single-character editing, Ctrl/Cmd+Z, Shift-click and Shift+arrow range selection are implemented. Rectangular tab/newline paste is validated all-or-nothing against bounds, value type, dates and locked rows. | Browser-tab session staged data only. CAPEX/OPEX line Save is separate from Run; Run is blocked while line drafts are dirty or paste errors remain. Browser acceptance is reported separately from these source-code claims. |
| Cross-screen context | Project identity, selected PPA, facility, scenario, run-comparison selection, OPEX period display, active scalar cell and CAPEX/OPEX cell are carried in navigation query parameters where applicable. Statement navigation carries sheet/view/period/trace/expanded-row/scroll context. | Query strings are navigation metadata, not persisted inputs, authorization, run provenance or backend state. Draft data are retained only in browser-tab session storage; reset/closing the tab clears the demo session. |
| Workflow entry points | PPA links to fixed P&L; CAPEX links to fixed draw/IDC statement; OPEX links to fixed P&L and CFADS; Tax links to fixed P&L; facility/Sources & Uses links to debt schedule/lender review; scenario, comparison, history and Results routes retain selected display context. | Every destination is a fixed synthetic illustration. Links do not assert numerical dependency. |
| Fixed output integrity | Balance Sheet check is explicitly `NOT EVALUATED`; Sources & Uses totals are explicitly not reconciled. Run History catalog and screen use three authored demo records. | No balance check, source/uses reconciliation, run creation, statement calculation or audited lineage occurs. |

See [`ITERATION_7_CLOSEOUT.md`](./ITERATION_7_CLOSEOUT.md) for the Iteration 7 acceptance verdict and [`INTEGRATION_READINESS.md`](./INTEGRATION_READINESS.md) for component-level integration boundaries, required authorities and the ten highest-priority remaining UX gaps below.

## State labels

- **Interactive Demo:** local interactions are implemented but use browser-tab session data or fixed synthetic references; no engine call is implied.
- **Visual Only:** layout is present without working data interaction.
- **Gated:** destination is explicitly unavailable pending verified product/release authority.
- **Missing:** no screen/control exists in this design.
- **Integration Pending:** any real server persistence, API, engine, permissions, import/export or authoritative provenance.

Current classification: Interactive Demo — Project Library search/filter/add/open, project-scoped local drafts, Hybrid Input Grid, PPA-A/B/C editors, CAPEX/OPEX planners, local facility/tax/scenario drafts, statement selection/trace navigation, fixed credit/run-history/compare/sensitivity selectors; Visual Only — Overview, Sources & Uses fixture, Trust Pack and migration/export layouts; Gated — BESS/storage calculations, developer/acquisition/investor waterfall and other technology workspaces; Missing/Integration Pending — actual calculations, formula lineage, canonical persistence/CAS, Excel file handling, live runs and certified credit/integrity checks.

## Ten highest-priority gaps vs. the supplied canonical FINCO inventory

The comparison below is against the user's supplied inventory, **not** an independent audit of FINCO main or a statement that every listed feature is currently released.

1. **Canonical Working Copy and atomic save/run provenance** — browser-tab session drafts now survive same-tab navigation/reload, but authoritative persistence, compare-and-swap revision checks, real run identity, input hash, engine version and audit trail are absent.
2. **Complete authorized workbook schema** — the interactive scalar grid covers 21 examples, not every production input, unit, validation rule or edit-permission boundary.
3. **Multi-PPA revenue execution** — contracts have separate illustrative drafts, but there is no combined allocation check, overlap, merchant residual, shaping/settlement, availability or P50/P90 linkage.
4. **Full-period CAPEX planning and funding linkage** — the 18-month grid is a partial fixture; no full construction horizon, profile application, calculated total, funding draw or IDC dependency exists.
5. **Full-period OPEX and frequency conversion** — quarterly samples and a locked semiannual fixture are independent; there is no full-life projection, escalation/step-up engine or quarterly-to-half-year aggregation.
6. **Debt sizing and lender policy** — Senior A/B, Junior/Mezz, SHL and equity terms are displayed, but no sizing, DSCR sculpting, reserve sizing, cash sweep, covenant test or approval decision exists.
7. **Sources & Uses reconciliation** — the fixed example totals are not tied to facility drafts, CAPEX, fees, IDC or reserves.
8. **Tax and depreciation** — tax/timing fields are local examples; no depreciation, tax loss, VAT, withholding or cash tax schedule is generated.
9. **Full statement lineage and period model** — six fixed statement sheets and navigational traces exist, but no formula lineage, cross-statement reconciliation, generated monthly/quarterly periods or linked drill-through evidence.
10. **Execution and adjacent workflows** — scenario outputs, multi-run comparison, sensitivity, Goal Seek, Excel import/export, certified Trust Pack, BESS/hybrid and other technology workspaces remain fixed, unavailable or gated design surfaces.

## Iteration 8 verification (2026-10-20)

Verification used the existing managed Component Preview Server and Chromium browser interactions; this is not a production or engine test.

- `pnpm --filter @workspace/mockup-sandbox run typecheck` passed. `PORT=5000 BASE_PATH=/ pnpm --filter @workspace/mockup-sandbox run build` passed. `git diff --check -- artifacts/mockup-sandbox/src/components/mockups/finco-model` passed.
- The three existing Canvas frames — Project Library, Model Workspace and Results & Analysis — rendered after the preview restart. Screenshots were captured at 1440×900, 900×900 and 390×844 for each frame. Browser measurements found no document-level horizontal overflow in any of the nine screen/viewport combinations; every screen retained its synthetic/no-backend notice.
- Chromium interaction checks passed for Library search, stage filter and creation of a sixth local demo row; opening Vela Storage carried its name and Solar + BESS technology into the workspace.
- Hybrid Input Grid checks passed for Enter/edit/Esc, arrow movement, local scalar edit, atomic paste rejection for an invalid date, valid two-row paste and separate local Save. Save left the UI at `NOT RUN`; after saving, demo Run opened the fixed 7.82% Project IRR / 12.46% Equity IRR illustration without recalculation. Dirty scalar drafts block Run; a rejected paste leaves the unchanged draft intact.
- CAPEX showed 18 monthly columns in an internal horizontal scroller. Chromium checks passed for arrow and Shift+arrow navigation, Shift-click range highlighting, Enter/Tab/Shift+Tab editing flow, Esc cancellation, Ctrl+Z undo, atomic rejection of a negative-value rectangle and an invalid calendar-date paste, acceptance of a valid 2×2 TSV rectangle, and local Save with Run still gated while unsaved. Profile selection changed explanatory copy only.
- OPEX showed 12 quarterly periods and six independently authored, read-only semiannual periods. An editable quarterly cell was changed and locally acknowledged; Run remained blocked while its draft was unsaved.
- PPA-A Fixed/Indexed/Scheduled modes exposed the corresponding editor state; switching among PPA-A/B/C retained each record’s mode and selected-contract context. Senior Debt B selection updated the active facility and navigation query.
- Results checks passed for the populated Scenario Compare and three-record Run History panels, all six statement sheets, Annual/Model-period switching, and a statement trace round-trip that restored the CFADS sheet, Model-period view and selected row. At 900px, horizontal scroll stayed inside the statement region; actual scrolling kept the header and first metric column anchored.
- No runtime exceptions or browser console errors were captured during the interaction run. Screenshots showed only Vite connection and React DevTools informational messages.

These are browser-verified design interactions, not an automated regression suite. Drafts are retained only in browser-tab session storage; they are not production-persisted. Formulas, calculations, exports/imports, source lineage, and production authority remain unavailable as described above.

## Iteration 9 status

- Implemented: shared model context strip; browser-tab-only demo drafts and Save acknowledgements with explicit Reset; active row/column indication and value/unit/source wording in grid bars; consistent compact sticky finance tables; financing review quick navigation; optional 60-quarter / 30-half-year OPEX UX fixture.
- The long OPEX horizon is a view/keyboard usability fixture only. The first 12 quarter values are authored examples; later editable quarter cells start at zero placeholders. The first six half-year references are authored; later columns are dashes. Neither view derives financial figures.
- Browser test method: Chromium DevTools Protocol against the running mockup preview; keyboard events, real button/select interactions and simulated `ClipboardEvent` TSV paste. No image files were saved; three preview screenshots were inspected at 1440×900, 900×900 and 390×844.
- Project Library: search reduced the register to the Vela row; Solar + BESS filter and local Create project added a sixth fictional row. Opening Vela Storage carried its name and Solar + BESS into the Workspace header/context and displayed the shared-example disclaimer.
- Hybrid Input Grid: F2/Enter staged an invalid −2 MW capacity, showed the blocking summary and disabled Run; correcting to 120 removed the error. Invalid calendar-date TSV was rejected without changing the cell; valid date paste staged. Save displayed DEMO SAVED in the browser tab; separate Run opened fixed DEMO-FIXED-018 values (7.82% / 12.46% / €8.7m / 1.25x).
- CAPEX: the 18-period monthly grid rendered; an editable cell changed by keyboard, showed UNSAVED and blocked Run; internal horizontal scrolling kept the first metric column in place. Save displayed LOCAL DEMO SAVE · NOT RUN.
- OPEX: default 12Q and extended 60Q periods rendered; an editable cell changed and Ctrl/Cmd+Z restored it. Invalid rectangular TSV left both cells unchanged; valid 1×2 TSV staged both values. Dirty state blocked Run; Save changed the line status to LOCAL DEMO SAVE · NOT RUN; separate Run opened fixed results. The 60Q table scrolled internally without document-level overflow at 900px.
- Revenue / Finance: PPA-A/B/C selection, Fixed/Indexed/Scheduled editor changes, independent saved PPA-A and PPA-B counterparty values, and context-strip contract ID updates were exercised. Senior A/B drafts retained different commitments after switching; Junior, SHL and Equity selectors, Sources & Uses and Credit Review routes opened.
- Statements / analysis: all six statement tabs switched; Annual/Model-period, EUR and decimal controls changed. Expanding P&L rows created actual vertical overflow; the header and first metric column stayed anchored during vertical/horizontal scroll. A Revenue cell opened a synthetic trace, navigated to Revenue/PPA and returned to the selected P&L trace/period.
- Results panels: Run History opened three labeled synthetic records; Scenario Comparison opened its distinct fixed-value table. Workbook navigation reached distinct Scenarios, Scenario Compare, Run Compare, Sensitivity, Goal Seek, Diagnostics, Credit, Trust, History, migration, exports and financing-trace surfaces; several are explicitly visual-only or unavailable, not calculation tools.
- Responsive checks: Project Library, Model Workspace and Results at 1440/900/390 CSS px had no document-level horizontal overflow. CAPEX had no document-level overflow at all three widths; the wide schedule scrolled inside its table. Results statement region passed horizontal/vertical scroll and sticky-anchor checks at 900px; Results mobile screenshot at 390px showed no document-level crop. OPEX extended grid at 390px had 60 periods, a 4,330px internal table in a 360px viewport, no document overflow, and a sticky header/first metric label during actual horizontal and vertical scrolling.
- No uncaught exceptions or browser console errors were captured during the exercised flows; preview screenshots showed only Vite and React DevTools informational messages. This is manual browser acceptance, not an automated regression suite. Real financial calculations, persistence, API/engine integration, Excel file import/export, covenant/integrity certification and released product authority remain unavailable.

## Iteration 10 scope and acceptance

- Model Library contexts now use project-ID-scoped browser-tab draft keys. Switching between Solar and Wind cannot display the other sample's PPA or scalar edits. All contexts still start from the common synthetic seed, and all Results remain fixed shared examples; project names do not identify separate financial models.
- Storage/BESS is marked “Preview-only technology” in the Library and shows a workspace gate. Dispatch, degradation, storage revenue and storage calculations remain unavailable.
- Smooth period-scroll controls respect `prefers-reduced-motion`; with the preference enabled, the Results scroll button passed a real browser click and supplied `behavior: auto`.
- Current manual browser interactions and viewport/layout evidence are detailed in [`BROWSER_ACCEPTANCE.md`](./BROWSER_ACCEPTANCE.md). These are not automated regression tests. The preview remains design-only; no canonical service, engine, database or production auth is connected.
