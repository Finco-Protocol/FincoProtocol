# RC-4 PPA-01 Financial Acceptance Dossier

Date: 2026-10-17. Scope: technical financial review and test-side post-merge
governance correction. No financial formula, released pin, activation flag,
production application, workflow or deployment change.

**Financial owner authorization: FINANCIAL_OWNER_APPROVAL_REQUIRED.**
This dossier is evidence, not the canonical acceptance record or a release.
`docs/rc3/PPA01_FINANCIAL_ACCEPTANCE.json` has not been created.

## Exact Source And Provenance

- Verified source main: `4483b30904a30cd3f5406506283202e2ebeaf427`.
- Source tree: `47921aff9bae0615231b68d57b1a2475dbe9f3ee`.
- PR #294: MERGED at `2026-10-16T21:48:50Z` (GitHub UTC).
- Normal merge parents: `540e1f4bb54d53ad6d2c1628074b94fdb0c9eb06`,
  `c791b125d6361828604a242ad515034a0d2936d7`.
- Original PPA candidate source `153a00384b2e4658863a967eec2184b5c5417eb4`
  is an ancestor of source main. Publication base:
  `540e1f4bb54d53ad6d2c1628074b94fdb0c9eb06`.
- Workstream: `feat/model-rc4-ppa-financial-acceptance`, based on verified main.
  Final workstream HEAD and live CI belong to the delivery handoff, not a
  self-referential containing-commit identifier.

| Protected financial source | Exact candidate Git blob |
|---|---|
| domain/revenue/multistream_runtime.py | b1896bdb156a53c8371286bb4198381d0c7904fe |
| domain/revenue/revenue_config.py | d62fc2c7d97986d2c0aed6c0ac9068759011e1ef |
| finco_core/revenue/generation.py | 8e23a949e72acc6422a6c7cd46f034b31f81fdfb |

All three remain unchanged by RC-4. The expected state is
`INTEGRATED_RELEASE_CLOSED_CANDIDATE`, not financially approved or activated.
Historical WF07/V2/V3/F3.5/Developer Economics and other financial maps remain
unchanged. BESS, acquisition, Junior and Revenue V3 flags remain literal False;
the existing candidate manifest remains `release_approved:false`.

## Separation Of Decisions

The coordinating agent previously implemented the PPA candidate and cannot
self-approve it. A separate GPT-6 High reviewer, with fresh context and no
write authorization for financial source, was assigned the independent
technical examination of these exact blobs. Its findings and independently
executed calculations are recorded in the completed review section below.
This is AI technical evidence, never a fabricated human review or owner decision.

The existing acceptance validator requires a human independent reviewer and
financial owner, exact accepted blobs, reviewed source head, decision reference
and candidate-only scope. An AI report does not meet that human-owner gate.
An eventual content-acceptance record still does not by itself authorize release.
Production release/activation must remain a separate explicit decision.

The PPA classification/acceptance functions are test-side governance, not a
runtime permission grant or a newly installed PPA kill switch. Explicit PPA
candidate inputs can execute in canonical acceptance cases. No PPA-specific
runtime activation flag was identified in the inspected Save/Run bridge;
the closed flags verified here belong to BESS/acquisition/Junior/Revenue V3.
Do not present formal candidate status as proof that every deployed user is
technically prevented from opting into PPA-01. Any required deployment/runtime
access restriction must be separately specified and verified before release;
this workstream does not alter production access or activation behavior.

## Financial Methodology And Owner Checklist

