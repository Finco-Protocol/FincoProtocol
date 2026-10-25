# WF-React-1 — Product Truth & Financial Workspace (Internal MVP correction)

Base: `main` @ `73529503cc2921ea9690cb66927fb7c45e4e1313` (tree `f869c395e67b42694cbcd617c9c465c15d5d0ce3`), which includes merged #375.
Open PR #376 (Run/Clone CSRF, draft) is **not** a base of this branch.

## Evidence-base statement

The private *Internal MVP Deep Audit V2* defect register was **not available** to this workflow (searched the
repository, `docs/`, `OPUS_V1_REVIEW/` and the session filesystem; no package present). The defects below were
therefore **independently confirmed** by driving the unmodified `main` bundle in Chromium against a real persisted
Run (baseline renders reproduced before editing). Mapping to V2 register IDs is **missing evidence** and must be
cross-referenced by the reviewer; each row names the observed defect so the mapping is mechanical.

## Defect coverage matrix

| # | Confirmed defect on main | Status | Proof |
|---|---|---|---|
| A1 | "Design prototype • No live calculations or backend connection" banner on every workspace page | **Resolved** | `Shell` live mode; browser `test_product_truth_*` (all sections + Library) |
| A2 | `DEMO-FIXED-018 · fixed reference` Last Run, `UNKNOWN · NOT CONNECTED`, `NOT EVALUATED` context strip on Results | **Resolved** | nested prototype Results page replaced by `FinancialResults`; same test |
| A3 | Nested second application Shell (duplicate header, breadcrumb, nav) inside Results | **Resolved** | `.fm-topbar` count == 1 asserted per section |
| A4 | Synthetic Library KPIs (`06` projects, `530 MW`, `02` under review, `18 JUN 2025`), portfolio composition (346/184/40 MW), "6 fictional reference projects" | **Resolved** | `LibraryView` rewritten on canonical payload only; forbidden-token browser + static guards |
| A5 | Hardcoded sponsor outputs `Equity IRR 12.46% · Equity MOIC 1.82x` on the live Sponsor sheet | **Resolved** | gated to `synthetic-demo` origin; static + browser guard |
| A6 | "DATA ORIGIN UNVERIFIED", "Source not provided", "Illustrative EUR model view", "Partial example rows", "Calculations are not available here" labels on persisted data | **Resolved** | `canonical-run` origin with canonical wording |
| A7 | Statement "SYNTHETIC SOURCE TRACE … DEMO-FIXED-018" panel + links into the design-harness route `/__mockup/preview/finco-model/…` | **Resolved** | canonical-source panel; no harness links |
| A8 | Shell breadcrumb "Portfolio / Renewables" + avatar "AR" + "EUR · IFRS" + broken harness `ProjectLibrary` link | **Resolved** | live breadcrumb links to `/v2/model-react/` (asserted) |
| B1 | **kEUR canonical values displayed under a "mEUR" label (×1000 error)**; default unit mEUR; EUR scale applied against a mEUR base | **Resolved** | exact-Decimal oracle across EUR/kEUR/mEUR × 0/1/3 decimals |
| B2 | Statement header showed raw `keur`; ratio detection regex `/x$/i` misclassified labels such as "Tax" | **Resolved** | word-boundary + canonical-unit-first classification; node tests |
| B3 | Negative/zero/rounding inconsistencies (float rounding, `(0.0)`) | **Resolved** | exact decimal-string scaling, half-away-from-zero, no negative zero; `units.test.mjs` |
| B4 | DSCR rows scaled/relabelled by unit selector | **Resolved** | ratios never unit-scaled; browser test under all three units |
| B5 | `Up to date` / `Earlier results shown` tag never matched (compared to `Freshness: current`) | **Resolved** | uses canonical `status.freshness` |
| B6 | Results page did not show the canonical Integrity verdict (existing browser test `test_results_distinguish_current_from_stale` failed on main) | **Resolved** | `Integrity: PASS` in Run context; test now green |
| C1 | Library persistence copy ("not stored on a server", "browser-tab session") | **Resolved** | accurate server-persistence description |
| C2 | Library search filtered only the loaded page locally ("Search filters the loaded page locally") with no input wired to the canonical paged list | **Resolved** | server-side search over the canonical list; pagination preserved |
| C3 | Reference vs Working Copy shown via a free-text "stage"; sponsor/size/region columns always empty; "Demo only · not persisted" on real projects | **Resolved** | REFERENCE / WORKING COPY badges, canonical type, template, Run freshness/id/time |
| C4 | Storage reference offered "Create working copy" that the server refuses | **Resolved** | disabled with "Working copy not yet available" (legacy Library parity) |
| D1 | Results showed only filtered-available metrics; unavailable metrics (e.g. Sponsor Net Cash Flow) silently dropped | **Resolved** | unavailable metrics stay visible, with the canonical "not persisted" reason |
| D2 | All three charts hardcoded `null` ("Chart data is unavailable") although the Run persists the series | **Resolved** | 7 canonical time-series charts + value tables (Analysis) |
| D3 | No presentation of EBITDA / operating cash flow / CFADS / debt service / DSCR / sponsor cash flow / debt & equity summaries | **Resolved** | Results + Analysis pages (mapping below) |
| D4 | Statement notes (`Share capital ★ placeholder`, `unavailable` lists) never displayed | **Resolved** | shown under the active statement |
| D5 | "Sponsor Returns" tab actually contains the distribution waterfall | **Resolved (label)** | tab renamed "Distributions"; sponsor cash flows shown in Results |
| E1 | Analysis nav led to a "Capability gated" placeholder; redundant "Run action" note; nav hrefs pointed at harness routes | **Resolved** | live `WorkspaceNav` with real `#section` links; Analysis is a live page |
| E2 | Facility selector always offered "Mezzanine" for aggregate debt | **Resolved** | selector built from persisted facility keys, hidden when single |
| E3 | Responsive coverage | **Resolved** | desktop / tablet / mobile no-overflow tests + screenshots |

