# F4/P1 canonical common-equity waterfall and returns

## Provenance and disposition

Implementation base: `1152dd2d98b5da8b41cea52ce9867619a3e85fba`.
Branch: `feat/model-f4-p1-investor-waterfall-v1`.
PR #259 F4/P0 and #263 F3.8 are merged. The latter's reviewed feature head
`760544c4755c018268450774d9259ab618688a0c` has the same baseline financial
content used for the independent before/after comparison.

One Draft PR, no self-approval, merge, deployment, rebase or force push.
Exact feature HEAD, PR URL and post-publication CI evidence belong in the PR
description to avoid a self-referential commit or an untested final doc commit.
Independent review remains mandatory. This is residual-only common equity,
not release of preference, carry, ROC, valuation or SHL-lender economics.

## Capability matrix

| Capability | Baseline | P1 disposition / authority |
|---|---|---|
| Investor, contribution and agreement contracts | EXISTING AND REUSABLE | Reuse P0 frozen types and adapter, with versioned persisted terms |
| Common-equity residual allocation | EXISTING AND REUSABLE | Existing `finco_core.sponsor.waterfall_runner.run_waterfall`; no second allocator |
| Dated XIRR | EXISTING AND REUSABLE | Existing `finco_core.sponsor.xirr.robust_xirr`, actual dates |
| Net eligible equity receipts | PARTIAL | G2C runtime has net/WHT fields; opt-in read-only serialization now preserves them before projection loses them |
| Multiple investors and unequal contributions | PARTIAL | Explicit IDs, legal ownership, commitments, actual paid-in events and per-investor accounts |
| Agreement Save / scenarios / CAS | MISSING | Narrow app-layer writer in existing scalar/scenario stores; no new persistence schema |
| Run / historical investor evidence | MISSING | Versioned extension in existing atomic runtime summary and immutable history |
| Investor workspace / export | MISSING | Isolated read-only Run projections and owned versioned agreement editor, run-bound XLSX |
| ROC-first legal ordering | UNSUPPORTED | No approved individual ROC legal policy; returned capital stays zero |
| Preference / catch-up / carry / special classes | UNSUPPORTED | Save and Run reject these terms; no defaults |
| SHL investor/lender allocation | UNSUPPORTED | No loan-holder inference; legal equity only |
| Individual tax domicile / WHT rates | UNSUPPORTED | Existing canonical dividend WHT is applied upstream; no investor-specific tax engine |
| NAV / TVPI / total-value MOIC / secondary transfers | UNSUPPORTED | No inferred valuation or transfer accounting |

The legacy multi-investor runner is not used: its GP/LP identities and carry
defaults are not equivalent to an explicit common-equity agreement. The
offline P0 `evaluate_candidate` is never called by production. The sole new
production consumer reuses only P0 contracts and its reviewed adapter.

## Financial source and integration map

Canonical production Run -> G2C `CovenantGatedWaterfallResult.waterfall_periods`
-> actual `cashflow_date`, `gross_dividend_paid_keur`, `dividend_wht_keur`,
`net_dividend_received_keur` -> existing common-equity RESIDUAL primitive
-> dated investor allocations -> existing XIRR -> atomic Last Run / history.

G2C is downstream of Senior debt, reserves, covenants, legal distribution
gates, SHL service and WHT. Raw CFADS, gross dividend, distribution-account
inflows and total sponsor/SHL cash are never substituted for net equity cash.
Gross/WHT/net and canonical totals are validated, not repaired.

Actual paid-in funding is the sum of the four existing G2C contribution fields:
`share_capital_contribution_keur`, `share_premium_contribution_keur`,
`other_committed_equity_contribution_keur`, `additional_equity_contribution_keur`.
Every agreement contribution must be on the explicit runtime date axis and
reconcile to that date's actual legal equity funding. Commitments never
manufacture contributions. Funding mismatch rejects before successful Run CAS.

`app/api/project_runner.py` only passes these fields through when an agreement
requests evidence. Without opt-in, the existing payload is unchanged. The
router allocates before the unchanged `v2_atomic_run_commit`; no agreement is
mutated during Run. All aggregate financial results remain canonical and
unchanged. Save and GET/export execute no solver, allocator or IRR calculation.