| Convention | Required interpretation |
|---|---|
| SIGNATURE / COD / PPA_START / CUSTOM | Distinct explicit anchors; COD only from Project Timeline, checked against PeriodEngine.cod |
| Base price date | Not after the commencement or first priced sale; no retroactive future base |
| Annual reviews | First exact anniversary and later exact annual anniversaries; no inferred date shifts |
| Pre-COD | Completed reviews establish opening price, but no construction-period PPA sales |
| Calendar versus model-year | Separate authorities; supplied model-year levels use PeriodMeta.year_index, not calendar year or contract anniversary |
| Dated index | Original price times explicit review observation/base ratio, exactly once; observed publication must be available at the effective review |
| Forecast index | Explicit assumption, not a published fact |
| Operating review dates | PERIOD_BOUNDARY_ONLY; intraperiod changes rejected rather than weighted or moved |
| Optional rounding | Default OFF; 2/3/4/6 decimals, HALF_UP/HALF_EVEN; only after a completed review |
| Price order | Indexation, existing floor/cap, one contractual quantization, existing revenue/settlement |
| Rounding boundaries | May cross nominal floor/cap by quantization; no hidden reclamp |
| Numerical safety | Positive Decimal lost in float conversion rejected; representable subnormals preserved; explicit quantized zero distinct from underflow |
| Multiple contracts | Explicit production shares and residual Merchant; no duplicated generation or automatic contract filling |

An owner must accept these limitations explicitly, particularly the two-period
model-year key (including an initial stub), date-boundary refusal, no inference
of missing index observations, and post-cap/floor rounding. These are not
generic claims that every external contractual convention is supported.

## Independent Technical Review

Separate reviewer: **GPT-6 High technical reviewer**, fresh-context task
`01a146b7-7e67-7d11-9661-5864f3b350d6` (AI, not a human financial owner).
Technical verdict: **ACCEPTED for the three exact blobs above**. Private
`REVIEW.md` SHA-256:
`ba7fe83cc1a606705e3e9dea2108c3edd37878ab59be5e592f7371c5ce89fd0a`.
The review read all three complete source files, ran independent Decimal
probes and genuine `run_clean_production` Solar/Wind executions. It is not
adopted from the earlier implementation agent's report or CI description.

Synthetic case: 35% calendar-indexed PPA at base 60.005, signature 2028-12-31,
2% annual reviews, HALF_EVEN/2; 25% model-year PPA at base 45.227 with explicit
levels 100/105 and HALF_UP/3; residual Merchant 40% at 80 with capture 0.8.
Both PPAs end after four operating periods; Merchant takes 100% afterward.
Independent expected PPA-price residual was zero; maximum stream-revenue
residual was 4.68e-13 kEUR Solar and 6e-13 kEUR Wind. The complete canonical
operating revenue vector exactly matched decomposition (0.0 kEUR residual,
53 Solar and 58 Wind rows including construction zeros).

Independent first-sale checks at COD 2030-12-31 and P0=60 returned SIGNATURE
62.424, COD 60, CUSTOM 61.2 and delayed PPA_START 60, with no earlier sales.
Dated levels 100/103/106/109 produced Solar initial prices 63.6/63.6/65.4 and
Wind 63.6/65.4/65.4 using explicit review/reference/publication dates, not a
second annual-rate factor. Wind's calendar anniversary repriced one PPA
while the model-year PPA remained in year 1, demonstrating distinct clocks.

Negative probes rejected future base dates, wrong actual COD, mixed bases,
midperiod reviews and late published observations. Extreme dated 1e308 and
subnormal 5e-324 stayed representable; positive 1e-816 was rejected with
rounding OFF while explicitly quantized zero was accepted with rounding ON.
Floor/cap followed by rounding and non-recursive pricing were independently
checked. The reviewer executed 280 pricing/parity tests and 49 P0-B3 tests,
all passing with process exit 0 and plugin autoload disabled.

**Low-severity finding RC4-PPA-D01:** runtime line 281 correctly rejects both
nonfinite overflow and zero underflow, but its shared message says "underflow
to zero" for overflow too. Reproduction: base price 60, model-year base level
1e-308 and later level 1e308, year 2. This is a diagnostic wording issue, not
financial mispricing or fail-open behavior. No protected blob was changed to
fix cosmetic wording during acceptance. A future separately reviewed change
would require its own exact-content review.

