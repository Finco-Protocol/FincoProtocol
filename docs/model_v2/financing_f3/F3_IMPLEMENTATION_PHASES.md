# Financing F3 — Implementation Phases

Nothing below starts in this PR. Effort = one engineer plus independent financial review. **Every phase has the
rollback "disable the project-level opt-in / do not enable; legacy path untouched."** Common CI gates: the five
required exact-head workflows, frozen-namespace diff review, reference equivalence suite (see test plan).

| Phase | Scope / exact files & contracts | Depends on | Test strategy | Financial-equivalence requirement | Stop conditions | Effort |
|---|---|---|---|---|---|---|
| **F3.1 Contract & validation authority** | new `finco_core/inputs/financing_instruments.py`; serialization; canonical hash; legacy mapping; **not** wired into `ProjectInputs` yet | approved `F3_TYPED_CONTRACT_SPEC.md` | validation, determinism, round-trip, mapping on 4 references | none (no runtime effect); `hash_inputs_for_cache` identical | contract rejected in review; any import from engine path | 3–4 d |
| **F3.2 Versioned persistence & migration** | optional `ProjectInputs.financing_instruments=None`; typed authority persistence with CAS (`workspace_repository`, `workbook_identity`, `input_set`); explicit opt-in action | F3.1 | CAS/owner/protected/scenario isolation; absent ⇒ byte-identical payload + hashes; no auto-migration | disabled ≡ reference bit-exact; Run History/exports untouched | any hash change when absent; any silent rewrite | 5–7 d |
| **F3.3 Multiple Senior facilities & rate schedules** | per-facility Senior solver instances, rate schedules, fees, IDC/commitment per facility (`senior_debt/*`, Stage B2, G2A); aggregate vs facility DS | F3.2; **F2 settled** | single mapped legacy Senior ≡ today; two-facility synthetic vs independent recomputation; fixed-point convergence | legacy-mapped run bit-exact on 4 references | non-convergence; DSCR denominator ambiguity unresolved | 8–12 d |
| **F3.4 Drawdown & repayment schedules** | per-facility draw vectors in allocator; repayment modes; grace; maturity | F3.3 | allocator property tests; underfund/overfund fail-closed; residual audit | legacy order reproduced exactly | residual > tolerance | 6–9 d |
| **F3.5 Junior / Mezzanine / SHL compatibility** | debt-facility presets for Junior/Mezz/Bond; per-provider SHL and equity ledger; waterfall insertion by rank; sweeps | F3.3, F3.4 | waterfall ordering, PIK, provider ledger reconciliation | Total Sponsor / Pure Equity unchanged for legacy mapping | investor-return semantics needed (→ F4) | 8–12 d |
| **F3.6 Add Debt / Add Equity UI** | new isolated workbook partials/projection; effective-vs-documentary field registry; compact tables | F3.3 (≥ one effective slice) | route/auth/CAS tests, Chromium, no fake controls | UI adds no calculation | any control whose field no engine consumes | 8–12 d |
| **F3.7 S&U reconciliation** | F1's S&U projection reads per-instrument funding; one reconciliation | F3.4; **F1 settled** | S&U identity per period and in total; constraint-precedence report | S&U for legacy mapping identical | second S&U calculator appears | 6–9 d |
| **F3.8 Statements, Tax, Investor Returns parity** | per-facility liabilities/interest; tax interest map; sponsor ledger by provider; export parity | F3.5, F3.7 | statement identities (balance check), tax recomputation, export parity | all legacy outputs identical | balance sheet fails; export mismatch | 8–12 d |
| **F3.9 Cross-vertical acceptance** | Solar, Wind, Data Center, EV: legacy-mapped and ≥ 1 multi-facility scenario each; browser acceptance; performance | all | golden regression + browser + governance full history | every reference bit-exact | any reference drift | 5–8 d |

## Parallelism (only AFTER the F3.1 contract is approved)

* F3.2 (persistence) ∥ F3.3 core engine work on a synthetic in-memory collection (no persistence dependency).
* F3.6 UI design/components ∥ F3.3–F3.5, but UI **ships** only after an effective engine slice exists.
* F3.7 (S&U) can start once F3.4's per-instrument funding vectors are stable; F3.8 tax/statements/returns streams
  can run in parallel with each other after F3.5.
* Serial: F3.1 → F3.3 → F3.4; F3.9 last.

## Coordination with F1 / F2

F3.3 and F3.7 touch F2's and F1's files respectively; they start only after those workstreams merge (or are
explicitly coordinated). Normal merges only; no rebase/squash/force-push.
