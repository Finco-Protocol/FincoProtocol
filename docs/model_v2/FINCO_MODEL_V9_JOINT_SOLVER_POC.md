# FINCO Model V9-A — Joint Fixed-Point Solver: isolated prototype and performance decision

**Mode**: isolated numerical research with an executable proof of concept.

What was not done:

* No production code, governance pin, numerical tolerance or golden fixture was modified.
* No PR, merge, deploy, self-approval, rebase, squash or force push was made in the production repository.
* V8-B2 CFADS seeding is not revived; no candidate seeds CFADS.

**Final disposition: `V9 JOINT SOLVER POC COMPLETE — PRECISION AUTHORITY REQUIRED`**

## 1. Executive summary

* **Five nested fixed points.** A production Run (`run_clean_production`) solves five nested fixed points:
  * L1: DSRA initial funding.
  * L2: PR9 construction IDC.
  * L3: G2A SHL↔Senior.
  * L4: SHL↔tax↔Senior.
  * L5: Senior sizing.

  Each inner level is re-solved to full tolerance at every outer iterate. The measured couplings are weak or linear:
  * The DSRA target does not depend on the reserve at all (∂T/∂F = 0).
  * The IDC loop contracts linearly with ρ = 0.010–0.045.
  * The G2A map is constant when gearing binds.

  Most of the work therefore only confirms values that are already known.
* **B1 — capacity-pass deferral (GO).** The G2A DSCR-only capacity run is executed once at the converged candidate instead of in every iteration.
  * Bit-identical in 31/31 feasible cases and 18/18 fail-closed cases.
  * 3–40 % faster.
* **C — joint reduced solver (CONDITIONAL GO).** One safeguarded Anderson fixed point over (DSRA funding, five capitalised financing costs) replaces the DSRA policy loop of complete engine runs. The canonical final verifications and the policy acceptance test are kept, with a canonical fallback.
  * Combined with B1 and a warm-started SHL↔tax loop (bundle **C+B1+BW**), it saves **45–86 %** of median Run time on every feasible case measured.
  * Typical gearing-bound project: 2.9 s → 1.0 s.
  * DSCR-bound stress cases: 30 s → 4.4 s.
  * No categorical change anywhere.
  * Not bit-identical: differences are ≤ 1e-8 kEUR in most cases and up to 6.3e-7 kEUR in one case (the DSRA tolerance band).
* **Rejected candidates (NO GO).**
  * **D** (analytic G2A seed) turns 3 baseline fail-closed Runs into feasible results.
  * **BG** (G2A secant) moves SHL lines by up to 1.85e-7 kEUR, above the 1e-7 strict-re-solve / REPAID scale.
  * Full Newton/Broyden is not justified.
* **Why the disposition is "precision authority required".** No existing authority says when two results computed along different iteration paths are the same result. That decision (OD-1) is required before C can be production-designed. B1 can proceed independently.

### Typical Run versus stress cases

| Project | Baseline Run | B1 | C+B1+BW |
|---|---:|---:|---:|
| Default Solar 50 MW (gearing-bound) — the usual 3 s Run | 2.87 s | 2.77 s (−3 %) | 1.02 s (−65 %) |
| Solar 16 MW, gearing-bound | 2.81 s | 2.46 s (−12 %) | 0.91 s (−67 %) |
| Data Center 20 MW | 1.28 s | 1.08 s (−16 %) | 0.40 s (−69 %) |
| Wind 25 MW (DSCR-bound) | 10.0 s | 8.3 s (−17 %) | 2.19 s (−78 %) |
| Solar 16 MW (DSCR-bound stress case) | 30.0 s | 23.6 s (−22 %) | 4.35 s (−86 %) |

The 10–40 s Runs are DSCR-bound projects, where the G2A loop needs 9–10 iterations instead of 2. They are reachable by ordinary inputs, such as a smaller plant or a higher target DSCR.


## 2. Preflight

