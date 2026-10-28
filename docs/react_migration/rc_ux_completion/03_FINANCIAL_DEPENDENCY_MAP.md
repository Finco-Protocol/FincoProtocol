# Financial integration dependency map (RC-UX ↔ FIN-V2)

| RC-UX item | Needs from FIN-V2 | Status | UI behaviour until available |
|---|---|---|---|
| C1 SHL terms / funding schedule | #391 SHL authority | not merged | read-only, "Pending FIN-V2 integration" |
| C1 Sponsor XIRR / Pure Equity IRR / Sponsor NPV | #391 | not merged | show only what current Run evidence carries; otherwise UNAVAILABLE (never 0) |
| C1 Valuation NPV / LLCR / PLCR bases | #391 | not merged | as above |
| C1 Senior DSCR sizing vs reporting case, payoff vs maturity | #391/#392 | not merged | only existing Run evidence |
| C1 Reserve Facilities | #393 | not merged | layout shell, every control disabled and labelled GATED; no calculation |
| C2 Reporting valuation sections | #391 reporting | not merged | sections absent / UNAVAILABLE |
| D01/D02 sensitivity truth | #392 | not merged | Sensitivity unchanged from #388 |

After FIN-V2 merges: merge main into this branch, resolve overlaps additively, bind, rerun financial and React regressions. The sync record
(RC-UX HEAD before sync, merged FIN-V2 commit, conflicts, final HEAD) will be appended to `09_INTEGRATION_SEQUENCE.md`.
