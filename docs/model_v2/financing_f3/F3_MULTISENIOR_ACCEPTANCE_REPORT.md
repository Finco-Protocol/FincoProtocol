# F3.2-F3.4: effective two-Senior acceptance

## Provenance and disposition

Implementation base: `2e199bc3fb8e7a5971e26d1a1a48e9875a63045d`.
Branch: `feat/model-f3-multisenior-financing-v1`. One consolidated Draft PR;
no deployment or merge. Exact feature HEAD, PR URL and five exact-head workflow
conclusions belong in the PR's delivery section after publication.

Merged F3.1 contracts are authoritative. The older phase proposal's optional
field on every ProjectInputs and independent facility sizing solvers are not
used: legacy ProjectInputs retains its exact shape; explicit activated inputs
use a frozen subclass and reuse existing repayment/interest and aggregate
Senior solver kernels. This is a restricted working vertical slice, not a
claim that all F3 roadmap financing modes are complete.

**Disposition: financial and browser gates must pass before activation is
released; independent financial review and all five exact-head CI checks are
required before any merge. No self-approval.**

## Effective capability matrix

| Capability | Effective authority | Supported boundary |
|---|---|---|
| Persistence | existing Workspace snapshot + authorized exclusive CAS | `f3-workspace-1.0`; no migration/new table |
| Proposal | F3.1 FinancingCollection | inert until explicit scoped activation |
| Activation | `F3_TWO_SENIOR_EXPLICIT_COMMITMENTS_V1` | exactly two active Senior term loans |
| Commitment | positive explicit facility amounts | sum constrained by project gearing; never automatically resized |
| Rates | fixed cash rate per facility | ACT/360 or ACT/365, no floating/PIK |
| Draws | actual dated cash draws | construction only; each fully draws its commitment |
| IDC | canonical period-interest primitive | dated draw + opening balance; equity-funded capitalization, no interest-on-interest |
| Upfront fee | fee rate x facility commitment | first construction period, capitalized once |
| Commitment fee | undrawn time integral x annual fee rate | actual draw dates, capitalized once |
| Repayment | existing level-principal / explicit schedule primitives | level principal after grace or bullet at maturity |
| Maturity | canonical operating period end | separate facility maturities; no hidden refinance or write-off |
| Aggregate debt | existing EXPLICIT_SCHEDULE Senior solver | sum of facilities; derived weighted rate hands aggregate interest to tax |
| Tax / CFADS | existing canonical engine | aggregate cash interest only; inactive SHL seed removed before solver |
| Sources & Uses | existing project uses, allocator and funding audit | equity-only residual; no prefunding or negative-equity plug |
| Statements / returns | existing canonical assemblies | actual aggregate debt and funding; no alternative calculation |
| Run audit | immutable full-precision facility vectors | operating + construction ledgers, collection digest and scoped run binding |
| Export | canonical immutable Last Run input authority | never takes current edited collection as historical terms |

Unsupported and fail-closed: more/fewer than two Seniors, DSCR facility sizing,
floating/hedged/period rates, PIK, agency fees, ranked facilities, providers,
Junior/Mezzanine/Bonds/Preferred, active SHL, other committed-equity accounting,
cash reserves/DSRA/DSRF, explicit competing construction authority, manual
CAPEX financing costs, developer economics, non-semiannual periods, off-axis
maturity, grace beyond maturity, out-of-construction draws, mismatched draw
totals, period overfunding, gearing breach and insufficient operating CFADS
for contractual service. Unsupported terms cannot silently activate.

The V1 user explicitly accepts residual funding EQUITY_ONLY and reserve NONE.
It does not inherit either policy from project identity. Competing F2 economic
configuration must be reset before activation. Requested gearing is a cap,
not actual funded debt. DSCR debt capacity is unavailable (`None`), not a
fabricated value for a contractually committed facility.

## Input, scope and lifecycle mapping

`debt.financing.instruments` -> strict canonical JSON -> existing workspace CAS
-> `financing_instruments_json` -> selected authorized Base/scenario scope
-> digest-bound explicit activation -> MultiSeniorProjectInputs -> canonical
Run -> immutable persisted financial evidence / Last Run -> export.

