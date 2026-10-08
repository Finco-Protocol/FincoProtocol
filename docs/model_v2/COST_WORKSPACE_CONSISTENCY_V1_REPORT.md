# Model V2 — Cost Workspace Consistency V1

Scope: one consolidated CAPEX / OPEX workflow across Solar, Wind, Data Center and
EV Charging — line lifecycle (ACTIVE → INACTIVE → REACTIVATED), provenance
presentation, totals reconciliation against canonical `ProjectInputs`, and
Last Run / scenario safety.

Base: `main` at `5de76e5b944350a57dff1121c80f77d3afbe23da` (after #220, #221).
Evidence marked *local* comes from a server started from the code under test with
disposable synthetic projects; no staging evidence is included.

**Zero diff** in `financial_engine/**`, `finco_core/**`, `finco_radar/**`,
`finco_yield/**`, `finco_protocol/**` and deployment configuration. No pricing,
debt, tax or waterfall methodology changed. The canonical negative-amount policy
is unchanged.

## 1. Changed-file map

| Area | File | Change |
|---|---|---|
| Persistence | `app/persistence/capex_sub_lines.py`, `app/persistence/opex_sub_lines.py` | `reactivate_sub_line_with_version` (exact inverse of deactivate, guarded by `row_version`), `list_inactive_sub_lines` |
| Commands | `app/v2/capex_commands.py`, `app/v2/opex_commands.py` | `reactivate_capex_line` / `reactivate_opex_line` inside the existing exclusive transaction + composite-identity CAS |
| Routes | `app/v2/capex_router.py`, `app/v2/opex_router.py` | `POST /v2/capex/line/reactivate`, `POST /v2/opex/line/reactivate` (generated from the deactivate handlers: same stale / conflict / render behaviour) |
| Context | `app/v2/router.py` | `_inactive_cost_lines` feeds both sheet contexts (full page and HTMX swaps) |
| Presentation | `app/templates/v2/partials/sheet_capex.html`, `sheet_opex.html`, `static/css/workbook_v2.css` | "Inactive lines" block with Reactivate; explained read-only category total where lines own the total; calculated rows show the live derived value; "Year 1 kEUR" / "Escalation %" headers; readable hints in dark mode |
| Run boundary | `app/services/opex_sub_lines_integration.py` | seeded rows replace the base consistently (see §5) |
| Tests | `tests/test_cost_workspace_consistency_v1.py`, `tests/test_cost_workspace_browser_v1.py`, one assertion in `tests/test_staging_acceptance_a.py` | see §9 |

## 2. Line lifecycle

* **ACTIVE → INACTIVE**: existing deactivate (soft delete, `is_active=0`). Nothing is
  physically deleted; deactivation is never a delete.
* **INACTIVE → REACTIVATED**: new, per kind. Same exclusive transaction and
  composite-identity CAS as every other cost command; rejected when the hash is
  stale, the `row_version` is stale, the row is already active, the row does not
  exist, the project is a protected reference, or the caller does not own it.
* Preserved on reactivation (asserted column by column): `sub_line_id`,
  `business_code`, parent category / group, `source`, `label`, `amount_keur`,
  `comments`, and for OPEX `inflation_pct`. `display_order` is kept unless an active
  line in the same group already uses it, in which case the line goes after the last
  active line so ordering stays unambiguous.
* A reactivated line returns to canonical economics (totals change causally) and
  the Working Copy identity changes. When the net effect of a deactivate +
  reactivate is zero the composite identity equals the Last Run's, so the model is
  truthfully CURRENT (not falsely STALE); the committed Last Run is never touched.

## 3. Source / status vocabulary (what is and is not displayed)

| Classification | Backed by | Shown |
|---|---|---|
| REFERENCE | persisted `source = reference_seed` | yes |
| OVERRIDE | persisted `source = user_override` | yes |
| CUSTOM | persisted user line | yes |
| CALCULATED | typed read-only / derived authority (e.g. Data Center B.08 power, contingency) | yes |
| LOCKED | protected reference project (`project_editable = false`) | yes (existing notice) |
| SCALED | **not persisted per line** — scaling is recorded only in the project-level seed profile | **not shown** (would be invented) |

Category totals: where editable persisted lines own the total, a read-only
"category total — sum of the line items below" replaces the former category-level
editor, which saved (marking the model STALE) without reaching canonical CAPEX/OPEX
(proved for CAPEX Solar, and for OPEX Solar / EV / Data Center). Where a category has
no editable lines (e.g. an unseeded legacy copy) the editor remains: it is that
category's only edit path.

## 4. Per-technology capability matrix (local, current code)

| | Solar | Wind | Data Center | EV Charging |
|---|---|---|---|---|
| CAPEX line add / edit / deactivate / reactivate | yes | yes | yes | yes |
| OPEX line add / edit / deactivate / reactivate | yes | yes | yes | yes |
| Derived power cost | n/a | n/a | B.08 CALCULATED (not editable) | B.08 editable lines (typed driver derives the base item) |
| Real Run after the cycle reads updated inputs | yes | yes | yes | yes |

Every cell is exercised by `test_line_lifecycle_active_inactive_reactivated`
(8 parametrised cases) and, for the HTMX forms, by real-browser tests on Solar and
Data Center.

## 5. Totals reconciliation — a double count found and fixed

Canonical OPEX before the fix, fresh seeded projects (kEUR, Y1):

| | base item(s) | seeded lines | **folded canonical** | run total OPEX |
|---|---|---|---|---|
| Solar | 237.5 (one aggregate item) | 237.5 | **475.0** | 15,137.6 |
| Wind | 458.3 (one aggregate item) | 458.3 | **916.7** | 32,243.0 |

The seeded lines decompose the aggregate, but the fold only replaced base items
whose name matched a seeded `canonical_key`; the aggregate ("User provided year 1
operating expense", which the adapter emits whenever capacity differs from the
reference) matched nothing, so the same cost was counted twice. The sheet showed
the line total while the model ran on double. A second flaw in the same fold: the
replaced-key set came only from *active* lines, so deactivating every line of a
category brought the replaced base item back.

Fix (`opex_sub_lines_integration.py`, application layer): derive the replaced set
from **all** seeded rows (active and inactive) and treat the aggregate as replaced
when seeded rows exist. After the fix: Solar 237.5 / run 7,568.8; Wind 458.3 /
run 16,121.5; Data Center and EV unchanged (named base items were already replaced
correctly). **This lowers Solar/Wind OPEX (and raises their returns) for newly
seeded projects on their next Run** — it corrects a double count, it is not a
methodology change, but it is a visible economic change and is called out for review.

Tests: seeded lines count once (Solar/Wind); deactivating every line of a category
lowers canonical OPEX by exactly that category's lines and reactivating restores the
total (all four technologies). Both fail on the previous fold.

## 6. Last Run and scenario safety

* Cost edits change the composite identity → Last Run STALE; the committed Last Run
  pointers, composite hash and Run History are asserted unchanged until the next Run.
* Scenario navigation after an edit: cost lines are project-level, so every scenario's
  run reads STALE (never NOT RUN, never CURRENT); history is not rewritten.
* Existing scenario cost overrides (`_capex/_opex_sub_line_overrides`, keyed by line
  id) survive deactivate → reactivate (the override lives on the scenario, not the row).
* #219 scenario restoration and #220 request-local context are untouched; no
  cross-request cache was introduced.

## 7. Existing projects

| Case | Behaviour (tested) |
|---|---|
| New Project / one-click clone (seeded since #221) | full lifecycle |
| Working copy created before #221 (no line items) | not reseeded or altered by viewing; custom lines can be added and deactivated/reactivated; CAPEX category editor retained |
| Existing custom lines | unchanged; lifecycle applies |
| Previously deactivated line (plain `is_active = 0` row) | listed under Inactive lines and reactivates with its data intact |
| Scenario overrides | preserved (§6) |

## 8. Browser evidence (local)

Real Chromium against a live server: ×, "Inactive lines (1) — excluded from totals",
Reactivate and reload persistence for CAPEX and OPEX on Solar and Data Center
(`tests/test_cost_workspace_browser_v1.py`, 4 cases; the process exits normally).
Screenshots of the inactive block in light and dark are in the session scratchpad
(`cost_inactive_{capex,opex}_{light,dark}.png`). A whole-page contrast audit with all
groups expanded (desktop and 390 px, light and dark) reports zero text below 3:1.
It also found, and this PR fixes, an unreadable hint in the new dark category-total row.

## 9. Tests (focused, local)

| Suite | Result |
|---|---|
| `tests/test_cost_workspace_consistency_v1.py` | lifecycle ×8, CAS/conflict ×2, owner/protected ×2, scenario/Last Run, legacy, previously-deactivated, display order, aggregate-once ×2, category-removal ×4, scenario overrides ×2, category-editor rules ×5 |
| `tests/test_cost_workspace_browser_v1.py` | 4 real-browser cases |
| related regression (45 existing modules: clone, seeding, OPEX/CAPEX sheets, run integration, scenario / Last Run, Goal Seek, governance) plus the two new modules | **1526 passed, 12 skipped, 3 failed** — the 3 are `tests/test_ui_protocol_shell.py` Radar/API shell tests (NVDA terminal navigation ×2, API placeholders) that also fail on clean `main` in this environment and touch nothing changed here |
| exit behaviour: new modules + `test_staging_acceptance_a` + `test_goal_seek_v1` + `test_p0a_model_execution` | 135 passed; the process returns to the shell ~2 s after the summary, no leftover processes |

## 10. Outstanding limitations / findings not changed here

* **Last Run export input reconstruction** (`app/services/export_service.py`, OPEX fold
  at ~L283–305) appends all persisted lines to the base with no seed replacement, so its
  reconstructed OPEX inputs may differ from the run's for seeded projects. Not verified
  end to end; flagged for the next workstream.
* **Data Center seeding scale**: with capacity 40 MW the B.08 derived power is 8,769
  while the seeded scalar is 17,538 (other categories scale ×2). The driver values do
  not appear to scale with capacity. Not changed (driver-seeding decision).
* SCALED / per-line "locked" provenance cannot be shown without persisting it.
* Negative CAPEX amounts remain accepted by the existing typed authority (product decision).
* Not part of this PR: reordering UX, bulk operations, per-line escalation editing for
  derived items, the remaining audit findings (run-integrity messaging, Investor tab,
  interest-rate unit, navigation).

## 11. GitHub status

Recorded on the PR (head SHA and the five required workflows).
