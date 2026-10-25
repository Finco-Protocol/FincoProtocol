# WF-06 advanced credit sizing/sculpting V1 — release CLOSED

## Source and existing authorities

Intake main a0c0d3efd215a28a82b6d01294186ddc373e943b, tree
8da40fcec8df1c843bd8de28562a7e760eeafb7c. No overlapping open WF06 PR was
found. Performance PRs #318/#321/#322/#324/#327/#328 remain independent.
This candidate owns only app/model_v2/credit_wf06_candidate, its new test and the
two WF06 documents. No released-source edit, governance extension or new pin.

Read authorities: financing_f3/F31_MULTITRANCHE_CANDIDATE_DESIGN.md,
F31_GPT61_ARCHITECTURE_REVIEW_PACKET.md, WFA_FINANCIAL_GAP_AND_AUTHORITY_REGISTER.md,
INSTITUTIONAL_CREDIT_V5_ACCEPTANCE.md and actual senior_debt policy/solver/models.
The gap register is historical, not proof every historical limitation still exists.

- Released Senior policy already distinguishes DSCR_SCULPTED, GEARING_CAP,
  COMBINED_MINIMUM and EXPLICIT_SCHEDULE. Repayment and sizing are separate:
  default gearing uses level principal; explicit M-6 opts into full-tenor sculpting
  without resizing gearing-sized debt; combined minimum retains DSCR repayment.
- Released solver owns iterative tax/CFADS/interest finalization, no-capitalization
  backward capacity and terminal checks. This candidate does not duplicate that
  production engine and does not accept debt-dependent CFADS for sizing.
- Released two-senior F3 has independently contractual facility schedules and
  exactly-two validation. Its source and all tests remain unchanged.
- F3.1 N-tranche candidate owns contractual level/bullet schedules, grace, dated
  draws/fees and sources/uses. Its reverse import guard prohibits another app
  module importing that package. WF06 therefore uses the explicitly allowed
  typed-equivalent receipt seam, not an allow-list modification or dynamic import.
- Existing valuation already owns dated NPV/LLCR/PLCR conventions, while Credit V5
  is read-only historical analyst headroom, not a new sizing or underwriting engine.
  No route or persisted Run authority is introduced here.

## V1 inputs and algorithms

Everything is immutable and non-authoritative. Explicit finite Decimal kEUR,
canonical integer period IDs, per-period cash CFADS, interest factors, sizing
DSCR targets, discount factors and provenance are required. Arithmetic uses a
fixed 50-digit ROUND_HALF_EVEN context. No currency/rate/day-count defaults or
missing CFADS-to-zero conversions. Canonical contiguous IDs need not begin at 1.
Rows represent fully drawn opening operating debt; future operating draws,
capitalized interest, FX, fees/reserves and construction funding are not recomputed.

`Facility` is typed-equivalent evidence: identity, fixed commitment, own grace /
repayment start, maturity, immutable rows (opening, interest, principal, closing)
and provenance. The supplied authority already determined interest. Each row must
conserve debt exactly and reconcile to the prior closing; service = interest +
principal; principal in grace, duplicate IDs or gaps are rejected. Float receipt
rounding/conversion is NOT guessed; an F3.1 adapter requires Gate R and an approved
precision/reconciliation policy. Existing engine floating tolerances are untouched.

`dscr_capacity`: for declared debt-INDEPENDENT CFADS only, a single contractual
rate-factor/target window uses backward induction. B_t=CFADS_t/target_t;
closing is capped to B_t/f_t to prevent unpaid interest capitalization, then
opening=(closing+B_t)/(1+f_t). Before repayment start only the interest-affordability
cap applies, with no principal. Missing sizing CFADS => UNAVAILABLE; negative sizing CFADS => UNSUPPORTED;
zero cash is a genuine zero capacity. Debt-dependent/non-monotone or iterative
solver capacity cases => UNSUPPORTED (requiring that capacity makes sizing UNAVAILABLE);
no fake CONVERGED result or algebraic scaling of a
committed Run. This does not jointly size heterogeneous tranches with shared cash.