| Item | State verified (2026-10-19) |
|---|---|
| `main` | `5be8c4b149` — "Merge PR #313: isolated quarterly research candidate (release-closed)". Read-only worktree used for all measurements; `git status` clean before and after. |
| PR #320 | Open, Draft, `integrate/model-rc7b-quarterly-production-v1` @ `b8b9b392d5`. Touches `financing/project.py` (+7 lines: quarterly scope gate at the top of `run_project_financing_model`), `orchestrator.py` (quarterly period engine), `quarterly_scope.py`, `period_engine.py`, `calendar_policy.py`. Used only as an **isolated worktree** for the quarterly 3/3 runs. |
| PR #321 | Open, Draft, `feat/model-v8a-run-overhead` @ `f4ff18cd66`. No change under `financial_engine/`, `finco_core/` or `app/services/` — no interaction with the solver levels studied here. |
| PR #322 | Open, Draft, `feat/model-v8b1-solver-efficiency` @ `a00cf1f599`. Only `financial_engine/senior_debt/solver.py` (bit-identical efficiency work inside the Senior solver, L5). Governance-blocked. Orthogonal to every V9 candidate (V9 changes the number of L5 calls, #322 the cost of one call); the two compose. |
| V8 Independent Architectural Audit | **Not found** in the repository (main or the three PR branches). Not used as a source. |
| V8-B2 Financial Decision Pack | **Not found** in the repository. The only V8-B2 fact available is the instruction that CFADS seeding is NO GO; no V9 candidate seeds CFADS. |
| Performance evidence | `docs/model_v2/PERFORMANCE_V8B1_SOLVER_EFFICIENCY.md` (#322): `run_clean_production` cold medians Solar 1.866 s → 1.778 s, Wind 2.273 s → 2.268 s; finalisation reuse rejected as not bit-identical (DSCR vs COMBINED fixed points differ by up to 1.8e-6 kEUR). |
| PR9 construction-IDC contracts | Read in code: `_run_with_construction_idc` (`financing/project.py:361-935`) — neutral seed, eight-component outer residual, strict final Stage B2, idempotence ≤ 10 × tolerance, unfunded ≤ tolerance. |
| G2A funding / service-budget authority | `run_project_financing_model` (`financing/project.py:936-1517`): `G2A_SERVICE_BUDGET_ACCEPTANCE_TOLERANCE_KEUR = 1e-6`, strict re-solve at `min(policy, 1e-7)` with relative 0, gearing handshake 1e-7, Senior = min(DSCR, gearing) ± 1e-7, SHL fixed point ≤ 1e-7. |
| Senior solver authority | `SeniorDebtPolicy.convergence_tolerance_keur = 1e-4`, `convergence_relative_tolerance = 1e-9` (`solve_senior_debt`, `senior_debt/solver.py:822`). |
| Terminal repayment authority | `project_returns/model.py:42` `_TOL = 1e-7`: Senior `REPAID` iff balance at contractual maturity ≤ 1e-7; SHL `REPAID` iff horizon balance ≤ 1e-7, `UNPAID_AT_CONTRACTUAL_MATURITY` iff maturity balance > 1e-7. |

## 3. The coupled numerical system

### 3.1 Dependency diagram (as executed by `run_clean_production` on `main`)

```
run_clean_production ─ classify ─ scenario ─ engine_run_scope
│
└─ L1  DSRA initial-funding policy           generic_product_policy.py:238
   │   seed  F0 = m·peakDS( engine(plain inputs, no construction financing, no DSRA) )
   │   loop  F_k → apply_generic_financing_policy(F_k) → ENGINE → T(F_k) = m·max_{t≥2} DS_t
   │         stop |T(F_k) − F_k| ≤ 1e-6 kEUR            (m = dsra_months · 2 / 12)
   │
   └─ ENGINE = L0 shareholder waterfall (U2 reserve-income loop; one pass when no reserve income)
      └─ L2  PR9 construction IDC outer loop     financing/project.py:562
         │   state x = (Senior IDC, commitment fee, structuring fee, VAT IDC, VAT fee)
         │   seed  G2A at x = 0 (neutral seed, construction gate off)
         │   x_{k+1} = StageB2prov( G2A( Uses(capex ⊕ x_k, F) ) )
         │   stop  max(Δx, ΔSenior, ΔSHL, ΔPIK, ΔUses, ΔUnfunded) ≤ 1e-7
         │   then  unfunded ≤ 1e-7; strict StageB2 + full G2A re-run; idempotence ≤ 1e-6
         │
         └─ L3  G2A SHL ↔ Senior fixed point     financing/project.py:1059
            │   state s = SHL cash principal (scalar)
            │   per iteration: DSCR-only capacity run (diagnostic) + funded run
            │                  (+ strict re-solve when service-budget excess > 1e-6)
            │   s_{k+1} = Uses − Senior(s_k) − fixed equity − junior   (reconcile_financing_stack)
            │   stop |s_{k+1} − s_k| ≤ 1e-7; gearing handshake 1e-7; Senior = min(DSCR, gearing) ± 1e-7
            │
            └─ L4  SHL ↔ tax ↔ Senior fixed point     orchestrator.py:1932
               │   state i = SHL gross-interest vector (+ interest-limitation states, Base and Bank)
               │   i_{k+1} = SHL( CFADS_Base( tax( i_k, SeniorInterest(i_k) ) ) )
               │   stop closing / interest / retained Δ ≤ 1e-6 abs (1e-9 rel), ratio Δ ≤ 1e-9, gate mismatch 0
               │   then final recomputation with the converged interest
               │
               └─ L5  Senior sizing / sculpting     senior_debt/solver.py:822
                      unknown D (debt size) and the sculpted schedule; callback tax_cfads_fn(senior interest)
                      stop 1e-4 kEUR / 1e-9 rel; _finalise_authoritative
```

### 3.2 Unknowns, derived variables and residuals

| Level | Unknown (iterated) | Derived (eliminated inside the level) | Residual / acceptance | Authority |
|---|---|---|---|---|
| L1 | F — initial DSRA funding (scalar, a Project Use) | Total Project Uses, every downstream quantity | \|T(F) − F\| | 1e-6 kEUR (`dsra_tolerance_keur`) |
| L2 | x ∈ R⁵ capitalised financing costs | Uses = hard CAPEX + x + F + fees; Stage B2 allocations and draws | 8-component max Δ | 1e-7; idempotence 1e-6; unfunded 1e-7 |
| L3 | s — SHL principal | additional equity, construction PIK, draw schedule | \|s′ − s\| | 1e-7; service budget 1e-6 / strict 1e-7 |
| L4 | i ∈ R^T SHL interest (+ limitation states) | Base/Bank tax, CFADS, SHL schedule | max vector Δ | 1e-6 abs / 1e-9 rel |
| L5 | D, sculpted debt service | Senior interest, principal, DSCR | debt-size change | 1e-4 kEUR / 1e-9 rel |

### 3.3 Binding constraints and discontinuities

* **Senior = min(DSCR capacity, gearing capacity)** — a kink. Which branch binds changes the whole L3 Jacobian: gearing-bound Senior is `gearing × Uses` and independent of s; DSCR-bound Senior depends on s through the SHL interest tax shield.
* **DSRA target = max over periods** (`max(due[1:])`) — non-smooth when the peak period switches.
* **Service-budget acceptance (1e-6)** — a discrete trigger for a strict re-solve; it fires on every G2A iteration in the DSCR-bound reference cases measured.
* **SHL maturity residual (fail-closed)** — evaluated inside L4 on **every** iterate, including non-converged intermediate ones (see §7.3).
* **Interest-limitation gates** (mismatch count must be 0) and the terminal classifications at 1e-7.

### 3.4 Measured dependencies (from instrumented baseline trajectories)

| Coupling | Measured | Consequence |
|---|---|---|
| ∂T/∂F (L1) | **0** to the last bit (Solar 50 MW, Wind 25 MW, DC: target identical in consecutive iterations) | F converges in one step once the debt service is settled; the L1 loop is a pure "re-run everything to confirm" cost. |
| L2 contraction ρ | linear, ρ ≈ 0.010 (Solar 50, gearing-bound), 0.021 (Solar 16, DSCR-bound), 0.025 (DC), 0.045 (Wind 25) — constant over 5-10 iterations | 6-10 outer iterations from the neutral seed; textbook case for multisecant (Anderson) extrapolation. |
| L3 map ∂s′/∂s | 0 when gearing binds or when DSCR capacity does not respond to SHL (Wind 25 typed path); ≈ −0.043, oscillating, when DSCR-bound with SHL tax shield (Solar 16) | 2-3 G2A iterations, or 9-10 in the DSCR-bound case. |
| L4 contraction | 1/20 … 1/60 per iteration, superlinear tail; 6-9 iterations from the zero seed | dominated by distance of the zero seed, not by the rate. |
| Cost share | L4 fixed points (each 6-9 L5 solves with 3-20 tax/CFADS evaluations) are 70-85 % of wall time | every avoided L3/L4 evaluation is the lever. |

Baseline evaluation counts are in §6.3. In the slowest reference case (Solar 16 MW, DSCR-bound, ~30 s) one Run performs 3 engine runs, 2 complete IDC loops, 21 G2A solves (9-10 iterations each), 465 Senior model runs, 408 SHL↔tax fixed points, 2 879 Senior solves and 17 175 tax/CFADS evaluations.

### 3.5 Eliminable variables and over-tight intermediate solves

* **Eliminable**: SHL principal, additional equity and Total Project Uses are Sources-and-Uses identities given Senior (`reconcile_financing_stack`); the reduced outer state is therefore **x = (F, five capitalised costs) ∈ R⁶**, and its effective rank is about 2 (F, and the Senior-driven cost direction).
* **Over-tight intermediate solves**: every inner level is solved to its full authority tolerance at every outer iterate, even when the outer residual is still kEUR-sized: the entire first L1 iteration (a full IDC loop to 1e-7) is computed only to learn that the DSRA target does not move; the plain seed run of L1 is a full engine run whose only output is one scalar; L3 is solved to 1e-7 while L2 is still moving by 7 kEUR.
* **Inexact inner solves** (looser L3/L4/L5 tolerances at non-final outer iterates) were **not prototyped**: they would change how the independent precision authorities are applied, which this task forbids.

### 3.6 Mandatory final verifications (retained by every candidate)

L5 `_finalise_authoritative`; L4 final recomputation, gate mismatch 0 and SHL maturity residual; L3 SHL fixed point ≤ 1e-7, Senior/capacity handshake ≤ 1e-7, gearing handshake ≤ 1e-7, service budget ≤ 1e-6 (strict re-solve ≤ 1e-7); L2 unfunded ≤ 1e-7, strict Stage B2 and full G2A idempotence ≤ 1e-6; L1 \|T(F) − F\| ≤ 1e-6 evaluated **on the returned result**; waterfall, statements and terminal classifications unchanged. No candidate removes, loosens, rounds or clamps any of them.


## 4. Candidates and algorithms

All candidates keep every financial calculation inside the canonical functions
(`run_stage_b2_provisional`, `run_stage_b2`, `apply_capitalized_financing_costs`,
`run_project_financing_model`, `run_senior_debt_model`, `solve_senior_debt`,
tax/CFADS, SHL schedules, `reconcile_financing_stack`, the policy's own
`_peak_forward_debt_service_keur`). They change only **which iterate** is passed to
those functions and **how many times** they are evaluated. No candidate is a second
financial engine.

| Id | Family | Level | What changes | What is kept |
|---|---|---|---|---|
| **A** | baseline | — | nothing (canonical `run_clean_production`) | — |
| **B1** | B — structural (nested) | L3 | The DSCR-only capacity run is evaluated **once, at the converged SHL candidate**, instead of in every G2A iteration. Its value was already used only after the loop (`project.py:1495`); inside the loop the expected Senior is overwritten from the funded diagnostics. | identical funded runs, checks and result; the capacity run still executes and still fails closed |
| **BA** | B — accelerated nested | L2 | Safeguarded Anderson(m = 2) on the five capitalised costs; plain Picard step whenever the residual does not fall by ≥ 50 %, a proposal is negative/non-finite, or the residual is below 1e-4 (terminal Picard phase). Convergence is accepted **only after a plain step** that meets the canonical 8-component residual. | neutral seed, Stage B2, strict final verification and idempotence check verbatim |
| **BW** | B — accelerated nested | L4 | SHL↔tax fixed point starts from the previous converged SHL interest vector of the same Run (memory discarded per Run) via the existing `_test_only_initial_shl_interest_guess` entry. | all L4 convergence tests and the final recomputation |
| **BG** | B — accelerated nested | L3 | Safeguarded secant (scalar Aitken/Broyden) on the SHL candidate: used only when the secant slope certifies \|ρ\| < 0.9, the residual decreased, and the step stays within 10 × the plain step; otherwise the plain update. | break test `|s′ − s| ≤ 1e-7` and all G2A handshakes |
| **C** | C — joint reduced | L1 + L2 | One fixed point over **x = (F, five costs) ∈ R⁶** with safeguarded Anderson: the DSRA funding is updated inside the construction loop from the current inner result, using the policy's own target function; the plain seed engine run and the second complete IDC loop disappear. The financing result is then handed once to the canonical waterfall/statements, and the policy's acceptance test \|T(F) − F\| ≤ 1e-6 is re-evaluated on the returned result (fallback: the canonical policy loop). Run as `C+B1`. | canonical tail of `_run_with_construction_idc` (strict Stage B2, idempotence, ConstructionFinancingResult), canonical waterfall, statements, returns |
| **D** | D — analytic reduction | L3 | SHL candidate seeded from the Sources & Uses identity with the Senior predicted from the previous G2A evaluation of the same Run (exact when the binding constraint and its value are unchanged). The canonical loop then confirms or continues. | every G2A test |
| — | D — Newton / Broyden | L1-L3 | **Not justified.** The outer state is small (R⁶) and nearly rank-2, the maps are linear contractions (ρ ≤ 0.045), and a Jacobian costs one full G2A evaluation per column: a single Newton step would cost ≥ 6 evaluations, more than Anderson needs to converge. Anderson is the multisecant (Broyden type-II) member of the family and the scalar secant (BG) is 1-D Broyden. | — |

Combined candidates measured: `B = B1+BA+BW+BG` (all nested accelerations),
`C = C+B1`, `FULL = C+B1+D+BW+BG`, `FULLnoD = C+B1+BW+BG`.

### 4.1 Prototype location and isolation

* Scratch prototypes: `v9_scratch/` next to this report (copied from the session
  scratchpad). `v9proto.py` builds each candidate at runtime from the canonical source
  text (`inspect.getsource`) with **asserted, exact** text substitutions, compiles it into
  a *copy* of the defining module's namespace and rebinds module attributes only inside a
  context manager; leaving the context restores the canonical functions.
* Self-test of the mechanism: the replica of the canonical IDC loop with no acceleration
  (`R`) reproduces the canonical result **bit-for-bit** (9 785 / 9 785 floats Solar 50 MW,
  12 602 / 12 602 Wind 25 MW).
* Production worktree `git status` is clean after all runs; no file under the production
  repository was written.


## 5. Methodology

* **Inputs**: synthetic only, built from the repository factories. Solar 16 MW and Wind 25 MW are on the 6/6 semiannual axis. The 16 MW solar CAPEX is scaled to the plant size (×0.26; ×0.18 for the high-DSCR/low-gearing variants that are otherwise infeasible), and the 25 MW wind CAPEX is ×0.7 for those variants. Data Center uses the 20 MW default. The variants cover DSCR 1.20/1.45/2.0/3.0, gearing-bound and DSCR-bound cases, DSRA 0/6/12 months, the construction-financing and DSRA policies switched off, SHL sizes, tenors 10/12/15/18, zero, near-zero and infeasible financing, tax losses (OPEX ×1.8) and positive tax, a 29 February 2028 close, and COD stubs of 9 and 15 months. Total: 49 cases, of which 31 are feasible and 18 fail closed in the baseline.
* **Quarterly 3/3**: run only in isolated environments — the research calculation on `main` (`tools/quarterly_research`), and a separate worktree of the PR #320 head using the test composition `canonical_run`. These runs never use production admission.
* **Parity**: every Run (`CleanProductionRun`: G2C, financing, S&U, schedules, tax/CFADS, waterfall, statements, returns, terminal states, integrity evidence) is flattened into roughly 13 000–22 000 leaves. Floats are compared bit for bit, and `max abs`/`max rel` is reported per field family. Any differing non-float leaf counts as categorical; solver bookkeeping (iteration counts, residuals, fingerprints) is listed separately. For fail-closed cases the exception type, reason code and numeric evidence are compared.
* **Timing**: genuine uncached Runs. The policy-run cache and the tax-year LRU are cleared before every Run, and each Run gets a fresh run scope. Candidates are interleaved, 5 repetitions on a quiet CPU (no other process), and the median and p95 are reported.

## 6. Results

### 6.1 Parity matrix

The table uses the following tags:

* **BIT**: every float is bit-identical.
* A number (e.g. `8e-09`): the maximum absolute difference in kEUR, with no categorical change.
* **FAIL=**: the candidate fails closed with an identical exception, including its numeric evidence.
* **FAIL~**: same reason code, but different numeric evidence.
* **FLIP**: feasibility changed.

Timings in this table are single-shot and were measured with several workers running in parallel; only §6.4 timings are authoritative.

| Case | Baseline | Outcome | B1 | BA | BW | BG | B | D | C | CBW | FULLnoD | FULL |
|---|---:|---|---|---|---|---|---|---|---|---|---|---|
| S16 | 29.89 s | DSCR | BIT | 2e-09 | 4e-11 | 7e-08 | 7e-08 | 7e-08 | 8e-10 | 8e-10 | 7e-08 | 7e-08 |
| S50 | 3.46 s | GEARING | BIT | 2e-09 | 1e-08 | BIT | 1e-08 | BIT | 2e-09 | 1e-08 | 1e-08 | 1e-08 |
| S16-dscr3.0 | 0.25 s | fail-closed | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= |
| W25-dscr3.0 | 0.42 s | fail-closed | FAIL= | FAIL= | FAIL~ | FAIL= | FAIL~ | FLIP | FAIL= | FAIL= | FAIL= | FLIP |
| W25-gear0.50 | 0.14 s | fail-closed | FAIL= | FAIL= | FAIL= | FAIL= | FAIL~ | FAIL= | FAIL= | FAIL= | FAIL= | FAIL~ |
| S16-dsra12 | 23.91 s | DSCR | BIT | 7e-10 | 8e-10 | 2e-08 | 2e-08 | 1e-08 | 7e-10 | 9e-10 | 2e-08 | 2e-08 |
| W25-noCF | 3.79 s | DSCR | BIT | BIT | 9e-09 | BIT | 7e-09 | BIT | BIT | 1e-08 | 7e-09 | 9e-09 |
| S16-tenor10 | 0.18 s | fail-closed | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= |
| S16-gear0.001 | 0.10 s | fail-closed | FAIL= | FAIL= | FAIL= | FAIL= | FAIL~ | FAIL= | FAIL= | FAIL= | FAIL= | FAIL~ |
| S16-gearbound | 3.09 s | GEARING | BIT | 4e-10 | 1e-10 | BIT | 4e-10 | BIT | 4e-10 | 4e-10 | 4e-10 | 4e-10 |
| W25-taxloss | 0.17 s | fail-closed | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= |
| W25-codstub15 | 8.70 s | DSCR | BIT | 5e-10 | 2e-08 | BIT | 2e-08 | BIT | 5e-10 | 2e-08 | 2e-08 | 2e-08 |
| W25 | 10.04 s | DSCR | BIT | 8e-09 | 3e-10 | BIT | 7e-09 | BIT | 8e-09 | 8e-09 | 7e-09 | 8e-09 |
| S16-dscr1.45 | 9.45 s | DSCR | BIT | 6e-10 | 2e-11 | 1e-07 | 1e-07 | 1e-07 | 2e-10 | 2e-10 | 1e-07 | 1e-07 |
| W25-dscr1.45 | 9.23 s | DSCR | BIT | 6e-09 | 3e-08 | BIT | 3e-08 | BIT | 6e-09 | 6e-09 | 3e-08 | 3e-08 |
| DC-dscr2.0 | 1.37 s | DSCR | BIT | 7e-10 | 2e-10 | BIT | 8e-10 | BIT | 7e-10 | 8e-10 | 8e-10 | 8e-10 |
| W25-gear0.90 | 10.61 s | DSCR | BIT | 8e-09 | 3e-10 | BIT | 7e-09 | BIT | 8e-09 | 8e-09 | 7e-09 | 8e-09 |
| W25-dsra12 | 4.52 s | fail-closed | FAIL= | FAIL= | FAIL~ | FAIL= | FAIL~ | FAIL~ | FAIL= | FAIL= | FAIL= | FAIL~ |
| W25-noDSRA | 6.14 s | DSCR | BIT | 4e-09 | 8e-09 | BIT | 7e-09 | BIT | 4e-09 | 1e-08 | 7e-09 | 8e-09 |
| W25-tenor18 | 0.01 s | fail-closed | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= |
| S16-raw-infeasible | 0.08 s | fail-closed | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= |
| W25-dscr9-infeasible | 0.13 s | fail-closed | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= |
| S16-leap | 31.83 s | DSCR | BIT | 9e-10 | 3e-09 | 4e-08 | 4e-08 | 4e-08 | 7e-10 | 3e-09 | 4e-08 | 4e-08 |
| DC-leap | 1.43 s | DSCR | BIT | 1e-09 | 2e-10 | BIT | 2e-09 | BIT | 1e-09 | 2e-09 | 2e-09 | 2e-09 |
| DC | 1.54 s | DSCR | BIT | 1e-09 | 2e-10 | BIT | 2e-09 | BIT | 1e-09 | 2e-09 | 2e-09 | 2e-09 |
| S16-dscr2.0 | 1.20 s | fail-closed | FAIL= | FAIL= | FAIL~ | FAIL= | FAIL~ | FLIP | FAIL= | FAIL= | FAIL= | FLIP |
| W25-dscr2.0 | 0.61 s | fail-closed | FAIL= | FAIL= | FAIL~ | FAIL= | FAIL~ | FLIP | FAIL= | FAIL= | FAIL= | FLIP |
| S16-gear0.50 | 0.18 s | fail-closed | FAIL= | FAIL= | FAIL= | FAIL= | FAIL~ | FAIL= | FAIL= | FAIL= | FAIL= | FAIL~ |
| S16-dsra0 | 2.16 s | GEARING | BIT | 6e-12 | 5e-13 | BIT | 5e-11 | BIT | 6e-12 | 6e-12 | 5e-11 | 6e-12 |
| S16-noCF | 2.44 s | DSCR | BIT | BIT | 1e-10 | 5e-08 | 5e-08 | 2e-08 | BIT | 8e-11 | 5e-08 | 5e-08 |
| S16-shl-small | 0.15 s | fail-closed | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= |
| S16-gear0 | 0.13 s | fail-closed | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= |
| S16-capex0.32-infeasible | 0.15 s | fail-closed | FAIL= | FAIL= | FAIL= | FAIL= | FAIL~ | FAIL= | FAIL= | FAIL= | FAIL= | FAIL~ |
| S16-taxloss | 0.18 s | fail-closed | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= | FAIL= |
| S16-codstub9 | 22.31 s | DSCR | BIT | 3e-10 | 4e-09 | 2e-08 | 3e-08 | 2e-08 | 5e-09 | 5e-09 | 3e-08 | 1e-08 |
| S16r | 3.68 s | GEARING | BIT | 1e-09 | 2e-13 | BIT | 1e-09 | BIT | 1e-09 | 1e-09 | 1e-09 | 1e-09 |
| S16r-dscr3.0 | 11.16 s | DSCR | BIT | 1e-10 | 2e-11 | 9e-09 | 8e-09 | 1e-08 | 1e-10 | 1e-10 | 8e-09 | 8e-09 |
| S16r-tenor10 | 15.87 s | DSCR | BIT | 1e-10 | 2e-13 | 5e-08 | 5e-08 | 5e-08 | 1e-10 | 1e-10 | 5e-08 | 5e-08 |
| S16r-dsra12 | 5.29 s | GEARING | BIT | 3e-10 | 1e-13 | BIT | 3e-10 | BIT | 3e-10 | 3e-10 | 3e-10 | 3e-10 |
| S16r-gear0.001 | 0.13 s | fail-closed | FAIL= | FAIL= | FAIL= | FAIL= | FAIL~ | FAIL= | FAIL= | FAIL= | FAIL= | FAIL~ |
| S16r-dscr2.0 | 16.96 s | DSCR | BIT | 2e-10 | 2e-10 | 4e-08 | 4e-08 | 3e-08 | 2e-10 | 2e-10 | 4e-08 | 4e-08 |
| S16r-gear0.50 | 1.39 s | GEARING | BIT | 9e-13 | 4e-09 | BIT | 4e-09 | BIT | 9e-13 | 4e-09 | 4e-09 | 4e-09 |
| S16r-tenor12 | 3.04 s | GEARING | BIT | 1e-09 | 2e-13 | BIT | 1e-09 | BIT | 1e-09 | 1e-09 | 1e-09 | 1e-09 |
| S16r-taxloss | 12.70 s | DSCR | BIT | 6e-10 | 2e-08 | 1e-07 | 1e-07 | 1e-07 | 2e-09 | 1e-08 | 1e-07 | 1e-07 |
| W25r-dscr2.0 | 17.88 s | DSCR | BIT | 1e-09 | 6e-12 | 3e-08 | 7e-08 | 2e-08 | 6e-07 | 6e-07 | 6e-07 | 6e-07 |
| W25r-gear0.50 | 4.19 s | GEARING | BIT | 2e-11 | 3e-10 | BIT | 3e-10 | BIT | 2e-11 | 3e-10 | 3e-10 | 3e-10 |
| W25r-dscr3.0 | 13.74 s | DSCR | BIT | 4e-10 | 3e-11 | 1e-07 | 1e-07 | 1e-07 | 1e-09 | 2e-09 | 1e-07 | 1e-07 |
| W25r-taxloss | 40.72 s | DSCR | BIT | 5e-09 | 2e-09 | 1e-07 | 1e-07 | 1e-07 | 3e-08 | 3e-08 | 9e-08 | 8e-08 |
| W25r-tenor10 | 35.62 s | DSCR | BIT | 8e-10 | 4e-08 | 2e-07 | 2e-07 | 2e-07 | 8e-10 | 4e-08 | 2e-07 | 2e-07 |

| Candidate | BIT | ≤1e-8 | ≤1e-7 | ≤1e-6 | >1e-6 | FAIL= | FAIL~ | FAIL≠ | FLIP | CAT | worst feasible max abs (kEUR) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B1 | 31 | 0 | 0 | 0 | 0 | 18 | 0 | 0 | 0 | 0 | 0.00e+00 |
| BA | 2 | 29 | 0 | 0 | 0 | 18 | 0 | 0 | 0 | 0 | 7.97e-09 |
| BW | 0 | 26 | 5 | 0 | 0 | 14 | 4 | 0 | 0 | 0 | 3.93e-08 |
| BG | 17 | 1 | 9 | 4 | 0 | 18 | 0 | 0 | 0 | 0 | 1.85e-07 |
| B | 0 | 15 | 12 | 4 | 0 | 9 | 9 | 0 | 0 | 0 | 1.76e-07 |
| D | 17 | 1 | 8 | 5 | 0 | 14 | 1 | 0 | 3 | 0 | 1.80e-07 |
| C | 2 | 27 | 1 | 1 | 0 | 18 | 0 | 0 | 0 | 0 | 6.31e-07 |
| CBW | 0 | 23 | 7 | 1 | 0 | 18 | 0 | 0 | 0 | 0 | 6.31e-07 |
| FULLnoD | 0 | 15 | 12 | 4 | 0 | 18 | 0 | 0 | 0 | 0 | 6.29e-07 |
| FULL | 0 | 15 | 11 | 5 | 0 | 9 | 6 | 0 | 3 | 0 | 6.29e-07 |

cases: 49 feasible: 31

### 6.2 Convergence analysis

| Level | Solar 50 MW | Wind 25 MW | Solar 16 MW (DSCR) | Data Center |
|---|---|---|---|---|
| L1 DSRA iterations (after the plain seed run) | 2 (seed 1850.20 → 1884.06, then identical) | 2 (1826.13 → 1856.40, then identical) | 2 (464.38 → 469.64) | 1 (target identical to the seed) |
| L2 outer iterations / ρ | 6 / 0.0101 | 10 / 0.045 | 7 / 0.021 | 8 / 0.025 |
| L3 G2A iterations | 2 (∂s′/∂s = 0) | 3 (Senior constant 28 399.339948107) | 9–10, ρ ≈ −0.043 oscillating | 2 |
| L4 SHL↔tax iterations | 7 | 9–10 | 6–7 | 8 |
| Joint solver C | 5 joint iterations, 2 Anderson steps | 5 / 2 | 5 / 2 | 4–5 |
| Final IDC residual, baseline → C | 7.6e-8 → ~1e-13 | 4.5e-8 → 2.3e-13 | — | 2.2e-8 → ~1e-13 |

Safeguards were exercised on Wind 25 MW:

* Anderson with m = 1 and m = 3: same result class.
* Forced rejection of every Anderson step: converges in 9 joint iterations, maximum difference 1.7e-9.
* Early and late switches to the terminal Picard phase: both converge.
* Forced exhaustion of the joint budget: the canonical fallback is bit-identical to the baseline (12 602 of 12 602 floats).
* No natural fallback or rejection occurred anywhere in the matrix.

### 6.3 Evaluation counts per Run (cProfile call counts)

| Case / candidate | Engine runs | IDC loops | G2A solves | Senior model runs | SHL↔tax fixed points | Senior solves | Tax/CFADS evaluations |
|---|---:|---:|---:|---:|---:|---:|---:|
| Solar 16 MW — A | 3 | 2 | 21 | 465 | 408 | 2 879 | 17 175 |
| — B1 | 3 | 2 | 21 | 318 | 280 | 1 978 | 13 143 |
| — C+B1 | 1 (+1 aborted probe) | 1 | 8 | 112 | 98 | 698 | 4 631 |
| — C+B1+BW | 1 (+1) | 1 | 8 | 112 | 98 | 380 | 2 275 |
| — D | 3 | 2 | 21 | 201 | 198 | 1 353 | 7 895 |
| Wind 25 MW — A | 3 | 2 | 25 | 189 | 120 | 1 187 | 5 438 |
| — B1 | 3 | 2 | 25 | 134 | 88 | 876 | 4 220 |
| — C+B1 | 1 (+1) | 1 | 8 | 54 | 40 | 384 | 1 940 |
| — C+B1+BW | 1 (+1) | 1 | 8 | 54 | 40 | 234 | 1 018 |
| Data Center — A | 2 | 1 | 12 | 44 | 22 | 198 | 682 |
| — C+B1+BW | 1 (+1) | 1 | 7 | 18 | 12 | 59 | 186 |

The aborted probe is the first waterfall call, which is stopped as soon as the joint financing result exists; that result is then consumed by exactly one canonical waterfall Run.

### 6.4 Performance (quiet CPU, 5 uncached Runs each, seconds, median / p95, time saving vs A)

| Case | A | B1 | B (nested, contains BG — NO GO) | C (C+B1) | C+B1+BW | FULLnoD (contains BG — NO GO) |
|---|---:|---:|---:|---:|---:|---:|
| Solar 16 MW, DSCR-bound | 30.04 / 31.71 | 23.58 / 23.67 (+22 %) | 6.21 / 6.29 (+79 %) | 7.01 / 7.35 (+77 %) | 4.35 / 5.46 (+86 %) | 2.49 / 2.76 (+92 %) |
| Wind 25 MW, DSCR-bound | 10.01 / 10.86 | 8.31 / 8.83 (+17 %) | 3.44 / 3.52 (+66 %) | 3.59 / 3.89 (+64 %) | 2.19 / 2.25 (+78 %) | 1.90 / 2.13 (+81 %) |
| Data Center 20 MW | 1.28 / 1.53 | 1.08 / 1.59 (+16 %) | 0.57 / 0.66 (+56 %) | 0.52 / 0.63 (+59 %) | 0.40 / 0.45 (+69 %) | 0.44 / 0.49 (+66 %) |
| Solar 50 MW, gearing-bound (default) | 2.87 / 3.38 | 2.77 / 3.25 (+3 %) | 1.82 / 2.34 (+36 %) | 0.99 / 1.16 (+65 %) | 1.02 / 1.12 (+65 %) | 0.91 / 0.95 (+68 %) |
| Solar 16 MW, DSCR 2.0 | 16.35 / 17.34 | 12.81 / 13.32 (+22 %) | 1.60 / 2.05 (+90 %) | 7.05 / 7.93 (+57 %) | 5.24 / 5.71 (+68 %) | 1.36 / 1.66 (+92 %) |
| Wind 25 MW, DSCR 2.0 | 18.84 / 19.73 | 11.25 / 11.67 (+40 %) | 3.08 / 3.37 (+84 %) | 6.73 / 6.98 (+64 %) | 4.80 / 5.34 (+75 %) | 2.72 / 2.95 (+86 %) |
| Wind 25 MW, DSCR 3.0 | 15.02 / 16.48 | 9.30 / 10.71 (+38 %) | 3.22 / 3.30 (+79 %) | 5.14 / 5.26 (+66 %) | 3.24 / 3.44 (+78 %) | 2.11 / 2.24 (+86 %) |
| Solar 16 MW, gearing 0.50 | 1.37 / 1.49 | 1.27 / 1.65 (+8 %) | 0.93 / 1.21 (+32 %) | 0.93 / 0.96 (+32 %) | 0.75 / 0.76 (+45 %) | 0.78 / 0.92 (+43 %) |
| Solar 16 MW, gearing-bound | 2.81 / 3.65 | 2.46 / 2.81 (+12 %) | 1.72 / 1.90 (+39 %) | 1.05 / 1.34 (+63 %) | 0.91 / 1.03 (+67 %) | 1.01 / 1.24 (+64 %) |
| Wind 25 MW, DSRA policy off | 6.26 / 7.00 | 5.06 / 5.55 (+19 %) | 2.08 / 2.38 (+67 %) | 3.96 / 4.10 (+37 %) | 2.61 / 3.04 (+58 %) | 1.90 / 2.37 (+70 %) |
| Solar 16 MW, construction financing off | 2.72 / 2.89 | 1.85 / 1.88 (+32 %) | 0.84 / 0.87 (+69 %) | 1.77 / 1.91 (+35 %) | 1.37 / 1.61 (+50 %) | 0.80 / 0.87 (+71 %) |
| Wind 25 MW, DSRA 12 m (fail-closed) | 3.69 / 3.76 | 3.18 / 4.19 (+14 %) | 0.84 / 0.99 (+77 %) | 6.53 / 7.00 (-77 %) | 5.21 / 5.82 (-41 %) | 4.59 / 4.67 (-24 %) |
| Solar 16 MW, DSCR 2.0 (fail-closed) | 1.08 / 1.23 | 0.96 / 1.23 (+11 %) | 0.53 / 0.60 (+51 %) | 2.01 / 2.14 (-86 %) | 2.02 / 2.23 (-87 %) | 1.75 / 1.93 (-62 %) |

A positive percentage is a time saving; a negative one is a slowdown.

The targets are met in every feasible measured case by C+B1+BW:

* ≥30 % for Solar/Wind: measured 45–86 %.
* ≥50 % for DSCR-heavy cases: measured 68–78 % on DSCR 2.0/3.0 and the DSCR-bound references.

B1 alone saves 3–40 %.

### 6.5 Cases where a candidate is slower

* **Fail-closed inputs, C family**: the fast path must fail before the canonical path re-decides the Run. Medians:
  * Wind 25 MW DSRA 12 m: 3.69 → 6.53 s (C), 5.21 s (C+B1+BW), 4.59 s (FULLnoD).
  * Solar 16 MW DSCR 2.0: 1.08 → 2.01 s (C), 2.02 s (C+B1+BW), 1.75 s (FULLnoD).

  The worst case is ×1.9, and it affects only Runs that are refused.
* **p95 above baseline p95 for B1** (medians are faster in every case): Data Center 1.59 vs 1.53 s, Solar 16 MW gearing 0.50 1.65 vs 1.49 s, Wind DSRA 12 m 4.19 vs 3.76 s. All of these are within the scheduling noise of 5 samples.
* **Single-shot matrix (noisy, parallel workers)**: D was up to ×4 slower in the cases where it flipped feasibility, because it computed a full result where the baseline failed fast.

### 6.6 Terminal-classification margins

For C, C+B1+BW and FULLnoD, every terminal balance (Senior and SHL, at contractual maturity and at the model horizon) was checked in the feasible cases:

* No REPAID/OUTSTANDING classification changed.
* 155 terminal balances in 31 feasible cases were checked, with 0 classification changes.
* Every balance is either exactly 0 or at most 3.5e-9 kEUR (the Wind 25 MW tenor-10 Senior maturity balance), which is at least 9.65e-8 below the 1e-7 threshold.

The candidate bands of §7.1 therefore did not reach the threshold in any measured case. They are, however, of the same order as the threshold, which is why OD-1 is required.

### 6.7 Quarterly 3/3 (isolated)

* **Research calculation on `main`**: Solar and Wind, each under DSCR_SCULPTED and COMBINED_MINIMUM sizing. All candidates are bit-identical, because no candidate's loop exists in that calculation.
* **PR #320 worktree** (equity-only, no DSRA, construction IDC on): Q and S frequencies, Solar and Wind, gearing default and 0.50.
  * All candidates show at most 1.5e-11 kEUR difference, with no categorical change.
  * B1, D and BG are bit-identical there.
  * Speed-ups were not timed on a quiet CPU.


## 7. Precision risks

### 7.1 Why the non-bit-identical candidates differ, and by how much

Every level accepts a state when its own residual is below its own tolerance. The
accepted state is therefore one *representative* of the fixed point, located inside a
band whose width is set by that tolerance and the contraction rate. A candidate that
reaches the fixed point along a different path accepts a different representative of
the same band. The measured differences match the bands exactly:

| Source of the difference | Band that defines it | Observed (feasible cases) |
|---|---|---|
| L2 representative (BA, C) | IDC tolerance 1e-7 × ρ/(1−ρ), ρ ≤ 0.045 | ≤ 8.0e-9 kEUR |
| L4 representative (BW) | SHL↔tax tolerance 1e-6 × contraction (1/20 … 1/60) | ≤ 3.9e-8 kEUR |
| L1 representative (C) | DSRA tolerance 1e-6: the canonical loop stops when \|T(F) − F\| ≤ 1e-6, the joint solver drives it to ~1e-12 | ≤ 6.3e-7 kEUR (one case, W25r-dscr2.0: baseline stopped at a 4.3e-7 residual) |
| L3 representative (BG, D) | G2A acceptance \|s′ − s\| ≤ 1e-7 on each side of the fixed point → up to 2 × 1e-7 | up to 1.85e-7 kEUR on SHL cash lines |

In every measured case the candidate's accepted state is **at least as converged** as
the baseline's (e.g. Wind 25 MW: IDC outer residual 2.3e-13 vs 4.5e-8; DSRA residual
~1e-12 vs 4.3e-7). The differences are therefore baseline truncation error, not candidate
error — but they are differences, and the task rules require them to be classified.