The reviewer did not complete persisted Save/Scenario/History validation;
that product ring is separately executed by the coordinator below. Reviewer
setup failures and an interrupted workspace attempt are not counted as pass.
External matched-input evidence was not supplied to that reviewer. The
coordinator's separate private archive inspection is classified below.

The bounded read-only sanity review of the new governance diff found no
genuine fail-open regression or excess scope; this is technical evidence,
not approval of its implementation or of financial release.

## Internal Numerical And Product Evidence

Current RC-4 execution results, not historical counts:

| Validation | Result |
|---|---|
| Unmodified-main candidate authority baseline | 3 failed, 34 passed, rc=1; two empty-diff failures and one obsolete pre-merge assertion |
| Corrected candidate and new post-merge Git negative tests | 50 passed, rc=0 |
| Additional original published candidate identity test | 1 passed, rc=0 |
| WF07/V2/V3, M7, finance integrity, Model V2 and CI governance ring | 167 passed, 10 existing skips, rc=0 |
| F3.9, four-vertical, P0-B3, WF-A impact regression | 125 passed, rc=0, 985.90 seconds |
| Independent reviewer pricing/parity ring | 280 passed, rc=0 |
| Independent reviewer P0-B3 reconciliation ring | 49 passed, rc=0 |
| New public two-PPA/dual-clock Decimal oracle and canonical Solar/Wind Runs | 2 passed, rc=0; max net-revenue residual 9.0949470177292824e-13 kEUR |
| Persisted Save/Scenario/Run/History ring | 23 passed, rc=0, 459.22 seconds |
| Full public source scan on LF checkout | PASS, rc=0; final changed files scanned again after dossier completion |

The 10 skips are existing retired-epic-marker conditions (9: Model V2 epic
scope marker absent; 1: scope marker absent). No skip/xfail was added or
selected to hide a failure. Historical negative tests and authority maps are
retained. Initial baseline setup also hit a missing disposable parent directory;
the reported clean baseline above was rerun after creating it, without any
test or financial change.

Framework/oracle tests are not automatically canonical engine acceptance.
Actual independently executed Solar/Wind financial Runs and their numerical
residuals must be identified separately in the final review section.

The new public `tests/test_rc4_ppa_financial_acceptance.py` retains explicit
production shares, independent Decimal tariffs, residual Merchant capture,
existing input-owned balancing costs and the full canonical revenue vector.
Its initial Wind net-revenue expectation omitted the unchanged 8 EUR/MWh
balancing input. Only that synthetic oracle was corrected; no output target,
engine formula or tolerance changed. The final Solar and Wind tests both pass.

## Post-Merge Governance Defect And Correction

Before correction, `collect()` used the merge base of moving `origin/main` and
candidate ref for candidate identity. After #294, HEAD equals main and that
protected diff is empty. All three exact blobs and correct ancestry are present,
yet the guard reports a partial slice. A second test incorrectly demands that
the pre-integration anchor is still absent from main after its normal merge.

The correction keeps candidate identity anchored to the immutable publication
base and verifies that base is an ancestor of both candidate source and target.
It retains a separate `branch_protected_changes` observation against current
main; an empty branch delta is not evidence that the candidate disappeared.
The original exact three-path/full-slice rule remains, including rejection of
an extra protected financial file even if moving main later contains it.
Missing Git refs, missing files, changed blobs, historical authority edits and
opened release flags fail closed. No new financial release map is introduced.

Real-Git tests cover HEAD==main, unchanged feature inheritance, a normal
integration merge, original candidate source, changed/missing candidate files,
extra domain/core/engine paths, moving-main concealment, historical pin edits,
all four activation flags, missing refs and invalid provenance facts. Existing
synthetic pre-merge anchor tests remain; the real-history test now verifies its
post-merge HEAD fallback and the immutable historical pre-candidate proof.

## External Matched-Input Parity

