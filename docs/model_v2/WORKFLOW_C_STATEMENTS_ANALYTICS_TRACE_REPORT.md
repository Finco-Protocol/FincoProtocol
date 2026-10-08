# Model V2 — Workflow C: Statements, Analytics & Trace

Baseline: `main` at `bc9652b0cb620d07ed51df2e4fa329efccea7c13` (after #224 and #225).
Branch: `feat/model-v2-statements-analytics-trace`. One consolidated Draft PR.

Scope discipline: presentation of already-persisted authority only. **No** financial formula,
accounting methodology, tax/debt kernel, engine, Run, Run History, certificate, export or schema change;
zero diff in `financial_engine/**`, `finco_core/**`, Radar, Yield, Crypto, Protocol and deployment
configuration. Workflow D files (`sheet_revenue`, `sheet_scenarios`, `sheet_compare`, `sheet_sensitivity`,
`sheet_goal_seek`, `goal_seek_results`, `scenario_presentation`, `scenario_kpi_projection`) and the shared
`app/v2/router.py`, `post_run_ui.py`, `workbook.html`, `workbook_v2.js`, `field_editor.html` are untouched.
No Workflow D branch or PR existed on GitHub when this work was done.

## 1. Capability inventory (before coding)

| Capability | State | Evidence / action |
|---|---|---|
| Persisted Income Statement / Cash Waterfall / Balance Sheet (`financial_statements` payload) | EXISTS / WORKS | rendered from `pnl`, `pf_cash_waterfall`, `balance_sheet` periods; values verbatim (None stays None) |
| Annual aggregation | EXISTS / WORKS | flows summed, stocks year-end (`aggregate_to_annual`, `is_stock`) |
| Statement presentation (negatives, hierarchy, units, sticky headers) | PRESENTATION GAP | fixed (§3) — the table's header could not stick vertically (no vertical scroll container) |
| Statement freshness vocabulary | PARTIAL | state bar only said "Outputs current / Run required"; now an explicit CURRENT / STALE · prior Last Run / NOT RUN / UNAVAILABLE badge |
| Balance check, share-capital placeholder | EXISTS | unchanged; the placeholder row is styled and titled, its value is not altered. **AUTHORITY GAP**: share capital is not modelled |
| Headline KPIs visible away from Overview | PRESENTATION GAP | the Smart Panel (right column) was rendered *below the whole sheet* (`#model-workspace-main` was a block, so its flex/sticky rules did nothing) — fixed (§2) |
| Canonical KPI catalog / `OutputMetricProjection` | EXISTS / WORKS | reused; catalog not modified (it is shared with Scenario / Run History) |
| Project NPV, total CFADS persisted aggregates | **AUTHORITY GAP** | `runtime_summary.project_npv_keur` is `None`; no aggregate CFADS key is persisted. Shown as unavailable with the reason, never derived |
| WACC, LCOE, payback, discounted payback, cash yield | **AUTHORITY GAP** | reserved vocabulary only in `canonical_analytics` (no canonical authority); listed as gaps, not computed |
| Full Calculation Trace | **AUTHORITY GAP** | needs the clean production run object, not persisted after a run; stays typed unavailable |
| Smart Panel Checks / Assumptions / Trace, validation summary | EXISTS / WORKS | extended (§4), existing contracts kept |
| Workspace navigation (tabs, deep link) | PARTIAL | the `#hash` deep link never worked (the nav script ran before the tab handlers existed); no active highlight; labels collapsed to one letter below 1100 px |
| Run integrity (#224) | EXISTS | surfaced separately from freshness in the strip and worklist |

## 2. Persistent Key-metrics strip

`app/v2/kpi_strip_projection.py` + `partials/_model_kpi_strip.html`, rendered at the top of the Smart
Panel (so it refreshes with the panel after every Save and Run through the existing OOB path — no new
refresh loop, no Run, no engine call). The Trust Pack gains a `kpi_strip_source` (raw persisted
`runtime_summary` and `sponsor_schedule.summary` read from the same workspace record its other sections
read — the request context's single read when one exists).

Metrics: Project IRR, Pure Equity IRR, Total Sponsor IRR (`sponsor_schedule.summary.total_sponsor_xirr`),
Total Sponsor MOIC (`total_sponsor_moic`), Project NPV, Min DSCR, Senior Debt, Actual Gearing
(`actual_gearing_pct`, a fraction), Total CFADS — each formatted by the canonical
`build_output_metric_projection` (raw → display, never the reverse).

* Unavailable → `—` with the reason in the tooltip (`data-available="false"`); a persisted 0 stays 0;
  strings / NaN are rejected.
* STALE Working Copy → values stay visible, the header reads **PRIOR RUN**, each value is marked prior.
* NOT RUN / no committed run → no values.
* Run integrity PASS / FAIL / INCOMPLETE is shown on its own line ("separate from freshness"): a CURRENT
  Last Run can show FAIL, a STALE one is not an integrity failure.
* Drill-down: each metric (and each Overview tile) opens the sheet with the authoritative detail
  (Returns, Senior Debt, Revenue, Financial Statements, CAPEX); only existing tab ids are targeted.
* The wide-screen layout is now a two-column grid (sheet + sticky panel); on narrow screens the panel
  dissolves into the flow and only the strip moves to the top.

## 3. Financial Statements

Template/CSS/formatting only (`sheet_financial_statements.html`, `_money_format.html`, `_fs_runtime_bar.html`,
`workbook_v2.css`): negatives in parentheses, unavailable as `—` (muted), zero as `0`; subtotal/total rows
bold with a rule; unit and basis line per table ("kEUR · Annual · flows summed per calendar year, balances at year
end · N periods"); period selector shows the counts ("Model periods (53)", "Annual (26 yrs)") and states
that the full tenor is shown; a real vertical + horizontal scroll container so the header row and the label
column stay in view; the share-capital placeholder row is italic with an explanatory title; a STALE Last Run's tables
are visibly dimmed and bordered; the state badge distinguishes CURRENT / STALE · prior Last Run / NOT RUN /
UNAVAILABLE. Persisted rows, the period axis, annual aggregation and the balance-check row are unchanged.

## 4. Trace and validation worklist

* **Trace** (`smart_panel_projection.py`): the Trace section stays typed unavailable (same contract and text)
  and now lists, separately, what *is* known: Last Run identity (snapshot, hash, time, engine version),
  the exact-persisted-values rule, the Trust Pack methodology pointer, and an "Authority gaps (not persisted,
  never derived)" list (Project NPV, Total CFADS, LCOE, WACC, payback). The five levels (exact value / typed
  derivation evidence / navigation / full trace / unavailable) are never blended; a missing Last Run reads
  UNAVAILABLE, never AVAILABLE.
* **Worklist**: the validation summary is grouped — Economic input errors · Financial integrity · Missing
  assumptions/evidence · Protected/calculated inputs · Last Run freshness — in a fixed order with typed meanings
  intact. New `INTEGRITY_CHECK` item appears only when the committed Last Run's integrity verdict is not PASS,
  with its typed reason codes; PASS is not invented and freshness never changes it.

## 5. Navigation

`_model_workspace_nav.html` / `workspace_shell_projection.py`: the item of the active sheet is highlighted
(`aria-current`) whichever control changed the sheet (nav, tab bar, deep link, Back/Forward, strip/tile drill-down);
the `#hash` deep link is applied once the tab handlers exist; nav clicks push a history entry and `popstate`
moves between sheets; Up/Down move between items; terminology bridge (`Development — CAPEX sheet`,
`Statements — Financial Statements sheet`, `Assumptions` anchors to the register). Smart-panel/strip
navigation is one delegated listener (the panel fragment is replaced out of band after every Save/Run, so its
former inline script silently stopped working after the first Run). Mid-width screens keep readable labels;
below 720 px the navigation is one horizontally scrolling strip above the sheet.

## 6. Evidence

Tests (all new, none weakened): `tests/test_workflow_c_statements_analytics_trace.py` (projection, worklist, trace,
navigation, number format, and real pages for Solar / Wind / Data Center / EV: strip equals the persisted Last Run,
freshness follows Save → prior run and Run → current with **no model Run** during Save/GET and the Last Run identity
untouched; every statement cell equals the persisted payload over the full period axis; the four statement states;
NOT RUN shows no figures) and `tests/test_workflow_c_browser_v1.py` (one integrated real-Chromium acceptance:
NOT RUN → Run → CURRENT, strip = persisted value, statements full axis + sticky header/column, drill-down,
Back/Forward, trace section, economic edit through the merged cost grid → STALE everywhere → Run → CURRENT; deep links;
keyboard; light/dark contrast; 390 px narrow viewport; Overview tile drill-down).

See the PR description for exact counts, CI results and isolation evidence.

## 7. Deferred / upstream limitations

* Project NPV, total CFADS, WACC, LCOE, payback: no persisted/approved authority — shown as gaps only.
* Full Calculation Trace: not persisted after a run — typed unavailable; no engine re-run was introduced.
* Share capital remains an engine placeholder in the Balance Sheet.
* Overview charts and analytics tiles were not redesigned (their data authorities are unchanged); only drill-down was added.
* Financial Statements export and the statement period axis are unchanged by design.