### 7.2 Interaction with the precision authorities

| Authority | Value | Interaction |
|---|---|---|
| Senior solver | 1e-4 kEUR / 1e-9 rel | Untouched: L5 is called with the same policy; all differences are ≥ 2 orders below. |
| G2A acceptance | 1e-6 kEUR | All candidates pass it on the returned state (the canonical checks run unchanged). |
| G2A strict re-solve | 1e-7 kEUR | Unchanged trigger and target. BG/D move the SHL representative by up to 1.85e-7 — **larger than this authority** — because two different accepted representatives can sit on opposite sides of the band. |
| REPAID classification | 1e-7 kEUR | No classification changed in any case. But the BG/D band (≤ 1.85e-7) and the C/DSRA band (≤ 6.3e-7) are of the **same order or larger** than the classification threshold: a terminal balance within ~2e-7 of 1e-7 could be classified differently by two equally valid representatives. Terminal margins of the measured cases are in §6.5. |
| DSRA policy | 1e-6 kEUR | C replaces the "stop at ≤ 1e-6" representative by a ~1e-12 one; the acceptance test is evaluated, unchanged, on the returned result. |

There is today **no authority that defines when two results computed along different
iteration paths are the same result**. Bit-identity is the only implicit standard.
Every non-bit-identical candidate therefore needs a precision-authority decision before
it can be production-designed; no tolerance was redefined in this research.

