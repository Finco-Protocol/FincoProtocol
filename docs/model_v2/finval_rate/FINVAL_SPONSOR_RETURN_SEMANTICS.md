# FIN-VAL — sponsor-return semantics and Overnight B handoff

No IRR formula, cash-flow sequence or investor economics is changed. Independent bisection of dated cash flows using an ACT/365 XIRR NPV equation reproduces the existing engine results within 1e-8. Every sponsor-period cash flow reconciles to pure-equity flow minus SHL contribution plus SHL interest/principal receipts. Full vectors and independent roots are in `evidence/sponsor-semantics.json`.

| Reference | Share-capital / Pure Equity IRR | Total Sponsor XIRR | Legal equity funded kEUR | SHL cash funded kEUR |
|---|---:|---:|---:|---:|
| solar | 45.95340565% | 16.61020031% | 500.00000000 | 8494.44389216 |
| wind | 68.42164724% | 18.71183106% | 500.00000000 | 11668.38598649 |

## Financial explanation

The default SHARE_CAPITAL_THEN_SHL funding structure commits a relatively small share-capital amount and funds the remaining sponsor requirement through subordinated shareholder loans. Pure Equity IRR considers share-capital/premium/additional-equity contributions and legal equity distributions. It excludes SHL cash contributions and SHL principal/interest receipts. Total Sponsor XIRR includes both instruments with their actual contribution and receipt dates.

A high share-capital-only return can therefore coexist with a substantially lower combined sponsor return. It is not an arithmetic contradiction and does not justify changing formulas. The larger sponsor-funded denominator, different cash-flow timing and senior/SHL distribution priority are economically relevant. Share premium and additional equity must remain in the legal equity contribution vector; do not describe the metric as “500 only” for arbitrary projects.

## Recommended display semantics for Overnight B

- Use **Share-capital equity IRR (excludes shareholder loans)** for the existing pure-equity metric, with scope help covering share capital, premium and additional equity.
- Use **Total sponsor XIRR (equity + shareholder loans)** for combined sponsor economics, alongside the legal-equity and SHL funding amounts.
- Explain that distributions are legal equity receipts; total sponsor receipts additionally include SHL interest/principal. Do not add those receipts twice.
- Bind both metrics to the same committed Run identity and dates. Retain unavailable statuses; do not replace undefined IRR with zero.
- Any change of headline ranking/default funding policy requires an owner decision. This report is semantic guidance for presentation, not approval to alter default funding, return definitions or IRR formulas.

Overnight B owns the React implementation. No React source or generated bundle is changed by this branch.
