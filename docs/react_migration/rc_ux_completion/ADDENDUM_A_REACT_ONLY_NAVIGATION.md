# FINCO — RC-UX COMPLETION / ADDENDUM A
## Remove All Legacy Navigation & Complete React-Only Routing

Repository: `Finco-Protocol/FincoProtocol` · Workflow: RC-UX Completion V1 · Priority: **P1 — mandatory before final acceptance**
Target: `https://app.finco.one` · Legacy reference: `https://staging.finco.one`

### 1. Financial Owner decision
FINCO React must operate as a standalone application. Remove all user-facing links, tabs, buttons, menus and redirects that lead from React to Legacy FINCO screens — both direct staging URLs and Legacy routes exposed on the same domain. The user must never need to leave React to complete an approved institutional Model MVP workflow. This is explicitly authorized by the Financial Owner and is part of the existing RC-UX Completion scope.

### 2. Mandatory navigation audit
Inspect the complete React application: main navigation and sidebar; Model Workspace tabs; Project Library and project cards; Financing Studio; Bankability and Senior Debt views; Investors Agreement; Revenue, CAPEX and OPEX sections; Analysis, Sensitivity and Goal Seek; Run History and Reporting; Diagnostics and Model Checks; breadcrumbs, contextual menus and action buttons; empty states, warning messages and error screens; landing-page links that open the Model; redirects after Save, Run, Clone and Create Project.
Identify every user-visible navigation path that leads to: `staging.finco.one`, Legacy Workbook, Legacy Library, Legacy Financing tabs, Legacy Model Analysis, Legacy Reporting, or any other classic/Legacy FINCO Model screen. Also inspect programmatic navigation, route helpers, redirects and dynamically generated URLs.

### 3. Replace Legacy links with React routes
For every detected Legacy link:
* **A. React functionality exists** → replace with the canonical React route.
* **B. Being implemented in RC-UX Completion** → connect to the new React component.
* **C. Intentionally deferred or release-closed** → do NOT redirect to Legacy; show an accurate React-native unavailable state explaining which capability is not yet released. Do not fabricate functionality or silently hide an approved MVP requirement.
* **D. React equivalent incomplete** → record in the master audit gap register and finish the functionality before claiming MVP completion.
No Legacy fallback may be used to close an audit gap.

### 4. Navigation architecture
One canonical React navigation map for FINCO Model. Internal navigation stays within React; project identity and working context preserved; Back/Forward work; deep links load after refresh; unsaved input changes protected; Save and Run remain distinct; Library and Workspace navigation consistent; the three themes remain supported; no redirect loops; no dead tabs or placeholder destinations presented as functional. **Do not create a second competing router.**

### 5. Preserve Legacy for audit only
`staging.finco.one` remains the independent Legacy reference environment. Do not modify or remove the Legacy application. Developers/auditors may use it for comparison and numerical parity testing; audit scripts, internal documentation and development-only comparison tools may reference staging. The restriction concerns **product navigation**: zero user-facing navigation from production React Model to Legacy screens.

### 6. Required tests
Automated navigation and browser acceptance tests covering:
1. every main navigation tab; 2. every financing and analysis subtab; 3. Library → Project → Workspace; 4. New Project → Working Copy; 5. Save → Run → Results; 6. Scenario → Compare → History; 7. Financing → Sponsor → Reporting; 8. direct deep-link access and refresh; 9. browser Back/Forward; 10. navigation with unsaved changes; 11. supported mobile and desktop viewports; 12. feature-gated and intentionally unavailable screens.
Add a test that checks all rendered user-facing Model navigation targets. **Acceptance rule: zero links or redirects from React Model to Legacy Model screens.** The test must reject both explicit staging URLs and same-host Legacy routes — not only a static search for `staging.finco.one`. Verify with browser interactions as well as source inspection.

### 7. Final acceptance gate
RC-UX Completion cannot be declared finished while React still contains user-facing Legacy Model navigation. Required final evidence: complete old-to-new navigation mapping; zero unexpected Legacy navigation targets; zero broken React navigation links; all approved MVP tabs functional; browser acceptance PASS; no regression to canonical Save/Run or CAS; no modification of financial engine behavior; all original audit navigation gaps reconciled; all mandatory exact-head GitHub CI checks GREEN.
Production acceptance on `app.finco.one` requires the separately authorized deployment of the integrated React build. Do not claim live production PASS from local or PR-preview testing.

### 8. GitHub delivery
Part of the existing RC-UX implementation. **No separate PR.** Implement in the RC-UX integration branch. COMMIT → PUSH → UPDATE THE EXISTING RC-UX PR. Focused checks locally, full acceptance through GitHub Actions. No self-approval, no merge to main, no production deployment without separate authorization.

Final requirement: **React-first is replaced by React-only** for all approved Model MVP functionality.

---
### Status at commit 61c7438 (see handover/HANDOVER.md §6)
Done: Legacy workbook/library/financing links removed from the workspace; rendered-text/href audit passes for the 4 verticals.
Open: Trust certificate/validation still link to classic HTML; Historical statements have no React view; no navigation map; no all-targets browser test; redirects after Create/Save/Run/Clone, Back/Forward, deep link + refresh, unsaved-changes and viewport coverage not yet verified.
