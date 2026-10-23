# V9-B2: Conditional Joint Solver Design

Design only. No C, BW, Anderson, warm start or precision-policy implementation is included in V9-B1.

## Authority and Reuse

Research checkpoint: `79270c9513cbd0ed7c0432733903482bc6528b93`.
Released implementation baseline: `5be8c4b149712dd39b38b54c6fabcf3fcf47ef0d`.

The prospective state is initial DSRA funding plus the five existing capitalized construction-financing costs. A safeguarded accelerator would call the existing construction allocator, capitalization, Senior/SHL, tax/CFADS and reserve-target functions. It must not introduce new financial equations. A verified final canonical evaluation and existing acceptance checks remain mandatory. No CFADS seeding, analytic G2A seed or G2A secant is proposed.

## Owner Decisions Required Before Implementation

| Decision | Required explicit policy | Safe default pending decision |
| --- | --- | --- |
| OD-1 | Whether different fixed-point representatives can constitute equivalent financial results; quantity-specific absolute/relative units, period aggregation, evidence fields and terminal-classification margins | Bit identity only; no production C/BW |
| OD-2 | Whether an intermediate-iterate refusal remains decisive, including failures in capacity-only evaluations | Preserve original rejection, reason and full numeric evidence |
| OD-3 | Maximum supported cost/latency of canonical re-decision for rejected Runs; absolute latency plus ratio and p95 under concurrent workloads | No claimed acceptance of research slowdowns |
| OD-4 | Whether a production SHL-interest warm start is eligible; source/axis/scenario binding, reset rules and seed-invariance criteria | Never use `_test_only_initial_shl_interest_guess` in production |
| OD-6 | How joint iterations and DSRA residuals are represented without reinterpreting historical `FinancingPolicyEvidence` | Preserve old fields/semantics; propose separate versioned joint evidence |

The research observed differences up to approximately `6.3e-7 kEUR` for a DSRA representative, while a terminal classification uses `1e-7 kEUR`. Passing the old loop tolerances does not prove unchanged financial classification near that boundary. A tighter representative is not automatically the same approved result. No new numerical bands are selected here.

## V8 Precision Authority Dependency

FD-1 through FD-8 are a separate decision process, not approvals implicitly supplied by V9 research or this implementation prompt. Their authoritative decision text is not present in the pinned baseline or the supplied V9-A report. An exact numbered crosswalk cannot truthfully be certified without that record.

Before B2 approval, attach the actual FD-1--FD-8 record and map each decision to solver termination, funded-capacity handshake, service-budget refinement, G2A/SHL convergence, construction residuals, DSRA residuals, maturity classification and externally persisted evidence. Conflicts must return to the Financial Owner. Research tolerances and empirical maximum differences cannot substitute for those decisions.

## Production Design Constraints

1. Request-local immutable state, no global mutable solver cache or source rewriting.
2. A bounded joint iteration budget, deterministic damping/decrease safeguards and explicit rejection of non-finite proposals.
3. Preserve the original neutral-seeded canonical path for fallback. Never start canonical re-decision from a partially accelerated state.
4. Any fallback eligibility must be typed and specific. Programming errors must escape, not be retried as financial non-convergence.
5. The final result must pass all current tax/interest, funding, service-budget, maturity, financial-statement and Run Integrity authorities before publication.
6. Scenario/CAS/Run History/export remain consumers of one canonical result, not parallel evidence builders.

## Validation Before a B2 Candidate May Proceed

- Re-run B1's full feasible/rejected matrix and expand around terminal thresholds, equal binding constraints, zero/near-zero funding and tax limitation transitions.
- Independent Decimal/Fraction recomputation of funding, interest/date fractions, capitalization, reserve targeting and terminal balances; baseline and candidate full-leaf/evidence comparison under the explicitly approved equivalence rule.
- Force safeguard rejection, peak-DSRA switching, iteration exhaustion, invalid proposals and each typed fallback. Require exact original rejection evidence when OD-2 retains that policy.
- Cover reserve financing income (U2), cash DSRA/DSRF, typed construction uses/timing, manual financing-cost conflicts, VAT facilities, Junior and multi-Senior routing without broadening their release scope.
- Cold/uncached interleaved measurements of successful and rejected Runs; absolute medians/p95, kernel counts, fallback counts and memory under concurrent sessions. Include fallback-cost tails rather than quoting successful-only savings.
- Prove inactive four-vertical and all historical output compatibility; audit financial statements, tax, sponsor/project returns and immutable persisted/export evidence.
- Assess quarterly only after an independently approved integration checkpoint, preserving release flags and frequency semantics.
- Obtain independent exact-content review, then separately authorized exact-path/blob successor recognition. Do not modify historical maps to obtain green CI.

## Integration Order

Keep V8-A database work and V8-B1 `senior_debt/solver.py` work separate. After their independent approvals, normal-merge current main into B1 and repeat complete bit-identity validation. PR #320 touches `financing/project.py`; resolve its conflict by preserving both reviewed economic/frequency authority and B1's accepted-iteration capacity input. No research source transplant, cherry-pick, rebase or activation is authorized. B2 implementation must await OD-1/2/3/4/6 and FD reconciliation.

Status: DESIGN PREPARED; OWNER DECISIONS PENDING; V9-B2 NOT IMPLEMENTED.
