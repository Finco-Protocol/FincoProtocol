# Workflow B: Financing and Bankability Transparency

## Baseline and ownership

Implemented from verified main `f763ba214e1dafa45ac071453ce13b4c8e3b3562`.
PRs #221, #222 and #223 were independently verified merged before implementation.
An isolated worktree uses `feat/model-v2-financing-bankability-ux`.
No overlapping cost-editing PR was open at the final pre-publication check.

This is application/presentation work. There are no financial-engine, core,
persistence, schema, Run/CAS, export, history, certificate or execution-worker
changes. Workflow A's cost templates/commands/routes and shared workbook JS/CSS,
the workbook shell, generic field editor and post-run OOB assembler are unchanged.
FinModels harvest/staging/handoff documents were requested but their paths were
not supplied; no claim of comparison with those unavailable artifacts is made.

## Corrected presentation

- Senior rate inputs display finance-native percentage points, including `5.50`.
- Scoped financing styles repair light/dark Senior field and heading contrast.
- Working requested gearing is separate from Last Run sized debt and gearing.
- Last Run target, minimum and average DSCR and minimum LLCR show persisted values
  or explicit unavailable evidence; unavailable is never substituted with zero.
- Overview links directly to model-period CFADS in Senior Debt.
- Overview displays canonical financial integrity independently from freshness.
- Investor separates sponsor equity, SHL and other funding with native labels,
  Working versus Last Run evidence and equity-only versus sponsor return definitions.
- DSRA policy/coverage and persisted cash movements/balances remain read-only.

## Authority map

| Surface | Exact authority | Presentation rule |
|---|---|---|
| Editable Senior rate | Registry `debt.senior.interest_rate_pct`; typed `senior_rate_authority` | Uniform typed fractional rate is projected to percentage points, without a magnitude heuristic |
| Last Run sized Senior | `RuntimeResult.runtime_summary.senior_debt_keur` | Raw finite number only |
| Last Run actual gearing | `RuntimeResult.runtime_summary.actual_gearing_pct` | This persisted field holds a ratio; format as percent, never divide by Working CAPEX |
| Last Run gearing cap | `RuntimeResult.runtime_summary.gearing_cap_pct` | Raw persisted ratio |
| DSCR | `RuntimeResult.debt_schedule.summary.target_dscr/actual_min_dscr/actual_avg_dscr` | No sizing or averaging reconstruction |
| LLCR | `RuntimeResult.debt_schedule.summary.min_llcr` and optional `llcr_unavailable_reason` | Typed reason preserved when exposed; otherwise state that neither is persisted |
| CFADS to Senior | `RuntimeResult.financial_statements.pf_cash_waterfall.periods.fcf_banks_keur` | Exact serialized Base CFADS, original period index/date/sign, kEUR |
| Senior service cash | Same periods, `senior_total_ds_keur` | Separate use of cash, not CFADS |
| DSRA funding/draw and release | Same periods, `dsra_funding_keur/dsra_release_keur` | Net funding/draw sign preserved; no inferred gross movements |
| Actual reserve balance | Existing `RuntimeResult.debt_schedule.periods.dsra_balance_keur` | Existing debt schedule unchanged |
| Working DSRA policy | Typed `ProjectInputs.financing` support mode, target policy, months, requirement, facility | Explicitly not the dynamic Last Run target |
| Pure Equity IRR | `RuntimeResult.runtime_summary.equity_irr` | Persisted result, no UI calculation |
| Sponsor IRR and MOIC | `RuntimeResult.sponsor_schedule.summary.total_sponsor_xirr/pure_equity_moic/total_sponsor_moic` | Raw values; cash-multiple and timing definitions |
| Integrity | Existing institutional `get_run_integrity_checks` | Same authority as Trust; not a new financial checker |
| Freshness | Existing `resolve_runtime_freshness` via V6 request context | CURRENT is not financial approval |

Upstream CFADS lineage was inspected in `financial_engine/financial_statements/assembly.py`:
the cash-waterfall field is canonical Base tax CFADS. It is not Bank sizing CFADS
and not post-Senior cash. The projection never adds revenue/OPEX rows or constructs
annual aggregates. Serialized period values are copied, including source precision.

## Percentage proof

The existing workbook registry/persistence contract stores percentage points:
entering `5.50` persists `5.5`; the unchanged input adapter supplies a uniform
typed all-in rate of `0.055`. A legacy fractional snapshot is displayed from its
resolved typed rate, not by guessing units from its magnitude. The UI transformation
is only `typed ratio * 100` for display. Save remains the existing registry path.

Solar/Wind real Save tests prove the persisted/typed values. Solar, Wind, Data Center
and EV projection tests prove exact native display. Values `21`, `-1`, `nan` and
`abc` fail existing validation. Calibrated and unresolved authorities remain locked;
reference projects remain read-only via existing protection.

## Independent integrity states

| Input freshness | Canonical report | Visible integrity |
|---|---|---|
| CURRENT | PASS with checks | PASS |
| CURRENT | FAIL | FAIL, reason and complete failure code |
| STALE | FAIL | FAIL, explicitly prior-run evidence |
| CURRENT | INCOMPLETE | WARN |
| NOT_RUN | No report | UNAVAILABLE |
| Any | No evaluable checks, even an empty PASS header | UNAVAILABLE |
| Concurrent mutation | Snapshot no longer coherent | UNAVAILABLE; never a mixed-run verdict |

