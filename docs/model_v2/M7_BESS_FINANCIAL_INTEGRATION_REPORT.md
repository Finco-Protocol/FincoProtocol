# M7 native BESS financial integration candidate

## Review Status

Existing Draft PR #283, branch `feat/model-m7-bess-institutional-v1`.
Base remains RC-2 main `6fc77de98bc0562fb51efdbf96e1803a29b5b148`.
Previous operating checkpoint: `ec856799c9114234a884c717479d9f7d2b9c4ee0`.
The new commit/tree and exact-head CI are recorded in the PR handoff.

**The positive, no-augmentation standalone financial path is now executable
end to end in isolated development tests.** It is no longer an isolated
operating calculator. Production activation is FALSE, and financial content
and Trust successor approval are still outstanding. No self-pins were added.

## Native Input and Financial Ownership

`finco_core/inputs/bess_native.py` introduces an immutable versioned wrapper:
`configuration` contains the existing chronological battery contract;
`variable_om_eur_per_dc_mwh` supplies explicit throughput-priced maintenance.
`NativeBessTechnicalParams` extends the existing TechnicalParams without
changing that legacy class or any inactive ProjectInputs representation.

The app bridge persists `bess_native_config_json` as a registered typed field,
`project_setup.bess.configuration`. The same canonical JSON survives
ProjectInputSet, effective child-scenario composition and Run-bound evidence.
Renewable tariff/yield fields cannot substitute for battery assumptions.

`financial_engine/adapters/project_inputs.py` carries that exact contract into
`NativeBessTechnicalInput`. Legacy annual BESS spread/cycle revenue is rejected
at this clean adapter, not activated beside the new model. The inherited legacy
BessParams is removed from native effective inputs; native dispatch is the only
physical/commercial authority.

`financial_engine/bess.py` uses the existing hourly model and canonical period
aggregator. It supplies gross merchant sales as Revenue and adds separately
identified charging purchases, grid-fed auxiliaries, grid import/export fees
and throughput O&M to ordinary fixed OPEX. No sale/purchase financial netting,
balancing plug, PPA proxy, annual production backfill or alternative finance
engine is introduced.

The existing orchestrator owns signed EBITDA and depreciation. Existing G2A/G2C,
construction policy, TaxPolicy, Senior solver, reserves, project/sponsor returns
and statement assembly own all downstream outputs. The baseline uses the
existing generic accounting policy and ordinary synthetic 25% tax assumption;
it is NOT a new statutory jurisdiction rule. Existing BESS asset-class book
lives remain distinct from physical battery useful life.

The browser audit caught a real additional-equity evidence omission for
single-Senior equity-only BESS and a legacy-XIRR recomputation mismatch for
large negative returns. `app/run_integrity/evidence.py` now records the actual
native BESS additional-equity component and declared canonical G2B robust-XIRR
authority. `checks.py` consumes those components and uses that same existing
robust-XIRR leaf. Other projects retain their historical evidence/verification
behavior. No accounting balance, cashflow, return, tolerance or check identity
is changed; no plug is calculated. Missing/altered equity, altered published
XIRR and missing return authority remain non-PASS. Persisted BESS Integrity
is PASS in the complete workflow, independently of input freshness.

The new default candidate uses equity-only sponsor funding, a single Senior
facility and no initial reserve. P50 here means the explicitly supplied native
plan, not renewable P50 production. Renewable P90 yield or legacy bank-price
curve replacements fail closed instead of silently leaving BESS prices unchanged.
No new lender forecasting methodology is claimed.

## Cost and Lifecycle Scope

Initial costs reuse canonical CapexStructure and the existing cost workspaces,
including existing BESS cells/power-electronics/civil asset classification and
editable generic cost categories/sub-lines. Fixed O&M/insurance/site costs retain
the existing OPEX authority. Throughput O&M and electricity procurement are
additional native period expenses, not duplicate fixed O&M or negative revenue.

Paid augmentation/replacement physical evidence is retained in the isolated
operating review. **Financial posting of events remains rejected** pending
independent post-COD commissioning/disposal, tax/book basis and funding policy.
Nonzero initial/terminal stored-energy financial basis is also unresolved and
rejected. No physical reset, free capacity, operating-cost disguise or premature
construction capitalization is used to close those gaps.