The schema contains `scopes[base|scenario_id] = {proposal, activation}`.
Activation binds the exact proposal digest and explicit funding/reserve
policies. `BIND_ON_SAVE` is a write-request-only instruction: the server
calculates the real digest before storage; readers reject an unbound token.
Unknown versions, duplicate JSON keys, extras and malformed collections fail
closed. Scope ownership is resolved inside the same write transaction.

Instrument IDs cannot change or be removed after first Save. Repeated canonical
serialization is deterministic/idempotent. Scenario scopes do not inherit a
Base collection; each requires its own proposal and activation. The ordinary
scalar scenario override channel cannot override the collection. A foreign
scope edit, cross-owner request, protected-reference write or stale CAS token
is rejected. No parallel sidecar stores economic authority.

Save changes Working identity and produces STALE. A successful canonical Run
commits CURRENT through the existing final CAS. Previous snapshots/history
are not edited. Rates/fees/grace/maturity in an active configuration disable
competing single-Senior editors. Working policy labels are separate from Last
Run evidence. Institutional S&U labels explicit commitments as contractual.
Preview explicitly resolves current active terms without a Run identity;
canonical export instead validates immutable run binding, scope and digest.
Sensitivity/Goal Seek consume the same selected activation, not legacy terms.

## Calculation and accounting boundary

Each facility produces independent dated draws, construction IDC/fees and
operating opening/interest/principal/service/closing vectors. Aggregate
opening, principal, interest, service and closing must agree with their sum
within the existing strict F3 `1e-7 kEUR` handshake. The canonical solver uses
EXPLICIT_SCHEDULE, not a second sizing engine. The gearing cap rejects a
contractual breach rather than scaling commitments to a desired result.

Hard CAPEX + once-capitalized IDC/fees is passed to canonical Project Uses,
book basis and existing funding allocation. Residual equity is the declared
funding policy, not a balancing adjustment to financial outputs. Each period
must fund its Uses; overdraws are rejected instead of parking undocumented
cash. Aggregate service exceeding canonical Base CFADS also fails closed.
Unpaid bullet maturity cannot produce a successful Run/returns. The existing
#233 terminal-liability guard is unchanged.

Two essential audit integrations are explicit, not tolerance relaxations:
Run Integrity reads actual aggregate period rates, and includes the existing
canonical additional-equity BS component once. Missing additional-equity
evidence for F3 is unavailable, never fabricated as zero. The engine/FS/tax
formulas outside the seven pinned integration modules remain unchanged.

The first expanded tax audit discovered that the factory's legacy SHL seed
could survive EQUITY_ONLY into the tax adapter. F3 now sets the effective SHL
principal to zero before the canonical solver, following the existing
financing-stack authority. Tests require zero SHL interest, aggregate Senior
interest in P&L, and full-horizon tax interest equal to facility interest.

## Independent financial evidence

Controlled commitments are independent input fractions of hard CAPEX (6% and
4%), not target-derived runtime values. A/B have 4%/7% cash rates, different
dated draws, 0/12-month grace, and operating-period 16/20 maturities. Both
have 1% upfront and 0.5% annual undrawn commitment fee.

| Reference | Legacy Senior kEUR | Active A / B kEUR | Active Uses kEUR | Senior service kEUR | Active tax kEUR | Minimum Base DSCR | Integrity |
|---|---:|---:|---:|---:|---:|---:|---|
| Solar | 26,983.331676477 | 1,980 / 1,320 | 33,191.730000 | 4,175.141666667 | 28,847.368992919 | 5.643349733 | PASS |
| Wind | 36,505.157959484 | 2,580 / 1,720 | 43,364.114444 | 5,439.450114379 | 55,098.150426233 | 6.811177091 | PASS |
| Data Center | 58,410.961795014 | 12,000 / 8,000 | 202,046.000000 | 25,475.032679739 | 30,233.995370841 | 1.809243807 | PASS |
| EV Charging | 6,477.352578925 | 540 / 360 | 9,044.620000 | 1,146.345000000 | 8,305.367698232 | 5.848665594 | PASS |

