# WF-23: Operating and Debt Frequency Authority V1

## Decision status and provenance

Architecture candidate, NOT financial methodology approval or quarterly enablement.
Branch: `feat/model-rc6-period-frequency-authority-v1`.
Inspected main: `97c5286a8bbd22e02e843a234a415765db6b95d7` (normal merge of #307).
Prior integration head: `af042d96b7351783439e876b094f9a2431f866a2`.

| Accepted prior work | Integrated source head | Main ancestry |
|---|---|---|
| #303 Performance V7 | `2a680a1410b307e0470c0f62cac7e45af821a42e` | Required and verified |
| #304 Product reliability | `025257eff4d121d805dfcdd1b595f32bf754a2a0` | Required and verified |
| #305 Excel migration V4 | `674d40032781ba09a52f1e0887f97daebcb24c9b` | Required and verified |
| #306 Project Timeline | `f37fb87132e4d96a5d974ebc5574d057291a11a4` | Required and verified |

This change owns two documents, a non-production geometry utility and its tests.
No shared application, financial/core/domain, writer, historical evidence,
workflow, tolerance, reference expectation or released authority file changes.
No new frequency control. All quarterly examples are explicitly shadow results.

## 1. Verified current authority

| Boundary | Actual current source and behavior | Consequence |
|---|---|---|
| Input enum | `finco_core/inputs/_models.py::PeriodFrequency`; separate numeric enum in `finco_core/engine/period_engine.py` | An enum member is not runtime support. Enum representations must not be conflated. |
| Calendar | `PeriodEngine.__init__` rejects all but SEMESTRIAL; validates supplied COD against FC plus construction months | Preserve this rejection and both released axis conventions. |
| Clean input bridge | `financial_engine/adapters/project_inputs.py::from_project_inputs` builds `CalendarInput`, which has no frequency field | Critical integration gap: the bridge cannot transmit a quarterly choice. |
| Clean orchestration | `financial_engine/orchestrator.py::_build_period_engine` and `_build_project_inputs_proxy` explicitly choose SEMESTRIAL | Do NOT claim every clean entry rejects quarterly. A changed upstream enum can lose its meaning before reaching this hard-coded calendar. The new test demonstrates adaptation only, never executes that input. |
| Senior contract | `financial_engine/senior_debt/project_adapter.py` permits only SEMESTRIAL; tenor is years times 2 operating rows | Parameterized solver primitives do not establish end-to-end quarterly support. |
| F3 legacy contract | `finco_core/inputs/financing_instruments_legacy.py::_map_legacy_financing` requires SEMESTRIAL and selects operating row `tenor * 2 - 1` | Maturity is an authoritative operating-axis date, not FC plus tenor. Existing unsupported-frequency test stays intact. |
| Axis contract | `CanonicalAxisContract.from_periods_and_policy` derives full, operating and Senior subsets before accepting solver results | Extend typed axis ownership, never derive expected periods from solver outputs. |
| Validator | `validate_canonical_period_axis` checks order, date continuity, counts, fractions, flags, and counters; counters explicitly use 2 | Quarterly needs independently reviewed generation AND validation changes. |

### Released six-month semantics that must not be cleaned up accidentally

- Calendar boundaries are June 30 and December 31, strictly after operating start.
- COD remains FC plus the configured construction months. The source convention
  does not authorize substituting the first operating boundary for actual COD.
- A COD less than seven days before the nearby boundary is rolled to that
  boundary for operating start; exactly seven days is NOT rolled.
- Operation has exactly `2 * horizon_years` rows, including an initial stub.
  The final date is consequently not necessarily COD plus horizon years.
- Model/operating year is sequential pairs of rows, NOT necessarily calendar year
  or completed twelve-month anniversaries. The stub participates in the count.
- When first operating start equals actual COD on day 1, operating metadata can
  include one extra day. This is not the universal debt-interest convention.
- Generic convention uses the period end year's 365/366 denominator. The released
  source-aligned convention uses the NEXT year's denominator for December-ending
  operations. Construction uses its own end-year denominator.
- Generic construction model columns use meaningful six-month segments, folding
  a less-than-seven-day terminal remainder; source-aligned uses one construction
  column. Neither is the monthly construction payment/IDC axis.
- `is_ppa_active` uses period START relative to the convention's PPA endpoint.
  This is a coarse legacy flag, not approval for new intra-period settlement.

Examples independently checked: Jan 31 plus one month in 2028 is Feb 29; plus two
months from the ORIGINAL anchor is Mar 31. June-29 COD can start operations June 30
without moving actual COD. H2 2027 metadata is 184/366 under the source convention
but 184/365 under generic; changing either would change released output.

## 2. Financial authority matrix

| Layer | Existing released authority | Future contract / unresolved approval |
|---|---|---|
| Monthly construction | `ConstructionFinancingInput.periods`, CAPEX codes and timing-only weights, `build_construction_runtime_config` | Keep dates, flags, profile totals and amount ownership unchanged; do not turn monthly weights into operating-quarter weights. |
| Draw waterfall | `finco_core/construction/allocator.py`: committed equity layers, additional equity, SHL, Junior, Senior residual | Same per-month cash sources and commitment checks; no extra draws to accommodate a new reporting axis. |
| Senior IDC / fees | `stage_b2.py` and construction adapter, capitalized finance costs, approved funding fixed point | Construction ACT convention is inclusive where adapter specifies it; retain rates, timing, opening/undrawn basis and commitment audit exactly. |
| VAT | Typed facility dates, lag in construction/facility periods, eligibility and tail | A six-period refund lag is not automatically six operating quarters. Keep the facility's own axis and cost basis. |
| Sources & Uses | `financial_engine/financing/project_uses.py` and canonical construction funding | Aggregate approved monthly results without recalculating cost, IDC or funding. Preserve construction-to-statements date joins. |
| Operating accrual | Released PeriodMeta semantics above | Q1/Q2/Q3/Q4 boundaries are Mar 31, Jun 30, Sep 30, Dec 31; actual COD, stub, day inclusion, fraction and horizon choices require D-01..D-04. |
| Revenue / OPEX | `year_index` / `day_fraction`, dated multistream validation and published index observations | Do not double the number of annual escalation events. Preserve actual contract dates and distinguish model year from tax/calendar year. |
| Senior debt quantum | Bank sizing CFADS and canonical sizing modes; gearing on independent Project Uses | Base cash must not resize a bank-sized contractual schedule. Reuse the solver, feed correctly matched cash/rates/DSCR targets. |
| Interest | Senior `period_day_fraction`: half-open actual date span / 360 or 365; separate construction and SHL conventions | Carry debt accrual dates separately from operating volume fractions; no blanket division of annual interest by 4. |
| Principal / maturity | Contractual axis subset, existing balloon rejection and terminal liability | Decide final partial debt period or refusal explicitly. No rounding maturity, forced payoff, terminal draw or hidden refinance. |
| DSRA / DSRF | Operation policy and facility fee authority | See D-09. Current forward target is next DS times months times periods/year / 12; it is NOT a general dated sum of variable future instalments. |
| Covenant / distributions | Existing DSCR checks, Senior-first cash, reserve/lock-up/release rules | New observation windows, rolling tests and cash held between debt dates require financial approval. Never average ratios or unlock cash from a geometry result. |
| Book/tax and returns | Existing book basis, depreciation, annual tax, dated Project/Sponsor returns | Preserve annual tax policy and finance-independent Project IRR; do not manufacture quarterly tax payments or rescale book lives. |

### The four frequency pairs

| Operations / debt | Current availability | Proposed path and non-inferred policy |
|---|---|---|
| 6 / 6 months | Released, subject to each project's existing typed financing support | Default. Preserve all existing reference results bit-for-bit. |
| 3 / 3 months | Not available | First future executable slice after matched-axis review: quarterly cash accrual, debt dates, rates, targets, taxes and downstream evidence together. Not activated here. |
| 3 / 6 months | Not available | Whole quarterly intervals can sometimes map into half-years. That does NOT approve cash accumulation, intra-half-year interest, reserves, DSCR testing or dividend release. D-06..D-09 required. |
| 6 / 3 months | Not available | Six-month totals do not prove quarterly cash arrival. Reject unless an independently authorized finer cash/settlement profile exists. No equal split or day-weighted CFADS invention. |

Important geometry counterexample: COD April 17 with fixed row counts gives
different terminal dates for `4*N` quarters and `2*N` half-years. A common-count
assumption therefore cannot support mixed frequencies. The shadow mapper rejects
this mismatch. An explicit COD-anniversary horizon can align both grids, but is
a DIFFERENT, not yet approved economic horizon with a possible terminal stub.

## 3. Implementable future contract (proposal only)

Do not add these fields to production in this PR. The next reviewed design must
carry a versioned `OperatingCalendarPolicy` and separate `DebtServiceCalendarPolicy`:

1. Operating policy: explicit 3/6-month enum, calendar-boundary rule, actual COD
   source, first-stub treatment, day-inclusion convention, fraction policy,
   model-year/escalation clock, horizon basis and terminal-stub treatment.
2. Debt policy: explicit service frequency, dated accrual start/end and due date,
   repayment start, contractual maturity and final-stub rule, rates and target
   DSCR keyed to debt dates, and contractual covenant observation dates.
3. `TemporalBridge`: typed construction, operation and debt axes, complete
   interval membership and cash receipt/payment timestamps. Reject missing,
   duplicated, overlapping or orphan intervals BEFORE calculation. Geometry and
   cash economics are distinct evidence. Do not infer cash from row positions.
4. Preserve the existing canonical full/operating/Senior axis invariant for 6/6.
   A mixed-frequency successor needs an independently derived DEBT axis, not a
   claim that one model period index can identify both quarterly cash and
   semiannual debt service. Use date-and-axis keys at cross-axis joins.
5. Serialization: versioned explicit fields, legacy absence resolves ONLY to the
   already released 6/6 contract. No defaulting unknown values to semiannual.
   Admit new modes only when adapter, orchestrator, validator and all consumers
   understand them. The current missing CalendarInput bridge must close first.
6. Identity: include both policies, convention version and effective axis in
   input fingerprints, Working Copy/scenario CAS and persisted Run evidence.
   Frequency changes mark old results STALE. Never reinterpret old Run vectors.
7. Compare/export: use each Run's stored dates and units. Different-frequency
   comparisons need an explicit common reporting basis or truthful unavailable;
   no index zip, quarter-to-half-year ratio averaging, or export-time rerun.

The precise field/module changes require separate exact-path scope and reviewed
financial Git blobs. No release-map additions or new authorization pins here.

## 4. Finance-owner decisions still OPEN

| ID | Required decision | Recommendation, NOT approval |
|---|---|---|
| D-01 | Quarterly short COD stub: keep, roll, or alternative | Show actual COD and operating start separately; no inherited 7-day rule without explicit acceptance. |
| D-02 | Operating first-day inclusion and quarter fractions | Keep released 6-month conventions; decide quarterly independently. Interest remains its own day count. |
| D-03 | Fixed period count vs exact dated economic horizon | Preserve fixed-count legacy. Review exact-anniversary alternative and terminal stub before any mixed grid. |
| D-04 | Model-year degradation/inflation vs elapsed anniversaries | Explicit clock per economic input; never make four rows behave as two years. |
| D-05 | PPA expiry/review inside a period | Preserve legacy and PPA-01 contracts. New weighting requires separate approval; otherwise refuse unsupported timing. |
| D-06 | 3/6 cash holding and interest timing | Specify cash carry, eligible CFADS period, due date, interest accrual and unpaid liabilities. Geometry alone is insufficient. |
| D-07 | 6/3 cash profile and contractual service budget | Remain unsupported without independently sourced subperiod cash timing. |
| D-08 | Covenant measurement and distributions between debt payments | Contractual measurement basis, lock-up/release authority and missing-evidence result must be explicit. |
| D-09 | Reserve months over nonuniform service/stub periods | Approve exact forward window vs existing next-payment multiplier; do not silently replace approved DSRA policy. |
| D-10 | Tenor not divisible by period length | Dated last stub or typed unsupported result; never extend maturity or hide unpaid debt. |
| D-11 | Annual CIT / ATAD / LCF and cash-tax due dates | Calendar-year policy stays authoritative; quarterly allocation/payment must follow approved TaxPolicy, not divide annual tax by 4. |
| D-12 | Scope of quarter-ready technologies/instruments | Prove Solar/Wind first; do not imply Data Center/EV, F3 multi-Senior, Junior, SHL or gated features are automatically supported. |

No new owner approvals were obtained in this workstream. Recommendations and
successful shadow tests cannot close these decisions.

## 5. Executable evidence and deterministic acceptance

Utility: `tools/period_frequency_shadow.py`; tests:
`tests/test_period_frequency_authority_v1.py`. No production imports in the tool,
no runtime consumers, no money allocation, no financial result or persistence.
`ShadowPeriod` deliberately lacks the production axis interface. Every result
is labelled `SHADOW_NOT_FINANCIAL_RUN`; all convention arguments are explicit.

- Released six-month axes: exact dates, day counts, float fractions, sequential
  model years/slots and final horizon against independent rational geometry for
  both conventions, leap years, month ends, 1/5/13/17 construction months and
  the six-versus-seven-day stub threshold. No numerical tolerance added.
- Actual quarterly PeriodEngine construction continues to raise
  `PERIOD_AXIS_FREQUENCY_UNSUPPORTED`. Preserve existing F3 legacy rejection
  `test_unsupported_period_frequency_not_silently_read_as_semiannual` unchanged.
- Quarterly geometry: ordered, positive, unique, contiguous intervals; explicit
  count/date horizons; rational fractions; observed terminal stub differences.
- Four frequency pairs: complete, nonduplicated whole-interval membership where
  valid; reject disaggregation, horizon mismatch and malformed row sequence.
- PPA expiry and 17-month tenor: report boundary/interior status, never relocate
  a date or generate revenue/principal for it.
- Existing annual presentation helper: flow sums versus last stock, using
  independent Decimal synthetic values on both grids. This is NOT tax, DSCR,
  contractual settlement or quarter-ready financial statement acceptance.
- Four released reference verticals: cold canonical financial evaluations
  before and after shadow study must be exactly equal across all unrounded
  dataclass fields and input fingerprints. Max permitted difference is ZERO.

Future financial acceptance (not demonstrated by this geometry PR): every
dated/monthly source maps exactly once; whole-vector Revenue/OPEX/depreciation/
tax/CFADS/DS/stock/returns evidence is reconciled independently; no missing cash;
full Sources=Uses, Assets=Liabilities+Equity and unpaid-maturity rejection retain
their EXISTING approved tolerances. New cases require approved independent
Decimal expectations, never expectations copied from candidate output.

### Independent numeric examples for the future acceptance fixture

These are synthetic arithmetic oracles, not executed quarterly financial Runs:

| Explicit assumptions | Independent expected value / refusal |
|---|---|
| Senior accrual Jan 1 to Mar 31 2028, half-open ACT/360, opening 1,000 kEUR, annual 6% | 90 days; DCF 90/360; interest 15 kEUR. Operating metadata can instead be 91/366 under the explicit first-day rule; never substitute it for debt DCF. |
| Construction Feb 1..Feb 29 2028 inclusive, unchanged opening 1,200 kEUR, annual 6%, ACT/360, no new draws/fees | 29 days; IDC 1,200 * 0.06 * 29 / 360 = 5.8 kEUR, regardless of proposed operating frequency. |
| Four service dates, CFADS 30 each, target 1.20, no interest/fees/reserves, debt 100, all cash service eligible | Capacity 25 per service date; principal 25 each; terminal zero. This toy oracle requires the stated conditions, not a new runtime mode. |
| Same dates with CFADS 20 each, no interest, debt fixed at 100 | Total service capacity 200/3 kEUR; unpaid 100/3 remains. Reject full repayment; do not plug the remaining principal. |
| Two quarterly CFADS values 30 and 60, proposed half-year test at 1.50 | A conditional SUM-window oracle is 90 / 1.50 = 60 service capacity ONLY IF D-06/D-08 approve that window and cash eligibility. It is NOT approved here and does not prove timing of payment. |

### Executed local validation

Windows, Python 3.12.10; disposable local test data, no staging activity.
New module: **56 passed**. Combined focused ring: **223 passed, 0 failed,
0 skipped**, including those 56 (not 279 unique tests); pytest process exit 0.
The combined ring also ran the existing complete modules:

- `tests/test_financing_f3_canonical_legacy.py`
- `tests/test_model_v2_revenue_runtime_parity.py`
- `tests/test_model_project_timeline_v1.py`
- `tests/test_workflow_c_statements_analytics_trace.py`
- `tests/test_model_v2_released_engine_authorities.py`

Four-vertical before/after unrounded financial structures compare exactly;
unexplained numerical changes: **zero**, maximum numerical difference **0**.
All documented source paths were checked for existence. New Python files compile;
the unchanged public safety scanner passes all four delivery files. Git diff
hygiene and frozen namespaces are checked again at publication. Exact-head
GitHub CI is a separate pending acceptance authority, not a local test claim.

## 6. Minimal coherent successor sequence

1. **Owner decision checkpoint:** close applicable D-01..D-12 and agree with
   CAPEX Workstream B / OPEX Workstream D. Approve exact financial paths before
   implementation; preserve all historical blob authorities.
2. **Matched 3/3 canonical slice, initially release-closed:** one coherent
   successor spanning typed/serialized calendar, adapter and orchestrator,
   generator and validator, Revenue/OPEX/depreciation/tax, bank-sized Senior,
   reserves/distributions, statements/returns and axis-bound result evidence.
   Internally staged commits are fine; do not expose a partially migrated axis.
   Exact content receives independent financial review before any release pins.
3. **Product admission and historical evidence:** only after financial acceptance,
   add authorized Save/scenario/CAS control, truthful availability, Run identity,
   Diagnostics/Trust, import and reporting/export. Default remains 6/6. No rollout
   until full exact-head governance, financial, security and browser acceptance.
4. **Mixed 3/6**, separate optional successor after D-06/D-08/D-09/D-10: dated cash
   bridge, service accrual, covenant and reserve evidence together. **6/3 remains
   blocked** until D-07 has real subperiod cash authority; it is not a UI option.

See [dependency matrix](PERIOD_FREQUENCY_DEPENDENCY_MATRIX.md) for exact current
consumers, owners, risk and required regression contracts. No shared edits with
Workstream B/D. Their PRs were not yet available at preflight; owner will provide
links. Interface acknowledgement remains outstanding, not a development blocker
for these isolated documents and shadow tests.
