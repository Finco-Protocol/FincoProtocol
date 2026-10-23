# V9-P2a Correction E — Run Engine Performance Research (isolated, NOT integrated)

Research only. No PoC code is part of PR #332 or of the Correction E candidate. PoCs were env-gated switches in a
disposable worktree of candidate `db92728d`. All numbers are local (Windows desktop, Python 3.12.10, shared machine with
variable clock 2.48/2.90 GHz and background applications). Call counts are deterministic; timings are paired per
repetition (interleaved arms, shuffled order, 5 repetitions) to cancel machine drift. Medians of independent samples on
this host varied by up to ±30 %, so absolute seconds are indicative only.

## 1. Where Run latency goes

V2 Run route (real route, disposable DB, reference products, median of 3):

| Product | Route total | Engine (`run_clean_production`) | Persistence (`v2_atomic_run_commit`) | Other (projection, identity, render, transport) |
|---|---:|---:|---:|---:|
| Generic Solar Reference 64 MW | 3.61 s | 2.89 s (80 %) | 0.09 s | 0.66 s |
| Generic Wind Reference 50 MW | 4.64 s | 3.87 s (84 %) | 0.09 s | 0.66 s |

Inside the engine (W25 cProfile, cumulative): 99.7 % is the financing policy / G2C evaluation; statements, developer
economics, Stage B2 and maturity gates together < 0.2 %. One Run = **three full engine evaluations** (initial-DSRA seed
without construction financing ≈ 32 % of Run time, plus two DSRA iterations with construction IDC). The self-time profile is
flat (tax vector evaluation, Senior forward roll, SHL roll-forward, tax-input merges): no single hotspot; cost is the
**number of nested evaluations**.

Deterministic solver inventory (canonical = OD-R candidate, identical at every level):

| Case | G2A | Senior/SHL/tax models | Senior solves | SHL schedules | Numeric tax evaluations | Full tax |
|---|---:|---:|---:|---:|---:|---:|
| reference-wind | 21 | 82 | 284 | 287 | 4 348 | 184 |
| W25 | 25 | 189 | 1 187 | 1 241 | 10 882 | 402 |
| S16 | 21 | 465 | 2 879 | 3 233 | 42 929 | 950 |

## 2. Isolated PoCs (OD-R semantics; 112-case matrix re-executed for each)

| PoC | Mechanism | S16 | W25 | Small cases | Verdicts (112) | Outputs |
|---|---|---:|---:|---|---|---|
| B1 capacity-once | DSCR-only capacity pass executed once, at the converging candidate (identical input to the canonical last pass) | 0.74× | 0.77× | 0.89–0.98× | identical | **79/79 feasible bit-identical incl. Integrity; final-state shortfalls identical; only the provisional-violation diagnostic count differs** |
| Warm G2A seed | G2A starts from the previous invocation's derived SHL (run-local) | 0.50× | 0.76× | **1.22–1.34× slower** | identical | not bit-identical (within tolerance) |
| Warm construction outer | construction loop seeded from the previous DSRA evaluation's converged inner state | 0.90× | 0.90× | 0.87–0.97× | identical | not bit-identical |
| All three | combined | **0.35× (≈2.9×)** | 0.54× (≈1.9×) | 0.92–1.11× | identical | 4/79 bit-identical; final shortfalls move ≈1e-7 kEUR |

Ratios are paired medians vs the OD-R candidate (lower is faster). Model-evaluation counts: S16 465 → 318 (B1) →
144 (all); W25 189 → 134 → 82. Warm G2A increases inner Senior solves on small cases (reference-wind 284 → 399), explaining
its regressions there.

## 3. Prioritised recommendation

| Optimization | Current bottleneck | Proposed change | Speedup | Numerical risk | Complexity | Recommendation |
|---|---|---|---|---|---|---|
| B1 capacity-once | ~30 % of Senior/SHL/tax evaluations are provisional DSCR-only capacity passes | run the capacity pass once at G2A convergence | **measured** 0.74–0.98× (S16 −26 %) | none for outputs (bit-identical); drops intermediate non-maturity capacity-pass exceptions (same semantics question as #324) | low (one function) | **first V9-P2b candidate**; requires an explicit decision on intermediate-exception semantics |
| Joint outer convergence (#327) + warm seeds under OD-R | nested DSRA × construction × G2A fixed points | #327 Anderson joint solver without guarded canonical re-run (OD-R removes the intermediate rejection authority that forced it) | research sandbox: 3.1× aggregate, S16 5.7× (not re-measured here); local combined warm PoC 2.9× on S16 | outputs within tolerance, not bit-identical; zero verdict changes in 102-case research and 112 here | high | **promising — requires OD-1 numerical-equivalence decision** |
| Initial-DSRA seed | seed run ≈ 32 % of Run (W25) | cheaper seed (e.g. reuse first evaluation, analytic peak DS) | estimated up to ~30 % on DSRA projects | trajectory change → OD-1 | medium | investigate in V9-P2b |
| Inner Senior/tax loop | ~15 numeric tax evaluations per Senior solve | warm-start Senior solver across SHL/tax iterations | estimated (not measured) | needs equivalence evidence | medium | coordinate with #322 |
| Route overhead | ~0.66 s non-engine per Run | projection/render profiling | estimated ≤ 15 % of route | none | low–medium | separate UX/perf task |

**Verdict: PROMISING — REQUIRES FURTHER NUMERICAL VALIDATION.** One measured bit-identical optimisation (B1, up to 26 %)
exists; ≈2–3× on heavy models is measured only for non-bit-identical variants that need OD-1.

## 4. Interaction with PR #327 / #328 / #322 / #324

* #327's "guarded" mode lost 35–50 % because it re-ran the canonical path to preserve intermediate rejection authority.
  Under OD-R that authority is final-state only, which is exactly what makes a joint solver viable — but only after OD-1.
* #324 debated intermediate capacity-first rejection semantics; B1 is the same decision and should be decided once.
* #328 (parallel G2A) is throughput, orthogonal; #322 targets the inner Senior solver.

Proposed V9-P2b structure: (1) B1 behind an explicit decision; (2) OD-1 decision; (3) joint/warm solver on the OD-R
finalization contract (Correction E), using the 112-case matrix + finalization fault injection as acceptance.
