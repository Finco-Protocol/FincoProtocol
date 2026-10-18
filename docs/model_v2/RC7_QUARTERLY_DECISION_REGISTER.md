# RC-7 Matched 3/3 Candidate: Financial Decision Register

Base: `05183b2a96c74fd4b3976903c593a61402cab7b3`.
Every decision below is OPEN. Executable proposal parameters are NOT owner
approval, financial release approval, or production activation.

Correction C keeps every decision OPEN while moving the executable research to
`tools/quarterly_research/`. Production financial/core/domain contents equal
verified RC-7A main exactly; no new protected-content successor is needed merely
to run isolated research. Future production quarterly integration still requires
owner policy decisions and independent financial/governance authorization.

Correction B: the decision-ready expansion against RC-7A main
`78e4c0edcc1bdb5013df79f11b3ba7b9c2151013` is in
[the owner decision pack](RC7_QUARTERLY_OWNER_DECISION_PACK.md). It supplies
released behavior, candidate proposal, consequences, numerical examples,
recommendations, required approvals and affected modules for every D-01..D-12.
All decisions below remain OPEN; no policy is accepted by adding that evidence.

| WF-23 decision | Bounded candidate proposal / exact consequence | Release requirement |
|---|---|---|
| D-01 COD stub | KEEP_ACTUAL_COD, no seven-day roll; a one-day initial quarter is retained | Owner acceptance of stub policy |
| D-02 Days | Half-open dates; annual volume fraction = actual days / period-end year's 365 or 366; Senior interest uses its own ACT/360 or ACT/365 | Owner acceptance; operating and debt DCF remain distinct |
| D-03 Horizon | Exactly 4N operating quarters INCLUDING initial stub, not COD+N years; April17 COD with N=1 ends March31 next year | Owner must choose this versus anniversary horizon with terminal stub; latter blocked |
| D-04 Annual clock | Four operating rows including the stub form a model year; degradation, flat annual OPEX and annual depreciation advance once per four rows | Not calendar tax years or elapsed anniversaries; owner acceptance required |
| D-05 Contract dates | No Revenue V2/V3 or dated PPA activation in this first candidate; no intra-quarter weighting | Minimal dated-period handoff to revenue owner; unsupported contracts refused |
| D-06 3/6 | Excluded | Separate cash holding and due-date decision |
| D-07 6/3 | Excluded | Sourced intraperiod cash timing required |
| D-08 Covenants/distributions | No covenant interpretation, distributions or sponsor receipts are authorized by this candidate | Contractual observation dates, lock-up/release and full waterfall integration remain blocked |
| D-09 Reserves | NONE only initially; CASH_DSRA/DSRF refused, not treated as zero reserves | Separate choice of exact dated forward window versus existing next-payment multiplier |
| D-10 Debt maturity | Explicit maturity must equal a quarterly service endpoint; off-grid maturity refused, never extended | A terminal partial debt period needs an explicit matched-axis successor |
| D-11 Tax | Reuse calendar-year ledger with explicit TaxPolicy, four-period metadata and last-tax-year-period payment with zero lag only | No quarterly division of annual thresholds; other timing/ATAD/source conventions blocked pending proof |
| D-12 Facilities | Isolated Solar/Wind clean operating/Senior contracts only; no active SHL, Junior, multi-Senior, BESS, Data Center or EV candidate admission | Legacy four-vertical 6/6 results remain released and unchanged |

## Authority and integration boundaries

`QuarterlyCalendarPolicy` is explicit, immutable and versioned; decoding missing,
unknown and mixed 3/6 or 6/3 policies fails closed. `QuarterlyCandidateCalendar`
binds actual project COD to FC plus construction duration. It does not introduce
a second project COD. All quarter dates and operating counters are carried in
existing `PeriodMeta` records. The existing `CanonicalAxisContract` and
`map_period_vector` retain duplicate/order/membership authority.

One FC-to-actual-COD candidate reporting column is an explicit proposal, not a
change to monthly construction periods, draws, fees, IDC or funding allocation.
Joining real monthly funding into complete project statements remains a separate
required proof; an operating/debt result cannot stand in for a full project Run.

No app writer, route, feature selector, Run History, export, release pin or
existing 6/6 PeriodEngine is changed by A1. Production quarterly admission remains
closed. New protected contents are candidates for independent exact-blob review;
no historical reviewed authority is replaced or self-authorized.
