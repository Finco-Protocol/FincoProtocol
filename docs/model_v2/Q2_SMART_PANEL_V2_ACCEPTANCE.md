# FINCO MODEL — Q2 Smart Panel V2 authority and acceptance notes

## Scope (one Draft PR; no Q1 or F3.1 dependency)

Three modes within the existing right-side Smart Panel:

- **Solutions**: issues arise only from the existing Run Integrity overall verdict,
  assumption register availability, reference regression availability, and the
  canonical CURRENT/STALE/NOT_RUN state. Existing validation summary remains the
  owner of live field errors. No lender covenants, sensitivity, or financial
  calculations are invented. Existing Checks, Assumptions and Trace are retained.
- **Inspector**: working-copy fields come from the route's actual Assumption
  Register *presentation view*: canonical path, display value, unit, label and
  source. An owning workbook field is navigable only on an exact field-id match.
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