The overview fragment shows counts and a reason above the KPI area. Detailed
evidence retains `DSCR_SCULPTING_INFEASIBLE_SCHEDULE`; Trust/Checks is linked.
No check, certificate, saved result or original failure is modified or suppressed.

## Request safety and refresh

Two read-only fragments resolve canonical accessible-project ownership before
capturing the existing immutable V6 `PostRunRequestContext`. Final
`validate_current()` rejects concurrent Working edits or scenario changes.
Unauthenticated/cross-owner reads are rejected. Context is request-local, not a
cache or authorization grant. Responses are no-store.

Overview reloads integrity when its existing OOB fragment is inserted. Investor
refreshes on tab opening and successful HTMX POST using its own scoped trigger.
The canonical 13 post-run fragments and shared shell/JavaScript are unchanged.
On coherence failure Investor discards numeric evidence and asks to reload.
Existing V6 tests protect scenario restore, legacy Base, isolation, concurrent
mutations and deterministic post-run HTML.

## Sponsor multiple plausibility audit

Tests run synthetic Solar/Wind working copies with a saved 5.50% Senior rate.
These are numerical audit assertions only, not new production calculations.

| Case | Legal equity kEUR | Legal-equity receipts kEUR | Pure Equity MOIC | Total Sponsor MOIC |
|---|---:|---:|---:|---:|
| Solar | 500.0 | 69840.08441290111 | 139.6801688258022x | 9.92703992521436x |
| Wind | 500.0 | 143312.1032329901 | 286.6242064659802x | 13.957673451995536x |

The test independently checks the persisted equity multiple against persisted
legal-equity receipts divided by contributions. A small legal-equity denominator
with residual SHL financing explains why equity-only MOIC can be much larger than
sponsor-inclusive MOIC. These values are not silently corrected or presented as
annual returns. No conclusion about investment quality follows from this identity.

## Honest authority gaps and follow-ups

- Binding constraint/sizing verdict is not persisted in this presentation contract.
  Expose typed solver evidence separately before claiming a binding constraint.
- Missing LLCR values often lack a persisted typed reason; do not infer one.
- No writable Investor equity/SHL or DSRA coverage registry contract exists.
  Future editors require explicit registry mapping, save/load/scenario ownership,
  validation and acceptance before any UI control is added.
- Dynamic reserve target and reserve interest series are not persisted here.
  Show no invented schedules or interest amounts.
- Only canonical model-period CFADS is shown. Annual aggregation needs its own
  explicit period authority; no sums are reconstructed in this PR.
- The existing narrow workbook navigation remains a shared-shell concern outside
  Workflow B. Screenshots retain that layout; financing evidence itself fits.

## Focused validation and browser evidence

Focused command (Windows Python 3.12; plugin autoload disabled):

```text
python -m pytest -q tests/test_model_financing_bankability.py
  tests/test_model_ux_sponsor_transparency.py
  tests/test_saas_overview_decision_dashboard.py
  tests/test_model_workspace_typed_error_transport.py
  tests/test_u2_2_returns_surface.py tests/test_v2_scenario_overrides.py
  tests/test_f05_shared_session_contract.py tests/test_post_run_request_context.py
  tests/test_h4b_run_integrity_checks.py tests/test_data_center_vertical_integrity.py
  -p no:cacheprovider
```

Browser acceptance: `python -m tests.model_financing_browser_acceptance`.
An authenticated isolated temporary database uses real canonical Runs for Solar,
Wind, Data Center and EV. Overview/Debt/Investor are captured in light/dark at
1440px and 390px: 48 views, plus Solar/Wind real HTMX Save/Run lifecycle checks.
Read-only navigation must preserve the complete workspace record. Senior input
and section-heading contrast is measured at >=4.5:1. Browser JavaScript errors,
route failures and missing evidence fail the script.

Ignored evidence: `artifacts/model-financing-bankability/acceptance.json`,
`browser.log` and 52 screenshots, including:

- `solar-debt-dark-1440.png`
- `solar-overview-light-390.png`
- `wind-investor-dark-390.png`
- `solar-investor-after-save.png` and `solar-investor-after-run.png`
- `wind-investor-after-save.png` and `wind-investor-after-run.png`

Initial focused ring: **281 passed**, normal exit 0 in 111.56 seconds. Final
focused ring: **291 passed**, normal exit 0 in 124.06 seconds, including the entire
public surface hygiene suite and 36 new bankability cases. Browser acceptance: **48 views and two HTMX lifecycle
flows passed**, normal exit 0 with 52 screenshots. Python compile and diff hygiene
pass. Public safety and exact-head CI run IDs are recorded in the Draft PR delivery
report after validation. The full local suite is intentionally not run; all five
exact-head GitHub workflows are final authority.

## Independent diff review

Review specifically checks no parsed formatted gearing, no Working denominator
for Last Run ratios, no speculative coverage/CFADS economics, no second checker,
no new write routes, no original assertion weakening, owner binding and final
coherence guards. Browser lifecycle coverage was added when review identified
that Investor was not an existing post-run OOB target. This is resolved solely
through the owned read-only partial; no global integration was changed.

The first full exact-head CI run `37834051564` exited normally with 8447 passed,
49 skipped and one failed existing public-surface test. Native Investor grouping
had removed the old row-level `Reference model` wording. The test's meaningful
reference-language requirement is retained unchanged: the protected Investor
notice now says `Reference model`, and an additional test explicitly proves that
notice and absence of editors. No financial or access behavior changed. Fresh
exact-head CI, rather than the first run, is required for final acceptance.

Final state: one OPEN DRAFT PR. No deployment, merge, rebase, squash or force push.
