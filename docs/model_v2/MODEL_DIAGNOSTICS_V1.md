# Model Diagnostics V1 — authority and acceptance contract

Baseline: `b47aa732f567e380cbe4c8e20b6c1a7dc0db9fbf`. Branch: `feat/model-diagnostics-v1`.
Parallel Draft PRs #265 (Revenue), #266 (AI Import), #267 (Investor Waterfall) were inspected;
none of their financial authorities are copied or changed here.

## One evidence workflow

Overview Model Health → Model Diagnostics → check/period evidence → existing authoritative sheet.
Diagnostics is a destination in the existing workbook manifest, not a separate routing system.
Query `sheet=diagnostics` and hash `#diagnostics` retain the existing navigation contract.
Optional `diagnostic_check=QM-SD-002&diagnostic_period=5` restores selection within that tab.
Schedule navigation is sheet-level: no unsupported exact-row selection is claimed.
`GET /v2/workbook/diagnostics` uses the existing authorized coherent request context for the
JSON grid Save refresh. It never runs the engine or writes; responses are no-store. Pending
refresh hides the previous CURRENT score and thresholds. A UI generation guard rejects a
late refresh after a newer Save/Run/scenario action. HTMX saves reuse the original OOB path.

The existing Quality registry/scorer is evaluated once for FINCO Insight. Diagnostics and
Overview reuse that same report/score/counts/top-issue order. No new check identities or
tolerances. Run Integrity is a separate original report over the same committed evidence.
CURRENT does not imply Integrity PASS. Quality readiness is advisory, not model correctness,
bank certification, asset verification, or independent market validation. Project-supplied
thresholds are not verified lender covenants. STALE describes the prior immutable Run, never
the changed Working Copy; current Working Copy thresholds are not bound to a STALE Run.
NOT_RUN has no invented score/checks. Missing evidence is UNAVAILABLE, not zero or N/A.

## Period scopes (seven existing check identities)

The adapter invokes the original pure Integrity validators on selected committed facts:

| Quality identity | Exact validation scope |
|---|---|
| QM-ACC-001 | One balance-sheet period; retains financing authority and matching Senior coverage |
| QM-SU-001 | One construction period **and unchanged global Sources/Uses summary**; global result disclosed separately |
| QM-SD-001 | **Cumulative prefix through period**, preserving initial commitment, all adjacent continuity, original row order; terminal condition applies only at actual last period |
| QM-SD-002 | One period, original interest/debt-service validator |
| QM-SD-003 | One period, original DSCR validator including debt-service applicability and its exact tolerance |
| QM-SD-004 | One period **and unchanged global solver authority**; solver prerequisite disclosed |
| QM-CASH-001 | One persisted cash period and matching persisted balance-sheet facts |

Cells are never inferred from aggregate PASS. Prefix/global scopes are explicit in tooltips
and detail, not described as independent local checks. Residual is the canonical validator's
maximum deviation in the stated scope. Raw observed/expected construction facts are shown
only where available; the global-inclusive residual need not equal their local difference.
An aggregate FAIL with no rendered failed cell always exposes a FAIL global/unrendered boundary
component. All period proofs fail closed on non-intact evidence digest.

Other rows show AGGREGATE_ONLY (unsupported local proof), NOT_PERIODIC (global check), or
UNAVAILABLE (missing evidence). These are presentation classifications, not new verdicts.
Junior Debt remains in the original Integrity report and is not invented as a 31st Quality check.
The axis uses persisted period indices/dates, not a new calendar or 30-year assumption.
Rendering is bounded to 600 periods with explicit disclosure; aggregate results retain full scope.

The inspector copies committed statement lines. It does not calculate a waterfall. Missing
lines/periods/date joins stay UNAVAILABLE. Full precision remains in diagnostic evidence;
existing persisted display schedules retain their own serialization precision.

## Coverage gaps — not additional passed controls

| Control family | Coverage | Existing authority / gap |
|---|---|---|
| CAPEX spending profile | PARTIALLY COVERED | QM-SU-001/002 funding reconciliation; no independent spending-profile control |
| OPEX reconciliation | PARTIALLY COVERED | QM-ACC-003 aggregate EBITDA identity; no independent detailed OPEX schedule reconciliation |
| Depreciation reconciliation | NOT SUPPORTED | BS uses depreciation; no independent depreciation control in 30-check registry |
| Cash-flow balance | PARTIALLY COVERED | Sources/Uses, debt-service and negative-cash checks; not a full independent cash-flow identity |
| SHL capitalization | NOT SUPPORTED | No dedicated capitalization identity; sponsor/terminal evidence does not prove it |
| SHL repayment | PARTIALLY COVERED | QM-TERM-002 contractual maturity and QM-ACC-002 sponsor flows; no local repayment schedule validator |
| Distribution timing | PARTIALLY COVERED | Sponsor flow dates, lock-up input advisory; no independent contractual distribution timing control |
| Circularity / solver termination | PARTIALLY COVERED | QM-SD-005 and sculpting authority; no general circularity validator |
| Yield-case consistency | NOT SUPPORTED | No independent canonical registry control |
| Scenario identity | EXISTING | QM-PRV-005 active scenario vs committed Run; global, not periodized |
| Reserve account movements | PARTIALLY COVERED | QM-CASH-001 negative balances and QM-CASH-002 proven initial target; no independent movement roll-forward |

## Acceptance and CI ownership

Unit tests exercise exact 30-check metadata/status/score/count parity on Solar, Wind, Data Center,
EV Charging, seven negative financial cases, initial/adjacent/global boundaries, digest corruption,
missing periods/covenant, aggregate-only PASS, CURRENT/STALE/NOT_RUN and persisted multi-frequency dates.
Existing Insight route/lifecycle/regression tests remain mandatory and unchanged.

Real Chromium tests are added to the **existing mandatory consolidation browser module**.
The six-role workflow and fail-closed collection/outcome/JUnit/PNG verifier are unchanged.
Every new test executes in that role; no skips, xfails, continue-on-error or weaker safeguards added.
Synthetic projects prove Health→matrix→period→schedule, filters, keyboard activation, Back,
four verticals, mobile horizontal scrolling, no GET mutation, real failure evidence and zero console errors.
Captures and console JSON: `artifacts/model-diagnostics/`, included by the existing role artifact manifest.
No production/staging data is changed. No self-approval, merge, deployment or financial output changes.

Known conservative V1 limits: no new period authority for 23 non-periodized check identities;
no exact-period deep link into existing schedules; unsupported inspector lines stay unavailable.
