# Model V2 — Staging Acceptance B: finding reconciliation

Source: "FINCO Staging — Full Product Behavior & UX Acceptance Audit" (8 Oct 2026,
browser-only run against staging).  Baseline for this wave: `main` at
`92615601eb702edd37285c1119737950ac054f27` (after PR #219).

Every finding below is mapped to a root cause, the correction, and the test that
proves it.  Findings that this wave does **not** change are listed explicitly as
follow-ups; nothing unimplemented is claimed as delivered.  Evidence marked
*local* was produced on a server started from the code under test with disposable
synthetic projects; it is not staging evidence.

Zero diff in `financial_engine/**`, `finco_core/**`, Radar, Yield, token / custody
and deployment configuration.  No financial formula or methodology changed.

## P0

| # | Audit finding | Root cause | Status | Acceptance |
|---|---|---|---|---|
| 1 | Scenario switch corrupts run status (NOT RUN after Base → X → Base) | `select_scenario` cleared the workspace Last Run pointers even when the scenario had a canonical Run | **Fixed in #219** (transactional restore from append-only Run History, fail-closed on a malformed newest row, immutable provenance) | `tests/test_staging_acceptance_a.py::TestScenarioLastRunAuthority`, `::TestRestoreAuthorityHardening` — PASS (local) |
| 2 | Cross-project Compare returns raw `{"detail":"Not Found"}` | Form posted to `/compare-projects`; the canonical route is `/v2/compare-projects` | **Fixed in #219** (+ project picker, friendly unresolved state) | `::TestCompareRouting` — PASS (local) |
| 3 | CAPEX category-level editor saves with no visible effect, starts empty, but marks the model STALE | A category with line items takes its total from those lines; the category scalar is not an input to canonical CAPEX (proved: saving 600 left canonical total at 20,625 while `dirty` became true) | **Fixed here**: for categories with line items the dead editor is replaced by an explained read-only total ("sum of the line items below"); categories without lines keep the editor | `::TestCapexControls::test_category_without_effect_editor_is_replaced_by_an_explained_total`, `::test_category_editor_save_was_inert_for_canonical_capex` — PASS (local) |
| 4 | CAPEX × (Deactivate) does not persist | The deactivate form omitted the `content_hash` field the endpoint requires, so every click got HTTP 422 and nothing changed (reproduced in a real browser; OPEX × includes the field and works) | **Fixed here** | `::TestCapexControls::test_deactivate_*` — PASS; real-browser check: POST 200, row inactive in DB, survives reload (local) |
| 4b | × "inert on reference rows" in OPEX | Not reproduced: with the native confirmation accepted the OPEX control deactivates reference rows and persists. The audit's automation most likely dismissed the confirmation dialog | **Could not reproduce** — recorded as hypothesis, no change | real-browser run (local) |
| 4c | No restore affordance after deactivation | No reactivate command exists in the CAPEX/OPEX command layer ("Reset to reference" is the only recovery) | **Follow-up** (new backend capability, not a defect fix) | — |
| 5 | Dark-on-dark text (Statements, Debt header, editor strips, Runtime Status rows) | Token-driven surfaces switched to dark while their text colour stayed hard-coded dark | **Fixed in #219** (shared tokens/classes) | whole-page contrast audit, desktop + 390 px, light + dark: 0 text nodes below 3:1 (local) |

## P1 / other findings touched by evidence

| # | Audit finding | Root cause | Status |
|---|---|---|---|
| 5 (matrix) | Data Center / EV OPEX (and CAPEX) detail is one raw-code row per category; no row editing; ×/Add absent | Projects created from the Model Home one-click cards go through `POST /library/clone`, which called `create_working_copy` only: **no detailed CAPEX/OPEX line items and no seeded Data Center / EV driver keys**. The New Project form uses `create_reference_seeded_project`, which seeds them | **Fixed here**: cloneable canonical references now use the same seeding authority at the reference's own capacity; Storage, non-reference and unknown sources keep their typed guards. Tests: `::TestLibraryCloneSeeding` (4 technologies + guards) — fail on the old code, pass now |
| 6 | Goal Seek / Run (found by acceptance, not in the audit) | (a) Goal Seek Apply on a legacy-seeded Wind project targeted the non-editable legacy tariff field, so the solved tariff could never be applied. (b) A run stopped by the typed `SHL_MATURITY_RESIDUAL_FAILS_CLOSED` check said only "try again or contact support" | **Fixed here**: Apply always targets the editable canonical `revenue.ppa.base_tariff` (legacy key is only read for the start value); typed fail-closed reasons get a plain-language message. Engine decision unchanged |

## Not changed in this wave (documented follow-ups)

* Run integrity FAIL shown next to a green CURRENT status; LLCR "—" unexplained;
  raw reason codes (`DSCR_SCULPTING_INFEASIBLE_SCHEDULE`) — presentation work.
* Investor / Sponsor tab is read-only with raw enums — needs a field-by-field
  authority classification before any editing is exposed.
* Interest-rate field takes a decimal (0.055) while the card shows 5.50 % — unit
  semantics must be decided before changing a persisted field.
* Implausible Pure Equity MOIC (Wind 286.62x): the audit asks for investigation.
  Not changed: it needs the equity-ledger numerator/denominator reviewed against
  the protected sponsor-schedule engine before any derivation is touched.
* Negative CAPEX amounts are accepted by the existing typed authority (finite
  values only). Whether negatives are valid is a product decision.
* Deep-linkable sheets, dual navigation, dead nav items, "Canonical Slice 1" and
  other internal wording, Escl % typo, "—" versus "0" rendering, contingency tile
  semantics, Storage card copy, project delete/archive, CAPEX/OPEX restore.

## Evidence

Local acceptance (exact main + this branch, synthetic projects): scenario
round-trip PASS, stale handling PASS, Compare Projects PASS, Last Run export and
identity PASS, Goal Seek Solar PASS, Goal Seek Wind PASS after the fix.  Observed
run timings (local, route total / engine): Solar 1.8 / 1.5 s; Wind 25.5 s and
19.6 s for the first two runs after startup, then 4.2 s; Wind after an OPEX line
add 4.6 / 4.3 s.  The slow first Wind runs were not investigated.

Staging was not reachable from the development environment (egress policy), so no
staging deployment or staging browser evidence is included here.