## Agreement and security contract

`AgreementTerms` uses P0 typed tuples and deterministic schema-version-1 JSON:
agreement ID/version, EUR/kEUR, RESIDUAL_ONLY, explicit common investor IDs,
ownership fractions, commitments and dated actual contributions. Duplicate
JSON keys, unknown fields, unsupported rights, nonfinite/boolean amounts,
invalid dates, duplicate investors, invalid ownership or excess calls fail closed.

Registry key `investor.agreement.common_equity` maps to
`investor_agreement_json`. The generic scalar writer rejects this key: only
the dedicated agreement writer may apply scenario/version/composite CAS.
It rechecks owner, project, protected state and selected scenario inside
`BEGIN EXCLUSIVE`. Two simultaneous Saves produce one winner and one conflict.
No new tables, migrations, financial inputs or alternative Run ledger exist.

Base stores its agreement in the existing draft snapshot. Non-Base scenarios
require their own explicit agreement Save; no silent inheritance of legal
terms. The selected scenario's own override participates in canonical identity.
An existing agreement advances exactly one version; a new identity starts at 1.
Removal changes Working state only, preserving historical evidence.

POST requires the existing signed, expiring CSRF token before any mutation.
Missing/forged/expired tokens, foreign owners/projects, protected writes,
stale version/hash and scenario-selection races reject. A concurrent agreement
edit after calculation but before CAS cannot commit the stale Run or alter
prior history. Existing #219 Base(None) restoration and canonical freshness
are reused, not reimplemented.

## Accounts, returns, history and export

Every cash event records exact date, paid-in, residual distribution, net cash
and unreturned paid-in. Per-investor totals expose paid-in, uncalled capital,
returned capital, residual/cumulative distributions, unreturned paid-in,
DPI, realized cash MOIC and XIRR/status.

Under RESIDUAL_ONLY, ROC is zero; residual dividends are not relabelled ROC.
Unreturned paid-in remains actual paid-in, not commitment. DPI and realized
MOIC use actual cumulative net cash distributions / actual paid-in, with no NAV.
XIRR is calculated from each investor's actual cash events, not sponsor IRR
multiplied by ownership. Unresolved SHL maturity and upstream-feedback blocks
also block investor return metrics. Zero distributions do not fabricate XIRR.

Versioned `investor_waterfall_v1` includes owner/project/scenario/snapshot/hash,
agreement identity/version/digest, source, canonical receipts, individual
accounts/events and evidence digest. Existing immutable history protects it.
Legacy Runs without it are UNAVAILABLE; GET does not reconstruct allocations.
CURRENT/STALE/NOT_RUN are canonical freshness; historical selection is read-only.
Final request-context coherence checks reject concurrent snapshot changes.

The F4 XLSX is bound to the owned persisted Last Run or immutable history entry,
including exact source/binding/digests. Export never recalculates. Text cells
are explicitly strings, including formula-like investor IDs/project names.
The existing institutional export path and its authority remain untouched.

## Numerical acceptance

Independent Decimal ACT/365 bisection uses actual dates, 50-digit arithmetic
and no production IRR implementation. Six two/three-investor synthetic cash
cases cover unequal ownership/contributions, different contribution dates,
low/partial distributions and changed final timing; 15 investor XIRRs are checked.

Measured maximums:
- Allocation residual: **0 kEUR**.
- Dated cash-conservation residual: **0 kEUR**.
- Independent XIRR absolute difference: **6.461174373306733e-10**.

No tolerance widening, golden refresh, balancing plug or hidden retained cash.
Negative tests cover unauthorized rights, contribution/source/date/WHT mismatch,
all five binding axes, digest corruption and blocked returns.

Controlled 16 MW actual Solar/Wind workspace Runs use 70/30 legal ownership
with independently specified 60/40 contributions (300/200 kEUR). Sponsor/debt,
tax, statements and all other numeric KPI/evidence results match pre-F4 Runs
exactly. Only immutable run bindings and the scoped investor evidence differ.

