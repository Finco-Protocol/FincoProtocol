# Model Quality Q1 — Lender Readiness Evaluation Foundation

**Label on every output: `MODEL QUALITY / LENDER READINESS ADVISORY`.** Not bank approval, not certification, not
verification. A convergent solver result is never treated as lender acceptance.

* Baseline: `main` `e84ffa65fa785af826642178854aafb4e0d5691c`. Branch `feat/model-quality-q1`. One Draft PR, no merge.
* Production code: `app/model_quality/` only (read-only, no route, no template, no engine call, no persistence).
* Zero diff: `finco_core/`, `financial_engine/`, `app/v2/`, `app/workbook/`, `app/templates/`, `static/`, `main_web.py`
  (so no overlap with F3.1 or the Q2 smart-panel files).
* **Research package:** `FINCO_REA_RESEARCH_PACKAGE_2026-10-10.zip` was **not available in this environment**, so none of its
  findings files were read and nothing was copied. The check design below comes from FINCO's own persisted evidence and the
  brief's description (31 validator groups / ~112 checks). The mapping in §6 is therefore at category level only.

## 1. Architecture

| Module | Responsibility |
|---|---|
| `contracts.py` | `QualityCheck` (strict, finite-validated), enums, `ScoreSummary`, `QualityReport`, deterministic JSON |
| `evidence.py` | `QualityEvidence` (persisted Last Run view), `ProjectTerms` (optional typed thresholds), builders |
| `evaluators.py` | one function per check; each returns an `Outcome`; reuses the Run Integrity report |
| `registry.py` | 30 stable `CheckDefinition`s + `run_registry` (malformed evidence → UNAVAILABLE, never PASS) |
| `scoring.py` | coverage-aware advisory score, blocking rule, ranking |
| `projection.py` | `evaluate_model_quality`, `evaluate_workspace`, `project_quality_report` (compact panel view) |

Integration seam for Q2: `evaluate_workspace(ws, current_composite_hash=…, terms=…)` or
`evaluate_model_quality(QualityEvidence(...))`, then `project_quality_report(report)`.

## 2. Check catalogue (30)

Class: **M** mathematical integrity · **C** contractual covenant (supplied threshold) · **A** advisory risk · **E** evidence availability.
"Real run" = status on the four unmodified reference verticals (Solar, Wind, Data Center, EV), terms read from the effective typed inputs.