### 7.3 A pre-existing property found by the research: path-dependent fail-closed outcomes

Candidate D turned three baseline **fail-closed** Runs into **feasible** results
(Solar 16 MW DSCR 2.0, Wind 25 MW DSCR 2.0 and 3.0). Root cause, traced on Wind 25 MW
DSCR 3.0: the baseline raises `SHL_MATURITY_RESIDUAL_FAILS_CLOSED` inside the
DSCR-only capacity run of the **first** G2A iteration of the IDC neutral seed
(`project.py:1221` → `orchestrator.py:2370` → `shl/production.py:731`), i.e. on a
non-converged SHL candidate (the gearing-based estimate). D starts the same loop from
the Sources & Uses identity, never visits that iterate, converges, and every canonical
check — including the SHL maturity check on the converged state, the final verification
and the waterfall — passes.

This is a categorical change, so **D is NO GO**. It is also evidence that the current
fail-closed outcome for some DSCR-heavy inputs is decided by an intermediate iterate,
not by the converged financial state. That is an Owner question (OD-2), independent of
performance. The prototypes keep the baseline behaviour by construction: whenever the
fast path raises, the canonical path re-decides the Run with every candidate removed,
which made all 18 fail-closed cases identical to the baseline, including the numeric
evidence in the error text (for B1, C, C+B1+BW, FULLnoD).

