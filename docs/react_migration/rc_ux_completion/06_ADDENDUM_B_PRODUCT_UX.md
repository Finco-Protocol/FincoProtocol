# Addendum B — Product-facing UX, template onboarding, clean Library

Financial Owner decision: FINCO is presented as a financial modelling product, not as a view of its internals. Implemented inside the existing RC-UX PR.

## 1. Library = My Projects only
* `GET /v2/model-react/my-projects` (`app/v2/react_projects.py`, read-only): only the caller's own, editable, saved projects (same predicate as the canonical `list_workspace_projects_paged`). System reference models are never returned; the legacy `/model-react/library` endpoint is untouched and no longer used by the UI.
* Card fields are saved facts: name, technology, country/market, capacity, **last updated** (latest saved change or Run — the canonical record keeps one activity time), last Run, results status (Results up to date / Results outdated / Not run yet), Open / Scenarios / Run history links. A value that was never recorded is `null` and shown as “—”; nothing is fabricated.
* Filters: search, technology, country, results status, last updated (7/30/90 days), only projects with Runs, archived projects. Sort: recently updated (default), name, last Run. Facet lists and the “no projects at all” state describe *all* of the account's projects, so a search with no match shows “No projects match these filters.” and never the first-use empty state.
* Empty Library: “No projects yet. Create your first project or start from a template.” with **New Project** and **Choose a Template**.
* Not supported, and said so: “recently opened” (opening a project is not recorded).

## 2. New Project — two paths, one creator
* Step 1 asks how to start. **Create a new project** = guided setup: technology, name, market, capacity; FINCO fills in its approved starting assumptions and says so (“A completely blank model is not available.” — no fake blank creation). **Start from a template** = template cards from `GET /v2/model-react/templates` (capability registry; Storage is not offered): description, capacity, construction/horizon, key starting assumptions read from the system template's own saved snapshot through the workbook registry, market note, limitation, preview acknowledgement where the registry says PREVIEW.
* Both paths finish in the unchanged request-keyed, exactly-once creator (`react_new_project`, CSRF-bound, byte-identical — its CSRF successor pin is untouched). The template is never modified (proved by test: baseline snapshot and `updated_at` identical after creation); no internal template id, project code or database metadata is shown.
* Hash routes `#new-project`, `#new-project/new`, `#new-project/template` (Back/Forward work; the in-flight request id still travels in `#new-project:<id>`).

## 3. Product language
Context-aware replacement (no blind global replace). Established finance terms (DSCR, LLCR, PLCR, IRR, NPV, PPA, CAPEX, OPEX, kEUR …) are untouched.

| Internal | Shown to the user |
|---|---|
| Working Copy / Reference Model / Clone Reference | project / template / Start from a template |
| CURRENT / STALE / NOT RUN | Results up to date / Results outdated / Not run yet (raw state kept in `data-*` and the audit trail) |
| composite hash, snapshot id, engine/workbook version | Saved inputs version / Run record / Model version — only in **Advanced details · audit trail** or provenance disclosures |
| canonical engine / persisted / canonical source | model / saved / source |
| Integrity: PASS | Model checks: passed |
| CAS conflict etc. | “This project was changed elsewhere. Reload the latest version before saving.” (stable code kept under *Technical details*) |
| internal source paths (`runtime_summary…`) | Run results / Sponsor returns / Debt schedule … (path in tooltip) |

Single mapping module: `frontend/src/app/productLanguage.tsx` (unit-tested in `src/app/__tests__/productLanguage.test.mjs`). Server display strings that surface in ordinary screens were reworded in the pinned router (exact, reviewed pairs asserted by `tests/test_rcux_governance.py::ROUTER_WORDING`); jargon in registry labels is cleaned at render time.

## 4. Navigation
Removed from ordinary screens: “Legacy workbook ↗”, “Open the legacy workbook”, “FINCO home ↗”, “classic workbook remains available”, “Statements (classic view)”, “Project Library” (now **My Projects**), reference-model rows in the Library. Header: My Projects · New Project. The shell caption no longer says “Renewable project finance”.
**Still open (recorded, not hidden):** the Trust section's two links (reference regression, certificate) open classic HTML fragments — Audit A GAP-R11 stays OPEN. The browser audit allow-lists exactly those two hrefs. Reports and What-if navigation arrive with Lane C/B1.
*Addendum A (React-only navigation) was not delivered to this session; the principle was applied from RC-UX §C3 and this addendum's §5.*

## 5. Business-friendly validation
`friendlyMessage(code, serverMessage)`: a human server sentence is kept; a bare code or jargon is replaced by the business wording; unknown codes never reach the user bare; `FriendlyError` offers expandable *Technical details* with the stable code. Applied to Library, workspace, canonical read hooks, compare/runs/CAPEX/insights error paths.

## 6. Acceptance (real Chromium, in the existing mandatory consolidation role)
`tests/model_react_rcux_product_acceptance.py`: empty Library without system references; the complete template journey for Solar, Wind, Data Center and EV Charging (new project → saved without Run → My Projects → open → Run → Run history → card shows Results up to date and a real last-Run timestamp); guided path disclosure; template untouched + cross-account isolation + read-only template link; lost create response reconciled with exactly one request and one project; populated Library filters/ordering/timestamps; **rendered-text audit of every ordinary screen for all four verticals** (banned vocabulary + Legacy hrefs); viewports 320/390/768/1440.
