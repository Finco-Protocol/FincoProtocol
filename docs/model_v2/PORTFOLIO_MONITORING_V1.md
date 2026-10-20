# Institutional Portfolio Monitoring V1

## Scope and entry points

Base: `5996453b8d5bbfaa48bc06922fc6963cf94d2f84` (live origin/main independently fetched before development).

`GET /v2/portfolio` is an authenticated, owner-only, read-only workspace over all non-archived projects owned by the signed-in user. Compare Projects links to it. It links back to the existing five-project Compare; no comparison calculator, comparison projection or second picker was introduced.

No portfolio tables, financial formulas, financial authority maps, Run writers, export implementation, shared workbook shell, activation flags or CI definitions change. The sole shared-router change is the dedicated router import/registration at the end of `app/v2/router.py`; this hook is explicitly identified for RC coordinator review. Coordinator acknowledgement is not fabricated by this report.

## Evidence contract

- One newest immutable `model_run_history` entry per project, ordered by the existing repository's `ran_at DESC, history_id DESC` authority. Multiple scenarios are not counted as multiple projects.
- This is the latest committed Run, **not necessarily the active scenario's selected Last Run**. If those differ, the row says so and is never promoted to CURRENT.
- Only owner-scoped repository APIs are used. Project ownership/archival is checked again after evidence assembly. Shared system reference projects are not silently included as portfolio assets.
- Freshness reuses `assemble_consistent_for_get` and `resolve_runtime_freshness`, including legacy Base equivalence. Repeated workspace/identity/history reads detect concurrent saves, cost changes, scenario selections or new commits; mixed reads are marked unverified. This is not a cross-project transactional snapshot or continuous live-currentness claim.
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

The displayed funding amounts are the committed initial financing/Sources & Uses, **not today's outstanding exposure**. Subtotals are grouped by identical recorded construction funding start/end dates, EUR/kEUR and the F1 metric scope. No grand total merges incompatible windows. Missing dates exclude an amount from aggregation, not from its truthful individual-project display.

The existing `NonConstructionFcUse` payload records FC/COD Uses and Sources but no cash-payment date. A positive such amount therefore excludes total Uses and all financing-source metrics from dated subtotals. Hard CAPEX can remain in its recorded construction-window cohort. No COD is inferred from a construction end date or today's Working Copy. This is a real upstream evidence limitation; V1 does not alter persistence or the financial writer to fill it.

Every subtotal shows its numerator/project coverage. No eligible values means **Unavailable**, not zero. Amounts use deterministic Decimal summation of persisted numeric representations before display rounding; unavailable/string/bool/non-finite inputs cannot become zero. Country/technology exposure breakdowns retain the same date cohort and exclusions.

No new evidence is persisted. Existing historical exports and committed Runs remain unchanged. Portfolio-specific export, archived-project inclusion, FX/as-of revaluation, current outstanding balances, shared-account aggregation and large-account pagination are not part of V1.

## Verification

Core tests use actual Solar, Wind, Data Center and EV canonical route commits in disposable SQLite, then compare raw persisted values and exact history IDs. GET repeats are guarded against engine execution and Run commitment and are checked against before/after Workspace and history snapshots.

Synthetic edge cases cover mixed/unknown units and currencies, missing dates, undated FC/COD funding, invalid binding, corruption, zero versus unavailable, negative and missing returns, deterministic ordering/summation, more than five projects and owner rechecks.

Chromium tests exercise authenticated HTTP, filters, reload/Back navigation, expanded provenance, horizontal scrolling and 1440x900, 1366x768, 390x844 light/dark presentation. Main text/background contrast must be at least 4.5:1. Screenshots are local test evidence, not fabricated mocks. Playwright absence uses the existing explicit optional-dependency collection pattern; browser-capable acceptance is reported separately.

The local pytest environment disables automatic third-party plugin loading because an unrelated installed Web3 plugin has an `eth_typing.ContractName` import conflict. No repository dependency, CI selection or assertion is changed to accommodate that machine-specific issue.

Local acceptance (Python 3.12.10 / Windows, disposable synthetic project storage):

| Ring | Result |
|---|---|
| Portfolio contracts, actual four-vertical commits, scenarios and Chromium | 41 passed; rc=0, normal process return |
| Existing Compare/Decision Support V1 | 28 passed |
| Existing Run History / Credit V3 / Sources & Uses / CSRF / workspace | 166 passed; rc=0, normal process return |
| Additional final Chromium drilldown/style rerun | 1 passed; rc=0, four theme/viewport combinations |
| Python compilation and diff whitespace check | PASS |

The final browser rerun follows the last CSS-only polish and validates actual history-detail and Credit Decision navigation, not only link strings. There are no financial/core/domain, persistence, export, comparison-projection, CI or financial-pin diffs. Full public-suite acceptance is deliberately left to fresh exact-head GitHub CI, not claimed from local focused tests.

Independent review and exact-head CI remain release acceptance authorities. This report does not grant merge, deployment or financial-methodology approval.
