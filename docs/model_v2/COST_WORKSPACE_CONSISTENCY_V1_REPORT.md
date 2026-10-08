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
| Run boundary | `app/services/opex_sub_lines_integration.py` | seeded rows replace the base consistently (see §5); shared `fold_opex_with_provenance`, `opex_fold_provenance`, legacy-Run predicate (§11) |
| Run commit / export / freshness | `app/persistence/workspace_repository.py`, `app/services/export_service.py`, `app/workbook/runtime_authority.py` | `opex_fold` record in the Run identity; export replays it; superseded-fold Runs are STALE / export fails closed (§11) |
| Tests | `tests/test_cost_workspace_consistency_v1.py`, `tests/test_cost_workspace_browser_v1.py`, `tests/test_cost_workspace_parity_v1.py`, one assertion in `tests/test_staging_acceptance_a.py` | see §9 |

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

* **Last Run export input reconstruction** — resolved in Correction A (§11).
* **Data Center seeding scale**: with capacity 40 MW the B.08 derived power is 8,769
  while the seeded scalar is 17,538 (other categories scale ×2). The driver values do
  not appear to scale with capacity. Not changed (driver-seeding decision).
* SCALED / per-line "locked" provenance cannot be shown without persisting it.
* Negative CAPEX amounts remain accepted by the existing typed authority (product decision).
* Not part of this PR: reordering UX, bulk operations, per-line escalation editing for
  derived items, the remaining audit findings (run-integrity messaging, Investor tab,
  interest-rate unit, navigation).

## 11. Correction A — OPEX economic authority, export parity, freshness

Independent review found two authority defects in this PR's first head
(`10a04a39`). Both are corrected in the same PR.

### 11.1 Export parity (root cause and fix)

`_apply_capex_opex_folds_from_identity` (canonical Last Run export) still used the
additive OPEX fold, while the Run used the seed-replacement fold. Reproduced on the
first head with real committed Runs: the effective `ProjectInputs.opex` of the Run and
of the reconstructed export differed on **all four technologies** (export kept the
adapter's aggregate item / named base items *and* added the seeded decomposition; a
Y1-total comparison would have hidden the ordering difference found as well).

Fix: one fold function, `fold_opex_with_provenance`, is now used by the Run
(`_fold_user_sub_lines_to_opex`) and by the export. The Run commits, inside the same
exclusive transaction as the composite CAS, an `opex_fold` record in
`last_runtime_identity_json`: `semantics`, `replaced_canonical_keys` (from immutable
seed provenance of ALL seeded rows), `replaces_aggregate`, `active_order` (the
order the Run appended rows, which fixes float summation order). Export replays that
record; it never reads current mutable cost values. A Run without the record fails
closed (below). There is no separate export formula.

### 11.2 Freshness (root cause and fix)

The composite hash covers values and active rows, not the fold semantics. A Run
committed before this correction therefore kept the same composite hash as its
unchanged Working Copy and displayed CURRENT although a new Run calculates different
OPEX (reproduced: after stripping the `opex_fold` record from a fresh Run, i.e. the
exact persisted shape of an old Run, the first head reports CURRENT).

Fix (no hash change, no workbook-wide invalidation): a Run is distinguished by the
presence of `opex_fold` in its identity. `resolve_runtime_freshness` reports STALE
(`source = opex_fold_semantics_superseded`) only when the Run lacks the record **and**
the project has reference-seeded OPEX rows. Projects without seeded OPEX rows fold
identically under both semantics and stay CURRENT. Nothing is rewritten and nothing is
re-run; Run History is untouched. The pre_scenario Base-equivalence path (#219) is
subject to the same check, so it cannot re-label such a Run CURRENT.

### 11.3 Historical Runs

| Persisted Run | Freshness | Canonical export |
|---|---|---|
| committed after this correction (`opex_fold` present) | by composite hash, as before | exact reconstruction |
| committed before, project has seeded OPEX rows | STALE (`opex_fold_semantics_superseded`) | fails closed: `CANONICAL_LAST_RUN_UNAVAILABLE: OPEX_FOLD_PROVENANCE_MISSING` |
| committed before, no seeded OPEX rows | unchanged | unchanged (additive == replacement when nothing is seeded) |
| committed before scenarios / pre-composite identity | unchanged | unchanged |

Affected existing Runs are those of projects seeded since #221 (reference clones and
New Project). Re-running them is the only path to CURRENT; the old values are not
reproduced or relabelled.

### 11.4 Reconciliation evidence

`tests/test_cost_workspace_parity_v1.py` (40 tests) captures the exact
`ProjectInputs` handed to the engine by the real V2 Run and compares them with the
canonical export, field by field and item by item (name, Y1, escalation, order), for
Solar / Wind / Data Center / EV in: fresh, custom additive row (OPEX and CAPEX),
partial deactivation, a whole category deactivated, deactivate + reactivate, and a
non-Base scenario with an amount override plus OPEX/CAPEX contingency (the test
asserts the override and the contingency item reached the Run); Solar and Wind at two
non-reference capacities. Plus: seeded decomposition counts once (Run total equals the
active line sum), a custom row adds exactly its amount, export resolution leaves the
committed identity/hash/snapshot id untouched, legacy-Run freshness and fail-closed
export, re-Run restores CURRENT, and an unseeded project is not invalidated. On the
first head 36 of these 40 fail; with the correction all 40 pass.

### 11.5 Focused tests (Correction A)

19 modules (cost workspace consistency / browser / parity, staging acceptance A, run
binding, run history, export lineage, canonical export authority, V2 export, XLSX
reconciliation, reference canonical Last Run, scenario and compare freshness,
contingency identity, reference seeding, scenario overrides, DC export, OPEX display):
**443 passed, 4 skipped, 0 failed.**

### 11.6 Limitations

* Over-invalidation is bounded but real: a pre-correction Run on a seeded Data Center
  or EV project with no inactive category and no aggregate would fold identically, yet
  is reported STALE because the project is seeded (proving equality would need the
  base inputs at freshness time). One Run restores CURRENT.
* Reordering rows between Run start and commit does not change the composite hash; the
  recorded `active_order` is the commit-time order.
* The three `tests/test_ui_protocol_shell.py` failures (NVDA terminal navigation x2,
  API placeholders) reproduce identically on clean `main` `5de76e5b` in this
  environment (3 failed / 80 passed with the local Chromium) and are unrelated.

## 12. GitHub status

Recorded on the PR (head SHA and the five required workflows).