| ID | Cat | Class | Sev | Check | Source / threshold authority | Real run |
|---|---|---|---|---|---|---|
| QM-ACC-001 | Accounting | M | CRIT | Balance sheet balances | Run Integrity `BALANCE_SHEET_BALANCES` (1e-6 kEUR) | PASS |
| QM-ACC-002 | Accounting | M | HIGH | Sponsor return flows reconcile | Run Integrity (XIRR 1e-9) | PASS |
| QM-ACC-003 | Accounting | M | HIGH | EBITDA = revenue − OPEX | persisted aggregates, 1e-6 kEUR | PASS |
| QM-ACC-004 | Accounting | E | MED | Return metrics published (0.0 ≠ missing) | none | PASS |
| QM-SU-001 | S&U | M | CRIT | Sources equal Uses (developer uses itemised) | Run Integrity | PASS |
| QM-SU-002 | S&U | M | HIGH | Construction funding reconciles | run-bound `financing_evidence`, 1e-6 kEUR | PASS |
| QM-SU-003 | S&U | E | LOW | Developer uses itemised | none | N/A (actual zero) |
| QM-SD-001 | Senior | M | CRIT | Senior roll-forward | Run Integrity | PASS |
| QM-SD-002 | Senior | M | HIGH | Interest and debt service consistent | Run Integrity | PASS |
| QM-SD-003 | Senior | M | HIGH | DSCR = CFADS / debt service | Run Integrity | PASS |
| QM-SD-004 | Senior | M | HIGH | Sculpted DS fits allowed DS | Run Integrity | PASS |
| QM-SD-005 | Senior | M | HIGH | Solver authoritative (not lender approval) | diagnostics | PASS |
| QM-SD-006 | Senior | M | MED | Actual gearing ≤ requested cap (actual, never requested) | `gearing_cap_pct` | PASS |
| QM-SD-007 | Senior | A | HIGH | Min DSCR: FAIL < 1.0×, WARN < effective sizing target | arithmetic + sizing target (a model assumption) | PASS |
| QM-CASH-001 | Cash | M | HIGH | No unfunded cash deficit | Run Integrity | PASS |
| QM-CASH-002 | Cash | C | HIGH | DSRA funded to proven target | typed fixed requirement only | **UNAVAILABLE** (dynamic target not persisted) |
| QM-COV-001 | Covenants | C | HIGH | Minimum-DSCR covenant | supplied term only | **UNAVAILABLE** (not supplied) |
| QM-COV-002 | Covenants | C | MED | Lock-up DSCR | `financing.lockup_dscr` (PROJECT_INPUT) | PASS |
| QM-COV-003 | Covenants | C | HIGH | Min LLCR requirement | `financing.min_llcr` | **UNAVAILABLE** (LLCR not persisted by the Run) |
| QM-COV-004 | Covenants | C | MED | Covenant ordering | supplied terms + sizing target | PASS |
| QM-CAP-001 | CAPEX | A | MED | Contingency adequacy vs documented policy | supplied policy only | **UNAVAILABLE** |
| QM-REV-001 | Revenue | E | MED | Revenue evidence complete | none | PASS |
| QM-REV-002 | Revenue | M | HIGH | Period revenue sums to total | 1e-6 kEUR | PASS |
| QM-TERM-001 | Terminal | M | CRIT | Senior fully settled at maturity (PR #233 protection) | solver precision 1e-4 kEUR | PASS |
| QM-TERM-002 | Terminal | M | HIGH | SHL settled at contractual maturity (Correction A) | canonical terminal state + committed balance sheet; SHL precision 1e-7 kEUR | PASS (maturity 52 / 57 / 43 / 41) |
| QM-PRV-001 | Provenance | M | HIGH | Evidence digest intact | Run Integrity | PASS |
| QM-PRV-002 | Provenance | E | HIGH | Run identity complete | none | PASS |
| QM-PRV-003 | Provenance | E | MED | Last Run CURRENT (STALE → WARNING) | canonical freshness | PASS |
| QM-PRV-004 | Provenance | E | MED | Financing evidence bound to this Run | `run_binding` | PASS |
| QM-PRV-005 | Provenance | E | LOW | Scenario identity | workspace | PASS |

Real-run totals (all four verticals identical): **registered 30, applicable 29, evaluated 25 (PASS 25), NOT_APPLICABLE 1,
UNAVAILABLE 4**, weighted coverage 87.6%, score 100.0 published — shown together with the coverage and the four gaps.

**Threshold authority.** Thresholds come only from arithmetic identities, the canonical solver precision, or terms the project
supplied. `lockup_dscr` and `min_llcr` are read from the effective typed inputs and labelled `PROJECT_INPUT`: FINCO cannot tell a
defaulted value from a negotiated one, so they are *not* called lender covenants unless the caller sets `contractual=True`.
No FinModels default (1.20× / 1.50×) is used as a standard. The sizing target is a model assumption and is labelled so.

## 3. Reuse, not duplication

Nine identities already proven by `app/run_integrity` (balance sheet, S&U, roll-forward, interest/service, DSCR identity, cash
deficit, sculpting feasibility, sponsor reconciliation, evidence digest) are consumed through the existing report. New arithmetic
exists only where Run Integrity has no check: EBITDA identity, revenue period sum, gearing cap, minimum DSCR, covenants, reserve
funding, terminal balance, identity, binding and freshness. Debt sizing, statements and IRRs are never recomputed.

## 4. Scoring methodology (all tested)

* **Applicable** = not NOT_APPLICABLE. **Evaluated** = applicable with PASS/WARNING/FAIL. **Eligible denominator** = severity
  weights of the evaluated checks. Weights CRITICAL 8 · HIGH 4 · MEDIUM 2 · LOW 1.
* **Credit:** PASS 1.0 · WARNING 0.5 · FAIL 0.0. UNAVAILABLE and NOT_APPLICABLE earn no credit and are not penalised as fails;
  UNAVAILABLE lowers *coverage*.
* **Coverage** = evaluated / applicable (count and severity-weighted). A numeric score is **published only at weighted coverage
  ≥ 80%**; otherwise `score = None` (`UNAVAILABLE_INSUFFICIENT_EVIDENCE`), never an invented 0. No Last Run → `UNAVAILABLE_NO_RUN`.
* **Blocking:** any FAIL of a MATHEMATICAL_INTEGRITY check or of a CRITICAL check. It is reported even when the score is
  unavailable; a published score is capped at 50 so many low-risk passes cannot offset it. Readiness label reads `BLOCKED …`.
* **Sorting:** top issues by (severity weight ↓, FAIL before WARNING, id); evidence gaps by (severity weight ↓, id).
* **STALE:** a stale Working Copy keeps the prior Run evaluable but the report states `score_is_current = false`.
* **Determinism / validity:** stable ids, registry order, finite-validated numbers, strict JSON (`allow_nan=False`), sorted keys.

## 5. Evidence for the required cases

`tests/test_model_quality_q1.py` (82 tests, incl. the 15-case SHL maturity matrix A–O): four real verticals; unbalanced S&U; wrong Senior roll-forward; DSCR covenant breach
(and pass); DSRA underfunding with a proven target; missing DSRA authority; terminal balloon (synthetic detection) plus the real
PR #233 rejection of the original P0 configuration (no Run ⇒ nothing to score); missing identity; corrupt digest; stale Working Copy;
legacy Run without evidence (score unavailable, no PASS from missing data); missing covenant targets; actual zero vs missing
(IRR 0.0, DSCR 0.0, developer uses, terminal balance); developer reimbursement/fee run; scoring unit tests; contracts; no engine
execution, no mutation, no engine/persistence/web imports, no route.

## 6. REA research mapping (category level; package unavailable)

| FinModels validator family (per brief) | FINCO Q1 coverage |
|---|---|
| Accounting / balance sheet | QM-ACC-001..003 |
| Sources & Uses, construction funding | QM-SU-001..003 |
| Debt sizing, DSCR, amortisation | QM-SD-001..007 |
| Liquidity, DSRA | QM-CASH-001..002 |
| Covenants, lock-up, LLCR | QM-COV-001..004 (supplied terms only) |
| CAPEX / contingency | QM-CAP-001 |
| Revenue evidence | QM-REV-001..002 |
| Terminal / refinancing | QM-TERM-001..002 |
| Provenance / freshness | QM-PRV-001..005 |

Not implemented (no canonical evidence today): tax-specific, working-capital, PLCR, equity-bridge, sensitivity-based and
market-benchmark validators.

## 6a. Correction A — SHL maturity evidence authority (QM-TERM-002)

**Defect (independent review, reproduced):** the original check passed whenever no sponsor return status equalled
`UNPAID_SHL_AT_CONTRACTUAL_MATURITY`. With 9,000 kEUR of SHL left on the balance sheet at and after maturity and an unrelated
status (`NO_POSITIVE_CASHFLOW`) it still reported PASS ("no unpaid shareholder-loan balloon"). A return-metric status is not
repayment evidence.

**Maturity authority (traced, not assumed).** The canonical `ShlTerminalState` is serialised by the production presentation
adapter into `sponsor_schedule.summary.terminal_financial_state.shareholder_loan`
(`contractual_maturity_period_index`, `balance_at_contractual_maturity_keur`, `unpaid_at_maturity_keur`, `status`).
`v2_atomic_run_commit` persists that `sponsor_schedule` in the same transaction as the runtime summary, integrity evidence,
snapshot id and composite hash, and Run History appends the identical sponsor schedule. The check therefore reads the
**committed** terminal state (`ws.last_sponsor_schedule["summary"]`), never the editable Working Copy or the last visible period;
a test proves the V2 Run persists it and Run History holds the same value. The immutable `last_runtime_snapshot` is not needed
and is not read. Limitation: the sponsor schedule is bound to the Run by the atomic commit, not by the integrity-evidence digest.

**Liability evidence.** `integrity_evidence.balance_sheet[].shl` (digest-bound), looked up by `period_index` at the proven maturity.

| Status | Condition (all must hold for PASS) |
|---|---|
| PASS | maturity is a plain non-negative int within the evidenced axis; the SHL balance at maturity and every later period is present, finite and <= 1e-7 kEUR; the canonical terminal balance at maturity equals the balance sheet; no unpaid signal |
| FAIL `UNPAID_SHL_AT_CONTRACTUAL_MATURITY` | balance at maturity > 1e-7 kEUR, or SHL liability reappears after maturity, or the canonical terminal state / bullet flag / return status reports unpaid |
| NOT_APPLICABLE | only when the canonical terminal state is `NOT_APPLICABLE` and the committed evidence contains no SHL; a zero last balance alone never qualifies |
| UNAVAILABLE | terminal state absent; maturity missing/non-int/negative; balance sheet missing, malformed, duplicated or non-finite; maturity beyond the horizon or its row missing; terminal vs balance-sheet inconsistency |

Precision is the SHL terminal-state classifier's own `1e-7` kEUR (`financial_engine.project_returns.model._TOL`, pinned by a
parity test), not the Senior solver tolerance. Return statuses are corroboration only (an unpaid status can fail the check; absence
proves nothing). No engine, rule or tolerance was changed.

**Reference Runs (unchanged result, now earned):** QM-TERM-002 PASS with maturity period 52 (Solar), 57 (Wind), 43 (Data Center),
41 (EV), each with an SHL balance of exactly 0.0 at maturity. Scoring is unchanged: 25 PASS, 1 NOT_APPLICABLE, 4 UNAVAILABLE,
weighted coverage 87.6%, advisory score 100.0 over the evaluated checks only.

## 7. Confirmed financial findings

None new from Q1. The evaluator surfaces, without hiding, the already-known open items: the DSRF accounting imbalance (appears as a
QM-ACC-001 blocking FAIL on a DSRF Run if still present) and Wind numerical DSCR-feasibility residuals (QM-SD-004).

## 8. Remaining Q2 / Q3 integration

Q2: surface `project_quality_report` in the Smart Panel (new route or panel section), pass `ProjectTerms` from the effective typed
inputs, link `navigation_target` to the workbook tabs. Q3: persist `ProjectTerms` with the Run (LLCR requirement, DSRA target,
documented contingency policy, contractual covenant set) so currently UNAVAILABLE checks become evaluable; publish LLCR/PLCR.
