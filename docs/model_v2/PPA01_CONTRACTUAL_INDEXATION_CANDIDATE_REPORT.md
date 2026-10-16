# PR #293 - contractual PPA indexation candidate

Status: **NEW PPA01 FINANCIAL CANDIDATE READY FOR INDEPENDENT REVIEW** describes
functional candidate delivery only. Financial release/governance approval,
integration, merge and deployment remain NOT APPROVED.

## C2 rounding candidate update

This section supersedes older candidate identities/results below, which remain
historical evidence. Current base is 540e1f4bb54d53ad6d2c1628074b94fdb0c9eb06;
C2 parent is 9df9d3b908c57cbad093e29eeb676de849a39b83.

Implemented optional version-2 indexed-PPA rounding in the existing price
kernel, not a parallel calculator. OFF preserves original arithmetic. ON keeps
Decimal through indexation, existing floor/cap and explicit quantization,
then uses the existing revenue calculation. Four precisions, both tie methods,
three indexing methodologies, four calendar anchors, pre-COD reviews and
delayed sales are covered. No first-base rounding or recursive compounding.
No new floor/cap JSON fields, hidden reclamp, or Merchant/CfD rounding.

The additional owner-authorized dated OFF underflow guard rejects a positive
1e-816 price rather than returning zero. It preserves 1e-320 and the smallest
positive subnormal conversion. Enabled quantization may deliberately produce
zero. Numerical refusal is distinct from an explicitly agreed zero tariff.

New focused tests live in `test_ppa01_price_rounding.py`,
`test_ppa01_rounding_workspace.py` and `test_ppa01_rounding_browser.py`.
Saved preview stages reuse Python PPAParams authority; the actual Run retains
the existing JSON policy/terms binding and per-period tariff/revenue evidence.
No new writer, Run repository, export calculator or execution path exists.

Initial numerical acceptance: 221 passed, process rc=0 (new rounding tests,
existing model-year/C1 and contractual timing suites). Real Chromium: 10 passed,
rc=0, Solar/Wind desktop/light and mobile/dark, including six existing calendar
cases. Full focused results, exact final HEAD/tree, independent review and
current CI are recorded in the final PR handoff after validation.

Protected candidate hashes are listed in the current three-path section of
`PPA01_FINANCIAL_AUTHORITY_SUCCESSOR_PROPOSAL.md`. No source outside those
protected paths changes. All historical pins and release-closed flags remain
unchanged. The 41 historical governance failures are not waived: final C2
governance work awaits exact-content review plus actual owner authorization.

Router overlap with #292 remains separate: this candidate only extends the
Revenue editor projection, not its statements-drilldown routes or Run identity.
Do not merge another workstream into this branch to substitute for RC review.

## Provenance

Repository Finco-Protocol/FincoProtocol; existing Draft PR #293; existing branch
`feat/model-sc34-input-workflow-reliability`. Main/base at live preflight:
`540e1f4bb54d53ad6d2c1628074b94fdb0c9eb06`; parent:
`1c257cb909d79af3a9afaa3a55c7e6da534231ec` (6 ahead / 0 behind).
Exact final candidate HEAD/tree is recorded in the PR handoff after commit.

The owner separately approved candidate methodology (four rules; operating
boundary-only reviews) and the minimal `generation.py` COD context bridge.
Neither decision approves financial bytes, a successor map, activation or merge.

## Implemented contract and boundaries

- An optional version-2 PPA `indexation_timing` object; old payloads and
  operating-year `index_series` remain unchanged, without migration.
- Separate Price Base Date, Indexation Start Date and First Effective Review.
  SIGNATURE requires signing_date; CUSTOM requires custom_start_date;
  PPA_START resolves to the contract commencement. COD resolves ONLY to
  ProjectInputs.info.cod_date from Project Timeline, checked against
  PeriodEngine.cod. The stored resolution is checked evidence, not another COD.