### 7.4 Other risks

* **Non-smooth DSRA target** (`max` over periods): Anderson is safeguarded (decrease test,
  reset, terminal Picard) and the joint loop has a 15-iteration budget with canonical
  fallback; forced-rejection and forced-fallback runs converge to the same result class.
* **U2 reserve-income loop**: the waterfall can request the financing for a non-empty
  income vector; the prototype then uses the canonical nested path. Not exercised by the
  matrix (no reserve-income input); must be covered in production.
* **Seed governance**: BW uses `_test_only_initial_shl_interest_guess`, whose docstring
  forbids production use and claims seed-invariance that no test currently checks. Measured
  seed effect ≤ 3.9e-8 kEUR.
* **Quarterly 3/3**: no candidate has any surface in the isolated research calculation on
  `main` (bit-identical, 4/4 configurations); on the PR #320 worktree the candidates behave
  as on 6/6 (≤ 1.5e-11 kEUR, no categorical change).

## 8. Classification

| Candidate | Decision | Basis |
|---|---|---|
| **B1** capacity-pass deferral | **GO** | Bit-identical in 31/31 feasible cases; all 18 fail-closed cases identical with canonical re-decision on failure. 22-62 % faster alone (§6.4). Pure ordering change inside one function. |
| **BA** Anderson on IDC state | CONDITIONAL GO (as part of C) | ≤ 8.0e-9 kEUR, no categorical change; needs OD-1. |
| **BW** SHL↔tax warm start | CONDITIONAL GO | ≤ 3.9e-8 kEUR; needs OD-1 and OD-4 (test-only seed promotion). |
| **BG** secant on G2A SHL | NO GO for now | Differences up to 1.85e-7 kEUR exceed the 1e-7 strict re-solve / REPAID scale; only reconsidered if OD-1 explicitly covers the G2A band. |
| **B** (all nested) | NO GO as a bundle | Contains BG. |
| **C** joint reduced solver (DSRA + construction state) | **CONDITIONAL GO** | ≤ 8e-9 kEUR in 29/31 feasible cases, 6.3e-7 kEUR in one DSRA-representative case, no categorical change, identical fail-closed outcomes; requires OD-1 (and OD-3 for failure-path cost). |
| **C+B1+BW** (recommended bundle) | **CONDITIONAL GO** | ≤ 3.9e-8 kEUR except the DSRA case (6.3e-7); largest gains without touching the G2A band. |
| **FULLnoD** (C+B1+BW+BG) | NO GO for now | Contains BG. |
| **D** analytic G2A seed | **NO GO** | 3 feasibility flips (fail-closed → feasible). |
| Newton / Broyden (full) | NO GO | Not justified (§4). |

