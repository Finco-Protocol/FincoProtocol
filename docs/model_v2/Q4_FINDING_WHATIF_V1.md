# WF-08 / Q4 Finding-to-Scenario — implementation contract

Status: DRAFT / independent review required. NOT MERGE APPROVED. No deployment authorised.

## Authority

Q4 is a narrow, user-controlled bridge from the **existing** committed Q1 findings embedded in
Q3 FINCO Insight to an isolated scenario. It does not claim to solve covenant breaches, optimize
financing, infer negotiated covenant thresholds or recompute financial KPIs.

The only Q1 mappings enabled in V1 are:
- QM-SD-004 and QM-SD-007 → financing.target_dscr → debt.senior.target_dscr → target_dscr.
- QM-SD-006 → financing.gearing_ratio → debt.senior.gearing_pct → gearing_pct.

These are conditionally available **only** for Solar/Wind, when the Q1 check exists, the
exact assumption path matches the unambiguous Workbook register path, the target field remains
BOUNDED/OVERRIDE/editable, and the canonical typed ProjectInputs materialization succeeds.
Target DSCR is rejected if an F3 financing collection is activated or the schedule is not FLAT.
Neither Senior A/B collection nor Reserve/DSRA/DSRF policy becomes Q4-editable.

Q1 PASS is eligible for **exploratory** sensitivity only and must never be labelled remediation.
For Q1 WARNING/FAIL, user-proposed inputs are still candidates, never approved solutions.
There are no programmatically generated solver/AI remedies.

## Lifecycle and transaction

1. Existing Q3 Findings surface starts a server-side, read-only preview.
2. Preview carries current Working Copy original and proposed scalar, canonical field, override,
   source Q1 Run snapshot and full composite identity. No scenario or Run is created.
3. The user explicitly checks confirmation and submits a short-lived, signed preview token.
4. One `BEGIN EXCLUSIVE` transaction revalidates ownership, project protection, Base lineage,
   active scenario, current composite hash, Q1 finding, field mapping, F3 policy, value, Run snapshot,
   scenario name and single-use nonce.
5. The transaction inserts one child scenario using canonical scenarios storage and resolver,
   with a proven Base parent, audit/replay metadata and no runtime result. A failure rolls back.
6. **No scenario activation or Run is automatic.** User explicitly selects the scenario via existing
   canonical selection route; canonical Run handles computation, persistence and Run History.
7. Q4 Compare consults the newest committed Run History entry of Base and the selected What-if.
   New scenario with no Run remains NOT_RUN; unreadable/missing evidence is UNAVAILABLE.
   KPIs use the existing formatting/comparison authority; Quality and Integrity are independently
   evaluated over their own committed run evidence with **no historical covenant term inference**.

The original Base Case, selected scenario, last-run identity and existing Run History are not
mutated by preview/creation. Scope intentionally avoids existing CAPEX/OPEX row mutations and
wide `app/v2/router.py` rewrites.

## Acceptance requirements

Focused test file: `tests/test_model_q4_whatif.py`. It includes mapping and token negatives,
not-run and cross-owner route negatives, and Solar/Wind real model → Q4 preview → commit → select →
canonical Run → immutable comparison lifecycle. Run full four-vertical suites and negative CAS,
concurrent-switch, rollback-injection, mobile/desktop authenticated Chromium testing independently.

**Do not report acceptance based only on this document or test definitions.**
The exact PR HEAD must pass all applicable CI workflows; full pytest exit status, supervisor
exit, artifact uploads, and authenticated screenshot evidence still require verification.

## Known V1 limits

- Mapping deliberately supports only two scalar debt assumptions, and only conditionally.
- No target remediation value is automatically recommended; the user provides the candidate.
- The user must select the created scenario in the canonical Scenarios workspace before Run.
- Historical covenant terms not persisted with a Run remain unavailable.
- Comparison is read-only; it is neither an investment recommendation nor a lender certification.