`size`: explicit, gearing (eligible uses * fraction), DSCR or minimum of all
explicitly applicable constraints. An immutable applicability declaration is
required for EXPLICIT, GEARING and DSCR; None never declares inapplicability.
Callers supply complete priority for ties;
all constraint values, all ties and violated caps are retained. An unavailable
DSCR constraint stays explicitly unavailable even when fixed debt is retained. EXPLICIT and
GEARING amounts are not silently reduced to DSCR capacity. MINIMUM proposes a
new hypothetical amount, never edits an existing commitment. No iterative solve
is claimed: numerical=CLOSED_FORM_NOT_ITERATIVE, lender acceptance=NOT_ASSESSED.
`check_committed_limits` applies gearing ONCE to the sum of supplied commitments,
not the full borrower cap once per tranche. A mixed-rate aggregate DSCR capacity
must be supplied by an appropriate authority or remain absent; never fabricated.

`sculpt`: a single supplied-debt proposal pays opening * supplied factor interest,
then nonnegative principal limited by CFADS/target minus interest, balance and the
explicit repayment window. Debt is never resized, interest never capitalized,
and unpaid terminal debt remains visible. Target feasibility is separate from
cash feasibility: an interest payment can fit actual CFADS while missing a sizing
target. Maturity principal above the explicitly supplied limit is rejected (this
limit means ALL principal due in that maturity period, not an inferred covenant
balloon definition). Residual terminal debt is never treated as a successful repay.

`assess`: validates immutable independent ledgers, aggregates each canonical
period's obligations once, reports aggregate Senior DSCR and cash feasibility.
Per-facility DSCR/LLCR/PLCR requires explicit nonnegative period shares, a stated allocation basis, and shares summing at
most one; no allocation means UNAVAILABLE, never every facility receiving the full
CFADS. Partial allocations leave cash unallocated. Sizing targets are NOT covenants:
contractual covenant comparison requires a separately supplied threshold.
Principal reconciliation, independently evidenced per-facility interest
reconciliation, combined accounting, cash feasibility, contractual maturity/balloon feasibility,
target feasibility, covenant feasibility
and lender NOT_ASSESSED remain distinct.

LLCR = supplied discounted loan-life CFADS / supplied opening debt at the declared
valuation origin; PLCR uses the full supplied project axis. Aggregate loan-life
ends at the last facility maturity (explicitly supplied and validated); each
facility uses its own maturity. DF dates/convention must be explicitly declared,
otherwise coverage is UNAVAILABLE. Factors must already be aligned to the opening
valuation origin, with matching nominal/real/currency basis. Zero denominators are
UNDEFINED, not infinity/zero/pass. Missing cash makes coverage unavailable. No
LLCR/PLCR target resizing, date interpolation or WACC choice is implemented.

`propose_sweep`: ONE period, explicitly supplied cash after reserves <= aggregate
CFADS minus contractual service. Explicit tranche weights sum <= one; proposals
are capped by each closing balance. No future schedule, interest/tax/CFADS or
waterfall mutation is claimed. A multi-period sweep/interest recomputation needs
the canonical engine under Gate R; repeated one-period calls are not an integrated
sweep plan and must not be summed as if independent histories.

## F-1/F-2/F-3 and unsupported semantics

F-1: historical names do not establish behavior. Current policy/solver mappings
above are authoritative. Candidate names describe their actual calculation; no
production mode is renamed.
F-2: `_solve_gearing` level-principal and `_solve_explicit` can finalize as
CONVERGED after cash/interest reconciliation without that being covenant/lender
acceptance. Current DSCR-sculpted paths also have explicit infeasibility gates.
Do not characterize every released path as still having one historical bug.
WF06 demonstrates reconciled fixed debt with DSCR <1 as a cash BREACH, without
changing its commitment, or turning convergence into feasibility/approval.
F-3: supplied-independent CFADS capacity is monotone on the tested fixed-factor
axis; this proves nothing about endogenous tax/CFADS feedback, binding-mode
switches or full production debt directionality. Those remain owner/canonical
solver questions. Non-monotone/endogenous sizing is explicitly unavailable.
Unsupported LLCR/PLCR resizing, EoD and executable cash sweep are not promoted by
the presence of arithmetic or historical Credit V5 analytical metrics.

## Acceptance and preservation

