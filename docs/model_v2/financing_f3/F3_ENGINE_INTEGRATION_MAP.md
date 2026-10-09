# Financing F3 — Engine Integration Map

Read-only analysis of where the single-Senior assumption lives and how multiple facilities must interact. **No code
in `financial_engine/**` or `finco_core/**` is changed by this PR.** File references are on `main` `1977033`.

## 1. Current funding waterfall and caps

Construction draws use **one** canonical allocator (`finco_core/construction/allocator.py`). Per period, in order:
Share Capital → Share Premium → Other Committed Equity → Additional Equity → SHL → Junior → **Senior (residual)**.
Each layer fills until its available amount is exhausted or the period need is met; the caps are the scalar amounts
of the funding classes. Senior is drawn last and equals the residual; `ConstructionPeriodAllocation.residual_keur`
audits `sources − uses`. Stage B2 and the G2A schedule both call it so the Senior draw used for IDC equals the draw in
the funding schedule (`PR9_CANONICAL_CONSTRUCTION_ALLOCATOR`). `reconcile_financing_stack`
(`financial_engine/financing/stack.py`) derives the residual SHL or additional equity and fails closed on
`G2A_FIXED_SOURCES_EXCEED_TOTAL_PROJECT_USES`.

## 2. Future multi-instrument requirements

| Requirement | Design |
|---|---|
| Multiple debt drawdowns | each facility has its own draw vector; sum feeds the allocator's debt layers |
| Multiple equity contributions | per-provider contribution vectors within the equity layers |
| Funding order | generalise the fixed 7-layer order into `(layer, seniority_rank, instrument_id)`; legacy order is the default and must be reproduced exactly |
| Independent facility limits | per-facility commitment caps; layer total = Σ facility caps |
| Underfunding | uses exceed Σ available → fail closed with a typed code (as today's `FundingShortfallError`), never silent plug |
| Overfunding | fixed sources exceed uses → fail closed (`G2A_FIXED_SOURCES_EXCEED_TOTAL_PROJECT_USES` generalised) |
| S&U reconciliation | **one** reconciliation (F1's), fed by per-instrument funding; no second calculator |
| Constraint precedence | explicit and ordered: (1) per-facility commitment cap, (2) facility gearing/DSCR sizing, (3) aggregate gearing cap, (4) funding order; binding constraint reported per facility |

**Integration seam:** an `InstrumentFundingProvider` adapter that, given the instrument collection, returns the same
inputs the allocator and `reconcile_financing_stack` take today (layer totals + per-period vectors) *plus* a
per-instrument draw ledger. For the mapped legacy configuration the adapter output must equal today's scalars exactly.

## 3. Facility interactions

| Topic | Today (single Senior) | Multi-facility requirement |
|---|---|---|
| Interest expense | one rate schedule (`senior_debt_interest_config`) | per-facility rate schedule; interest = Σ facilities |
| IDC | Stage B2 on the Senior draw | per-facility IDC on its own draws, capitalised per policy; inside the G2A outer fixed point |
| Commitment fees | `commitment_fee` on undrawn Senior | per facility on its undrawn commitment |
| Structuring/arrangement fees | single rates on Senior | per facility, per fee term (basis becomes effective only when consumed) |
| Principal amortisation | one solver (`senior_debt/solver.py`) | per-facility schedule; sculpting target per facility or on aggregate |
| Debt maturity | `senior_tenor_years` | per-facility maturity; tail/refinancing must be explicit |
| CFADS | project CFADS | unchanged; allocated across facilities by priority |
| DSCR | CFADS / Senior DS | **per-facility** (CFADS available to that rank / its DS and senior-ranked DS) and **aggregate** (CFADS / Σ DS) — defined separately |
| LLCR / PLCR | NPV(CFADS to maturity)/Senior balance | per facility with its own maturity and rank; aggregate over Σ balances |
| Cash sweeps | Senior/SHL sweep options | sweep applies per facility in seniority order after scheduled DS |
| DSRA / DSRF | single Senior DS (`dsra/target.py`) | reserve target over the facilities it supports (explicit) |
| Tax deduction | interest map into ATAD limitation | per-facility interest lines into the same limitation; SHL keeps its eligibility policy |
| Financial statements | `senior_debt` lines in `financial_statements/assembly.py` | per-facility liability roll-forward + aggregate lines |
| Shareholder waterfall | post-senior cash after one Senior DS | post-senior cash after Σ senior-ranked DS; junior/mezz DS inserted by rank before SHL/distributions |
| Sponsor returns | contributions by capital class | by capital class **and** provider ledger (F3.5); individual returns only with that ledger (F4) |

## 4. Individual facility vs aggregate Senior debt service

Define two vectors: `facility_debt_service[f][t]` (own interest + principal + fees) and
`aggregate_senior_debt_service[t] = Σ_{f ∈ senior-ranked} facility_debt_service[f][t]`. Covenants and sizing refer to
one or the other **explicitly**; no code may assume a shared DSCR denominator or covenant requirement.

## 5. Where the single-Senior implementation must change (not changed now)

| Area | File(s) |
|---|---|
| Inputs | `finco_core/inputs/_models.py` (`FinancingParams`, `hash_inputs_for_cache`), `serialization.py` |
| Allocation | `finco_core/construction/allocator.py`, `stage_b2.py` |
| Stack / S&U | `financial_engine/financing/{stack,project,contracts,project_uses}.py` (F1-owned) |
| Senior solver / policy | `financial_engine/senior_debt/{solver,policy,inputs,project_adapter}.py` (F2-owned) |
| Reserves | `financial_engine/financing/{reserve_policy,dsrf}.py`, `dsra/target.py` |
| SHL | `financial_engine/shl/*`, `adapters/shl_cash_seam.py` |
| Tax | `financial_engine/tax/*` |
| Statements | `financial_engine/financial_statements/assembly.py`, `contracts.py` |
| Waterfall / returns | `financial_engine/shareholder_waterfall/*`, `sponsor_returns/*` |
| Orchestration / results | `financial_engine/orchestrator.py`, `results.py` |
| Workbook/persistence | `app/workbook/{registry,input_set}.py`, `workbook_identity.py`, `app/persistence/workspace_repository.py`, `app/v2/router.py` run path, export |

## 6. Invariants to preserve

Existing Solar / Wind reference economics; Data Center and EV financing behavior; SHL methodology; sponsor returns;
Run History; scenario input identity; exports; financial statements. All guarded by the equivalence plan.
