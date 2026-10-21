# Institutional Credit V5 - Isolated Read-Only Analysis

## Provenance and Ownership

Base: verified `origin/main` at `b28a05723967df590f6a684c64504d845e576508`.
Branch: `feat/model-institutional-credit-v5`. One Draft PR; no merge or activation.
The source contains merged V4, including the date/interval correction `8f951e2c`
(verified as an ancestor of main). V4 was integrated through PR #319 and subsequent
quarterly composition. WF-A numerical/credit validation is also present on main.

No changes to financial_engine, finco_core, domain, persistence, Run writers,
goldens, numerical tolerances, release flags or historical governance pins.
The sole shared hook appends V5 router registration to the root V2 router (three
lines plus spacing). The V3/V4 router, handler, tests and payload contracts are
unchanged, including its existing single-GET-route invariant.

Overlap audit: #332 changes financial policy/evidence and its application
authority; #327 changes solver candidates and the production authority; #335
changes `.gitattributes` and the safety scanner. None of those paths is edited
by V5. Their commits are not incorporated. The shared Replit workbook shell,
existing comparison projection and reporting exports are untouched.

## V4 to V5 Inventory

| Capability | Existing authority | V5 addition / boundary |
|---|---|---|
| Authorized history and scenario identity | Run History owner/project-scoped reads | Reuse; selected immutable IDs, no simulated scenario results |
| Senior DSCR, CFADS, debt schedule | V3 projection of committed Integrity evidence | Per-period proposed-threshold headroom, relative headroom, first observed breach and worst period |
| Date-exact cross-Run comparison | V4 interval parser and comparisons | Reuse interval validation; full-axis/frequency/engine proof before aggregate headroom deltas or observed ordering |
| DSCR/gearing sizing capacities | Persisted V3 bankability evidence | Show existing capacity only; never resize debt algebraically |
| Covenant findings | Existing Model Quality rules and V3 classification | No changes; no conversion of a sizing target into a contractual covenant |
| Actual contractual policy | Not consistently persisted in historical Runs | Explicitly unavailable; HTTP thresholds are hypothetical analyst proposals |
| Multiple constraints | No V5 comparison contract | Typed immutable results; rank restrictive proposals only within the same metric/unit/scope |
| Integrity and solver status | Existing V3 Integrity evaluator | Retain status; do not treat financial failure or solver convergence as lender approval |
| Quarterly / Junior / SHL activation | Existing release-closed authority | No activation; quarterly V5 evaluations are unsupported; no new Junior/SHL covenant methodology |

## Supported Constraint Matrix

All supplied thresholds are labelled `HYPOTHETICAL_ANALYST_PROPOSED`. No supplied
threshold is presumed contractually binding. Missing thresholds remain missing.

| Constraint | Metric basis / unit | Implemented scope |
|---|---|---|
| Minimum DSCR | Persisted reported Senior DSCR, per committed serviced period / x | Headroom = observed minus proposed minimum; no new CFADS denominator |
| Minimum LLCR | Persisted V3 minimum LLCR / x | No new discounting, PLCR or loan-life methodology |
| Maximum gearing | Persisted actual Senior gearing / fraction | Headroom = proposed cap minus actual; not a total-debt covenant |
| Minimum equity | Validated V3 initial equity sources / kEUR | SHL is not reclassified as legal equity |
| Maximum balloon | Persisted Senior balance at contractual maturity / kEUR | Requires the persisted contractual maturity date; no repayment/write-off inference |
| Debt/equity ratio | Unsupported | Need a separately agreed debt/equity definition and valuation date |
| Reserve coverage | Unsupported | Need a run-bound required reserve schedule and CASH_DSRA/DSRF distinction |
| Maturity limit | Unsupported | Need a contractual measurement origin and period/day-count convention |
| Actual resized debt | Deferred to Workstream A | Requires a new canonical financing solve |

Zero monetary thresholds are valid. DSCR/LLCR thresholds must be finite and
positive; gearing is a fraction between zero and one. No financial tolerance is
introduced or widened: the hypothetical comparison uses exact signed differences
of Decimal representations of persisted values. Equality is `AT_LIMIT`.