Every facility closes to zero in these supported cases. Solar A/B IDC is
93.28 / 62.113333333 kEUR; undrawn fee 0 / 3.336666667; upfront 19.8 / 13.2.
Wind A/B IDC is 174.293333333 / 142.473333333; undrawn fee 0 / 4.347777778;
upfront 25.8 / 17.2. Independent tests calculate dated-draw IDC, undrawn
integrals, grace-eligible counts and operating amortization outside production
functions. Multiple draws and ACT/360 are checked separately.

| Reference | Legacy Project IRR | Active Project IRR | Active Pure Equity / Sponsor IRR |
|---|---:|---:|---:|
| Solar | 0.117679780388670 | 0.117679780388670 | 0.114247695518708 |
| Wind | 0.133109979707442 | 0.133109979707442 | 0.129654589555191 |
| Data Center | 0.023012141497372 | 0.023012141497372 | 0.020333024876707 |
| EV Charging | 0.150859063299858 | 0.150859063299858 | 0.145752909567877 |

No return metric or coverage value is manufactured. These API references have
no `min_llcr` KPI; it remains unavailable rather than inferred here. The known
F0-B stressed legacy Solar precision case (9-year, 90% gearing) remains a
separate precision concern; no solver tolerance, golden or expected value is
changed. F3 contractual handshake and cash/maturity guards are tighter and
explicit; this is not generic DSCR sizing precision repair.

## Legacy equality and evidence reproduction

`tools/model_financing_f3_legacy_equivalence.py --base-checkout <detached-base>`
requires exact immutable base HEAD. It launches separate fresh Python
processes on base and candidate for Solar/Wind/DC/EV, comparing every clean
result field, input serialization/cache key, API/export payload, full Integrity
evidence and report. Nonfinite values are retained losslessly, never omitted
or zeroed. No baseline or golden file is refreshed.

It also compares historical certificate signing bytes under identical
synthetic committed provenance and actual institutional workbook cells,
formulas, number formats and styles under identical provenance. Current
export-generation clock and ZIP creation timestamps are nondeterministic and
explicitly normalized/excluded; no financial cell is excluded. This is not a
claim that independently generated XLSX ZIP bytes are identical.

The collection-absent class/payload/key remains the legacy authority. No
factory migration, existing Run re-identity or financial target changes.
Run certificates continue to attest provenance/integrity, not economic truth.

## Local tests and browser evidence

Completed pre-final regression ring: 453 passed, normal process rc=0. Includes
F3.1 contract/legacy, active F3, Workspace, #233 maturity, H4b Integrity, F1,
bankability, F07B and reference Last Run. After required S&U/export integration,
the focused Workspace + F1 + F07B ring passed 83 tests. Expanded engine
independent/serialization ring passed 32 tests. Final post-correction counts
and governance/certificate ring are recorded in the PR delivery section.
Final post-correction engine + authorized Workspace + F1 + #233 maturity +
F07B ring: **157 passed, rc=0, normal interpreter termination**.
Final F3 engine + Workspace + exact-blob governance ring: **72 passed, rc=0**,
including actual immutable institutional XLSX output and zero export engine
execution. Exact-blob governance alone: **25 passed**. The only existing skips
in the wider governance ring concern the intentionally retired epic scope
marker; no regression is newly skipped.
Cold base/candidate comparison: **all four EXACT**, including deterministic
workbook cells/formulas/styles and historical certificate signing bytes.

Authenticated Chromium: real UI Save, Reload, canonical Run, STALE after rate
Save and immutable Last Run; actual construction/operating ledgers and S&U
route checked. Solar/Wind, light/dark, 1440px/390px: eight cases pass; no page
errors, editor width within viewport, field contrast >=4.5, collapse/expand.
Server and execution pool terminate normally. CAS/scenario/protected/cross-owner
rejection is additionally covered by authenticated route tests.

Evidence is local and deliberately not committed as binary/generated artifacts:
`artifacts/model-financing-f3/evidence.json`, `solar-saved.png`, `wind-saved.png`,
`solar-{light,dark}-{1440,390}.png`, `wind-{light,dark}-{1440,390}.png`, editor
screenshots in the same folder, and `artifacts/f3/legacy-equivalence.json`.

