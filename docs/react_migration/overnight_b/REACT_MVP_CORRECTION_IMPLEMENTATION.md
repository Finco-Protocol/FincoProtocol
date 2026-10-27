# React Institutional Model MVP — product truth, UX consolidation, pilot readiness (Overnight B)

Branch `claude/wonderful-clarke-tiswep` from main `6f10f3927b33a5715ac6313da200d0f96c023524` (tree `62e70c3bfda7a91280c8c16acc89eeef9f780d6b`).
One integrated correction PR. **No merge, deployment, activation or self-approval.** Verdict: see `REACT_FINAL_PR_CI_REPORT.md`.

## 0. Inputs and how findings were verified

The two audit archives named in the brief (`FINCO_REACT_MVP_AUDIT.zip`, `finco_model_mvp_audit_6f10f39.zip`) were **not present
in the execution environment** (searched the whole filesystem; none in the repository). The findings were therefore taken from
the brief's own descriptions and **each one was independently reproduced or refuted in real Chromium against source before
implementation**, as the brief required. Model-MVP-audit items that could not be checked against the archive are limited to
what the brief lists (financing, returns, metrics, vertical availability).

| ID | Brief's claim | Independently verified? | Evidence |
|---|---|---|---|
| F02 | Statement shows placeholder Solar identity | **Confirmed** (Solar, Wind; hostile query overrides all) | `REACT_STATEMENT_IDENTITY_ACCEPTANCE.md` |
| F03 | Short Run labels collide | **Confirmed** (`snapshot_id[:12]` equal for Runs within 10 minutes) | `REACT_RUN_IDENTITY_ACCEPTANCE.md` |
| F04 | "writer out of scope" copy beside a working editor | **Confirmed** (router note + rendered text) | `REACT_INPUTS_UX_REDESIGN.md` |
| F05 | `IT Capacity (MW) (MW)` | **Confirmed** (Data Center, EV Charging; Field = label + unit) | same |
| F06 | literal `→` | **Confirmed** in Results ("Analysis → Financial intelligence"); no other occurrence in live React text | `test_live_react_text_has_no_literal_unicode_escapes` |
| U01 | Inputs 11,889 / 15,199 px | **Confirmed**: 11,889 px at 1440 reproduced exactly | `REACT_INPUTS_UX_REDESIGN.md` |
| U02 | engineering jargon | **Confirmed** (RuntimeResult…, CAS, R8/N02, registry text) | same |
| U03 | later destinations not discoverable at 320–390 | **Confirmed**: nav clipped after "Financing" with no cue | `REACT_BROWSER_ACCEPTANCE.md` |
| G01 | D-029 release-state mismatch | **Confirmed** (merged + reachable; docs say closed; flag unused) | `D029_RELEASE_TRUTH_RECONCILIATION.md` |
| extra | not in the brief | Green/white theme top bar unreadable (chip, "Appearance", "EUR", FM mark, brand caption < 4.5:1); fixed | theme test |
| extra | not in the brief | Stale-bundle cache risk (`REACT_ASSET_VERSION` constant + nginx `immutable 7d`) — **not fixed, out of scope**; owner decision | `REACT_PILOT_DEPLOYMENT_READINESS.md` §3 |

## 1. Scope actually used (Financial Owner authorization, brief §0)

Changed: `frontend/src/app/**`, `frontend/src/finco/_workbook/StatementWorkbook.tsx` + `statementContract.ts`, new
`frontend/src/styles/rx-mvp-correction.css`, `frontend/src/styles/fm-themes.css`, presentation projection/copy in
`app/v2/react_workspace_router.py`, rebuilt `static/react/finco-react.{js,css}`, tests, and these documents.

**Not touched** (verified by `test_model_react_overnight_b_governance.py`): `app/input_adapter.py`,
`app/persistence/projects_repository.py`, `app/runtime/model_execution.py`, `financial_engine/`, the canonical Run endpoint,
Run History writers, D-029 ledger/service/repository, statement numerical services, `.github/` workflows, historical golden
values, **`app/v2/router.py`** (Overnight A), `app/v2/react_poc_router.py`, `returns_projection.py`.

## 2. What changed, by finding

