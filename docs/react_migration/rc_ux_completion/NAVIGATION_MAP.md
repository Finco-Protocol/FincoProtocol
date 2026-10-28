# RC-UX Completion V1 — Addendum A: navigation map (old target → React route)

Rule (Financial Owner): FINCO React is a standalone application. No user-visible link, tab, button, menu or redirect leads from the React Model to a
Legacy screen — neither `staging.finco.one` nor a classic route on the same host. `staging.finco.one` stays the audit reference (scripts and docs
only). One canonical router (`/v2/model-react/<project>#<section>` with `?financing=` / `?analysis=`); no second router was added.

## 1. Canonical React navigation map

| Destination | React route |
|---|---|
| My Projects (Library) | `/v2/model-react/` |
| New Project wizard (two paths) | `/v2/model-react/#new-project` · `#new-project/new` · `#new-project/template` |
| Project workspace | `/v2/model-react/<project_code>` |
| Sections | `#inputs` `#statements` `#financing` `#results` `#scenarios` `#analysis` `#diagnostics` (Model checks) `#trust` (`#overview` = landing) |
| Financing subtabs | `?financing=terms\|overview\|bankability\|facilities\|sources-uses\|investors#financing` |
| Analysis tools | `?analysis=overview\|sensitivity\|goal-seek\|whatif\|runs#analysis` |
| Input studios | Inputs › Studios: CAPEX spending profile · Revenue assumptions · Import from Excel / CSV |
| Trust evidence | `#trust` — explicit buttons "Run the reference regression" / "Request certificate" (results shown in place) |
| File downloads (attachments, the page does not leave) | `/v2/workbook/export`, `/v2/workbook/run-history/export` — the ONLY non-`/v2/model-react` paths a rendered control may name |

## 2. Old Legacy / classic target → replacement

| Old target (Legacy / classic) | Class (Addendum A §3) | Now |
|---|---|---|
| `staging.finco.one/*` (any) | — | No product link. Present only in audit documents and the audit scripts. |
| `/v2/workbook?project=…` (Legacy workbook, any tab) | A | The section routes above. |
| `/library`, `/library?…` | A | `/v2/model-react/` (My Projects). |
| `/projects/new` | A | `#new-project` wizard (Create New / Choose a Template). |
| `/library/clone/{id}` (browser redirect) | A | Creation is a fetch to the existing canonical writer; the browser opens `workspace_url` (`/v2/model-react/<code>`). |
| Legacy Financing tabs (bankability, two-senior, sponsor/SHL) | A / B | `?financing=…#financing` subtabs. |
| Legacy Model Analysis / Sensitivity / Goal Seek / What-if | A | `?analysis=…#analysis`. |
| `/v2/workbook/run-history` (list, compare) | A | Analysis › Run history & compare (`?analysis=runs`). |
| `/v2/workbook/trust/certificate`, `/v2/workbook/trust/validation` (classic HTML fragments) | **B (built here)** | `#trust`; `GET /v2/model-react/trust/certificate`, `/trust/validation` (adapter `app/v2/react_trust.py`, same canonical builders, allow-listed JSON). |
| `/v2/workbook/run-history/statements` (historical statements) | **A (React)** | Analysis > Run history & compare > "View statements" opens `HistoricalStatements` in React (`GET /model-react/analysis/run-statements`, cell-for-cell equal to the Legacy page; test `test_model_react_rcux_run_statements_v1.py`). The Run **detail** page (`/v2/workbook/run-history/detail`) has no React twin: its evidence is covered by the Run history list, Compare and the statements view; export stays the file download. |
| `/v2/capex/spending-profiles` | A | Inputs › Studios › CAPEX spending profile. |
| `/v2/import` (Excel/CSV import) | A / B | Inputs › Studios › Import from Excel / CSV (adapter `app/v2/react_import.py`). |
| Credit decision (`/v2/credit-decision`) | **A (React)** | Analysis > Run history & compare > "Credit decision" panel (`GET /model-react/analysis/credit-decision`, JSON equal to the Legacy embedded payload; test `test_model_react_rcux_credit_decision_v1.py`). IC pack / credit pack / FINCO Verify pages stay unlinked (open gap R12-IC, owner-blocked: no JSON authority released). |
| `/login` | — | Not rendered as a link; the session guard redirects, not a product navigation. |

## 3. Redirects (programmatic navigation) audited

| Action | Behaviour |
|---|---|
| Create project | `workspace_url` = `/v2/model-react/<code>` (opened with `location.assign`); verified for both wizard paths. |
| Save (field, grid, studios, import) | No redirect; the page stays on the same URL (verified for the grid Save). |
| Run | Canonical Run, then reload of the SAME `/v2/model-react/<code>` URL. |
| Open from My Projects | `/v2/model-react/<code>`; "My Projects" returns to `/v2/model-react/` and Back returns to the workspace. |
| Unsaved changes | Leaving the workspace asks first (Stay / Discard); no navigation happens while the user stays. |
| Deep link / refresh / Back / Forward | Hash sections and the `financing` / `analysis` query survive refresh; Back/Forward walk the section history. |

## 4. How this is enforced

* `tests/model_react_rcux_navigation_acceptance.py` (mandatory consolidation role): every rendered target (`a`, `area`, `form`, `formaction`,
  `iframe`/`frame`, `[data-href]`, `meta refresh`) of every section and every subtab/studio/tool, all four verticals, Library→Project→Workspace,
  New Project→Working Copy (both paths), Save→Run→Results, Scenarios→Compare→History (disclosures opened), Financing→Sponsor→Reporting→Trust
  evidence, deep link + refresh + Back/Forward, the unsaved-changes guard, 320/390/768/1440 px × three themes, template and no-Run gated
  screens, plus a negative control that proves the audit fails on an injected staging link, an injected same-host classic link and a real
  navigation to `/library`. The browser also logs every top-level navigation: all must stay under `/v2/model-react`.
* `tests/test_rcux_navigation_source.py` (no browser): the classifier rejects staging **and** same-host classic routes, accepts only React
  destinations, hash links and the two export downloads; source inspection of `frontend/src` finds no navigation sink naming a classic route.
* `model_react_rcux_product_acceptance.py`: the former Trust exception (`PENDING_GAP_R11`) was removed — no allow-list remains.

Production acceptance on `app.finco.one` requires the separately authorised deployment of this build; nothing here claims a live PASS.