| Actual Run | Investor | Net cash distributions kEUR | XIRR | Realized DPI |
|---|---|---:|---:|---:|
| Solar | alpha | 12732.489458850847 | 0.3089230121463347 | 42.44163152950282 |
| Solar | beta | 5456.781196650365 | 0.2482592138408466 | 27.283905983251824 |
| Wind | alpha | 33900.24907705645 | 0.4415782068564418 | 113.00083025685483 |
| Wind | beta | 14528.678175881334 | 0.35833968907123337 | 72.64339087940667 |

These are cash-only legal-equity metrics for explicitly SHL-funded fixtures,
not total sponsor returns or a project-valuation claim.

All six complete canonical-result SHA256 fingerprints match before/after:

| Case | SHA256 |
|---|---|
| Solar | `a24ac63a228a63e9ddecf6c2f7bbe094d4633f56edc0cdb9c6c5f1af92e0f481` |
| Wind | `b8f2dee7eaa64272f209a9e554e64bfb06d3f702d7d08151060ac0e93c696333` |
| Data Center | `bfbdd3d64bfccb36242fe5a78172e24d9f9dcb03e98c375629b729a738217bed` |
| EV | `45b428a84725864fb39e6d15f37c2a0b79c85ac5081b2e8c0192e3e704e4f545` |
| Two-Senior Solar | `5f101488ed30e6364b75274a921b96bcbb71f1377aa185271919ebbdb9a2b42d` |
| Two-Senior Wind | `06af88ed77a019844e4a218e9a180b905560c4ffba0768e3645ff9e5dbc02265` |

## Local and browser evidence

Python 3.12.10, isolated disposable SQLite, real canonical execution through
the suite's bounded thread-mode executor (no mocked financial output).
- F4 plus F3 actual financial ring: **168 passed**, rc=0, normal termination.
- Coherent post-run context, scenario freshness, U2.1/F07-B canonical export
  lineage: **120 passed**, rc=0, normal termination; legacy Base restoration,
  immutable Last Run and authorized read/export boundaries remain intact.
- F4/Returns/history/F3/WF-04/WF-07/Model V2 integrity governance ring:
  **353 passed, 10 skipped**, rc=0, normal termination. Those ten existing
  skips are retired Model V2 scope-marker tests; no new financial test is skipped.
- Real F4 Chromium covers Solar/Wind Add/Edit/Save, reopen STALE, first Run,
  CURRENT accounts, run-bound download, immutable history, light desktop and
  dark narrow viewport, no JS errors/viewport overflow, protected read-only mode,
  and delayed pre-edit CURRENT response rejected after a newer Save.

Screenshot evidence outside Git: `f4-p1-browser-evidence/solar-light-1440.png`,
`solar-dark-390.png`, `wind-light-1440.png`, `wind-dark-390.png`.
Final Chromium and prior-bankability ring: **39 passed**, rc=0, normal exit
(three real F4 browser cases and 36 existing bankability cases). The existing
UTF-8 JS fixture is read with Python UTF-8 mode on Windows; no unrelated test
encoding or shared JS change is made.
The Investor parent's accepted refresh/CSP behavior is retained; F4 uses isolated
static JS, preserves disclosure presentation state and rejects late read responses.
The browser module uses the accepted optional-Playwright collection guard;
actual local Chromium executes, rather than treating optional collection as proof.

Compilation/diff hygiene and changed-file source safety pass. Full Windows
safety reports the pre-existing unchanged Swagger CRLF email-exemption mismatch.
No vendor bytes or scanner are changed to bypass it. Full Linux source safety,
unsharded pytest normal exit, evidence uploads, six browser roles and every
mandatory exact-head workflow remain publication acceptance gates, not assumed
successful in this pre-publication report.

## Ownership and remaining gates

ZERO diff in financial_engine, finco_core, domain, Radar/Yield/Protocol,
financial governance pins, goldens/tolerances, schema, persistence repositories,
canonical CAS/history writer, execution workers and CI workflows.

Open #264 owns cost-grid/shared JS/CSS; F4 does not change those files.
Open #265 Revenue and #266 AI have no financial F4 implementation overlap;
shared router/registry changes need ordinary normal-merge review when integrating.

Independent review must approve this exact app-layer evidence/writer integration.
ROC-first ordering, investor-specific tax, preferences/carry/NAV/transfers and
SHL lender attribution remain blocked for separate explicit legal/financial scope.
No assertion of full F4 economics or authorization to merge/deploy is made.
