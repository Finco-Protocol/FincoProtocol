# WF-03A — Generation Losses & Pre-COD Candidate V1 — Financial Owner Decisions

Candidate branch: `feat/wf03a-generation-losses-precod-v1` (base `b72942f22f1d3a8dcce351b56b96fdba0e6b9cdd` = current main; the mission checkpoint `0397d9af…` is a contained ancestor).
Candidate package: `app/generation_v2_candidate/` (release-closed; `GENERATION_V2_RELEASE_CLOSED`; never imported by production).
Companion document: `WF03A_GAP_CROSSWALK.md`.

**Every decision below is OPEN.** The candidate implements only the deterministic
core each decision would operate on. Where the code pins a convention, it is
stated explicitly as the V1 candidate convention, never as approved policy.

Reference note: Harvest V4 observations are OBSERVATIONS of reference
behaviour, not FINCO-approved policy. Nothing in this packet treats a
reference number (e.g. a loss factor, a ramp shape, an NPV delta) as authority.

## D-01 — Order of physical losses

The candidate composes, per operating period: degradation factor (explicit
onset) × availability (first-year vs normal) × transmission loss (evaluated at
the period's canonical boundary date), and applies named volume-adjustment
events to GROSS generation by exact day-count proration.

OPEN: is that the authoritative order (events on gross, transmission last), or
do volume events apply to grid-delivered energy (i.e. after transmission
loss)? The two orders produce different lost/compensated quantities whenever
both an event and a non-zero loss factor hit the same period. The candidate's
`compose_operating_adjustments` + `apply_volume_adjustments` keep the
mechanisms separately auditable precisely so either order can be wired once
decided. Confirm or replace.

## D-02 — Compensation basis and over-recovery

- CONTRACTED compensation settles at an explicit EUR/MWh price supplied on the
  event; MERCHANT compensation settles at declared market-price evidence (a
  missing price is UNAVAILABLE — the aggregate is not published, never zeroed).
- `compensation_pct` is capped at 100 in V1: over-recovery (compensation
  above the lost revenue) is NOT representable. Owner decides whether
  over-recovery exists contractually and, if so, its cap and its ledger
  (the candidate would need a typed extension; it is deliberately absent).
- The candidate fails closed when the total event deduction exceeds a period's
  gross energy. Owner confirms that deductions above production must always
  fail (vs clamp).

## D-03 — Curtailment versus compensated generation

V1 models a curtailment/outage as one event with `energy_loss_pct` plus an
optional compensation. OPEN: must curtailment events also reduce the
production basis used by availability/degradation statistics, or are they
purely additive deduction lines on top of the canonical schedule? The V1
candidate treats them as additive deductions (the canonical released schedule
is never re-derived). Confirm the reporting basis.

## D-04 — Degradation onset timing

- V1 convention: `first_affected_year` is expressed in the released
  COD-anchored operating-year indexing; `first_affected_year=2` reproduces the
  released formula `(1 - pv_degradation) ** (year_index - 1)` exactly (proven
  against `finco_core/revenue/generation.period_generation` in tests).
- OPEN: contract-anniversary vs operating-year anchoring for the onset (a
  contract signed mid-period may degrade on a different clock). The released
  axis has no mid-period degradation semantics (cf. PPA-01's
  `PERIOD_BOUNDARY_ONLY` review policy); any anniversary-based onset needs the
  same boundary rule decision.
- OPEN: does the zero-degradation case (`annual_rate = 0`) also need an
  explicit onset for documentation, or is the rate sufficient?

## D-05 — First-year availability conventions

- V1 convention: every operating period with `operating_year_index == 1`
  (including a partial COD stub) uses `first_year_availability`; later years
  use `normal_availability`; no annualisation exists anywhere in the candidate
  (the canonical `day_fraction` proration is the only energy proration).
- OPEN: should a very short COD stub instead inherit the normal availability
  (or be excluded from availability statistics entirely)? The alternative
  treatments fail closed in V1 (`PARTIAL_COD_TREATMENTS` carries exactly one
  member) pending this decision.

## D-06 — Commissioning energy basis and ramp

- V1 convention: monthly potential energy = `capacity_mw × declared month
  hours × ramp_pct/100 × availability`, with month hours DECLARED as evidence
  (never derived from a calendar inside the candidate) and the ramp window
  exactly `[commissioning_start, COD)` — the COD month is never a
  commissioning month.
- OPEN: the source and vintage of the declared month hours (P50-based
  simulation vs contractual commissioning schedule) and their timezone/day-count
  convention.
- OPEN: ramp granularity (calendar-month percentages pinned in V1) vs
  daily/half-daily ramp curves for dense commissioning programmes.

## D-07 — Pre-COD revenue, tax, CAPEX, financing and equity treatment

The candidate produces PROPOSALS ONLY: per-month physical generation and
potential sales. **Nothing is posted** into the construction waterfall, tax,
IDC, equity balancing, or any persisted authority — that is exactly the
Financial Owner accounting decision this candidate does not preempt:

- Are pre-COD sales credited against CAPEX (reducing the depreciable base),
  booked as operating revenue with a construction-period P&L, or deferred?
- Tax treatment of pre-COD receipts (and interaction with IDC capitalisation).
- Equity/financing: do commissioning receipts fund construction cash needs
  first (reducing draws/IDC), flow to sponsors, or sit in DSRA-like reserves?
- Currency/timing: settlement dates for pre-COD sales (delivery month vs
  payment lag).

Until decided, the candidate must remain un-wired (it is, by construction:
`TestProductionIsolation`).

## D-08 — Revenue V4 settlement integration boundaries

The Revenue V4 candidate (merged via PR #363, release-closed) owns
negative-price-hour policies, contracted-volume modes, merchant price modes
and route-to-market fees; WF-03A owns physical generation adjustments and
pre-COD commissioning. Deliberate non-assumptions:

- A WF-03A curtailment event and a Revenue V4 CURTAIL negative-price policy
  are DIFFERENT mechanisms (physical removal vs settlement of negative-priced
  energy). Whether they may co-exist on the same stream, and their order, is
  open.
- WF-03A volume events are keyed by dates and percentages; Revenue V4
  contracted volumes are share/fixed/shape modes. If a fixed-annual-MWh
  contract (Revenue V4) must net against WF-03A losses, the netting authority
  is undecided.
- Compensation pricing for volume events (contract price vs merchant
  evidence) must not silently conflict with Revenue V4 price-mode resolution;
  the integration order is undecided.

## Required approvals for ANY release path

1. Financial Owner exact-content decision for the released slice (house style:
   `FINANCIAL_OWNER_*_DECISION_*.md` + exact JSON record + tests-side content
   pin, cf. the V11 Stage 3 precedent).
2. Independent review of every byte that would leave this package.
3. A governance successor slice in `tests/test_ci_acceptance.py` (exact path +
   exact blob map) if/when any protected file must change to wire a released
   policy — including `finco_core/revenue/generation.py`, which is currently
   held at its PPA-01 pinned blob.
4. Until then the package stays release-closed and production-invisible.
