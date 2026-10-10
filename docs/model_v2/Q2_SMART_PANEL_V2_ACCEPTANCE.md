# FINCO MODEL — Q2 FINCO Insight (formerly Smart Panel V2): authority and acceptance notes

## Scope (one Draft PR; no Q1 or F3.1 dependency)

FINCO Insight is the user-facing feature name. The user-facing modes are Findings / Explore / Changes. The stable internal mode keys remain solutions / inspector / changes to avoid scope expansion and regressions.

Three modes within the existing right-side panel:

- **Findings (internal solutions)**: issues arise only from the existing Run Integrity overall verdict,
  assumption register availability, reference regression availability, and the
  canonical CURRENT/STALE/NOT_RUN state. Existing validation summary remains the
  owner of live field errors. No lender covenants, sensitivity, or financial
  calculations are invented. Existing Checks, Assumptions and Trace are retained.
- **Explore (internal inspector)**: working-copy fields come from the route's actual Assumption
  Register *presentation view*: canonical path, display value, unit, label and
  source. An owning workbook field is navigable only on an exact canonical-path match (see Correction B).
  KPI values/identity/freshness derive from the preexisting persisted Last Run
  KPI strip; the same raw persisted values remain canonical.
- **Changes**: uses canonical overall freshness and in-browser pending input
  indicators. Does **not** claim historical field-level diffs, an audit ledger,
  an unsaved server-side comparison, or calculate the difference from KPI values.

Mode selection stays in memory across HTMX swaps; one delegated handler; the
existing navigation and `v2FieldValidationUx.jump` remain navigation owners.
Assets are loaded once in the existing workbook shell.

## Invariants

1. NOT_RUN: no computed financial values.
2. STALE: all displayed KPIs belong to the previous committed Last Run.
3. Run Integrity PASS/FAIL/INCOMPLETE never certifies the current modified
   Working Copy when freshness is STALE.
4. Calculation Trace is UNAVAILABLE for persisted runtime because the
   clean run is not stored. `AUTHORITY_ONLY` is a calculation-trace
   *capability*, not evidence of a persisted complete formula tree.
5. No HTTP GET runs the engine. No financial/DB writes or modified finance
   formula/methodology. No assumptions automatically changed.
6. Reference is rendered read-only by the canonical workbook rows; the
   Smart Panel never introduces editing controls.

## Deferred authority gaps

- The register presentation view omits `assumption_id`, provenance
  `source_kind` separate from `source_ref`, and verified assumption→KPI
  joins. Q2 intentionally marks them UNAVAILABLE.
- Exact calculated formula lineage for persisted Last Run KPIs is not stored.
  Neither full trace nor trace completeness may be fabricated.
- Canonical saved individual-field change lists are not exposed in the
  Smart Panel route; only aggregate freshness and local pending inputs are
  safely visible. Run History is read-only.
- Financing / bankability issue cards require real covenant authorities and
  proven thresholds. No invented breaches or percentile ranges.
- The Phase 4 / Phase 5 research ZIP named in the task was not available in
  the current workspace; this pass uses the documented Q2 acceptance
  specification and live repository authorities. Reconcile on independent review.
- Q1 Model Quality integration belongs in a follow-up PR after Q1 and Q2
  are both independently merged.

## Required independent browser acceptance (not verified by this document)

Authenticated local checks using synthetic Solar and Wind Working Copies:
populated Solutions, Inspector field, Inspector KPI, real Integrity FAIL,
CURRENT, Save → STALE, NOT_RUN, 390px mobile, protected Reference read-only.
Capture screenshots and browser console/HTMX event logs. Verify selected mode
persists through Save/Run OOB updates, no duplicate event handlers, keyboard
tab + arrow navigation, jump-to-field and return-to-field.

**Release gate:** the 5 exact-head GitHub workflows SUCCESS, focused pytest
process exit 0, and browser evidence on the exact PR head. Until recorded:
NO MERGE / NO DEPLOY.

## Correction A — narrowly revised legacy read-only contract

The original workspace productivity tests prohibited every `<select>` because
no financial editor could live in the panel. FINCO Insight introduces exactly
one navigation-only `#v2-sp-inspect-select`, without form/name/binding/write
capability. The old negative assertions remain protected for form/input/textarea,
extra selectors, submit buttons, contenteditable attributes and HTMX writes.
Both known original test names are retained, alongside positive/negative probes.
The feature remains advisory; no bank approval claim or financial solver in UI.

The existing Protocol UI workflow is not evidence of the full FINCO Insight
Solar/Wind authenticated browser matrix: Q2-specific screenshots and logs must
be recorded independently on the final head. If absent: BROWSER_NOT_RUN.

## Correction B — canonical Explore field mapping

Assumption Register paths (for example `technical.operating_hours_p50`) and workbook row
field ids (for example `project_setup.technical.p50_hours`) are different identifiers; the
first release compared them directly, so no Explore selection could ever reach its owning
row. The only proven bridge is the registry `FieldSpec.engine_path`, which equals the register
`canonical_path` by exact string equality.

- `app/v2/register_path_map.py` exposes `register_path_for_field(field_id)`: the registry
  `engine_path`, only when exactly one registry field claims it; otherwise `None`.
- `field_editor.html` renders `data-register-path="<path>"` beside the unchanged
  `data-field-id` (escaped; absent when unmapped). Presentation only.
- The panel script resolves a row only by exact `data-register-path` equality and only when
  exactly one row matches. "Go to field" passes that row's existing field id to
  `v2FieldValidationUx.jump`. Zero or several matches render a disabled, truthfully labelled
  jump and never navigate. Focusing a mapped sheet input selects its register assumption.
- Focus moved by the panel's own navigation never overwrites the return origin.
- Coverage on the generic Solar and Wind references: 236 register paths, 35 rendered rows,
  30 rows carrying a registry path claim, 21 rows whose claim is a register path (navigable),
  0 ambiguous. 215 register paths have no workbook input row and stay UNAVAILABLE.
- Regression: `tests/test_model_smart_panel_q2_register_mapping.py` (server contract) and
  `tests/test_model_smart_panel_q2_navigation_browser.py` (real panel + JS in Chromium with
  register path != field id).