- Annual fixed: explicit first review must be the first exact anniversary;
  completed reviews, including pre-COD, determine the integer rate exponent.
  No fractional-year compounding or automatic leap-date adjustment.
- Dated CPI/PPI: exact base observation and explicit annual review/reference
  map, including pre-COD reviews. Positive finite levels, observation dates,
  publication availability, source references and OBSERVED/FORECAST declarations.
  P0 * reviewed level / explicit base level; no duplicate rate escalation.
- Missing observations, unavailable observed publications, mixed bases,
  wrong COD binding or an effective review inside an active operating period
  fail closed. Nothing is shifted, averaged, interpolated or forward-filled.
- The existing Indexed PPA editor exposes four commencement rules, conditional
  date inputs, dated observation/review tables and strict TSV replacement.
  Saved per-period price previews call the canonical Python authority, not a
  second JS calculator. Edits hide the old preview until Save succeeds.
- Existing CSRF, owner, protected Reference, scenario CAS and immutable Run
  writers are reused. No new POST endpoint, alternate writer or data store.

## Project Timeline integration

The operating axis is not a COD authority. An actual COD 2031-12-29 produces a
first operating start 2031-12-31 under existing stub handling. Tests preserve
that distinction, reject a stale COD resolution, accept an explicitly updated
resolution and reject ProjectInputs/PeriodEngine COD disagreement.

Changing project dates must leave the existing Timeline internally coherent;
this candidate does not recalculate or silently move Financial Close, construction
duration, COD or contractual review dates. Long PPAs anchored to a date such
as 15 April will be refused if later annual reviews fall inside the existing
semiannual periods. That is the authorized limitation, not permission to round.

No Inputs Timeline redesign was needed. A future separately scoped hook may
summarize affected contracts when project dates change; it must call this same
validation rather than store another project-date authority. There is no new
independent project-level PPA activation field: the existing Timeline/operating
axis supplies project context; stream-specific commencement remains explicit.
The editor reads Timeline context separately from invalid contract terms,
keeps their validation error visible and offers an explicit local-draft action
to use the current Timeline COD. It never moves the first review automatically.
The changed-COD editor regression passes without rewriting stored terms.

## Numerical evidence

Independent Decimal oracle cases use the real canonical axis, not assumed
January/July boundaries. Four-anchor Solar/Wind expectations at COD 2030-12-31,
P0=60 and r=2%, are 62.424 (signature 2028-12-31), 60 (COD), 61.2 (custom
2029-12-31); delayed PPA_START 2031-12-31 begins at 60 with no earlier PPA sales.
Later prices are independently recomputed for every active period.

Maximum measured annual-price residual: 5.6843418860808015e-14 EUR/MWh.
Maximum measured annual PPA-revenue residual: 2.7284841053187847e-12 kEUR.
New assertions explicitly use rel=0 and existing 1e-12 price / 1e-8 kEUR
absolute precision; no tolerance or golden changes.

Dated levels test flat, rising and falling series, real pre-COD reference and
publication dates, partial initial periods, missing pre-COD/future observations,
nonfinite/zero/negative levels, mixed methodologies and expiration into residual
Merchant. A signing date 2029-04-15 with reviews before COD is accepted when
no review falls inside the active contract's operating period.

Twenty legacy Solar/Wind full revenue schedules remain bit-exact against the
immutable pre-PPA-01 runtime (fixed, annual-indexed, scheduled PPA, scheduled
Merchant, signed CfD; normal and partial COD). Existing inactive four-vertical
input-class/serialization checks and two-Senior financial integration pass.
A separate four-vertical test also executes the genuine canonical production
Run twice, comparing complete G2C financial results and financial statements
exactly against the immutable pre-bridge generation authority. Application
memoization is cleared between runs so cache reuse cannot create false parity.
The financial engine outside the explicit bridge is unchanged.

## Local results