The new matrix covers fraction-based PV capacity, matching released single-facility
backward capacity at zero/nonzero rates, mixed three-facility maturity/level/bullet,
aggregate shortfall and no CFADS duplication, explicit shares and hand-discounted
LLCR/PLCR, fixed debt breaches, grace/interest starvation/balloon, missing/negative /
zero cash, invalid input, monotonic conditional cases, unavailable endogenous solve,
rounding independence and bounded sweep. Existing F3.1 tests independently exercise
N=2 equivalence with released Solar/Wind schedules and the released exactly-two
boundary. No new N-tranche production composition is claimed.

All protected financial/core/domain/native sources, reference inputs, four-vertical
Run paths, provenance and old tests are unchanged. Local and exact-head CI evidence
must be read with their actual source IDs; no earlier green SHA is inherited.

## Gate-R dependency map

1. Financial Owner decisions in WF06_FINANCIAL_OWNER_DECISIONS.md, then independent
   numerical/architecture review. Neither the flag nor text provenance is approval.
2. F3.1 receipt adapter with original period IDs, facility rate/grace/maturity axes,
   construction funding/fees and explicit float precision policy; retain released
   two-senior handshake, do not bypass the current reverse-import guard.
3. A separately authorized protected-source successor for joint heterogeneous sizing,
   tax/CFADS/reserves feedback and executable sweep; existing canonical solver must
   supply actual convergence/residual status. Stop that path in this PR.
4. Exact-content pin-chain/owner records for any released blob change, followed by
   four-vertical and N=2 bit-identity/inactive parity, N>=3 independent oracles.
5. Only later authorized canonical Run/CAS/serialization/evidence/export wiring and
   product acceptance may release anything. No frontend, persistence, flags or CI
   changes belong here. No lender acceptance inferred from green technical CI.

## Correction A — explicit applicability and accounting evidence

`size` and `check_committed_limits` require a tuple of exactly three unique
`Applicability(name, state, reason)` records. States are REQUIRED or INAPPLICABLE;
every declaration needs a nonblank rationale. No default inference from None.
Inapplicable constraints must have no supplied value/partial value/status evidence;
selected fixed modes must themselves be required. Empty mandates, duplicate or
unknown names/states and contradictory values fail closed.

`Sizing.evidence` records every constraint in declared priority: AVAILABLE, MISSING,
UNSUPPORTED or INAPPLICABLE. A required DSCR capacity supplied as None or an
UNAVAILABLE Metric is MISSING; the capacity function now explicitly labels
unsupported endogenous/negative sizing as UNSUPPORTED. A complete MINIMUM needs
ALL required constraints AVAILABLE; otherwise status UNAVAILABLE, complete=False,
and amount=None. Explicit exclusions are recorded, not treated as missing.
Fixed EXPLICIT/GEARING amounts remain unchanged even if another required cap is
unknown, but the result is incomplete/UNAVAILABLE rather than a complete candidate.
Known caps and breaches remain visible. Complete numerical minima and all tie
priority results are unchanged. No released API or financial mode is altered.

`validate_facilities` proves principal roll-forward only. It checks interest is a
finite nonnegative amount but that alone does NOT prove contractual accrual.
`Credit.principal_reconciliation` is RECONCILED after those checks. Comprehensive
candidate `accounting` is UNVERIFIED by default, including supplied zero interest.

Optional `InterestEvidence` is independently supplied immutable contractual evidence
per facility: its own canonical period IDs, annual rates, year fractions, source
reference and accrual convention. The independent check compares every supplied
interest amount against opening * own annual rate * own year fraction at the
candidate's declared precision. It never uses the project's sizing interest_factor
or another facility's rate/convention. Missing facilities remain UNVERIFIED;
malformed/duplicate/foreign/shifted evidence fails closed; any discrepancy gives
per-facility MISMATCH and combined accounting NOT_RECONCILED. Only complete matching
evidence for every facility yields accounting RECONCILED. Principal reconciliation
is still separately visible for incorrect interest.

This is mathematical reconciliation within the represented principal/interest
ledger, not authentication of the caller's source text, an approval of a day-count
policy or a general certification of tax/fees/reserves/financial statements.
Gate R still owns actual receipt authentication, period/day-count/rate generation,
precision policy and lender/owner authorization. Supplying evidence never promotes
covenant or lender acceptance. Neither sculpt output nor fixed zero-rate receipts
are self-attested as interest-verified by the library.
