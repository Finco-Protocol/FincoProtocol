# FIN-V2-3 financial core review package

Previously the typed valuation engine had no complete saved-input workflow and
committed sponsor rows omitted SHL contributions. This branch connects explicit
valuation policies to Save/Reload/Run, preserves dated sponsor evidence, extends
coverage and Goal Seek, and exports the results from a selected frozen Run.

Branch: `feat/fin-v2-3-financial-core`. Main baseline:
`128bf0c2b79af56985326543132cc806ff7f001c`, tree
`459d67a89c8c204f03d364dbba2242c168dea5bf`. PR #389 is merged.
PR #388 remains open/draft; FIN-V2-2 is PR #390 at inspected head
`842fedadd57f33d87e73ed5d231f451977889bf8`. FIN-V2-1 was not yet visible in
the inspected open PRs. Research package/report digests are in RESEARCH_INPUTS.json.
Historical research proposals and earlier authorization gates are interpreted
under the later assigned FIN-V2-3 prompt, including its standing Owner approval
and prohibition on merge/deploy/release activation.

## Financial decisions

- SHL timing is `ABSOLUTE_INDEX` for absent historical fields. `COD_RELATIVE`
  explicitly resolves the first operating row after contractual Senior maturity
  and the last supported operating row. Absolute drift is a typed visible issue,
  `SHL_MATURITY_NOT_AT_MODEL_END`; existing off-grid/residual refusals remain.
- Total Sponsor XIRR is primary; Pure Equity IRR is secondary. Existing IRR
  calculations, funding amounts, financial-close cash dating, debt sizing,
  amortisation, reserves and generic tax mechanics are preserved.
- Entered SHL amounts are indicative; actual SHL remains engine-derived Sources
  & Uses. Sponsor cash dates and SHL balance-recognition dates are separate
  evidence axes. The latter records opening + draw + PIK - principal = closing;
  no attempt is made to equate loan recognition with FC sponsor cash dating.
- Discount/hurdle rates are explicit. No Senior rate, WACC or IRR is substituted.
  `ACT_365_FIXED` compounds annually using actual days/365. The periodic policy
  uses the quoted rate per model period and end-of-first-period exponent 1;
  there is no automatic annual-to-semiannual rate conversion.
- Contractual and actual loan life remain distinct. Rolling LLCR uses the
  explicitly selected remaining loan-life convention (actual repayment in the
  synthetic acceptance policies). Historical `min_llcr` retains its existing
  first-Senior-opening meaning. PLCR independently selects the project horizon.
- BASE and BANK remain different cases; BANK means canonical debt-sizing CFADS,
  never P50. Coverage excludes reserve additions. Sponsor NPV uses full dated
  equity plus SHL flows and an explicit hurdle/date policy.
- Reports classify source/status and disclose `GENERIC_MVP_POLICY`. No formal
  lender covenant, statutory tax compliance or lender acceptance is asserted.

## Numerical evidence and boundaries

All 29,620 pre-existing G2C float paths on the four unchanged references retain
their captured `float.hex()` baseline. Configuring valuation leaves all other
existing economic/result floats exactly unchanged. Decimal(50) oracles verify
Project NPV, both LLCR horizons, every rolling observation, PLCR, Sponsor NPV and
dated Sponsor/Pure Equity XIRR, including BASE/BANK and periodic/ACT conventions.

FINANCIAL_ACCEPTANCE.xml records the sealed 153-test financial/F3 selection;
FULL_GOVERNANCE.xml records 1,016 PASS and 10 existing retired-scope skips.
NATIVE_IDENTITY.xml records 54 PASS without skips. VALIDATION_MANIFEST.json seals
their checksums and implementation SHA. Final exact-head results are authoritative
in PR #391 Checks and the exact-head oracle artifact source attestation.
The normal retired Model V2 scope skips are not new financial test skips.

The generated FIN_V2_3_INDEPENDENT_ORACLE.xlsx contains 25 sheets and 4,548 formulas across
8 disposable committed working-copy Runs and 48 metric comparisons. Maximum
absolute monetary difference is 1.1641532182693481e-10 kEUR. BASE CFADS is rebuilt
from full-precision persisted statement components. BANK CFADS, debt balances,
tax cash components, C1 unlevered flow components and sponsor receipts remain
engine-derived inputs and are explicitly labelled. The workbook contains
independent Decimal formula caches and recalculates in Excel. Excel numeric
serialization has 15-digit precision; JSON evidence remains full precision.
No LibreOffice/Excel application recalculation was available in this environment.
Repository safety forbids tracked spreadsheet binaries. The dedicated
`FIN-V2-3 Independent Oracle Artifact` workflow replays the committed frozen
inputs without invoking FINCO, then publishes the workbook, input JSON,
reconciliation and exact-source attestation as a GitHub Actions artifact named
`fin-v2-3-oracle-<head SHA>`. The scanner policy remains unchanged.

The isolated branch intentionally refuses actual/rolling debt-bound valuation
without FIN-V2-2's `SENIOR_DEBT_EVIDENCE_V1`. Its pure mathematics is tested on
isolated canonical schedule fixtures. The external workbook capture additionally
composes the exact PR #390 module (blob
`f9e0caefd74d86c368ae2b74cef2cfc035b937b1`) with this branch in disposable
transactions. This is test-only integration, not a duplicate implementation or
a merge of the source branches.

Independent oracle replay without calling FINCO:

```sh
python tools/fin_v2_3_oracle_workbook.py --inputs docs/financial_validation/fin_v2_3/ORACLE_COMMITTED_INPUTS.json.gz --output-dir /tmp/fin-v2-3-review
```

Source successor blobs and parent blobs are in SOURCE_SUCCESSOR.json. Recognition
requires the whole finite cohort and unchanged historical authority outside it;
it confers no native/quarterly/junior/BESS activation. No database DDL, migration,
historical backfill, source-reference mutation, release flag or native kernel
change is included. Independent financial review remains pending.