Missing cells do not become zero. Partial coverage cannot become a complete pass.
Known breaches in partial coverage remain observations; unknown periods are
retained. No cross-unit or DSCR-versus-LLCR combined "binding" score is produced.
Repeated proposals on the same metric can be compared through the typed service;
the GET form accepts one proposal per metric per request and rejects duplicate
query keys rather than choosing an arbitrary value.

## Service and Route Contract

`app.services.credit_v5.analyze_runs(entries, constraints, *, owner_id, project_id,
project_code)` returns frozen, tuple-only decision objects. It performs no I/O
and mutates no entries. The existing V3 projection is the financial evidence
adapter and V4 supplies interval parsing; no second lender engine is introduced.

Entry validation checks owner/project, required Run identifiers, Integrity digest,
financing snapshot/hash/scenario binding and existing Model V2 binding when
present. Malformed/mismatched evidence fails closed. Safe analysis of a committed
Run whose financial checks failed does not imply an underwriting pass.

`GET /v2/credit-decision/v5?project=<code>&run=<history-id>&min_dscr=1.25`
renders a new isolated workspace. `format=json` returns the same typed analysis
as JSON. Up to three explicitly ordered Runs may be selected; selection 1 is
the reference. No Run defaults to an invented scenario. The default is the
newest immutable history entry, not a computed Working Copy result. The picker
lists the 25 most recent entries; an explicitly supplied older history ID is
still owner-scoped and can be evaluated.

The route is authenticated, protected-reference guarded, owner/project scoped,
GET-only and `private, no-store`. Foreign or missing IDs reject the whole request.
It never reads Working Copy thresholds or claims CURRENT freshness: historical
results remain `HISTORICAL_NOT_ASSERTED_CURRENT` even after a concurrent Save or
scenario switch. A new Run cannot rewrite the selected historical evidence.
This avoids a new current-input binding or CAS authority on this read-only path.

An unrun scenario is unavailable, not a simulated downside. V5 does not infer
that yield, price, rate, OPEX or construction cost caused an observed difference
merely from a scenario label. Only previously committed canonical Runs are used.

## Workstream A Phase 2 Contract Proposal

Actual lender-constrained resizing must be a separate authorized engine change:

1. Accept explicit lender-policy thresholds, their basis, dates/frequencies,
   scenario and supported financial-structure identity.
2. Use the existing canonical Senior/financing, interest, construction funding,
   tax, reserve, CFADS, repayment and sponsor-return authorities at each candidate.
3. Preserve structural rejection, convergence/idempotence and terminal-debt gates.
4. Return the final solved debt and active constraints with full numerical
   residuals; never infer new capacity by multiplying current debt by a DSCR ratio.
5. Only the normal authorized canonical Run/CAS path may commit results; keep
   failed attempts out of Last Run and immutable history.
6. Require separate financial-owner exact-content review, inactive legacy parity
   and independent numerical oracles. V5 grants no engine authorization.

## Acceptance Evidence

Initial analytical suite: 36 passed, rc=0, normal process exit, 3.67 s on Windows,
Python 3.12.10 / pytest 9.0.3. Independent Decimal expectations, invalid thresholds,
zero/missing values, exact dates, partial periods, comparable groups, changed
scenarios, tenant/provenance mutation rejection and immutability are included.

Combined V5 unit/real committed-Run and unchanged V3/V4 regression suite:
103 passed, zero failures/skips, rc=0, normal process return, 62.72 s.
Actual completed Solar, Wind, Data Center and EV Runs provide independent Decimal
per-period headroom checks, read-time no-engine guards, owner isolation, protected
Reference rejection, immutable history, saved Working Copy isolation and two-Run
comparison identity. Changed-file public safety and Python compilation passed.
An initial registration attempt exposed the existing V3 single-route invariant;
the V3 module and test were preserved, and registration moved to a root-router
hook before this successful regression. No test was weakened.

Actual committed-Run, V3/V4 regression, source safety, browser and exact-head CI
results are recorded in the independent review handoff and PR checks after
execution; none is presumed green merely because its test exists.

No whole 200-minute Public Safety suite is run locally. Existing GitHub Actions
provides full exact-head CI. Generic browser acceptance is not a substitute for
explicit V5-specific browser coverage.

**No self-approval, merge, deployment, financial release or production underwriting.**
