# WF-07 — Advanced Financing & Reserve Integration (Candidate V0)

**Status:** release-closed, non-authoritative candidate. Authority string
`WF07_FINANCING_RESERVES_CANDIDATE_V0` (distinct from the released
`F3_TWO_SENIOR_EXPLICIT_COMMITMENTS_V1`). `ACTIVATION_ENABLED` is a literal
`False`; every calculation raises `WF07_RELEASE_CLOSED`. Nothing imports the
package and it adds no route, flag, persistence or UI.

Package: `app/model_v2/financing_wf07_candidate/` (stdlib only).
Tests: `tests/test_financing_wf07_candidate.py`. Decisions:
`docs/model_v2/WF07_FINANCIAL_OWNER_DECISIONS.md`.

## 1. What already exists (not re-implemented)

| Released capability | Location | WF-07 relationship |
|---|---|---|
| SHL period engine (period-start draw, cash/PIK, bullet/explicit principal) | `financial_engine/shl/engine.py` | WF-07 reproduces the arithmetic in exact Decimal; equivalence is tested to 1e-9 |
| Cash DSRA roll-forward (opening, top-up, release, draw) | `financial_engine/dsra/model.py` | same identity; WF-07 adds evidence-driven targets and the aggregate view |
| DSRF commitment fee only (no draw engine) | `financial_engine/financing/dsrf.py` | WF-07 adds a DSRF *standby ledger* (draw/restoration); **fees stay OPEN** |
| Exactly-two pari-passu Senior authority | `financial_engine/financing/multisenior.py` | untouched; WF-07 consumes aggregate service as evidence |
| N-tranche schedules / reconciliation | F3.1 candidate | not imported; WF-07 takes schedules as supplied evidence |
| Junior (F3.5) and F4 investor authority | `financial_engine/financing/junior_debt.py`, `investor_f4*` | untouched; junior service is supplied evidence |

All protected files are byte-identical to `main` (blob pins in the tests).

## 2. Interface (WF-06 compatible, no cross-branch coupling)

The candidate reads **only** immutable, explicitly supplied evidence:

| Evidence | Type |
|---|---|
| period index / end date / phase / accrual fraction | `PeriodEvidence` |
| available cash (CFADS) + source id; `None` = MISSING | `PeriodEvidence` |
| facility id, layer, contractual service, optional paid service, source id | `FacilityService` |
| reserve target per period + source id + evidence status | `ReserveTargetEvidence` |
| existing reserve balance (DSRA cash / DSRF drawn) | `ReserveOpening` |
| dated senior draws, dated SHL draws, equity pools, construction uses | `SeniorDraw`, `ShlTerms`, `EquityPool`, `ConstructionUse` |
| creditor ordering and reserve policy | `WaterfallPolicy` (mandatory, explicit) |

A future WF-06 schedule is supplied as `FacilityService` rows. The candidate
never resizes debt, never changes a contractual payment and never imports the
WF-06, F3.1 or F4 candidates.

## 3. Contract boundaries

* **A. Shareholder loans** — explicit commitment and dated draws (Σ ≤ commitment,
  unique evidence ids) **in construction periods only**: an operating-period draw
  is rejected (`WF07_SHL_OPERATING_DRAW_UNSUPPORTED`, at the `Wf07Inputs` boundary
  and again in `shl_due`) because V0 has no evidenced, reconciled operating funding
  contract, so debt could rise with no matching cash movement (Correction A; see
  decision W-13). Operating SHL balance changes are exactly disclosed PIK less
  scheduled principal; construction PIK is `CAPITALIZED`, operating interest is
  an `OPERATING_EXPENSE_CANDIDATE` classification only (deductibility OPEN);
  cash vs PIK per phase; explicit scheduled principal (never a sweep); an SHL is
  `SPONSOR_DEBT` and can be neither `LEGAL_EQUITY` nor a `DISTRIBUTION`.