* **F02** `StatementWorkbook` receives the authorized identity; no demo fallback for live Runs; conflict and missing-identity states fail visibly; the workspace no longer writes identity into the URL.
* **F03** one Run-identity contract (`runIdentity.tsx`), applied to Results, Overview, Statements, Scenarios, Run History, Export, Diagnostics/Trust and the Library; full ids available through an accessible disclosure/copy.
* **F04** accurate Save-scope language: per-editor "Saves:" line, a "What each Save writes" table (Project setup, Assumptions, CAPEX lines, OPEX lines, PPA contracts, Financing, Scenario overrides, Run), router copy corrected. No global writer, no autosave, no change to any request.
* **F05** label+unit rendered once (`fieldLabel.ts`).
* **F06** real `→`; a source guard test forbids literal escapes in JSX text.
* **U01** sectioned grid, derived sections collapsed, state badges, sticky anchored navigation, compact scroll-region line tables (heights in the redesign document).
* **U02** plain finance wording with technical notes behind disclosures; interest-rate value representation untouched.
* **U03** the section navigation scrolls inside its own box, signals overflow (fade, scroll buttons, "n of 8 sections · swipe or scroll for more"), keeps the active and the focused destination in view, supports ←/→/Home/End, 44 px targets ≤820 px; no document overflow at 320/390/768/1440.
* **Visual consistency**: every theme verified; green/white top-bar contrast fixed; the corrected and top-bar surfaces are checked against 4.5:1 in all four themes.
* **Institutional truth** (presentation only, no calculation changed):
  * Returns: Project IRR / Pure Equity IRR (share-capital return) / Total Sponsor IRR (all sponsor capital incl. SHL) are separate labelled figures with an explainer; nothing relabelled.
  * Lender/valuation metrics: `results.lender_metrics` reports exactly what the committed Run published (`min_dscr`, `avg_dscr`, `min_llcr`, `project_npv_keur`, `equity_npv_keur`); anything missing is **"Not available"** with a reason — never zero, never a proxy; PLCR is always unavailable; a footnote says this is not a full lender-grade set.
  * Verticals: `workspace.vertical` is read from `app/product_capability.py` (status, runnable, limitations) plus the owner's stated pilot tier. Solar/Wind → "PILOT CANDIDATE"; Data Center/EV Charging → "PREVIEW VERTICAL … validation coverage is narrower than Solar and Wind … not a validated full-vertical financial model"; Storage → release closed; unknown → "scope unconfirmed". The Library shows the same tier. BESS engine admission is unchanged.
  * Scenarios: the page states the canonical override boundary (`supported_editor_fields()`): the listed assumptions are the only ones a scenario can override; all others inherit from the Working Copy. No new scenario authority.

## 3. Governance (protected sources)

Twelve pinned files changed (router, six React sources, bundle JS/CSS, three acceptance files). Per repository practice an
additive **successor layer** (`REACT_MVP_CORRECTION_SUCCESSORS` in `tests/model_mutation_security_successor.py`) admits their exact
reviewed blobs; every original pin, the FIN-VAL layer and the D-029 layer are untouched and re-verified; older tests that asserted
"current file == previous layer" were widened to "∈ admitted layers" (the same step FIN-VAL took for D-029). The authorization
cited is the brief's §0 and is recorded as **relayed, not independently verified**. `tests/test_model_react_overnight_b_governance.py`
proves one-byte drift in any of the 12 paths fails, original and previous blobs stay individually admitted, `app/v2/router.py`
and the CSRF token module are not in the layer, and no unauthorized path differs from baseline.

## 4. Known limitations (carried forward honestly)

* Financing interest rate: unchanged representation, pending Overnight A (F01). Pilot sign-off on financing numbers must wait.
* Data Center / EV Charging are previews; BESS closed; NPV/LLCR/PLCR often unavailable; Solar/Wind are *candidates*, not approved products.
* The React workspace still has no guided Excel import, Goal Seek, sensitivity batches (legacy-only) — unchanged and labelled.
* D-029 policies remain unapproved; the router flag is not a switch (report).
* Stale-bundle cache prerequisite (readiness §3).
* The two audit archives could not be consulted.
* One pre-existing order-dependent flake in the D-029 React Chromium case on unmodified main (see D-029 report §5).

## 5. Outstanding owner decisions

1. Approve or amend the successor layer (and the relayed authorization it rests on).
2. Bump `REACT_ASSET_VERSION` / static cache policy before the pilot (pinned file).
3. D-029 policy decisions and whether the documents should be rewritten (D-029 report §4, §8).
4. PPA-01 and multi-senior pilot status (D-029 report §6).
5. Wait for / integrate Overnight A F01 before pilot sign-off on financing figures.
6. Whether Data Center / EV Charging should stay selectable in a pilot at all.
