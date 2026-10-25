# WF06 Financial Owner decisions — all PENDING

No authentic approval reference is supplied or inferred from implementation or CI.
This paper records questions, not resolved policy. Candidate remains release closed.

| Decision | Candidate boundary | Required independent owner / evidence |
|---|---|---|
| Sizing mode names/priority and applicable caps | explicit caller priority, all ties shown; fixed commitments never resized | Financial + Credit: actual mandate and binding-constraint hierarchy |
| Fixed debt DSCR <1 | reconciled accounting can coexist with cash breach; convergence is not approval | Financial + Application: covenant/EoD treatment and authorized execution behavior |
| Endogenous/non-monotone sizing | unavailable, no new iterative engine | Financial + Numerical: canonical tax/CFADS response, bracketing, residuals, failures and mode-switch cases |
| N-tranche shared CFADS | aggregate once; per-tranche needs explicit shares <=1 | Financial + Lender: intercreditor ranking, allocation basis, period coverage and cash ownership |
| Rate/day-count and debt windows | supplied rate factors, preserved period IDs, own maturity/grace | Financial: dated rate/accrual policy, grace interest, stubs, calendar boundaries |
| Balloon meaning and limits | candidate limit is principal due in maturity period; residual debt remains breach | Financial + Legal: balloon vs ordinary last installment, refinancing and terminal balance authority |
| Discount methodology | explicit aligned factors/convention, no defaults | Financial + Valuation: valuation origin, rate source, nominal/real/currency basis, LLCR/PLCR windows and debt denominator |
| LLCR/PLCR target sizing | absent; analytical ratios only | Financial: targets, actual canonical re-solve, joint sensitivity and validation |
| Cash sweep / reserves | one-period proposal only, explicit cash after reserves; no future interest changes | Financial + Application: reserve priority, lender share, schedule feedback, excess/unallocated cash, taxes and capitalized-interest prohibitions |
| Precision / supplied receipts | strict Decimal ledgers; no guessed float normalization | Financial + Numerical: supported receipt precision, approved reconciliation tolerance and exact-content review |
| Promotion / lender acceptance | NON_AUTHORITATIVE=True, ACTIVATION_ENABLED=False, lender NOT_ASSESSED | Financial, independent reviewer, application release owner: Gate-R successor, original Run evidence and later product acceptance |

Existing released two-facility and F3.1 candidate authorities remain their own
sources of truth. WF06 does not approve their open institutional expansion policies.
Any need to modify financial_engine, finco_core, domain, workbook or routes stops
that integration path here and requires a separately authorized successor. Technical
review is requested only for this isolated candidate; no owner self-approval.