## Governance, integration and review

The first full Linux CI run exited normally with 12 assertion failures:
11 V6 exact-HTML comparisons exposed random unsaved-editor UUID generation,
and the older productivity DOM guard did not recognize the new F3 registry
field. The same-PR correction makes unsaved proposal IDs deterministic for
the authorized owner/project/scenario/slot, without persisting anything on
GET or replacing saved IDs. Regression tests prove repeatability, isolation
and missing-scope rejection. The DOM guard admits only the exact editable and
protected F3 field keys; every historical golden DOM hash remains unchanged.
No financial, solver, core, workflow or golden file changes in this correction.
Correction ring: **188 passed, rc=0, normal interpreter termination**, covering
all 12 previously failing cases, V6 coherence/isolation/restoration, productivity
DOM, and F3 financial/Workspace/governance tests. Authenticated Chromium's eight
Solar/Wind theme/viewport cases pass again with normal server/executor shutdown.
The earlier certificate + Model V2 governance + F2 ring completed with **99
passed, 10 existing retired-marker skips, rc=0**. The corrected exact-head full
suite remains the final acceptance authority.

No workflow modification or blanket freeze exemption. Exact Git blob pins in
`tests/model_v2_governance.py` recognize only these necessary F3 authorities:

| Path | Git blob SHA |
|---|---|
| finco_core/inputs/multisenior.py | 605e17d743c5999fc4ac1b0a8ce1957a1980511d |
| finco_core/inputs/_models.py | 4d3e07613a69405b443b50d351b828aead825137 |
| finco_core/inputs/serialization.py | 3bd2ee7ce58e1404724bf60487d200059be2d417 |
| financial_engine/financing/multisenior.py | 7fbe0a7b6d0bcd351f019c6a1e85988238a28d3c |
| financial_engine/financing/project.py | 4f8bb815bedef04fd6719cd6f48aea03b2f6e2dc |
| financial_engine/financing/generic_product_policy.py | 9442d55d1579fd050587b4a2692313e4006ec1b2 |
| financial_engine/senior_debt/project_adapter.py | 4d979a9cd97d17ec6560075a852060d6c76eff8d |

Negative tests prove unrelated core/solver/tax/product paths remain blocked;
changing any pinned blob loses approval. Historical exact released hashes
remain valid only at their original contents. The F3.1 two-module pins are
unchanged. No broad namespace authorization, identity dispatch, calibration,
target replay, plug, forced repayment or hidden refinancing.
The historical Finance Integrity helper now checks these exact seven pins
before its older engine path list; a tampered F3 blob cannot inherit the older
path-only exemption. All other historical policy stays unchanged.

Local Windows full safety scan found one environment-only issue in unchanged
`static/vendor/swagger-ui/swagger-ui-bundle.js`: autocrlf bytes differ from its
existing trusted hash. Removing CRLF conversion reproduces the exact Git blob
and expected SHA-256 `fd76294e33356ab3fd111ddaeeb10d3f79de8ae1a4d34dbf777f5eef224648d9`.
All changed files pass the scanner. Neither vendor nor scanner is modified;
the full Linux exact-head safety workflow remains mandatory acceptance.

Essential F1 route/projection and immutable export resolver integration is
included under this mission, after merged F1/F2. Parallel open #239 AI import,
#238 quality/Insight and #237 Radar are not modified. Domain, Radar, Yield,
Protocol and project factories have zero diff. No new financial-statement,
tax, SHL, reserve or sizing solver.

Exact-head CI must include Governance Full History, Dependency Security Audit,
Protocol UI Browser Acceptance, PR Compile and Safety Gate, Public Safety and
Model Smoke. Full pytest must exit normally and evidence upload must succeed;
100% progress alone is not acceptance. Any incomplete/failed gate means
**NO MERGE**. Rollback: disable new activation; historical immutable terms
remain readable, legacy absence unchanged. Independent financial reviewer
must inspect aggregate tax, facility ledgers, maturity, funding and BS before
authorizing a merge.
