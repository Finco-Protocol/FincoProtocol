# RC-UX - implementation inventory, source-ownership matrix and preflight

Status: **coordination document for the RC-UX integration branch.** Nothing here is a financial approval. No financial engine, core or domain
file, no historical pin map, no CI budget or selection and no release flag is touched by RC-UX.

## 0. Preflight (all verified from live state)

| Check | Result |
| --- | --- |
| `origin/main` | `8777b3d6f4523034d1e9f2f2df82933db2d1e586` (merge of PR #285) |
| PR #285 | merged (two-parent merge `4527cea` + `bed275a`); post-merge CI was running at the time of writing |
| Open PRs / competing changes | only dependency-update PRs (#10-#17, #256, #260, #261) and the unrelated Yield draft #184; **no UX work in flight** |
| Release flags on main | BESS, M6, Junior, Revenue V3 `ACTIVATION_ENABLED = False`; M7 `release_approved:false`; no M7 acceptance record |
| Audit evidence | 40 executed checks: 30 PASS, 8 PARTIAL, 2 FAIL (check 25 STALE/CURRENT lifecycle, check 36 Goal Seek); findings UX-001..UX-031 (IDs kept) |
| Staging access from this environment | **none** (network policy blocks `staging.finco.one`); acceptance below runs against a local real-Chromium server, not staging |

## 1. Inventory: EXISTING / REUSE / CORRECT / REPLACE PRESENTATION / REQUIRES APPROVAL

| Surface | Today (verified in code) | Class | RC-UX action |
| --- | --- | --- | --- |
| Post-Run response | `app/v2/post_run_ui.py::build_post_run_ui_state` already OOB-refreshes run controls, banner, toolbar chip, Overview, Debt, Tax, Statements, Returns, Revenue, Scenarios, header, Smart Panel, Run History | EXISTING | keep |
| Trust sheet after Run | `sheet_trust.html` is page-load rendered; **no OOB** (UX-001 root cause) | CORRECT | add OOB from the trust pack the Smart Panel step already builds (build once, reuse) |
| Hybrid status strip | `.hy-status` inside `_hybrid_nav.html`; **no OOB** (UX-002) | CORRECT | split into `_hybrid_status.html` (`id=v2-hybrid-status`), refresh by OOB |
| Freshness / integrity | `resolve_runtime_freshness` + `trust_pack.integrity`; strip already treats them as independent fields | EXISTING / REUSE | one read-only `ResultStatus` projection over them; no new authority, no arithmetic |
| Scenario routes (create/select/rename/archive) | return their own fragments; strip and header keep stale labels (UX-002/020) | CORRECT | same shell OOB set; derive label from scenario id at render |
| Goal Seek panel | `sheet_goal_seek.html`: lazy GET with `hx-swap="outerHTML"` on the panel root + POST target inside it (UX-004) | CORRECT | stable result container outside the swapped node; invariant test; delayed GET/POST browser test |
| Other lazy panels | same pattern in several roots | CORRECT | audit list + same invariant |
| Global "Running..." | CSS `.htmx-request .v2-run-loading` not scoped (UX-012) | CORRECT | scope to the clicked control |
| Cost staging (CAPEX/OPEX) | now `static/js/cost_staging.js` (C-0) | EXISTING / REUSE | keep atomic writer, CAS, focus, structural guards |
| `normNumber()` | strips whitespace, comma -> decimal point (UX-017) | CORRECT | strict ASCII decimal syntax; reject, never reinterpret |
| Server amount parsers | `float(raw)` in `capex_commands._parse_finite_amount_keur` and `opex_commands._parse_finite_opex_numerics` (accepts `1_000`, non-ASCII digits, padded whitespace) | CORRECT (writer boundary) | one shared strict syntax gate in front of both; finite guard unchanged |
| Arrow keys in cost cells | `adjust()` nudges the number (UX-018) | CORRECT | arrows move; nudge only with a modifier |
| Add / Duplicate | immediate POST re-renders and drops staged edits (UX-019) | CORRECT | preserve staged edits across the swap |
| OPEX `total_y1` | F06 sets `value` only, sheet renders stale `display_value` (UX-003) | CORRECT | set `display_value` from the same live total (router, one line) |
| OPEX sticky columns | hard-coded `left: 4.2rem` (UX-005) | CORRECT | one CSS variable for both offsets |
| Navigation manifest | `app/v2/workspace_destinations.py` | EXISTING / REUSE | single source; hierarchy relabel only, aliases kept |
| Shared copy / errors | many inline strings and three error styles (UX-006/031) | REPLACE PRESENTATION | shared macros + code->sentence map; codes unchanged |
| Design tokens / theme | mixed light/dark, no toggle (UX-009/029) | REPLACE PRESENTATION | `model_tokens.css`, `<main>`/`<h1>`/skip link |
| Run History detail | Python reprs, 166,119 px wide, dead Back (UX-024) | REPLACE PRESENTATION | definition list + collapsed technical evidence |
| Revenue contract date rule | JSON 422 swallowed (UX-022) | CORRECT (UI) | show the rule and valid dates; **server rule untouched** |
| Tariff override under contracts (UX-023) | rule in `scenario_revenue_authority.py` | **REQUIRES APPROVAL** | not changed here |
| Export identity (UX-025) | `app/export/institutional_workbook.py` | **REQUIRES APPROVAL** | not changed here |
| Active scenario name persistence (UX-020 if stored) | persistence layer | **REQUIRES APPROVAL** | derive label at render instead; no repository change |
| Trust / methodology wording | governed content | **REQUIRES APPROVAL** | structure only; wording changes deferred |
| Missing LLCR/CFADS/MOIC/NPV persistence | financial-authority question | **REQUIRES APPROVAL** | out of scope |
| `financial_engine/**`, `finco_core/**`, `domain/**`, pin maps, CI budget/selection, release flags | - | **NOT TOUCHED** | enforced by the RC-3 inventory and governance tests |

## 2. Source-ownership matrix

| File / area | A (result lifecycle) | B (shell, copy, tokens) | C (grids, tables, acceptance) | Rule |
| --- | :-: | :-: | :-: | --- |
| `static/js/cost_staging.js` | - | - | **owner** | C only |
| `static/js/workbook_v2.js` | **lifecycle / htmx regions** | - | - | A only (cost region moved by C-0) |
| `app/v2/post_run_ui.py` | **owner** | consumer | - | A only |
| `app/v2/router.py` | scenario/run routes | error-mapping hook | `display_value` line | **coordinator-owned**, one integration diff |
| `app/templates/v2/workbook.html` | partial includes | **owner** | script tags | **coordinator-owned** |
| `_hybrid_nav.html`, new `_hybrid_status.html` | **owner** | consumer | - | A then B (A first) |
| `sheet_trust.html` | structure / lazy | wording (approval) | - | A completes structure before B edits copy |
| `sheet_goal_seek.html` + lazy panel roots | **owner** | copy after A | - | A only |
| `sheet_opex.html`, `sheet_capex.html`, `field_editor.html` | - | copy after C | **owner** | C only |
| `workbook_v2.css` table/sticky regions | - | tokens (new file) | **owner** | tokens first, then C |
| `app/v2/capex_commands.py`, `opex_commands.py` | - | - | amount syntax gate | C only |
| `workspace_destinations.py`, shell projection, shared macros | - | **owner** | - | B only |
| `tests/` browser acceptance, fixtures | - | - | **owner** | C only |

Order: C-0 (done, reviewed) -> A structure + C editor safety in parallel (disjoint files) -> B tokens/copy (after A's `ResultStatus`) -> C table styling after B tokens.

## 3. C-0 review record

C-0 commit `742afb07aea4293ed1ebe7f815280447e4b601dd` was reviewed read-only by an independent reviewer who was given the diff, not the conclusion.
Result: **PASS on all six checks** - byte parity (parent blob sha256 `84bb5a364289a5ad49e18879bb5323d7de884b78f1c7909edaeb38b47b07dafe` equals new core + module body, no CR/line-ending or trailing-newline difference), `node --check` on both files, unchanged execution position, no weakened assertion, no change outside the six listed files, and no identifier the module shares with the core outside the IIFE.
One note, accepted: the module is now a separate `<script>` element, so a top-level throw in `workbook_v2.js` no longer prevents the cost grid from initialising (fault isolation, not a change to normal behaviour).
Baseline vs extraction on the 14-module JS/cost-editing ring: unmodified main 425 passed / 1 failed; extracted tree 425 passed / 1 failed - the identical single failure (`test_model_workspace_productivity_v1_browser::TestDenseLayout::test_first_row_save_control_is_clickable_under_the_sticky_header`, a null element inside the test's own `page.evaluate`, pre-existing on main).
