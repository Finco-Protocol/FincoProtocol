# Q3 — Model Quality × FINCO Insight, covenant and scenario intelligence

Status: DRAFT for independent review. NO MERGE / NO DEPLOY. Advisory only.

**MODEL QUALITY / LENDER READINESS ADVISORY** — not bank approval, not lender certification, not SOC 2
certification and not FAST/IFC compliance certification.

## What the user sees

| Where | Content | Authority |
|---|---|---|
| Insight → **Findings** (top) | Run context chip (CURRENT / STALE / NOT_RUN), advisory score, evidence coverage (separate), counts, then groups: blocking failures → lender-readiness findings → missing authority/evidence → passed → not applicable. Each check is an expandable row: category, class, severity, measured value, threshold + threshold authority, evidence source, reason code, owning-sheet link, Explore links. | `app.model_quality` registry (30 stable checks) evaluated by `evaluate_model_quality` over the committed Last Run |
| Insight → **Findings** (covenants) | Minimum DSCR covenant, distribution lock-up DSCR, minimum LLCR, DSRA funding, default DSCR: threshold, threshold authority, observed metric, unit, testing period, headroom, status, freshness, missing-data reason | Q1 checks QM-COV-001..003, QM-CASH-002 |
| Insight → **Explore** | When an assumption or KPI is selected, the Q1 checks that reference it (exact id match only) with a button back to the check | server-rendered `data-sp-q3-link` metadata |
| Insight → **Scenarios** | Each scenario's own newest committed Run (identity, basis, KPIs, Model Quality score/coverage), plus a read-only comparison of the active scenario with a chosen scenario | immutable Run History via existing `_enriched_kpis`, `build_scenario_projection`, `build_compare_rows` |

The pre-existing "Workbook and Trust Pack findings" (field validation, Trust Pack) stay in their own list: Q1 quality
results and field-validation errors are different authorities and are never merged.

## Rules enforced

* The score is the Q1 scorer's number (published only at ≥ 80% weighted coverage, capped at 50 while a blocking
  check fails). JavaScript never computes or adjusts it.
* UNAVAILABLE is never PASS; evidence coverage is displayed separately from findings.
* A covenant row never uses an industry-standard level. ProjectInputs holds no minimum-DSCR covenant and no
  default-DSCR term, so those rows read `CONTRACTUAL_THRESHOLD_UNAVAILABLE`. Lock-up DSCR and minimum LLCR are
  **project inputs**; FINCO cannot tell a default from a negotiated term, so they are labelled
  "Project input (not verified as a contractual term)". A caller that can prove a contractual term passes it as
  `ProjectTerms(contractual=True, …)` and the row is labelled "Supplied contractual term".
* **Threshold binding.** The Run does not persist the terms it was executed with. Working Copy terms are bound to
  the Last Run only when the canonical freshness is CURRENT (inputs identical to the Run). For a STALE Last Run the
  thresholds are unavailable (`RUN_THRESHOLD_NOT_BOUND`) and the observed values are labelled as the prior Run.
  For other scenarios' historical Runs no threshold is bound and no covenant verdict is produced.
* Scenario values are pass-through of each scenario's own committed Run; only the active scenario has a freshness
  against the Working Copy. Other scenarios read "HISTORICAL RUN". Missing metrics render "—", never zero.
* The active scenario's quality row is the same report shown in Findings (not a second derivation).
* Links: check → owning sheet (validated against `workbook.html` tab ids), Explore assumption (only when the
  Q1 `related_assumption_ids` path is an Assumption Register path), Explore KPI (only for an existing Last Run KPI).
  Go to field / sheet-to-Explore / return navigation are the corrected Q2 mechanisms (exact `data-register-path`).
* Nothing runs the engine, selects or creates a scenario, or writes. Scenario create/select stay explicit actions in
  the existing Scenarios workspace (current authorization and CAS controls); the panel only links to it.

## Files

`app/v2/insight_quality_projection.py`, `app/v2/insight_scenario_projection.py` (new adapters);
`app/model_quality/evidence.py` (`evidence_from_history_entry`, LLCR merged from the committed debt-schedule summary,
same rule as the Run History KPI view); `app/v2/smart_panel_projection.py` (`insight` field);
`app/v2/router.py` (`_attach_insight`); `_model_smart_panel.html`, `_model_insight_q3.html`,
`_model_insight_scenarios.html`; `model_smart_panel_v2.js/css`.
The Q1 isolation test now allow-lists exactly the two adapters; engine/core remain forbidden.

## Known gaps

* No minimum-DSCR covenant, default-DSCR term or contractual flag exists in ProjectInputs; covenant rows for them
  are structurally unavailable until a typed contractual-terms contract is reviewed.
* Run-time thresholds are not persisted with the Run, hence the CURRENT-only binding.
* Reserve/DSRA target is evaluated only for a proven fixed target (Q1 rule).
* Optional create/switch scenario action from the panel is not implemented (link to the Scenarios workspace only).
* Calculation traces and assumption-to-KPI lineage remain UNAVAILABLE (no proven map).
