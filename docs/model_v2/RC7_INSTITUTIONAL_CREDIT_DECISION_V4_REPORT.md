# RC-7 / Workstream D — Institutional Credit Decision V4 / Authority & Acceptance

Status: DRAFT. Read-only committed financial evidence; no new debt solver, no calculation authority, no lender certification.

## Provenance

- Independently verified base main: `05183b2a96c74fd4b3976903c593a61402cab7b3` (RC-6 PR #312 integrated).
- Single feature branch: `feat/model-rc7-institutional-credit-v4`.
- Existing Institutional Credit Decision V3 route, authorization, V3 projection, historical identity, notes and findings are retained. V4 appends optional observational projection and compact template inside the existing workspace. No new route or POST.
- No modifications to financial_engine, finco_core, debt solver, senior sizing, period engine, run persistence, scenario persistence, financial goldens, tolerance, Diagnostics authority, export or deployment.

## Functional authority inventory

| Evidence | Existing V3 persisted authority | V4 |
|---|---|---|
| Senior sizing mode / lender P50-P90 case | Committed V3 capacity where present; working terms only if CURRENT last Run, not saved historically | Reused unchanged; unavailable for historical/stale when not Run-persisted |
| DSCR / gearing sizing capacity; binding constraint | Run financing_evidence.bankability, never inferred when absent | Reused unchanged |
| Facility commitments / construction draws, initial S&U | V3 F1/F3 read-only validated instrument evidence | Reused unchanged, including two-Senior/Junior |
| Maturity, repayment, interest, balance | V3 committed debt_schedule / integrity_evidence.senior_debt.periods | Extra period-evidence completeness screening |
| Min / avg DSCR, solver termination | Committed Run summary + senior_debt diagnostics | OBSERVED screening; solver convergence never treated as feasibility |
| Cash DSRA / DSRF distinction | Run cash balances where persisted; reserve regime only if tied to CURRENT Last Run | Explicit absence of approved historical reserve coverage policy |
| Minimum LLCR | Only persisted value, no alternative discount basis | Existing V3 remains source; PLCR UNAVAILABLE |
| Covenant / advisory / sizing / observed | V3 Model Quality source-classification and persisted thresholds | Separate unavailable-policy register; no made-up default or EoD |
| Run / scenario / engine identity and input hash | V3 Run History owner/project scope + freshness authority | Preserved; no Working Copy comparison masquerading as Run |
| Period date comparison | V3 per-run matrix, V3 cross-Run aggregate comparisons | NEW strict ISO exact-date join for committed DSCR, CFADS, debt service, closing balance, DSRA and distribution |
| Per-period revenue / sponsor returns | Summary aggregates available; precise cross-Run period statement-row identity not proven for V4 | Explicit UNAVAILABLE for V4 per-period differences, not guessed |

## V4 specifically

- Pure projection in `app/v2/credit_v4_evidence.py`: validates period dates and indices, prevents duplicates, rejects invalid or missing vector shape, checks debt service and coverage evidence for serviced periods, and labels missing values UNAVAILABLE.
- One to three authorized committed Runs; exact-date intersection only. Different dates must not be lined up by period index; unmatched periods are explicitly counted. Plain signed differences between persisted values are classified CHANGED/UNCHANGED/UNAVAILABLE, with CHANGED expressly **not** a materiality or causal verdict.
- Risk row per Run: REVIEW_REQUIRED on integrity not proven PASS, missing period evidence, absent min DSCR or an observed DSCR below 1.0x. Otherwise OBSERVED_ONLY_NO_SHORTFALL_IDENTIFIED, intentionally not PASS or contractual compliance.
- For responsive performance at most 90 changed/unavailable cells are rendered; the counts and truncation disclosure preserve the fact that only a subset is shown. Not an authoritative complete downloadable report.
- Existing V3 sections retain committed sizing, capital structure, cash flow, covenants, Source/Uses and historical aggregate comparisons. The new panel does not change original calculations or V3 check classifications.

## Policy decisions deliberately unresolved

1. No source-proven contractual covenant thresholds/dates or Event of Default mechanics for these historical payloads: EoD cannot be inferred from 1.0x coverage or solver convergence.
2. No approved PLCR discount rate and whole-life cash-flow policy, and LLCR stays available only if persisted.
3. Reserve coverage definitions and DSRF standby versus cash DSRA requirements are not persisted as a contractual schedule in every Run.
4. Per-period revenue and sponsor return differences require verified statement row/date identity. V4 leaves them UNAVAILABLE; existing V3 total revenue, sponsor distributions and returns still available where committed.
5. Persist lender-case/sizing mode/reserve-policy input terms with each Run only after separate schema and persistence approval.
6. Current/STALE/ historical Working Copy terms must never be silently copied into historical Runs.

## Test and security plan

- `tests/test_model_credit_decision_v4.py`: numeric and provenance contracts; invalid/missing date, nonfinite values, repeated IDs, no-write input mutation, converged solver with DSCR below 1x, exact-date historical matching.
- `tests/test_model_credit_decision_v4_real_runs.py`: actual Solar/Wind committed Run History, CURRENT→STALE, two committed P50/P90 observations, and GET non-mutation.
- `tests/test_model_credit_decision_v4_render.py`: Jinja2 escaped read-only lender risk panel and optional real Chromium desktop/mobile layout smoke (isolated rendered component; not a substitute for authenticated full-app browser acceptance).
- Mandatory re-run of original Credit Decision V3 synthetic and real lender fixtures: P50/P90, two-Senior, DSRA/DSRF, unavailable LLCR, owner isolation and no POST. Required Public Safety full suite, Governance History, mandatory six-role browser evidence, compilation and dependency scan on exact PR HEAD.

### Evidence limitations

Standalone V4 Python projection smoke: 11 local tests passed before stage 1 push, using synthetic V3-compatible view objects. Full repository-backed pytest, actual committed Solar/Wind and authenticated browser tests were not locally run because a full checkout is unavailable (GitHub DNS cannot be resolved from this execution container). They require exact-head CI. Do not claim merge readiness until required checks, V3 regression and independent review pass.

**NO MAIN MERGE / DEPLOY / SELF-APPROVAL.**