## 9. Owner decisions required

| Id | Decision | Options | Research recommendation |
|---|---|---|---|
| OD-1 | **Fixed-point representative equivalence authority** — when are two results from different iteration paths the same result? | (a) bit-identity only (status quo: only B1 qualifies); (b) every canonical acceptance test passes on the returned state, no categorical change, and each difference stays within the band of the loop that defines the quantity (IDC 1e-7, SHL↔tax 1e-6, DSRA 1e-6); (c) a single result-level bound, e.g. ≤ 1e-8 kEUR, with a documented exception list | (b) with the bands stated per level; G2A band explicitly **excluded** until a G2A-specific decision exists. |
| OD-2 | Should a fail-closed check on a **non-converged intermediate iterate** decide the Run? | keep (status quo) / decide on the converged state only | Separate review; until then keep, via canonical re-decision. |
| OD-3 | Failure-path cost of canonical re-decision | accept up to ~2× on fail-closed Runs (measured worst 3.3 s → 6.3 s) / accept same reason code with path-dependent evidence numbers | accept re-decision (identical evidence). |
| OD-4 | Promote the SHL warm start (today a test-only seed entry) | approve with a seed-invariance test / reject (C+B1 without BW) | approve with test. |
| OD-5 | Approve B1 as a bit-identical structural change on a protected financial path | approve / reject | approve. |
| OD-6 | DSRA policy evidence: `iteration` count and residual in `FinancingPolicyEvidence` change meaning under C (joint iterations, ~1e-12 residual) | keep fields with new semantics / add explicit joint evidence fields | add explicit fields. |

