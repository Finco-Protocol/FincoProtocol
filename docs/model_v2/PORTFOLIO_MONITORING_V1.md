# Institutional Portfolio Monitoring V1

## Scope and entry points

Base: `5996453b8d5bbfaa48bc06922fc6963cf94d2f84` (live origin/main independently fetched before development).

`GET /v2/portfolio` is an authenticated, owner-only, read-only workspace over all non-archived projects owned by the signed-in user. Compare Projects links to it. It links back to the existing five-project Compare; no comparison calculator, comparison projection or second picker was introduced.

No portfolio tables, financial formulas, financial authority maps, Run writers, export implementation, shared workbook shell, activation flags or CI definitions change. The sole shared-router change is the dedicated router import/registration at the end of `app/v2/router.py`; the RC coordinator explicitly acknowledged this hook. PR #329's separate historical-export route and all workbook/Compare logic are untouched by Correction A.

## Evidence contract

- One newest immutable `model_run_history` entry per project, ordered by the existing repository's `ran_at DESC, history_id DESC` authority. Multiple scenarios are not counted as multiple projects.
- This is the latest committed Run, **not necessarily the active scenario's selected Last Run**. If those differ, the row says so and is never promoted to CURRENT.
- Correction A uses one request-local, query-only SQLite transaction with explicit owner/project joins, the existing Project/Workspace record decoders, the existing Run History decoder and its exact latest-entry ordering. Ownership/archival is checked again in a fresh read before returning. Shared system reference projects are not silently included as portfolio assets.
- Freshness reuses `assemble_transactional` inside that snapshot and `resolve_runtime_freshness`, including legacy Base equivalence. SQLite data-version changes trigger one bounded second snapshot. Changed workspace state, composite identity or latest history ID becomes unverified; an unrelated tenant write can be proved irrelevant. Continued changes fail closed. This is a captured snapshot, not a continuously live-currentness claim, and there is no cross-request cache.
- A malformed newest history entry is unavailable. No older row, live draft, project baseline estimate or new engine calculation replaces it.
- Run date, engine/workbook version, scenario, snapshot, input hash and exact history ID are available per row. Engine-version currency is independent of input freshness and Integrity.
- Project country, technology and development stage are explicitly current **project metadata**, not invented historical Run attributes. Missing metadata remains Not set.

## Implemented capabilities

| Capability | Implementation |
|---|---|
| Composition | Counts/shares by technology and country; no five-project portfolio cap |
| Project performance | Project IRR, Pure Equity IRR, Total Sponsor IRR, minimum/average DSCR, minimum LLCR |
| Financial sourcing | Existing Compare `run_metric_view`; same persisted debt/sponsor summary mappings |
| Funding | Hard project CAPEX, total Uses, actual Senior financing, equity, SHL, Junior/other financing |
| Actual leverage | Persisted `actual_gearing_pct`, never requested gearing cap |
| Validation | Existing F1 Sources & Uses read projection validates schema, authority, units, identity and reconciliation |
| Review | Missing Runs, stale/unverified inputs, incomplete credit/return/version evidence, Integrity failures/incompleteness and observed DSCR below 1x |
| Filters | Technology, country, stage, project, review category and financial metric min/max/sort |
| Drilldown | Exact committed history entry, project workspace and existing Credit Decision with exact Run ID |
| Presentation | Dense financial tables, local horizontal scroll, light/dark themes, desktop/laptop/mobile |

Risk observations are **not lender covenant decisions**. No portfolio IRR, weighted DSCR, consolidated statements, currency conversion, current debt outstanding estimate or automatic Run is produced.

## Monetary comparability and limitations

FINANCING_F1_V1 explicitly records `units=kEUR` under the existing EUR canonical result contract. The editable project display-currency label is not a conversion authority. Unknown units/schema or explicit conflicting/missing currency metadata on the financial evidence is rejected, rather than relabelled or converted.

The displayed funding amounts are the committed initial financing/Sources & Uses, **not today's outstanding exposure**. Correction A adds historical project-capital totals by currency, units and F1 metric scope. Different construction dates do not prevent these nominal historical totals. There is no claim of common-date valuation, discounting, inflation rebasing or current outstanding debt. Monetary evidence coverage and complete-funding-date coverage are reported separately.

The existing `NonConstructionFcUse` payload records FC/COD Uses and Sources but no cash-payment date. Validated amounts remain included in historical capital totals, but not in date-specific financing subtotals. Hard CAPEX can remain in its recorded construction-window cohort. No COD or payment date is inferred from a construction end date or today's Working Copy. This is an upstream date-evidence limitation, not evidence that an otherwise validated funding amount is zero or unavailable. Persistence and financial writers are unchanged.

Every subtotal shows its numerator/project coverage. No eligible values means **Unavailable**, not zero. Amounts use deterministic Decimal summation of persisted numeric representations before display rounding; unavailable/string/bool/non-finite inputs cannot become zero. Technology/country breakdowns are available for both historical capital and the separate strict date cohorts, without mixing their meanings.

No new evidence is persisted. Existing historical exports and committed Runs remain unchanged. Portfolio-specific export, archived-project inclusion, FX/as-of revaluation, current outstanding balances, shared-account aggregation and large-account pagination are not part of V1.

## Verification

Core tests use actual Solar, Wind, Data Center and EV canonical route commits in disposable SQLite, then compare raw persisted values and exact history IDs. GET repeats are guarded against engine execution and Run commitment and are checked against before/after Workspace and history snapshots.

Synthetic edge cases cover mixed/unknown units and currencies, missing dates, undated FC/COD funding, invalid binding, corruption, zero versus unavailable, negative and missing returns, deterministic ordering/summation, more than five projects and owner rechecks.

Chromium tests exercise authenticated HTTP, filters, reload/Back navigation, expanded provenance, horizontal scrolling and 1440x900, 1366x768, 390x844 light/dark presentation. Main text/background contrast must be at least 4.5:1. Screenshots are local test evidence, not fabricated mocks. Playwright absence uses the existing explicit optional-dependency collection pattern; browser-capable acceptance is reported separately.

The local pytest environment disables automatic third-party plugin loading because an unrelated installed Web3 plugin has an `eth_typing.ContractName` import conflict. No repository dependency, CI selection or assertion is changed to accommodate that machine-specific issue.

Original V1 local acceptance at `256d2a808a1f4286be3139122513dd1baee2d29d` (Python 3.12.10 / Windows, disposable synthetic project storage):

| Ring | Result |
|---|---|
| Portfolio contracts, actual four-vertical commits, scenarios and Chromium | 41 passed; rc=0, normal process return |
| Existing Compare/Decision Support V1 | 28 passed |
| Existing Run History / Credit V3 / Sources & Uses / CSRF / workspace | 166 passed; rc=0, normal process return |
| Additional final Chromium drilldown/style rerun | 1 passed; rc=0, four theme/viewport combinations |
| Python compilation and diff whitespace check | PASS |

The final browser rerun follows the last CSS-only polish and validates actual history-detail and Credit Decision navigation, not only link strings. There are no financial/core/domain, persistence, export, comparison-projection, CI or financial-pin diffs. Full public-suite acceptance is deliberately left to fresh exact-head GitHub CI, not claimed from local focused tests.

Independent review and exact-head CI remain release acceptance authorities. This report does not grant merge, deployment or financial-methodology approval.

Current correction: [Correction A performance and acceptance](PORTFOLIO_MONITORING_CORRECTION_A.md).