* **B. DSRA / DSRF** — separate contract types, never netted. DSRA is cash:
  `opening + deposit − draw − release = closing`. DSRF is a standby limit:
  `opening drawn + draw − restoration = closing drawn`, `available = limit −
  drawn`; it never carries a cash deposit and cannot be pre-funded as a project
  use. Targets are supplied evidence; `forward_requirement()` derives candidate
  aggregate / per-facility values from supplied contractual schedules and returns
  a `ForwardRequirement(amount, truncated, status, reasons)`. Input is validated:
  duplicate (period, facility) rows, duplicate source identities, malformed rows
  and a facility used in two layers raise; an unknown or non-senior requested
  facility raises (never a zero). Coverage is explicit: with the canonical
  `axis` every in-scope senior facility needs a row in each window period
  (explicit zero after maturity), otherwise status `UNAVAILABLE` with typed reasons
  and `amount=None`; a short tail is `TRUNCATED`; without an axis, no future rows is
  `UNAVAILABLE` (`WF07_FORWARD_WINDOW_EMPTY`). A real zero contractual service is a
  valid zero. Initial DSRA funding is a `RESERVE_FUNDING` construction use and
  must equal the operating opening balance (counted once).
* **C. Creditor ordering** — single supported order: N pari-passu SENIOR
  (aggregate) → reserve draws/restoration/top-up → JUNIOR → SHL → distribution
  candidate. Any other ranking, reserve position or draw/restoration order is
  `UNSUPPORTED`. A shortfall is never shared pro-rata: allocation must be supplied
  as `paid_service` evidence, otherwise `UNAVAILABLE`.
* **D. Cash and funding reconciliation** — construction Sources & Uses per
  period: dated senior and SHL draws first, depleting equity pools in declared
  order for the residual; sources + gap = uses; a residual is a typed
  `WF07_FUNDING_GAP`, explicit draws above uses are `WF07_SOURCES_EXCEED_USES`.
  Operating cash identity per period: `CFADS + reserve draws + release = senior
  service + restoration + top-up + junior + SHL + distribution candidate +
  retained` (`OperatingRow.conservation_residual() == 0`). Reserved cash is never
  distributed; surplus is a *candidate*, retained when a reserve is below target.

## 4. Fail-closed behaviour

Typed halts (run stops, nothing is invented): `WF07_CASH_EVIDENCE_MISSING`,
`..._CONTRACTUAL_SERVICE_EVIDENCE_MISSING`, `..._RESERVE_TARGET_EVIDENCE_MISSING`,
`..._RESERVE_OPENING_MISSING`, `WF07_SHORTFALL_ALLOCATION_POLICY_OPEN`,
`WF07_DEFAULT_CURE_POLICY_OPEN`, `WF07_JUNIOR_SHORTFALL_POLICY_OPEN`,
`WF07_SHL_SHORTFALL_POLICY_OPEN`, `WF07_RELEASE_AND_SHORTFALL_OPEN`,
`WF07_POLICY_COMBINATION_UNSUPPORTED`. Evidence conflicts raise
(`WF07_RESERVE_FUNDING_MISMATCH`, `WF07_PAID_EVIDENCE_MISMATCH`,
`WF07_DUPLICATE`, `WF07_SHL_COMMITMENT_EXCEEDED`, …).

## 5. Verification summary

66 focused tests; independent `Fraction` oracles (SHL accrual, DSRA ledger,
randomised 300-scenario waterfall); SHL schedule equals the released float
engine at 1e-9; 27 guard mutations all caught; protected blobs pinned; import
isolation by AST and by `sys.modules` delta; nothing outside the package refers
to it.

## 5a. Correction A (PR #369 review)

Reproduced on `abab077`: an SHL draw in an operating period raised the balance
(408 → 708) while the operating cash reconciliation stayed balanced (residual 0)
— debt with no cash source; `forward_requirement` summed duplicate rows (109) and
returned a valid zero for an unknown facility. Both fixed; tests and mutations
cover each boundary.

## 6. Integration plan (future, separate approval)

Gate R approval → wire evidence from the canonical engine and an accepted WF-06
schedule → owner decisions → authority regression → activation behind a new flag.
Out of scope here: any edit of `financial_engine/**`, `finco_core/**`, `domain/**`.
