# FIN-V2-D01 + D02 — Financial Sensitivity Truth: implementation, evidence and limitations

Baseline: `main` after merged PR #389 (FIN-VAL F01), commit `128bf0c2`. Status: **candidate, not self-approved, not merged, not deployed.**
The Financial Owner's explicit approval of the assigned scope is recorded in the task prompt; this document asserts no further owner decision.

## 1. Defect proved (FIN-V2-C1)

| Surface | Before | Evidence |
|---|---|---|
| Legacy `/scenarios/sensitivity`, lender case `interest_stress` | shifted `financing.base_rate` | with an explicit all-in schedule (every reference and F01 working copy) the engine never reads `base_rate`; equity-IRR delta for ±100 bps was exactly `0.0` (Solar, Wind) |
| V2 one-driver `interest_rate` | percent applied to the stored scalar, unit not checked against the typed vector | historical rows could be misinterpreted |
| EV `ppa_price` / `merchant_price` / `availability` | offered | EV adapter is all-merchant with a calendar price schedule and `availability` pinned at 1.0, so the shock changed an unread field (revenue delta `0.0`) and returned a valid-looking result |
| React two-driver matrix | already shocks the typed rate vector | **unchanged and bit-identical** (see §5) |

## 2. Design

* **One shared authority**: `app/services/rate_shock.py` (`senior_all_in_rate_bps_v1`). It reads the effective Senior rate from the typed explicit all-in vector (`senior_rate_authority`), computes `current_percent + bps * 0.01` (the matrix's own arithmetic), and writes through the existing F01 setter `_set_financing_interest_rate` — the **only** %→ratio conversion; this module contains no second conversion.
* **FLAT** schedule: every period moves by the requested bps (5.5 % → 6.5 % / 4.5 %).
* **CALIBRATED / non-uniform / absent** vector: refused `RATE_SHOCK_CALIBRATED_SCHEDULE`; nothing is invented. Bankability-owned rates: `RATE_SHOCK_BANKABILITY_OWNED`. Result outside the 0–20 % human-percent contract: `RATE_SHOCK_OUT_OF_RANGE`. Senior pricing disabled: `RATE_SHOCK_SENIOR_PRICING_DISABLED`. A shock that does not change the effective vector: `RATE_SHOCK_NOT_APPLIED`. Pre-F01 historical rows: the F01 refusal `RATE_UNIT_PROVENANCE_AMBIGUOUS` is surfaced unchanged — **no migration or reinterpretation**.
* **D01-A guard** (`sensitivity_service`, `lender_case_service`): any non-zero shock that leaves the typed inputs unchanged raises `ShockNotApplied` (`SHOCK_NOT_APPLIED`); rows carry `error_code` and, for interest, an auditable `evidence` block (`before_pct`, `after_pct`). `run_lender_case` returns `rate_stress_evidence`.
* **V2 one-driver** (`app/v2/router.py`, `v2_scenario_sensitivity_run`, interest driver only): plans steps from the typed authority; whole-run refusals happen **before any model execution** (zero runs, zero writes); one unrepresentable step (e.g. below 0 %) fails alone; the applied rate is asserted equal to the requested one after `to_projectinputs`.
* **D02**: EV offers `capex, opex, yield, interest_rate, tax_rate`. `ppa_price`, `merchant_price`, `availability` are refused (`SENSITIVITY_DRIVER_UNSUPPORTED`, HTTP 422 on the legacy route). EV `yield` moves stabilised EFLH, the P90-10y hours the adapter pins to it, **and** the derived `Electricity Procurement` OPEX (identity with re-running the adapter on scaled EFLH ≤ 1.8e-15). Inert shocks on other verticals (PPA tariff with no PPA volume, merchant curve overridden by a calendar schedule) are refused (`SHOCK_DRIVER_INACTIVE`). An EV label on non-EV inputs (the legacy resolver's Wind-factory fallback) is refused (`EV_RUNTIME_AUTHORITY_UNAVAILABLE`).
* Unlevered KPIs (project IRR, revenue, EBITDA, CFADS) do not move under a rate shock; `FINANCING_DEPENDENT_KPIS` do. The distinction is encoded and tested.

## 3. Numerical acceptance (independent run on the working tree, `run_sensitivity`, ±100 bps)

| Vertical | Rate | Equity IRR base → shocked | Senior DS total (kEUR) base → shocked | Project IRR |
|---|---|---|---|---|
| Solar | 5.5 → 4.5 % | 45.953 % → 46.522 % | 36 312.5 → 33 996.3 | unchanged |
| Solar | 5.5 → 6.5 % | 45.953 % → 45.272 % | 36 312.5 → 39 649.9 | unchanged |
| Wind | 5.5 → 4.5 % | 68.422 % → 68.805 % | 47 493.5 → 44 589.2 | unchanged |
| Wind | 5.5 → 6.5 % | 68.422 % → 68.073 % | 47 493.5 → 50 885.1 | unchanged |
| Data Center | 6.0 → 5.0 % | −4.883 % → −1.957 % | 78 112.9 → 92 310.7 (see note) | unchanged |
| Data Center | 6.0 → 7.0 % | fails closed `PR8_CLEAN_ENGINE_FAIL_CLOSED` (`SHL_MATURITY_RESIDUAL_FAILS_CLOSED`) | — | — |
| EV Charging | 6.0 → 5.0 % | 37.628 % → 38.516 % | 8 230.5 → 7 863.6 | unchanged |
| EV Charging | 6.0 → 7.0 % | 37.628 % → 37.027 % | 8 230.5 → 8 639.2 | unchanged |

Before the change every one of these rows had equity-IRR delta `0.0`. The Data Center −100 bps debt service rises because debt is DSCR-sculpted: a lower rate raises debt capacity, so total debt service increases with a larger facility; this is the engine's authoritative sizing, not a rate artefact. Data Center +100 bps is refused by the existing Senior/SHL maturity-residual guard of the engine, which this work does not edit — it is reported as a fail-closed row, never a flat result.

## 4. Tests

New: `tests/test_finv2_d01_rate_shock_authority.py` (54), `tests/test_finv2_d01_d02_sensitivity_surfaces.py` (32), `tests/test_finv2_d01_routes_and_matrix.py` (41), `tests/test_finv2_d01_governance.py` (18). One existing test was updated because it encoded the defect (`tests/test_p1_dc_sensitivity_semantics.py`: EV driver set).

Local results (Python 3.12 venv matching CI, per-suite on this candidate; no full CI wave is claimed):

* governance, F01 and CSRF/CAS/protected-reference set (25 files incl. `test_finval_*`, `test_model_mutation_security_successor`, `test_model_react_overnight_b_governance`, `test_rc2/rc3_*`, `test_trust_readiness_*`, all `*csrf*`): **869 passed, 1 skipped** (the skip is pre-existing).
* focused sensitivity/EV/goal-seek/run regression (m3 matrix, DC semantics, rc5 compare, goal seek, decision workspace, p0a, all `test_ev_charging_*`, f39 four-vertical, ci_acceptance, D-029 HTTP, scenario tariff authority, insight q3): **685 passed, 4 failed**; the four were one stale test (fixed, §4) and three `test_ci_acceptance` failures caused by the scratch venv lacking `yaml`; with `pyyaml` installed and the fix, those files are 114/114.
* second regression batch (credit decision v3/v4/v5 real runs, wfa credit/impact, revenue v2/v3, financing f2, api v1.1, post-run context, public reference models, EV and compare browser files): **381 passed, 3 skipped**.

## 5. React matrix bit-identity and unchanged boundaries

* `app/services/sensitivity_matrix.py`, `app/v2/sensitivity_matrix_projection.py`, `app/v2/react_*`, `app/input_adapter.py`, `main_web.py`, the model-execution runtime, `frontend/`, `static/react/`, `.github/`, engines and native kernels are byte-identical to the merge base (asserted in `tests/test_finv2_d01_governance.py` and `tests/test_finv2_d01_routes_and_matrix.py`).
* End-to-end route comparison, baseline worktree (`128bf0c2`) versus candidate: **333 matrix cells and all response statuses identical** across Solar, Wind and Data Center for interest-rate × {CAPEX, gearing, tariff} and CAPEX × OPEX with metrics `equity_irr`, `min_dscr`, `project_irr` (the Data Center interest × tariff pair is 422 in both trees). Raw HTML hashes were also recorded but are not comparable: the pages embed per-project identifiers that the helper did not normalise, so the cell values and statuses are the comparison.
* The shared authority is bit-identical, period by period, to the matrix cell builder and to the Save path (±100/±200 bps, all four verticals).
* Previews never write: DB dumps before/after one-driver previews show no change to scenarios, Last Run or Run History.

## 6. Governance

`app/v2/router.py` is a pinned file. The change is registered as one additive exact-blob layer, `FINV2_D01_SENSITIVITY_SUCCESSORS`, in `tests/model_mutation_security_successor.py`, and as `SUCCESSORS` in `tests/finval_f01_scope.py` (which attributes the router to F01). Every earlier layer remains admitted; any other byte is still refused. `tests/test_finv2_d01_governance.py` proves the layer is exactly one path, that the router diff is confined to the one-driver handler at AST level, and that the operation-bound CSRF gates, the protected-reference guard and the D-029 run order are unchanged.

## 7. Remaining financial limitations

1. Legacy lender-case route can only show a generic "Results unavailable" for a refused stress (`main_web.py` is not editable here); the typed code is in the service result.
2. The legacy resolver falls back to the Wind reference factory for an unresolved project code. EV now fails closed through `assert_ev_runtime_authority`; Solar/Wind/Data Center are not guarded (resolver is in a protected file).
3. Legacy sensitivity table labels basis-point levels with `%` (template/pinned UI; numbers are correct).
4. Lender `yield_haircut` / `availability_stress` are not EV-aware (no vertical context in `apply_lender_adjustments`).
5. Legacy renewable `availability` shock clamps at 1.0 (unchanged); where the clamp leaves the inputs identical the row is now refused (`SHOCK_NOT_APPLIED`) instead of shown flat.
6. V2 one-driver interest sensitivity remains unsupported for EV; Data Center +100 bps is refused by the engine's SHL maturity guard.
7. CALIBRATED / rate-locked schedules are refused; schedule-aware shifting of a contractual vector needs an explicit contractual authority that does not exist yet.

## 8. Integration control

PR #388 (draft, unmerged at the time of writing, base `128bf0c2`) was not modified. It widens two governance tests and adds `RC_M_SUCCESSORS`; expect textual conflicts in `tests/model_mutation_security_successor.py` and the governance tests this change also touches. They are to be reconciled after #388 merges, followed by the full exact-head CI wave. No full CI wave was triggered for this preliminary candidate.
