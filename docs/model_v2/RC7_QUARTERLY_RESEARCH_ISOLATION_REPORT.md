# RC-7 Correction C: Isolated Quarterly Financial Research

## Scope and provenance

Main: `78e4c0edcc1bdb5013df79f11b3ba7b9c2151013`.
Prior PR HEAD: `1288f95595935744fcfe05441d458fb3605f6681`.
Same branch/PR #313. No main integration, release approval, governance exception,
activation, deploy, rebase, squash or force push is performed by Correction C.

Exact-head Public Safety run **39123372999**, job **117663383016**, completed
**12934 passed / 49 failed / 105 skipped**, pytest rc=1, normal supervisor child
exit=1. The complete log confirms financial namespace, M7/PPA exact-content and
historical scope conflicts. Mandatory Browser Evidence **39123372980** passed;
Security **39123373128**, Governance history **39123373076** and Compile/Safety
**39123373077** passed. No full CI rerun preceded the structural correction.

The 49 failures were not 49 numerical discrepancies: two protected M7 candidate
blobs were replaced and three new calculation files placed in the frozen engine.
Approximately thirty independent scope guards correctly rejected that content.
None of those guards, source pins, negative tests or assertions is changed.

## Production and research are structurally separate

| Boundary | Correction C result |
|---|---|
| financial_engine/adapters/project_inputs.py | Exact main blob `14bd759a9958515a7796626f93c1bd2233d69150` |
| financial_engine/orchestrator.py | Exact main blob `be7ac31c6c4fed43b5fd7ca49fe53bfd1cc54c03` |
| financial_engine/quarterly three Python modules | Removed AFTER isolated execution matched all 16 original financial structures |
| Entire financial_engine / finco_core / domain diff against main | ZERO |
| M7 and PPA content | All eleven M7 and all three PPA identities retained, no successor exception |
| Historical governance/CI/financial maps | Unchanged |
| Application routes, writers, workers, reporting/export | Unchanged; no research imports |
| Research location | `tools/quarterly_research/` only |
| Admission | RESEARCH_ONLY / RELEASE_CLOSED / NOT_A_PROJECT_RUN |

The manifest is a byte inventory, not an authorization map. It records current
four research modules, restored production blobs, and the archived original five
candidate blobs at the prior source HEAD. It is not imported by runtime/governance.
The old code is retained in Git history and private before/after captures, not
destroyed or replaced by a mock demonstration.

## How real financial calculation is preserved

`calendar.py` preserves the typed immutable/versioned 3/3 policies, actual COD,
stub, leap-day fractions, counters, axis and maturity checks. `runtime.py`
preserves all configuration refusals, wrapper and complete-project BLOCKED gate.

`calculation.py` is a small **research coordinator**, not a copied orchestrator
or a second debt solver. It directly calls existing, unchanged primitives:

| Research operation | Existing source reused read-only |
|---|---|
| Generation/revenue | finco_core.revenue.generation full_generation_schedule / full_revenue_schedule |
| OPEX / signed EBITDA | finco_core.opex.projections / finco_core.ebitda |
| Input proxy, tariff, depreciation | financial_engine.orchestrator pure builders/assemblers |
| Calendar-year tax, annual FIFO, cash tax | financial_engine.tax.engine calculate_tax / calculate_cfads_and_cash_tax |
| Canonical CFADS | financial_engine.cfads.calculate_canonical_cfads |
| Lender operating case and tax-interest merge | Existing orchestrator pure helpers |
| Sculpting, ACT/360/365, principal and convergence | financial_engine.senior_debt.solver.solve_senior_debt and existing schedule primitives |
| Bank-result and post-Senior assembly | Existing strict axis-aware orchestrator assemblers |
| Absent reserve presentation | Existing run_cash_dsra_model with None only; no reserve activation |

Private assembly helpers are an explicit research dependency, NOT a promise of
a supported production extension API. Future helper changes require numerical
regression. The code does not patch globals, rebind functions, execute rewritten
source, inject a calendar into production orchestration, copy its solver, install
a plugin or register an alternate Run entry. The local input proxy alone carries
research frequency. Production inputs and all module callables remain unchanged.

All 16 original complete result structures were captured BEFORE removal and
compared with the isolated result structures BEFORE and AFTER restoration.
Operating, tax, debt, Bank/Base CFADS, balances, cash, axis, diagnostics and
unavailable sections compare exactly; input fingerprints also compare exactly.
Only provenance path/source now truthfully identifies tools.quarterly_research.
Independent Decimal oracles are re-executed, not replaced with captured output.

## Frequency safety: explicit limitation, no false claim

The extra #313 adapter rejection is REMOVED by restoring the main blob. The
baseline clean `CalendarInput` has no frequency field; calling the low-level
adapter on typed Quarterly ProjectInputs can erase frequency and the standalone
operating helper can then construct a six-month calendar. That limitation is
NOT fixed by this research package. Do not expose that helper as a quarterly API.