## 10. Roadmap (at most three staged PRs)

No second production financial engine: every PR reorders or reduces evaluations of the
existing canonical functions.

| | PR-1 — G2A capacity-pass deferral (B1) | PR-2 — Joint outer solver (C + BW) | PR-3 — G2A acceleration (BG) — only if OD-1 covers it |
|---|---|---|---|
| Modules | `financial_engine/financing/project.py` (`run_project_financing_model` loop only) | `financing/generic_product_policy.py` (joint path + unchanged acceptance test + canonical fallback), `financing/project.py` (`_run_with_construction_idc`: joint state hook, budget, fallback), new pure-numerics helper (Anderson, no financial logic), `orchestrator.py` (internal warm-start argument replacing the test-only seed) | `financing/project.py` (secant step inside the G2A loop) |
| Reuse | `run_senior_debt_model` unchanged | Stage B2, `apply_capitalized_financing_costs`, G2A, policy target function, canonical tail of the IDC function, waterfall, statements — unchanged | `reconcile_financing_stack` unchanged |
| Approvals | Financial Owner (OD-5); protected-path governance successor | OD-1, OD-3, OD-4, OD-6; protected-path governance successors | OD-1 extended to the G2A band |
| Coverage | Full matrix bit-identity (digest of every float); capacity-run count = 1 per G2A; failure-path identity incl. error text | Matrix under the OD-1 rule; forced Anderson rejection; forced budget exhaustion → bit-identical canonical; fail-closed identity; DSRA peak switch; U2 reserve income; junior / multi-senior routing; manual IDC conflict; VAT facility; quarterly 3/3 isolation | Matrix with terminal-margin report; DSCR-bound oscillating cases |
| Risks | Failure ordering (handled by re-decision) | Representative changes (bounded, §7.1); fallback cost on failures; evidence-field semantics | REPAID band interaction |
| Dependencies | none; orthogonal to #322; small textual overlap with #320 at the top of `run_project_financing_model` | PR-1; #320 (same file) | PR-2 |
| Fallback | canonical loop on any exception | canonical nested policy loop with every candidate removed | plain update |
| Target (median, measured in §6.4) | Solar/Wind −20 … −40 % | Solar/Wind ≥ 75 %, DSCR-heavy ≥ 80 % | additional −30 … −45 % on DSCR-bound cases |
| Effort | Solar/Wind: ~2 days; wider financing: +1 day (junior/multi-senior paths do not enter this loop) | Solar/Wind (construction + DSRA + SHL): ~1-1.5 weeks; wider financing (U2 reserve income, VAT facility, legacy construction uses vector, manual IDC, policy-off variants): +1-2 weeks | ~3 days after OD-1 |