Private reference archives and prior bounded investigation artifacts are
available. Selected archived CPI stream inputs/outputs were read as structured
JSON; no archived scripts, authentication captures or live external service
were executed. No proprietary evidence or identifiers are copied into Git.

The inspected source stream declares year ranges, a price, escalation type/rate
and an index identifier, but not a complete matching contractual anchor,
distinct base/reference dates, dated publication observations or C2 rounding
policy. No complete current FINCO immutable Run identity/input fingerprint
was bound to the archived response. Mapping those missing conventions silently
would invent source truth.

- C2 dated/rounding external parity: **NOT COMPARABLE**.
- Exact current paired external Run bundle: **EVIDENCE UNAVAILABLE**.
- First unresolved causal stage: **input/convention and period-axis matching**,
  before certifying a common financial period. No downstream difference is
  labelled explained by an approved convention without an actual bridge.
- Revenue, EBITDA, CFADS, service, DSCR, project/equity return external equality:
  **NOT ASSERTED**. Prior captures or tax bridges are not current PPA approval.

Required external bridge: paired units/currency and full input snapshots;
actual timelines and period axes; PPA base/index/review/publication/rounding
terms; indexed/fixed contracted volumes; Merchant capture/settlement; tax and
financing assumptions; immutable output identities. Then use P0-B3/F3.9
reconciliation to identify the earliest component/period divergence.

## Release-Risk Assessment And Decision Path

Numerical correctness, contractual applicability and release authorization are
separate. Existing unsupported conventions (mid-period resets, lag inference,
unsupported settlement or volume contracts) must remain explicit refusals.
A successful Run, matching financial identity or green CI is not an approval.

1. Review the three exact blobs and this independent technical dossier.
2. Resolve any confirmed numerical finding before content acceptance; no
   financial formula correction is authorized in this workstream.
3. Obtain a genuine named independent human financial review and explicit
   owner decision, with real decision reference and exact three-blob list.
4. Only then prepare the existing canonical acceptance record with its actual
   provenance. Do not reuse synthetic test names/signatures as acceptance.
5. Obtain separate release authorization and activation/security/product
   acceptance if proposed. This branch does not open any production flag.
6. Require exact integration-head CI and independent review before any merge.

Current disposition: **FINANCIAL_OWNER_APPROVAL_REQUIRED**. No release, merge
or deployment authorization is granted by this dossier.

## CI And Integration Boundary

The source-main post-merge runs inspected were Public Safety `38971866301`
(full pytest still IN_PROGRESS at the last live inspection; source-safety
job succeeded), Dependency Security `38971866350` (SUCCESS), and Protocol
Verification Corpus `38971866192` (SUCCESS). They are source-main evidence,
not a green exact-head result for this workstream or financial acceptance.

This delivery publishes a workstream branch only, not a direct main PR. The
existing Public Safety workflow triggers on main pushes, PRs or explicit
dispatch; a feature-branch push alone is not full mandatory CI acceptance.
No workflow selection, timeout, requirement or safety assertion is changed.
The coordinator must test the actual RC-4 integration HEAD with all mandatory
evidence and obtain independent review before proposing any merge/release.

## Workstream Changed Files

| File | Purpose |
|---|---|
| tests/ppa01_candidate_authority.py | Immutable candidate provenance, separate branch ownership, unchanged-history and closed-state checks |
| tests/test_ppa01_candidate_authority.py | Replace obsolete pre-merge expectation with post-merge and immutable historical proof |
| tests/test_ppa01_post_merge_authority.py | Real-Git positive inheritance and fail-closed mutation tests |
| tests/test_rc4_ppa_financial_acceptance.py | Reusable synthetic dual-clock Decimal/production-Run reconciliation |
| docs/rc4/PPA01_INDEPENDENT_FINANCIAL_ACCEPTANCE.md | Technical dossier, limits and genuine owner-approval checklist |

Financial source, application, workflows, historical pin maps, goldens and
numerical tolerances: ZERO DIFF against the verified workstream base.
