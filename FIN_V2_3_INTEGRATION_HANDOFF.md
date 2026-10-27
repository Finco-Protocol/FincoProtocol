# FIN-V2-3 integration handoff

Branch: `feat/fin-v2-3-financial-core`.
Main/base: `128bf0c2b79af56985326543132cc806ff7f001c`.
Source content: the exact finite cohort in
`docs/financial_validation/fin_v2_3/SOURCE_SUCCESSOR.json`.
Publication HEAD and exact-head CI: pending the cohesive draft PR push.
Disposition: **CORRECTION REQUIRED until exact-head hosted checks pass**.

## Completed scope

- Versioned SHL calendar basis and visible absolute-index drift; unchanged strict
  maturity refusals and historical input meaning.
- Dated sponsor contributions/receipts/PIK/net flows and separately dated SHL
  balance-recognition evidence; Total Sponsor primary / Pure Equity secondary.
- Explicit saved valuation policy, F01-compatible percent boundary, Project
  NPV, distinct loan-life coverage, rolling observation evidence, PLCR and Total
  Sponsor NPV. Missing rate/authority/dependency remains typed and unavailable.
- Canonical finance-aware Goal Seek targets, units, bounded evaluations, exact
  rerun verification and local financing-regime refusal. Existing Save/CAS Apply
  path remains authoritative and never automatically creates a Run.
- Frozen institutional reporting, committed Run/hash binding, evidence classes,
  generic tax/loan-life/funding disclosures and explicit noncanonical legacy pack.
- Decimal oracles, four-vertical float identity, real HTTP persistence tests and
  external Excel-compatible oracle with independent cached formula values.

Full source/parent blob inventory: SOURCE_SUCCESSOR.json. Typed contracts and API
wire details: POLICY_AND_API_CONTRACT.md in the same review-package directory.
No database schema change: additive evidence resides inside the existing JSON
financing block and sponsor schedule, atomically committed with Last Run/history.
Historical absence is `NOT_PERSISTED`; nothing is backfilled.

## Acceptance evidence

- Complete feature/negative/source selection at implementation commit
  `b5eb8b5d5823732e32a0f45a6c1e18ee0afbadb3`: 129 PASS; subsequent
  authority/drift guards have focused validation.
- Final lifecycle/Goal Seek/source selection: 64 PASS.
- Existing V10/V11 identity selection: 54 PASS, zero skips, approved GCC13 image.
- Initial reconciled focused governance selection: 203 PASS. Committed-head full
  governance and hosted CI remain pending at this documentation checkpoint.
- Existing reference economic/schedule float identity: 29,620 exact `float.hex()`
  paths across Solar/Wind/Data Center/EV Charging; no tolerance substitution.
- Independent workbook: 8 committed synthetic Runs, 48 metric comparisons,
  25 sheets / 4,548 formulas, largest absolute monetary difference
  1.1641532182693481e-10 kEUR. BASE CFADS rebuilt from persisted full-precision
  statement components. BANK CFADS, taxes, C1 components and receipts remain
  explicitly engine-derived input evidence. Application-level Excel/LibreOffice
  recalculation was not available; Decimal caches and formulas were inspected.

Artifacts and replay instructions are in
`docs/financial_validation/fin_v2_3/README.md`. All fixtures use synthetic projects
and disposable databases; source references and historical Runs are preserved.

## Exact integration order and overlaps

1. The integration agent synchronizes accepted financial source branches after
   RC-M #388/F01/main reconciliation; keep this source PR open.
2. Retain FIN-V2-1 sensitivity/rate-shock/EV fixes; the FIN-V2-3 worker adds only
   observational `regime` metadata alongside unchanged `kpis`.
3. Integrate FIN-V2-2 #390's debt evidence builder and schema. The inspected
   module blob is `f9e0caefd74d86c368ae2b74cef2cfc035b937b1`, PR head
   `842fedadd57f33d87e73ed5d231f451977889bf8`.
4. In project_runner, populate `senior_debt_evidence` BEFORE FIN-V2-3's
   `attach_financial_core`. Consume `llcr_inputs.loan_life_end_candidates` and
   retain all existing debt evidence; no duplicate Senior diagnostics are added.
5. Union the two institutional reporting additions. Preserve FIN-V2-2's Senior
   lender section and FIN-V2-3's appended valuation section.
6. RC-M consumes the typed policy/evidence/Goal Seek contracts and renders rates,
   statuses, source labels, metric units and Total Sponsor priority. This branch
   does not modify its React sources or bundles.
7. Resolve shared hunks additively, issue a combined exact-source successor, and
   run full combined numerical/security/CI and relevant staging/browser acceptance.

Detailed path/hunk collision register: SOURCE_OVERLAP_REGISTER.md. Shared source
hunks: project_runner, institutional_reporting_v3, sensitivity_execution,
goal_seek, input_adapter, v2/router (one unit-conversion hunk), workbook registry
and validation, sponsor serialization, RunEvidence accessors, governance helpers.
FIN-V2-1 had no visible matching open PR at the last inspection. Recheck its diff
before integration. Never push to another workstream's branch.

## Fail-closed dependencies and limitations

Actual/contractual extended loan-life coverage and rolling LLCR require the
FIN-V2-2 contract; on this isolated branch they report
`DEBT_EVIDENCE_NOT_AVAILABLE`. Existing configured C2 first-opening LLCR/PLCR and
Project/Sponsor NPV remain available. Isolated canonical-schedule tests verify
the mathematics. The external workbook additionally uses the exact FIN-V2-2
module in test-only composition, through real disposable atomic commits.

Sponsor NPV currently supports ACT/365 annual discounting only; unsupported
conventions refuse explicitly. DC/EV scalar tariff Goal Seek is unavailable;
lender acceptance for those verticals is unverified. No formal covenant contract
or statutory tax assessment is invented. No DSRA methodology, balloon/refinance,
Junior activation, F3+SHL, BESS, quarterly activation, Senior solver or native
kernel change is included.

Independent financial review remains pending. No self-approval, merge, deployment,
historical migration or production/release activation was performed.
