# WF-07 — Financial Owner Decision Packet

All decisions below are **OPEN**. The candidate encodes none of them: where a
choice is needed it is supplied as explicit evidence, represented as a
`Decision` whose only value is `OPEN`, or returns `UNSUPPORTED` / `UNAVAILABLE`.
No policy is silently inferred. Self-approval is not permitted.

| ID | Decision | Candidate behaviour until decided |
|---|---|---|
| W-01 | DSRA target horizon (months/periods) and measurement date | target is supplied evidence; `forward_requirement()` takes an explicit horizon and is never applied implicitly |
| W-02 | Aggregate vs per-facility reserve determination | both derivations available as evidence; neither is selected |
| W-03 | DSRF availability, drawing conditions, fees, interest and commitment fee | draws allowed only by explicit policy flag; `fee_policy` can only be `OPEN`; no fee is computed |
| W-04 | Cash waterfall ranking (reserve position, DSRF restoration vs DSRA top-up, DSRA vs DSRF draw order) | one supported order (mirrors released DSRA-after-senior); every other combination `UNSUPPORTED` |
| W-05 | SHL cash vs PIK treatment, PIK-to-cash switching, accrual convention | cash/PIK per phase supplied; accrual fraction supplied; no day count chosen |
| W-06 | Tax deductibility of SHL interest and capitalisation for tax | `tax_deductibility` can only be `OPEN`; classification (capitalised / operating candidate) is accounting-only |
| W-07 | Junior / senior and SHL intercreditor treatment | fixed order SENIOR → JUNIOR → SHL; no turnover, standstill or sharing mechanics |
| W-08 | Reserve release conditions (excess release, release with simultaneous shortfall) | excess release mirrors released engine; release together with a shortfall ⇒ `WF07_RELEASE_AND_SHORTFALL_OPEN` |
| W-09 | Default, shortfall and cure mechanisms (deferral, arrears, cure period, pro-rata) | any shortfall halts the run with a typed reason; allocation only as supplied `paid_service` evidence |
| W-10 | Sponsor distribution restrictions (lock-up ratios, reserve conditions, retained-cash carry-forward) | surplus is a *candidate* only when every reserve meets target; retained cash is reported, never carried forward |
| W-11 | Equity vs SHL funding order and mix during construction | equity pools depleting in declared order after dated senior and SHL draws; no optimisation |
| W-12 | Initial DSRA funding source (construction use vs operating build-up) | `RESERVE_FUNDING` use must equal opening balance; DSRF is never cash pre-funded |