| Scope | Actual result |
|---|---|
| New dated numerical/COD cases + PPA-01 + WF07 financial suites | 172 passed, rc=0 |
| Dated Save/Scenario/Run/history + PPA-01 + SC-04/06/07/10 + advanced Revenue + atomic batch | 117 passed, rc=0 |
| New real Chromium Solar/Wind desktop/light and mobile/dark, dated tables, failed Save | 6 passed, rc=0 |
| Existing PPA-01 and advanced Revenue Chromium on this candidate | 16 passed (separate completed run) |
| Complete new + existing PPA/Revenue/SC browser ring | 38 passed, rc=0 |
| Stale contract dates / current Project Timeline editor recovery | 1 passed, rc=0 |
| Final complete dated workspace suite after Timeline editor recovery | 5 passed, rc=0 |

Counts are focused and can overlap; not a full-suite total. All cited processes
returned; no skips/xfails were added. During development, tests exposed a missing
table tbody and closed-preview visibility assumptions; both were corrected and
the new six-case real-browser run passed. Baseline January-boundary fixture
assumptions were corrected to the real axis, never by changing PeriodEngine.
The final five-case workspace run completed in 58.67 seconds, and the final
six-case Chromium run in 35.90 seconds, both with process rc=0. A redundant
sandboxed workspace repeat was interrupted after making no visible progress;
the completed run used disposable storage and normal local process permissions.

Real screenshot files (private, no binaries committed):
`pr293-private/calendar-browser/calendar-{sola,wind}-{desktop,mobile}.png` and
`dated-levels-{sola,wind}.png`. JUnit, failure-development logs and final acceptance
evidence are retained privately. No provider research/source material is copied.

Separate GPT-6 High-context technical review identified and reproduced a future
base-date back-application and an intermediate-overflow refusal. Both were
corrected, with four new tests. Its follow-up found no remaining finding in
those two corrected paths. This is limited technical feedback, not financial
release approval; the reviewer did not authorize a governance successor.

## Changed paths

```text
app/templates/v2/partials/revenue_contracts.html
app/v2/router.py
app/workbook/revenue_multistream.py
domain/revenue/multistream_runtime.py
finco_core/revenue/generation.py
static/css/model_revenue_contract_editor.css
static/js/model_revenue_contract_editor.js
tests/test_ppa01_contractual_browser.py
tests/test_ppa01_contractual_timing.py
tests/test_ppa01_contractual_workspace.py
docs/model_v2/PPA01_CONTRACTUAL_INDEXATION_METHODOLOGY.md
docs/model_v2/PPA01_CONTRACTUAL_INDEXATION_CANDIDATE_REPORT.md
docs/model_v2/PPA01_FINANCIAL_AUTHORITY_SUCCESSOR_PROPOSAL.md
```

Protected candidate Git blobs:

```text
domain/revenue/multistream_runtime.py 4c53ed15491e3f4a3faddde0e142681ed0a13ae2
finco_core/revenue/generation.py 8e23a949e72acc6422a6c7cd46f034b31f81fdfb
```

## Governance and CI

No historical map, financial pin, M7 candidate, activation flag, workflow,
golden or numerical tolerance is changed. ZERO diff in financial_engine/ and
other domain/core paths. Both candidates require independent exact-content
financial and governance review; there is no self-approval.

The previous exact-head Public Safety run 38886753393 remains FAILED (11688
passed, 87 skipped, 11 authority failures, pytest/process rc=1), not current-head
acceptance. The eleven original nodes were rechecked before candidate commit
and remain failed; this is intentional visibility, NOT a waiver. Guards read
Git HEAD, so that precommit run does not authorize/test the new committed blobs.
Postcommit governance, source safety, compilation and new CI details belong
to the final PR handoff. New context-bridge content can trigger additional
protected-path rejections; these must not be concealed or pre-labelled green.

No full local public suite or repeated CI reruns were used. No main/workstream
merge, rebase, squash, force push, new PR or deployment. PR #289 remains separate.
The candidate is for independent review, not RC integration approval.
