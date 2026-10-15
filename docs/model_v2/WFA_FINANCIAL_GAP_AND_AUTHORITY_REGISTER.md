# WF-A financial gap and authority register

Statuses: **VALIDATED** · **FUNCTIONALLY EXECUTED — NUMERICAL VALIDATION INCOMPLETE** · **NOT COMPARABLE** · **REQUIRES FINANCIAL APPROVAL** · **RELEASE-CLOSED**.

## Revenue capability matrix

| Capability | Product support | Status |
|---|---|---|
| Legacy single PPA | supported | VALIDATED (baseline Run, F3.9 identities) |
| Fixed-price PPA, volume share | Revenue V2 contract | VALIDATED (P1, P7) |
| Two PPAs + residual merchant | Revenue V2 | VALIDATED (P2) |
| Indexation by operating year | OPERATING_YEAR only | VALIDATED for that convention; convention itself REQUIRES FINANCIAL APPROVAL |
| Partial indexed share | expressible only by splitting a PPA into a fixed and an indexed stream | FUNCTIONALLY EXECUTED — NUMERICAL VALIDATION INCOMPLETE |
| Stepped price | `price_curve` (version 2, no indexation with a curve) | supported; reconciled in the PPA price identity where exercised |
| PPA expiry then merchant | windows on period boundaries | VALIDATED (P5) |
| CfD overlay | signed settlement vs reference stream | VALIDATED (P6) |
| Price base year / indexation basis other than operating year | not supported | NOT COMPARABLE |
| MWh volume cap / take-or-pay | not supported | NOT COMPARABLE |
| Market-linked formula pricing | not supported | NOT COMPARABLE |
| Lagged settlement | not supported (SAME_PERIOD only) | NOT COMPARABLE |
| Revenue V3 | closed | RELEASE-CLOSED |

## External reference parity gap register

No authorised private reference material is available in this environment, and none is included in the public repository. **EXTERNAL NUMERICAL PARITY — NOT COMPARABLE.** The register below lists the capability or convention that would have to be mapped under authorised private conditions before any parity statement could be made; no external value is asserted.

| Area | Product convention / capability | Parity status |
|---|---|---|
| Contract base year and indexation anchor | operating-year buckets from the first operating period (F-4); no base-year field | NOT COMPARABLE |
| Partial indexed share | split into two streams | NOT COMPARABLE (mapping required) |
| Stepped tariffs | `price_curve` per active operating period | NOT COMPARABLE (mapping required) |
| Market-linked pricing, MWh cap, lagged settlement | unsupported by schema | NOT COMPARABLE (capability missing) |
| Contract term relative to COD | ISO boundary dates that must equal operating period boundaries | NOT COMPARABLE (mapping required) |
| P50 / P90 horizon and lender-case selection | P90-10y lender case with P50 operating case; no writable P90 | NOT COMPARABLE |
| Merchant price conventions | single price per merchant stream/period | NOT COMPARABLE |
| Debt / equity structure and fee conventions | F3 level/other repayment, explicit fixed rate, act/360 or act/365 | NOT COMPARABLE |
| Day count and period start/end conventions | end-exclusive periods, first operating period starts on the last construction key | NOT COMPARABLE |

## Financial defect / approval register

| ID | Description | Evidence | Needed |
|---|---|---|---|
| F-1 | sizing-mode naming vs behaviour | tests/test_wfa_credit_validation.py, credit matrix F0/R0 | financial authority decision; no production change made |
| F-2 | DSCR < 1 CONVERGED under fixed debt | credit matrix `F-*` cases | feasibility check owner decision |
| F-3 | non-monotone debt when gearing binds | credit matrix directional checks | confirm intended |
| F-4 | operating-year indexation convention | RC-PRICE identity | FINANCIAL APPROVAL |
| U-1 | LLCR / PLCR / EoD / cash sweep | UNSUPPORTED_CREDIT in `credit.py` | separate authorised capability work |

## Release-closed

Junior, BESS M7, M6 valuation, F4/P2, Revenue V3 — **RELEASE-CLOSED**; not exercised and not opened by this work.