## Working Copy and Immutable Runtime

- Original protected Storage reference remains unchanged and non-runnable.
- Gated clone action uses the existing canonical-reference clone service,
  authenticated owner and signed CSRF; an ordinary project cannot masquerade
  as a source reference. The service rechecks canonical source provenance.
- BESS assumptions Save uses the existing transactional contract writer, with
  only Revenue and BESS exact field IDs admitted. Arbitrary fields are rejected.
- Owner/protected/scenario/composite CAS checks happen inside BEGIN EXCLUSIVE.
- Base Save updates the draft; child Save updates only its explicit override.
- Generic field POST cannot bypass the dedicated BESS CSRF/CAS editor.
- Run uses the existing worker, pre-engine composite identity and final atomic
  commit. Controlled tests use the existing thread executor mode and prove
  executor/server termination; no mocked financial results replace the engine.
- Period audit and exact effective native contract are saved in runtime_summary
  in the same Last Run/history transaction. No hourly-array sidecar or schema.
- Save makes the old Run STALE; reopen preserves STALE; rerun makes it CURRENT.
- Selecting Base after a child Run restores Base evidence without scenario leak.
- Invalid dispatch Run preserves the previous Last Run and history count.

The native form appears in the ordinary Project & Technical panel; normal
CAPEX/OPEX, financing and financial-output navigation remains in use. It uses
server-signed tokens, explicit units, percentage serialization, daily tables
and a bounded typed chronology editor. Financial evidence refreshes from a
read-only GET after Run/scenario operations, not a second calculation.

## Time and Performance Boundary

Physical UTC intervals remain `[start,end)`. Actual FINCO operating end dates
are used, not assumed January/year-index boundaries. The 2028/2029 synthetic
case contains 730 physical days because the authoritative horizon ends on
2029-12-31. The financial COD-inclusive extra accrual day does not add energy.

Full chronology is calculated transiently, bounded by the existing 300000-hour
contract; UI/Last Run carry period summaries, never hundreds of thousands of
hourly records. The existing request/run-scoped immutable memo avoids repeating
hourly calculations across financial fixed points. Full detailed physics can
be reproduced from immutable stored assumptions. The kernel still materializes
its bounded hourly tuple transiently; peak-memory/load profiling for maximum
horizons remains a pre-activation performance acceptance item, not a benchmark
claim. No cross-request physical cache or price optimizer was added.

## Independent Numerical Case

Original 1 MW / 2 MWh usable daily synthetic dispatch, 40/100 EUR/MWh purchases/
sales, 0.9 efficiencies, .01 MW auxiliaries, 2/1 EUR/MWh grid charges, 1 EUR/DC
MWh variable O&M, 1 kEUR annual fixed OPEX, 35 kEUR initial hard CAPEX.
Declared gearing ceiling .5, 2-year Senior, 5.5% existing pricing authority.
This is a verification case, not a profitable investment or fitted return.

| Canonical evidence | Value |
| --- | ---: |
| Hard CAPEX | 35.0 kEUR |
| Project Uses including construction finance | 35.2351885872243 kEUR |
| Funded Senior, naturally DSCR-limited | 11.391576374133786 kEUR |
| Operating gross sales | 14.661 / 14.904 / 14.661 / 14.904 kEUR |
| Operating OPEX including all native expenses | 10.396157759562842 / 10.565692240437158 / 10.394780410958903 / 10.567069589041097 kEUR |
| Operating EBITDA | 4.264842240437158 / 4.338307759562841 / 4.266219589041096 / 4.336930410958903 kEUR |
| Cash CIT | 0 / 1.2683563595853524 / 0 / 1.3398411368640522 kEUR |
| CFADS | 4.264842240437158 / 3.069951399977489 / 4.266219589041096 / 2.9970892740948507 kEUR |
| Project XIRR | -0.43779459337387083 |
| Pure Equity / Total Sponsor XIRR | -0.6412239945397319 / -0.6412239945397319 |
| Maximum operating BS residual | 1.0880185641326534e-14 kEUR |
| Hourly energy residual | 0 MWh |

Independent Decimal checks reproduce each period's sale, purchases, variable
O&M, fixed OPEX, signed EBITDA and EBITDA-minus-cash-CIT CFADS. Sources/Uses
and every available operating BS check preserve the existing 1e-7 kEUR bound.
Construction BS checks are None under the existing COD/operating-only authority;
they are not fabricated zeros or claimed complete construction Balance Sheets.

