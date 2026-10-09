# Financing F3 — Architecture Blueprint

**Status: FOUNDATION ONLY. Zero production financial behavior change. No multi-tranche activation.**

| Item | Value |
|---|---|
| Verified canonical `main` | `1977033da8967a93d581d6407337798dc0a44aad` (merge of #228) |
| Branch | `feat/model-v2-financing-f3-foundation` (separate worktree) |
| Exact PR head, Draft PR URL, five CI conclusions | recorded in the PR description and final report — a document cannot contain its own commit SHA |
| Parallel workstreams | F1 (Sources & Uses), F2 (Senior Debt Bankability): **no branch or PR exists on GitHub at the time of writing**; the open PR list contained only dependency bumps and #184 (Yield). Nothing of F1/F2 was touched. Their expected files are listed in §9 so a later reviewer can detect overlap. |
| Reference input "FinModels Financing Harvest" | **Not present in the repository or session.** Instrument families were therefore derived from the repository's own financing code and general project-finance practice; no external material was copied. |

## 1. Mission and non-goals

Prepare FINCO for several independent debt facilities and several capital providers, **without** changing today's
single-Senior economics. This PR delivers contracts-on-paper, a catalogue, an integration map, a phased plan and a
financial-equivalence test plan, plus an isolated, tested, *non-authoritative* validation prototype.

Not delivered (deliberately): a multi-tranche engine, Add Debt / Add Equity controls, persistence of instruments, a
second Sources & Uses calculator, preferred equity, investor-level returns, any change to `ProjectInputs`, fingerprints,
Run History or exports.

## 2. Existing economic authorities (verified in code, reused unchanged)

| Concept | Authority today | Location |
|---|---|---|
| Senior debt amount and terms | single set of fields `FinancingParams.senior_debt_amount_keur`, `senior_tenor_years`, `target_dscr`, `lockup_dscr`, `min_llcr`, `debt_sizing_mode`, `gearing_ratio`, `senior_debt_interest_config`, `senior_sculpting_config`, fees (`commitment_fee`, `arrangement_fee`, `structuring_fee`) | `finco_core/inputs/_models.py` (`FinancingParams`) |
| Senior sizing / schedule | `SeniorDebtPolicy` (DSCR_SCULPTED / GEARING_CAP / COMBINED_MINIMUM / EXPLICIT_SCHEDULE), per-period rates / DSCR targets, solver producing one `SeniorDebtSchedules` | `financial_engine/senior_debt/*` |
| Junior funding | scalar `junior_or_other_project_funding_keur` (no terms, no ledger, no interest) | `FinancingParams`, `financing/stack.py` |
| Share capital, share premium, other committed equity | scalars `share_capital_keur`, `share_premium_keur`, `other_equity_funding_before_shl_keur` | `FinancingParams` |
| Additional equity / SHL (residual) | derived by `reconcile_financing_stack`: residual = Uses − Senior − Junior − Capital − Premium − Other equity, assigned to SHL (`SHARE_CAPITAL_THEN_SHL`) or additional equity (`EQUITY_ONLY`) | `financial_engine/financing/stack.py` |
| Shareholder loan economics | typed SHL engine (fixed rate, cash/PIK, bullet / sweep / explicit; inclusive day count) | `financial_engine/shl/*` |
| Construction source allocation | one canonical allocator, waterfall order Share Capital → Share Premium → Other Committed Equity → Additional Equity → SHL → Junior → Senior (Senior is the residual) | `finco_core/construction/allocator.py` |
| IDC, commitment fees, structuring fee, VAT facility | Stage B2 + outer G2A fixed point, **single Senior facility** | `finco_core/construction/stage_b2.py`, `financial_engine/financing/project.py` |
| Project uses | `ProjectUses` (hard CAPEX, explicit financing costs, reserves, other, developer reimbursement/fee) | `financial_engine/financing/contracts.py`, `project_uses.py` |
| Sources & Uses reconciliation | per-period `ConstructionFundingPeriod` + `ConstructionFundingResult` (residual audit) | `financial_engine/financing/stack.py`, `contracts.py` |
| Reserves | DSRA / DSRF policies (single Senior debt service) | `financing/reserve_policy.py`, `dsrf.py`, `dsra/target.py` |
| Tax interest | per-period interest map feeding ATAD / interest limitation; SHL interest eligibility is separate | `financial_engine/tax/*` |
| Cash waterfall | covenant-gated shareholder waterfall: post-senior cash → reserves → distribution account → SHL service → legal-equity distribution | `financial_engine/shareholder_waterfall/*` |
| Investor returns | Pure Equity and Total Sponsor XIRR/MOIC from the sponsor cash-flow ledger (contributions by class, SHL interest/principal, distributions) | `financial_engine/sponsor_returns/*` |
| Developer funding | typed Developer Economics V1 (separate ledger; reimbursement/fee are project uses) | `finco_core/inputs/development.py`, `financial_engine/developer_economics/` |

**Dependency chain (today):** `ProjectInputs.financing` → project uses → Stage B2 (IDC/fees on the single Senior draw) →
G2A fixed point (Senior commitment, residual SHL/equity) → construction funding schedule → Senior solver (operating
schedule) → SHL schedule → tax (interest map) → financial statements → shareholder waterfall → sponsor returns.
Every arrow after "Senior commitment" assumes exactly one Senior facility.

A generic amount field is **not** a facility: `junior_or_other_project_funding_keur` is an unleveraged funding scalar
with no interest, repayment, tax or ledger; it must not be re-labelled as a Junior facility without a new authority.

## 3. Actual engine gaps (what blocks multi-tranche today)

See `F3_ENGINE_INTEGRATION_MAP.md` for exact seams. Summary:
1. One Senior facility is hard-wired through allocator, Stage B2, G2A, solver, DSCR/LLCR, DSRA, tax, statements.
2. No per-facility ledger (opening / draw / interest / principal / closing) exists anywhere.
3. Junior funding has no economics; Preferred/Mezzanine have no authority at all.
4. Sponsor returns assume a single sponsor: contributions are by *capital class*, not by *capital provider*.
5. `ProjectInputs` has no collection field; the Workbook snapshot is a flat string dict.

## 4. Design principles

* **Identity ≠ classification ≠ economics.** A stable `instrument_id` identifies; a `classification_label`
  ("Club Deal", "DFI Loan") describes; only typed economic fields consumed by a canonical authority change numbers.
  Two loans with identical economics produce identical results whatever their label.
* **Presets share engines.** One debt-facility economic engine serves Senior / Construction / Junior / Mezzanine /
  Bond presets when their calculations genuinely match; types differ by *defaults, seniority and permitted terms*,
  not by separate calculators. SHL keeps its existing typed engine (different day-count and tax semantics).
* **Explicit opt-in.** No instrument collection ⇒ the exact current path. Absence is never "zero Senior".
* **Non-circular.** Instrument terms never reference outputs of themselves; derived amounts are marked
  `CANONICAL_SIZING_DERIVED` / `RESIDUAL_DERIVED` and are outputs, not inputs.
* **Documentary vs effective.** A field is editable only when a canonical authority consumes it; otherwise it is
  disabled or labelled documentary.
* **F3 vs F4.** F3 = funding-source structure (who funds what, when, on what terms). F4 = preferred equity and
  investor-level waterfall (who is *paid* what). F3 never invents individual investor returns.

## 5. Candidate prototype (non-authoritative)

`app/model_v2/financing_f3_candidate/` — pure dataclasses + validation + deterministic serialization + a read-only
legacy mapping (fails closed on anything it cannot prove: unset funding mode, unproven SHL repayment modes, unset Senior sizing mode; invents no dates). Not imported by any production module (test-enforced), not persisted, no routes, no financial
result, no Run-fingerprint participation. It exists to make the specification executable and to prove the legacy
Senior can be represented without changing economics. **It is not multi-tranche financing.**

## 6. Backward compatibility and release strategy

* A project with no instrument configuration keeps the exact current path (byte-identical payloads, fingerprints,
  Run History, exports).
* Activation is per project, explicit, versioned, and gated by a *proven* equivalence: a single mapped legacy Senior
  must reproduce current results to the bit before the multi-facility path can be enabled (see test plan).
* Historical Runs are never converted; they keep their run-bound identity.
* Release: ship contract (F3.1) dark → persistence (F3.2) dark → engines (F3.3–F3.5) behind a project-level opt-in
  → UI (F3.6) only once an engine slice is effective → S&U/statements/tax/returns parity (F3.7–F3.8) → cross-vertical
  acceptance (F3.9). Rollback at every phase = disable the opt-in; legacy path untouched.

## 7. Risk assessment

| Risk | Severity | Mitigation |
|---|---|---|
| Circularity between facility sizes, IDC and fees across several facilities | High | extend the existing G2A fixed point; per-facility convergence audit; stop condition if residual > tolerance |
| Silent change to reference economics | High | bit-exact legacy-mapping equivalence gate before any activation |
| Decorative controls (fake preferred return, unconsumed rate fields) | High | field-level `effective | documentary` registry; UI renders documentary fields disabled |
| DSCR/LLCR denominator ambiguity across facilities | High | per-facility and aggregate-senior ratios defined separately; covenants per facility |
| Persistence/CAS/identity regressions | Medium | additive versioned authority following the contingency-authority precedent; no change to existing hashes when absent |
| Scope creep into F4 | Medium | hard F3/F4 boundary in the spec |
| Concurrent F1/F2 edits to S&U / senior files | Medium | contract-first, no shared-file edits now; rebase-free normal merges |

## 8. Timeline (engineering estimate, one engineer + reviewer; excludes waiting on contract approval)

F3.1 3–4 d · F3.2 5–7 d · F3.3 8–12 d · F3.4 6–9 d · F3.5 8–12 d · F3.6 8–12 d · F3.7 6–9 d · F3.8 8–12 d · F3.9 5–8 d
≈ 8–11 weeks serial; ≈ 6–8 weeks with the parallelism in `F3_IMPLEMENTATION_PHASES.md`.

## 9. Parallel-workstream boundary (files this PR does not touch and F3 later must coordinate on)

F1 (Sources & Uses): `app/v2/financing_sources_uses_projection.py`, `app/v2/financing_projection.py`,
`financial_engine/financing/{stack,project,project_uses,generic_product_policy}.py`.
F2 (Senior bankability): `financial_engine/senior_debt/*`, `app/templates/v2/partials/sheet_senior_debt.html`,
`app/v2/router.py` financing routes. This PR changes none of them.

## 10. Exact next PR scope

**F3.1 — Contract and validation authority:** promote the reviewed contract to a canonical namespace
(`finco_core/inputs/financing_instruments.py`), add `to_dict/from_dict` with `schema_version`, validation and
canonical hashing — **still unused by the engine and absent from `ProjectInputs`** — plus the legacy-mapping
equivalence proof against the four reference verticals. Needs financial sign-off on `F3_TYPED_CONTRACT_SPEC.md` first.

## 11. Target Add Debt / Add Equity journey (wireframe-level; the live Financing workbook is NOT modified)

**Add Debt:** `Add instrument` → choose type (preset sets defaults, rank, permitted repayment modes) → amount →
terms (maturity, grace) → interest (fixed / period schedule / base + margin) → repayment mode → fees → covenants →
Save (CAS) → Recalculate (canonical Run) → inspect funding schedule → view Sources & Uses → inspect the instrument's
own results (balance, interest, principal, DSCR/LLCR as defined for that facility).

**Add Equity:** `Add capital provider` → source type → commitment → timing (contribution dates) → funding priority →
Save → Run → inspect actual capital contributions per provider. *Return entitlement is shown only where a supporting
cash-flow ledger exists* — never for preferred/mezzanine before F4.

**Compact table contract (one row per instrument):** Name · Type · Commitment · Drawn · Rate · Maturity · Repayment ·
Rank · Status. Each editable cell carries a field-registry flag `effective | documentary`; documentary cells render
disabled with the reason. No control is shown whose field no canonical authority consumes. Empty collection renders
today's single Senior as read-only ("legacy single facility") with an explicit `Enable multi-instrument financing`
action that records the equivalence evidence (F3.2/F3.6).