### Requires pending #376 integration (recorded, **not** edited here)

| Item | Shared file(s) | Needed change |
|---|---|---|
| Per-row canonical unit metadata in the statements projection (currently only the sheet's first-row unit survives; ratios are classified by label fallback) | `app/v2/react_workspace_router.py` (`_sheet_from_tables`, `_row_texts`) | pass each row's `unit` (and cell `v`) through; the React side already reads `row.unit` first (`resolveRowFormat`) |
| Numeric `v` for statement cells (chart geometry currently parses the authoritative display text) | same router | add `v` beside `text` |
| Financing view developer-facing helper text (e.g. "Persisted via inputs_section form … PARTIAL path") | `frontend/src/app/ux040506Views.tsx` | presentation copy only |
| Run history "Scenario —" column | `ux040506Views.tsx` / router | read scenario label |
| Bundle | `static/react/finco-react.js` | **rebuild after ordinary merge of #376** (minified single line; any textual conflict is resolved by rebuilding, never by hand) |

### Belongs to WF-React-2

Financing / Scenarios / Model-checks / Trust surface copy and structure, Insight panel, Run comparison, export, scenario
KPI compare (`kpi_compare` is explicitly unavailable in the backend), Inputs grid UX beyond what is here.

## Canonical source mapping for every displayed financial KPI

All values are server-formatted strings from `GET /v2/model-react/statements` (persisted Run only). The browser performs
display-unit conversion, rounding, ordering and chart scaling; it derives **no** financial result.

| Displayed | Canonical field | Origin |
|---|---|---|
| Project IRR, Pure Equity IRR, Total Sponsor IRR | `results.metrics[].display` | `RuntimeResult.runtime_summary.project_irr` / `.equity_irr` / `sponsor_schedule.summary.total_sponsor_xirr` |
| Sponsor MOIC | `results.metrics` | `sponsor_schedule.summary.total_sponsor_moic` |
| Total Equity Invested / SHL Funded / Sponsor Distributions | `results.metrics` | `sponsor_schedule.summary.total_*_keur` |
| Sponsor Net Cash Flow | `results.metrics` (unavailable) | not persisted by the clean sponsor schedule → shown "Not available" + reason |
| Minimum / average DSCR | — | not a persisted Run metric → stated unavailable; series shown as persisted |
| Revenue, Operating expenses, EBIT, Net income (annual) | `snapshot.sheets[pl].rows[revenues_keur, operating_expenses_keur, ebit_keur, net_income_keur].annual` | Run P&L statement |
| EBITDA (cash), CFADS, Senior debt service, FCF for distribution (annual) | `sheets[cashflow].rows[ebitda_cash_keur, fcf_banks_keur, senior_total_ds_keur, fcf_for_distribution_keur].annual` | Run PF cash waterfall (`fcf_banks_keur` = CFADS to Senior) |
| CFADS / debt service / DSCR series | `sheets[cfads].rows[cfads_keur, senior_service_keur, dscr].model` | Run CFADS table |
| Debt summary / balance | `sheets[debt].rows[*].model` | Run debt schedule |
| Distribution waterfall | `results.distributions` | Run distribution projection |
| Sponsor cash flow | `results.sponsor_table` | `CovenantGatedWaterfallResult` |
| Run identity, time, scenario, engine, Integrity | `status`, `results.ran_at/scenario`, `status.integrity` | Run identity + committed integrity |
| Library Run state / id / time | `GET /v2/model-react/library` → `last_run` | persisted workspace freshness |

Every table cell carries `data-canonical` (the server text) so the browser tests compare displayed value ↔ canonical
value ↔ API; chart marks carry `data-canonical` and a tooltip with the displayed value and unit.

## Tests added

* `frontend/transfer/scripts/units.test.mjs` — exact EUR/kEUR/mEUR conversion, rounding, negatives, ratios, unavailable.
* `tests/test_model_react_wf1_product_truth_v1.py` — static guards (no prototype/synthetic tokens in live modules,
  no number derivation, canonical-only Shell chrome, units suite).
* `tests/model_react_wf1_browser_acceptance.py` (bodies) executed through nine wrapper nodes in the existing mandatory
  `tests/test_model_workspace_consolidation_browser.py` role (see Correction A) — product truth in every section, unit/ratio/negative/rounding
  oracle, same-Run Results/Analysis/Statements parity, CURRENT/STALE/NOT_RUN consistency (Overview, Results, Analysis,
  Statements, Library), Library pagination/search/status, navigation, responsive (1440/820/390).

Screenshots (real persisted Run): `screenshots/{desktop,mobile}-{library,results,analysis,statements}.png`.

## Boundaries honoured

* No edits to `app/v2/react_workspace_router.py`, `frontend/src/app/api.ts`, `frontend/src/app/types.ts`,
  `frontend/src/app/ux040506Views.tsx` (owned by #376). Clone/Run contracts untouched (`createWorkingCopy`/`runModel`
  callers unchanged).
* Canonical engine, Run identity, CAS, ownership and protected-reference paths untouched; no backend change.
* `static/react/finco-react.{js,css}` rebuilt from this source with `npm run build` (CI bundle-identity gate); it must be
  rebuilt again after #376 is merged forward.

## Correction A (PR #377) — CI V3 recovery, KPI precision, unit integrity

### 1. CI V3 collection governance

* **Failure:** Public Safety and Model Smoke run `40233631274`, job `safety-and-smoke / plan` (`121290669908`):
  `ContractError: collection skip change; reviewed reconciliation authority required`
  (`tools/ci_v3_source_reference.py::reconciliation` compares the Counter of `{nodeid, reason}` collection skips of
  the accepted-source reference with the PR inventory).
* **Reproduced** by collecting `tests/` with `playwright` unimportable (the plan environment): accepted base
  `7352950` yields **66** collection skips; PR head `3255ab4` yielded **67**. The exact delta was one record:
  `tests/test_model_react_wf1_browser_acceptance.py — "playwright not installed in this workflow"`
  (the module-level `pytest.importorskip`).
* **Resolution (PR #375 precedent):** the nine browser cases moved into the already-governed
  `tests/test_model_workspace_consolidation_browser.py` (same module, same `browser`/`live_server` fixture
  lifecycle). Bodies live in the non-collected helper `tests/model_react_wf1_browser_acceptance.py` (no skip), with
  thin wrappers that keep the original test names. The standalone module was deleted.
* **Verified:** collection skips with Playwright blocked are **66 on main and 66 on the corrected head** (identical
  sorted inventory); no node of main was removed; no baseline, pin, allowance or governance source was edited.
  `tools.ci_browser_job.validate_consolidation` (the role's fail-closed inventory/JUnit/screenshot verifier) passes
  locally on the 45-node module (36 original + 9 WF-React-1), driven by the role's own inventory plugin.

The nine nodes: `test_product_truth_no_prototype_or_synthetic_content_in_any_section`,
`test_statement_units_ratios_negatives_and_rounding_match_canonical_api`,
`test_results_and_analysis_values_are_the_canonical_values_of_the_same_run`,
`test_current_stale_not_run_are_consistent_across_every_surface`,
`test_library_search_pagination_and_reference_working_copy_status`,
`test_results_analysis_navigation_and_back_forward`,
`test_responsive_layout_has_no_page_level_horizontal_overflow[desktop|tablet|mobile]`.

### 2. Monetary KPI precision

`metricDisplay()` returned the canonical string unchanged when the display unit equalled the canonical unit, bypassing
the selected precision. It now delegates to `formatMetricDisplay()` (`frontend/src/app/units.ts`): a KPI is monetary
only when its canonical text carries an explicit `EUR`/`kEUR`/`mEUR` suffix, and every such value is re-expressed
through the exact-decimal formatter for every unit/precision (including unit == canonical). IRR, XIRR, MOIC, DSCR,
percentages, unsuffixed text and unavailable text stay verbatim. The canonical string is preserved in
`data-metric-canonical`. Proof: a 3×3×4×16 matrix (576 combinations; positive, negative, zero, midpoint, carry,
no negative zero) against an **independent BigInt oracle** in `units.test.mjs`, and the same matrix in the browser
against an independent `Decimal` oracle for every KPI of a real Run.

### 3. Statement-unit integrity (residual limitation, explicit)

`tests/test_model_react_wf1_unit_integrity_v1.py` runs the real statements route on a real persisted Run, spies the
canonical output projection and compares **every row of the six destinations** with the canonical unit the projection
assigned:

* canonical units present in the statement projection: **`keur` and `x` only** (no percentage rows exist in the six
  destinations; percentages occur only in key metrics, which are verbatim);
* every row's React classification equals its canonical unit; money rows convert exactly, ratio rows never scale;
* rows that depend on **label inference** (canonical unit differs from the sheet-level unit that the router derives from
  the first row): exactly **`cfads.dscr` and `debt.dscr`** (asserted as the exact set); every other row is classified
  from the sheet unit, which assumes a homogeneous-unit sheet (also a limitation until row units are forwarded);
* unit provenance is visible in the DOM (`data-unit-source` = `canonical-row-unit | sheet-unit | label-inference |
  unspecified`), so a reviewer can see it per row; rows with no row unit, no label hint and an unrecognised sheet unit
  are shown **verbatim as "unit unavailable"** (previously silently treated as kEUR);
* unavailable cells (`v is None`) arrive as `—` and are asserted never to render as zero.

**Minimal backend change required at the authorized #376 integration** (`app/v2/react_workspace_router.py`, not
edited here): in `_sheet_from_tables` / `_debt_sheet` pass each canonical row's `unit` through (`"unit": row.get("unit")`)
and add the numeric cell value beside the text (`_row_texts` -> `{text, v}`); the React side already reads
`row.unit` first, so label inference then disappears for every row with no other change. Chart geometry currently
parses the authoritative display text; with `v` it would use the numeric value.
