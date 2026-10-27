# FIN-VAL F01 acceptance matrix

Canonical human percentages: 0.056 → 0.00056, 0.56 → 0.0056, 5.60 → 0.056, 9.00 → 0.09. The independent interest oracle uses Decimal(opening debt) × Decimal(human percent)/100 × actual period days / identified day-count denominator. It also verifies debt service = interest + principal, and persisted presentation sums within their explicit two-decimal rounding bound.

| Vertical | Human % | Seed/Clone/Single+Batch Save/Reload | Canonical HTTP Run | History rows | Direct 20 MW clean input | Full-factory Python/V10/V11 |
|---|---:|---|---|---:|---|---|
| solar | 0.056 | PASS | COMMITTED | 1 | OK | exact FEASIBLE |
| solar | 0.56 | PASS | COMMITTED | 1 | OK | exact FEASIBLE |
| solar | 5.6 | PASS | COMMITTED | 1 | OK | exact FEASIBLE |
| solar | 9.0 | PASS | COMMITTED | 1 | OK | exact FEASIBLE |
| wind | 0.056 | PASS | COMMITTED | 1 | OK | exact FEASIBLE |
| wind | 0.56 | PASS | COMMITTED | 1 | OK | exact FEASIBLE |
| wind | 5.6 | PASS | COMMITTED | 1 | OK | exact FEASIBLE |
| wind | 9.0 | PASS | COMMITTED | 1 | REFUSED | exact FEASIBLE |
| data_center | 0.056 | PASS | FAILED | 0 | REFUSED | exact REJECTED |
| data_center | 0.56 | PASS | COMMITTED | 1 | OK | exact FEASIBLE |
| data_center | 5.6 | PASS | COMMITTED | 1 | OK | exact FEASIBLE |
| data_center | 9.0 | PASS | FAILED | 0 | REFUSED | exact REJECTED |
| ev_charging | 0.056 | PASS | COMMITTED | 1 | OK | exact FEASIBLE |
| ev_charging | 0.56 | PASS | COMMITTED | 1 | OK | exact FEASIBLE |
| ev_charging | 5.6 | PASS | COMMITTED | 1 | OK | exact FEASIBLE |
| ev_charging | 9.0 | PASS | COMMITTED | 1 | OK | exact FEASIBLE |

Machine-readable [matrix](evidence/acceptance-matrix.json); fresh [financial evidence](evidence/financial/), [native evidence](evidence/native/), [browser evidence](evidence/browser/). Untouched factory inputs are separate native `None` cases (four cases); sixteen edited-rate cases do not claim identity with their original economics. Each arm must match the other arms for the same typed inputs, including exact fail-closed outcomes.

The direct 20 MW materialization matrix has three existing clean-engine refusals: Data Center 0.056% fixed sources exceed uses; Wind 9% and Data Center 9% have unsettled SHL maturity residuals. The real HTTP Run pipeline additionally applies its existing persisted CAPEX/OPEX folds. Observed input changes are `capex, opex` for Solar/Wind and `opex` for DC/EV. Its Wind 9% case is feasible, so the actual HTTP matrix has **14 commits and 2 refusals**. The test observes the actual post-fold inputs without replacing execution, verifies the requested typed rate, and applies the independent interest oracle to those same effective inputs. These are distinct inputs; the evidence does not conflate their verdicts or alter financial policy to force agreement. Both HTTP refusals append zero history rows.

Every successful HTTP case persists coherent Debt and Financial Statements alongside the same immutable history snapshot id. Subsequent Save leaves all old history columns byte-identical. Existing keyed/keyless tests cover later Run/replay, D-029 tests cover intent retry/idempotency. Save never Run. Current Chromium proves both 0.056 and 5.60 edit/Save/reload on all four verticals, with displayed percentage, typed ratio and zero Runs created by Save.

Standalone Solar/Wind creation uses the existing `/projects/create` adapter and all four user percentages, checking baseline/draft/saved and typed ratios. Four reference-derived verticals use the canonical clone adapter. Storage is inventoried only; its release fence is unchanged.

Negative coverage: unit missing/unsupported/forged, source provenance ambiguous, no double conversion, finite bounds, metadata relabel/lineage replacement refused, calibrated/non-uniform authority preserved, bankability-owned rate blocked, stale/concurrent CAS, foreign actor/project, protected reference, CSRF and scenario mismatch, interrupted single/batch transaction, repeat Save, immutable reference/bootstrap and prior Run rows. Exact blob and structural CSRF/Run-order negatives remain active. See raw JUnit and exact-head hosted workflow artifacts for counts; do not infer a pass from this inventory alone.

Pre-existing genuinely ambiguous copies are not migrated. Safe read projections expose partial binding with typed remediation; financial materialization/Save fails closed. Create a verified Working Copy or obtain a separately reviewed historical provenance repair.