## 11. Final disposition

**`V9 JOINT SOLVER POC COMPLETE — PRECISION AUTHORITY REQUIRED`**

* **B1** is production-design ready. It is bit-identical and needs only OD-5 and a protected-path governance successor.
* The **joint solver (C, recommended bundle C+B1+BW)** meets every performance target. It changes no category, but it returns a different (more converged) representative of the same fixed point. It cannot be production-designed until the Financial Owner sets the fixed-point representative equivalence authority (OD-1).
* **D**, **BG** and full Newton/Broyden are not pursued.

## 12. Reproduction

Scratch code, raw results and the scripts live in `v9_scratch/`:

| File(s) | Purpose |
|---|---|
| `v9proto.py` | candidate builders |
| `harness.py` | uncached Runs, flattening, parity |
| `matrix.py` | case definitions and parity matrix |
| `bench.py` | timing |
| `evals.py` | evaluation counts |
| `terminal.py` | terminal margins |
| `robust.py` | safeguards and fallback |
| `quarterly.py`, `q320.py` | quarterly 3/3, isolated |
| `traj.py`, `tree.py`, `g2atraj.py`, `dsraF.py` | convergence traces |
| `results/` | JSON outputs |

The scripts expect a read-only checkout of `main` at `/home/user/v9`; set `V9_ROOT` to point them at another checkout.