## Focused Evidence

- Original physics/boundary/stateless-security/Storage production guards:
  **95 PASS**, including all 34 original Storage guard tests after integration.
- Canonical financial tests: **9 PASS**; zero case is a verified fail-closed
  limitation, NOT proof of a successful zero-capacity G2C Run.
- New workflow tests: **12 PASS** (full Run/history/scenario, 9 Save adversaries,
  failed physical Run atomicity, protected clone endpoint).
- Four inactive operating comparisons + authority/bank/writer negatives:
  **8 PASS**, equal to actual source at pinned RC-2 base, with exact manifest
  altered/missing/extra/unreviewed-release/provenance negatives. This is narrow exact
  operating parity, not a broad renewed financial-source acceptance campaign.
- Integrated actual Chromium: **2 PASS**, light/1440 and dark/390, real Save,
  canonical Run, Current, period evidence refresh, changed price/reopen Stale.
- Original isolated candidate Chromium: **2 PASS** on the integration candidate;
  four real Chromium cases in total. Server/worker teardown exits normally.
- Integrity regression ring: **116 PASS**, including 9 overlapping M7 financial
  tests and 107 existing H4b/Senior/developer integrity tests. No assertions skipped
  or tolerances widened. Unique local focused coverage totals **235 PASS**.
- Screenshots external to Git: `bess-integrated-light-1440.png` and
  `bess-integrated-dark-390.png`; reproducible via M7_SCREENSHOT_DIR.
- Full local repository pytest/broad parity/staging acceptance not performed.

## Exact Protected and Trust Successor Proposal

`M7_BESS_FINANCIAL_CANDIDATE_MANIFEST.json` lists nine financial/core/domain
paths plus two native accounting-evidence successors and actual Git blobs.
It is **review evidence, not release
authority**. Original domain blobs remain identical; the new core type, clean
input adapter, operating orchestrator and native operating provider require
independent exact-content financial review. No historical pin was changed.

After independent approval, the narrow governance successor must preserve all
historical maps and deny unknown paths, changed content and missing refs. No
blanket financial/core/domain exemption is requested.

The unchanged Trust CSRF inventory rejects two new exact module call-sites:
`app/v2/bess_candidate_router.py` and `app/v2/bess_workspace_router.py`.
Request a separately reviewed inventory addition for exactly these modules,
its truthful registry/doc successor only where necessary, and exact-content
scope guard protection. Existing assertions must still reject any third unknown
validator, removed validation, altered approved content or unrelated Trust/
financial/writer edits. No Trust code, inventory, docs generator or guard is
self-modified in this candidate. Missing/forged/expired tokens and arbitrary
writer-field mutation already have negative behavioral tests.

## Remaining Independent Decisions

1. Exact-content financial successor and narrow Trust inventory authorization.
2. Financial augmentation and nonzero stored-energy basis policy; excluded from
   baseline instead of falsely enabled.
3. **Zero financial debt capacity:** physical and operating zero-volume paths
   work, but existing canonical Senior financing rejects NO_DEBT_CAPACITY as a
   non-authoritative solver result. A declared zero gearing cap is separately
   rejected by existing maximum_gearing validation. No fake zero-debt success,
   IRR, solver policy relaxation or forced debt was added. An explicit reviewed
   all-equity/no-Senior financing authority is needed for such G2C completion.
4. Maximum-horizon memory/load and deployed-browser acceptance before activation.
5. Fresh exact-head CI, including full Public Safety normal exit, after reviewed
   financial/governance authorization. Current green gates cannot be claimed
   for unapproved successor content.

`app/workbook/bess_config.py::ACTIVATION_ENABLED` remains FALSE. Revenue V3 and
Junior remain closed. Original developer operating review remains separately
closed; its handoff stub is NOT the native finance path. No Hybrid, trading,
optimization, new tax/IRR/debt equation, post-COD financial asset posting,
exports/reports, schema migration, self-approval, merge or deployment.

**M7 PARTIALLY BLOCKED - positive no-augmentation canonical BESS workflow is
implemented and tested; exact release/Trust approval, augmentation accounting
and zero-debt-capacity authority remain unresolved.**