The actual production execution path still refuses unsupported frequency before
successful financial Run / immutable history commitment:

1. Default generic financing: existing derive_construction_financing raises
   H1_UNSUPPORTED_PERIOD_FREQUENCY.
2. Auto-construction disabled or explicit typed construction: the existing tax
   adapter raises unsupported period_frequency; the Senior adapter independently
   permits only SEMESTRIAL. No financial policy is weakened.
3. Released PeriodEngine itself continues to reject quarterly/annual frequency.

These three production paths were independently executed on unchanged main AND
on the restored branch for Solar, Wind, Data Center and EV (12 cases each).
There is no new admission boundary invented by this correction.

### Actual input-entry inventory

| Surface family | Existing input/admission authority | Consequence |
|---|---|---|
| API /api/run (app/api/router.py) | ProjectInputsSchema -> input_adapter factory resolver -> project_runner | No typed frequency field; complete runtime uses the existing guards above |
| API reference run /api/v1/model_router.py | Explicit reference key + capacity scaling | Existing semiannual factories, no arbitrary typed-input/calendar upload |
| Workbook /v2/workbook/run | Registry/scenario/composite-CAS -> snapshot resolver -> project_runner | Frequency field is unregistered; canonical writer rejects it as unknown |
| Legacy /run, /save-run and matrix/scenario run | run_service/save_run_service factory/schema/snapshot authorities | No independent frequency writer; same production financial execution boundary |
| Sensitivity/2D matrix/Goal Seek | Existing allowed scalar shocks on resolved inputs | No period-frequency shock or research import; same production runtime |
| Import, Working Copy, scenario restore | Registered input mapping and snapshot/scenario authority | No activation/serialization bridge for quarterly research types |
| Worker boundary | app/runtime/model_execution executes existing authorized runner arguments | No research registration or new worker code |
| Read-only history/export/credit/reporting | Persisted committed evidence | Research output is not substituted into a committed Run |

The Pydantic input schema **ignores unknown extra keys**; sending an unrecognized
period_frequency key is not an explicit HTTP refusal and still resolves to the
template's semiannual default. This pre-existing behavior predates the candidate,
and the removed adapter guard never saw such an ignored key either. Tests record
the limitation honestly; no strict-schema or generic validation change is hidden
inside this correction. Raw programmatic typed non-semiannual production inputs
are separately refused by the real runtime, not merely omitted from the UI.

Any future writer/import/API exposing frequency, or a direct operating-only API,
requires a separately reviewed fail-closed admission contract before release.
No reachable successful complete quarterly production path was found in this
preflight; otherwise the correction would have stopped without restoring guards.

## RC-7A compatibility and unresolved financial policy

The prior monthly CAPEX/funding/IDC, separate FC/COD Senior allocation and actual
opening liability proofs remain. Construction inclusive days and operating
half-open days are distinct. Nullable cashflow_date is not guessed; monthly
period dates do not prove every subperiod settlement date. Positive COD opening
debt remains refused by the research study; no monthly-to-quarterly accounting
or project funding bridge is invented.

Credit V4's equal-end-date match does not prove equal interval/frequency. Reporting
V2 does not establish quarterly statements. Revenue V2 physical PPA/Merchant MWh
and separate CfD notional settlement are retained; unproven dated/advanced revenue
contracts remain refused by research.

D-01..D-12 remain OPEN, including fixed-count horizon versus actual economic life
and model-year versus anniversary escalation. D-06/D-07 mixed modes remain
deferred. No active SHL, Junior, multi-Senior, reserves, BESS, DC/EV quarterly,
contractual covenants, sponsor distributions, full statements, project/sponsor
returns or quarterly Save/History/export is authorized. The owner decision pack
and original compatibility findings remain available, with their packaging status
explicitly updated rather than silently rewritten as financial acceptance.

## Validation and publication

Ring A: calendar, 16 independent Decimal financial cases, tax/FIFO, refusal
matrix, real monthly compatibility, production admission and isolation tests.
Ring B: real RC-7A construction/Revenue/Credit/reporting regressions and fresh
complete four-vertical 6/6 unrounded comparison against exact main.
Ring C: original unmodified M7/PPA/WF07 and freeze/CI contracts, including their
negative tests and all 49 previously failing nodes. Exact counts and process
exits are appended after execution; incomplete work is not marked green.

Before final branch commit, HEAD-sensitive governance tests require a real Git
tree containing restored blobs. A private detached verification checkpoint is
used for those tests; it is not a branch approval, CI-trigger commit or published
feature commit. Final feature tree must equal the tested snapshot. No guard is
patched to read arbitrary expected HEAD bytes. The actual correction remains
one normal commit on the existing branch, followed by exact-head CI.

No full-project quarterly release or independent financial-content acceptance
is claimed by governance-clean research packaging.
