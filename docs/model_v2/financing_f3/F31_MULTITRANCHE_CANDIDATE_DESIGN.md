# F3.1 Institutional Multi-Tranche — Candidate Design & Pre-Integration Matrix

Status: **CANDIDATE-ONLY DESIGN (WF-05A / F3.1). No production activation.**
Branch: `feat/financing-f31-multitranche-candidate` from verified main
`93c549e160772acd8258c26556bd46ff9ca29156` (2026-10-24; V11 Stage 3a+3b with
V10 Stage 1+2 released and blob-pinned).

Companion documents:
- `docs/model_v2/financing_f3/F31_GPT61_ARCHITECTURE_REVIEW_PACKET.md` — the
  structured review packet for the follow-on independent architecture review.
- Existing roadmap authority: `docs/model_v2/financing_f3/F3_IMPLEMENTATION_PHASES.md`
  (F3.1→F3.9 phases), `F3_INSTRUMENT_CATALOGUE.md`, `F3_TYPED_CONTRACT_SPEC.md`,
  `F3_ENGINE_INTEGRATION_MAP.md`. This document **extends** the roadmap; it
  does not replace it.

---

## 1. Mission and hard boundaries

Extend the released **two-pari-passu-Senior** F3.2-4 capability toward
**3+ institutional tranches** as a candidate-only slice:

- ONE smallest incremental slice: **typed N-tranche validation + N-tranche
  facility schedules + multi-instrument source/use reconciliation**, as pure
  candidate code with unit/property tests and **zero changes to canonical
  production output**.
- No modification of `financial_engine/financing/project.py`,
  `financial_engine/shareholder_waterfall/model.py`, any V10/V11 protected
  blob, or any approved financial source (workflow stop condition #6).
- LLCR/PLCR target sizing and senior sweep are **out of scope** (WF-06
  overlap) — interface proposal only (§9).
- Everything stays OFF/release-closed: the candidate is `NON_AUTHORITATIVE`,
  has no route, no persistence surface, and is invisible to product users.

## 2. Live-state anchors (verified 2026-10-24)

| Anchor | State |
|---|---|
| `origin/main` | `93c549e160772acd8258c26556bd46ff9ca29156` (merge PR #360, V11 Stage 3) |
| `finco_core/inputs/financing_instruments.py` | present; F3.1 schema `f3-1.0`; header: "immutable, validated, NOT runtime-activated" |
| `financial_engine/financing/multisenior.py` | present; two-pari-passu-Senior composition (`F3_DATED_FACILITY_CONSTRUCTION_FINANCING_V1`) |
| 2-tranche gate | `finco_core/inputs/multisenior.py:18` — `F3_EXACTLY_TWO_SENIORS_REQUIRED`; authority `F3_TWO_SENIOR_EXPLICIT_COMMITMENTS_V1` |
| Production reachability | two-Senior path IS production-reachable (`app/workbook/multisenior_config.py` `ACTIVATION_ENABLED=True` → `app/v2/router.py` run routes → `serialization.py:1429` payload gate → `financial_engine/financing/project.py:959` isinstance dispatch → exports). Both multisenior files are **blob-pinned** (`F3_2_4_FINANCING_AUTHORITIES`, `tests/model_v2_governance.py:129-137`) and enforced byte-exact by `tests/test_financing_f3_multisenior_governance.py`. |
| V10/V11 chain | `tests/v11_stage3_successor.py`: `PROTECTED_PREFIXES = ("financial_engine/", "finco_core/", "domain/")`; the protected-namespace diff from the V10 checkpoint must be exactly the recognized slices — **any new file under those prefixes breaks `V11_PROTECTED_SCOPE_INVALID`**. `HISTORICAL_AUTHORITY_MODULES` (14 modules) does **not** include `tests/test_financing_f3_canonical_legacy.py`. |
| Scope marker | `docs/model_v2/ACTIVE_EPIC_SCOPE.json` **absent at main** (deleted at RC closeout, `14eee5da`). |
| Quarterly | RC-7B/7C merged release-closed (`period_engine.py` QUARTERLY support + `quarterly_scope.py`, twelve decisions OPEN, `ACTIVATION_ENABLED=False`); orthogonal to F3 — `validate_project_boundary` rejects non-SEMESTRIAL (`F3_PERIOD_FREQUENCY_UNSUPPORTED`). |

**Consequence (architecture):** extending N in place is impossible without
rewriting the release pin chain and the live activation surface. The only
CI-clean candidate shape is the established precedent
(`app/model_v2/financing_f3_candidate`, F3.5-A junior files): a **new
non-authoritative candidate package under `app/model_v2/`** with no route, no
persistence, no `financial_engine` imports, plus a single **additive** entry
in the `test_financing_f3_canonical_legacy.py` AST import allow-list (that
test file is deliberately NOT in `HISTORICAL_AUTHORITY_MODULES`; the F3.5-A
stream used the identical extension pattern).

## 3. Instrument-family policy table (work item 2)

Distinction policy: a row is a **real algorithmic family** only if its cash
economics need different solver/waterfall treatment; a cosmetic label is one
that `classification_label` already covers inside an existing family.

| InstrumentType | F3.1 schema | Released runtime | This candidate (3+ tranches) | Target state | Gap / blocker |
|---|---|---|---|---|---|
| SENIOR_TERM_LOAN | ✔ | ✔ exactly 2, rank 1, fixed cash interest, LEVEL/BULLET, dated construction draws, IDC+fees | ✔ **N ≥ 2**, same per-instrument rules generalized; rank 1 pari passu | N tranches incl. staggered maturities/grace; DSCR-sculpted variant later | real algorithmic family (the only one with released F3 economics) |
| CONSTRUCTION_FACILITY | ✔ typed | ✖ (validator: SENIOR_TERM_LOAN only) | ✖ fail-closed `F3_MULTITRANCHE_INSTRUMENT_UNSUPPORTED` | distinct availability window + draw-autopilot + conversion-to-term | needs: availability-period semantics, expiry/limit math, auto-conversion policy (owner) |
| JUNIOR_DEBT | ✔ typed | ✔ separate candidate F3.5-A (ONE junior under ONE senior; `junior_debt.py` reuses `build_facility_schedules`) | ✖ fail-closed (rank > 1 → `F3_PARI_PASSU_SENIOR_ONLY`) | junior + multi-senior composition; intercreditor between junior and N seniors | needs: junior ranking vs N seniors, combined service waterfall slotting (owner) |
| MEZZANINE_DEBT | ✔ typed | ✖ | ✖ fail-closed | PIK/cash mix, exit fees, equity kicker | no economics exist anywhere; owner policy + solver design |
| SHAREHOLDER_LOAN | ✔ typed | canonical engine: full SHL; F3: fail-closed (`F3_ACTIVE_SHL_INTEGRATION_NOT_RELEASED`) | ✖ fail-closed | SHL alongside N seniors | needs: SHL/subordination vs tranches, PIK waterfall slot (owner) |
| BOND | ✔ typed | ✖ | ✖ fail-closed | coupon schedule + indenture conventions (30/360, semiannual coupons, day-count resets) | no accrual conventions implemented; owner policy |
| COMMON_EQUITY / SHARE_PREMIUM / ADDITIONAL_EQUITY | ✔ typed | canonical financing params (non-F3); F3: provider economics fail-closed (`F3_PROVIDER_ECONOMICS_UNSUPPORTED`) | ✖ (labels only) | provider-level equity accounting | owner decision on provider ledger |
| PREFERRED_EQUITY | ✔ typed | ✖ schema fails closed (`F3_PREFERRED_EQUITY_DEFERRED`) | ✖ | F4 investor waterfall | blocked on F4 |
| GRANT / DEFERRED_PAYMENT / DEVELOPER_REIMBURSEMENT | ✔ typed | ✖ | ✖ | OTHER-family uses treatment | owner policy (uses-side credits) |

**Not yet financially supported (explicit):** everything outside
SENIOR_TERM_LOAN; PIK interest; floating/period-scheduled rates inside F3;
DSCR-sculpted tranche repayment inside F3; reserves (DSRA/DSRF) for F3;
provider-level equity; currencies other than EUR; non-SEMESTRIAL axes;
junior/mezz in the same collection as 3+ seniors; LLCR/PLCR target sizing
and senior sweep (WF-06).

## 4. Current-vs-target F3.1 matrix (backend)

| Capability | Released (main 93c549e1) | Candidate slice (this PR) | Release target |
|---|---|---|---|
| Typed proposal schema (13 types) | ✔ `f3-1.0` | consumed unchanged | stable |
| Activation authority | `F3_TWO_SENIOR_EXPLICIT_COMMITMENTS_V1` (exactly 2) | new `F31_MULTITRANCHE_CANDIDATE_V0` (N ≥ 2), **non-authoritative, no activation surface** | owner rename/promotion decision |
| Facility schedules | 2 facilities, canonical kernels | N ≥ 2 facilities, candidate math **proven equal** to released math at N=2 (1e-9 property test) | swap-in after review |
| Aggregate senior contract | ✔ through canonical `EXPLICIT_SCHEDULE` solver + handshake | out of slice (design §7.4; needs engine seam = Gate R) | reviewed integration PR |
| Construction IDC/fees | ✔ per-instrument dated draws, Stage-B2 capitalization | candidate math mirrored; capitalization out of slice | same |
| Source/use reconciliation | ✔ (`allocate_construction_sources_per_period` + stack) | candidate reconciliation with supplied canonical uses; equity-first fill after contractual senior draws | same |
| Gearing cap | ✔ constraint (`F3_AGGREGATE_GEARING_CAP_EXCEEDED`) | ✔ same rule | same |
| Reserves (DSRA/DSRF) | ✖ `F3_RESERVE_INTEGRATION_NOT_RELEASED` | ✖ unchanged (workflow item 5: reserve failures stay fail-closed) | owner Gate R |
| SHL / PIK | ✖ in F3 | ✖ unchanged | owner Gate R |
| Junior alongside 3+ seniors | ✖ | ✖ | F3.5-B+ |
| Quarterly axis | separate release-closed candidate | ✖ SEMESTRIAL only | RC-7 decisions |
| Waterfall | ✔ released two-senior waterfall | ✖ untouched (3+ tranche waterfall is design-only §7) | Gate R |

## 5. Backend dependency graph (what 3+ tranches touches)

```
FinancingCollection (f3-1.0, unchanged)
  └─ [CANDIDATE] validate_multitranche_collection        (new, pure)
       └─ [CANDIDATE] build_candidate_facility_schedules (new, pure; mirrors
            released build_facility_schedules math on plain date/period inputs)
            ├─ primitives mirrored: level/bullet principal, ACT_360/365
            │  period_day_fraction, per-draw construction IDC,
            │  undrawn-integral commitment fee, upfront fee
            └─ [CANDIDATE] reconcile_multitranche_sources_uses (new, pure)
                 inputs: total_project_uses_keur + period_uses_keur
                 (canonical authority outputs, supplied), gearing_ratio,
                 equity seeds, REQUIRED canonical CFADS map
Released (untouched): build_facility_schedules → build_aggregate_contract
  → run_multisenior_financing → canonical solver/CFADS/tax/waterfall/statements
Future Gate-R integration seam: candidate schedules → aggregate contract →
  canonical solver (replaces build_aggregate_contract input path) → existing
  handshake F3_FACILITY_AGGREGATE_HANDSHAKE_FAILED unchanged
```

## 6. Candidate contract (implemented in this slice)

Module `app/model_v2/financing_f31_multitranche_candidate/` —
`NON_AUTHORITATIVE = True`; imports ONLY
`finco_core.inputs.financing_instruments` + stdlib; no route; no persistence;
no `financial_engine`/persistence/fastapi/sqlite3 imports (AST-pinned by its
own test).

- `F31_MULTITRANCHE_CANDIDATE_V0` — authority string; deliberately distinct
  from the load-bearing `F3_TWO_SENIOR_EXPLICIT_COMMITMENTS_V1` (which gates
  workspace CAS, payload deserialization, run evidence and exports).
- `validate_multitranche_collection(collection)` — per-instrument rules are
  the released two-senior rules **verbatim** (same stable codes:
  `F3_PARI_PASSU_SENIOR_ONLY`, `F3_FIXED_CASH_INTEREST_ONLY`,
  `F3_REPAYMENT_UNSUPPORTED`, `F3_EXPLICIT_CALENDAR_MATURITY_REQUIRED`,
  `F3_FULL_EXPLICIT_DRAWS_REQUIRED`, `F3_FEE_UNSUPPORTED`,
  `F3_DUPLICATE_EFFECTIVE_FEE`, `F3_PROVIDER_ECONOMICS_UNSUPPORTED`), plus
  the count generalization: N ≥ 2
  (`F3_MULTITRANCHE_COUNT_UNSUPPORTED` below 2; the released exactly-2 code
  remains untouched for the released authority).
- `build_candidate_facility_schedules(collection, construction_periods,
  operating_periods, day_count)` — one `CandidateFacilitySchedule` per
  instrument on **plain date inputs** (maturity must match exactly one
  operating period end; grace via `relaxed relativedelta`; two-pass
  principal-plan → interest-on-profile → final roll, mirroring released
  math exactly; per-draw construction IDC from own draw date; undrawn-
  integral commitment fee; upfront once). Fail-closed:
  `F3_MATURITY_NOT_ON_OPERATING_BOUNDARY`, `F3_GRACE_EXCEEDS_MATURITY`,
  `F3_FACILITY_MATURITY_UNSETTLED`, `F3_DRAW_OUTSIDE_CONSTRUCTION`.
- `reconcile_multitranche_sources_uses(facilities, *, total_project_uses_keur,
  period_uses_keur, gearing_ratio, share_capital_keur, share_premium_keur,
  other_equity_keur, cfads_by_period=None)` — aggregate = Σ commitments;
  gearing cap as constraint; per-period contractual senior draws vs uses
  (`F3_PERIOD_OVERFUNDING`); uses reconciliation; equity residual fill
  (share capital → premium → other → additional equity) after contractual
  senior draws; required canonical-CFADS coverage check on the aggregate service per operating period; equity commitments are depleting pools across all construction periods
  (`F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL`).

## 7. 3+ tranche design (work item 3 — design level, NOT implemented)

### 7.1 Cashflow waterfall slotting (operating periods)

```
CFADS (canonical, bank case)
→ 1. N senior tranches' cash debt service — ranked rank-1 pari passu;
     within equal rank and equal maturity: pro-rata by commitment;
     DIFFERENT maturities: each pays its own contractual service;
     shortfall inside rank 1 (aggregate contractual service > CFADS):
     fail-closed F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL (released rule —
     contractual commitments are never resized by cash)
→ 2. (future) rank-2 junior/mezz service — intercreditor: junior is paid
     ONLY after aggregate rank-1 service; subordination is structural
→ 3. DSRA top-up (released policy; sized on next payment — see §8)
→ 4. distributions per the canonical sponsor waterfall (unchanged)
```

### 7.2 Funding order (construction periods) — released semantics, documented

Contractual dated senior draws are **committed first** (they are contractual
facts, and dated-draw IDC accrues from each draw date); the equity allocator
(`allocate_construction_sources_per_period`: share capital → share premium →
other committed → additional equity; SHL/junior/senior-residual = 0 under
F3) fills the residual uses. A period whose dated draws exceed its funded
uses fails closed (`F3_PERIOD_OVERFUNDING`) — the released rule prevents
senior cash funding anything outside that period's uses.

### 7.3 Invariants (owner-review list)

1. Σ facility closing at each maturity == 0 (`F3_FACILITY_MATURITY_UNSETTLED`).
2. Σ facility interest/principal/DS per period == aggregate (released
   handshake `F3_FACILITY_AGGREGATE_HANDSHAKE_FAILED`).
3. Aggregate senior ≤ gearing capacity (constraint, never a resizing
   authority — `F3_AGGREGATE_GEARING_CAP_EXCEEDED`).
4. No interest capitalisation between periods (construction IDC is
   capitalized to uses once, never compounded into balances).
5. Deterministic ordering by (seniority_rank, instrument_id) — never
   insertion order.
6. Proposal identity: `content_digest()` is proposal identity only, never a
   run fingerprint.
7. All-or-nothing activation: a collection is validated whole; no partial
   enablement.

### 7.4 Unavoidable owner policy decisions (Gate R list)

| # | Decision | Why it cannot be derived |
|---|---|---|
| O-1 | Promote `F31_MULTITRANCHE_CANDIDATE_V0` to an activation authority (rename + `ACTIVATION_ENABLED` surface + pin-chain successor) | release decision, not derivable |
| O-2 | Staggered maturities: allowed maturities set and whether the earliest maturity retires its tranche into the waterfall while later tranches persist | covenant-structure policy |
| O-3 | Pro-rata rule inside a same-maturity shortfall (commitment-pro-rata adopted as candidate default) | legal intercreditor policy |
| O-4 | Reserve (DSRA/DSRF) integration for multi-tranche (sizing basis: aggregate vs per-tranche next-payment) | `F3_RESERVE_INTEGRATION_NOT_RELEASED` is an explicit owner boundary |
| O-5 | Junior/mezzanine ranking relative to N seniors; mezzanine PIK economics | needs F4 waterfall policy |
| O-6 | SHL coexistence with N seniors (currently EQUITY_ONLY) | owner boundary |
| O-7 | Bond accrual conventions (30/360 vs ACT, coupon dates) if BOND enters | convention policy |
| O-8 | Quarterly (or other) model axis combined with multi-tranche | RC-7 decisions OPEN |
| O-9 | LLCR/PLCR target sizing + senior sweep with tranches | explicitly deferred to WF-06 |
| O-10 | Facility-level fees in institutional export granularity | product surface |

## 8. Edge cases (fail-closed or documented)

- Maturity on a non-operating-boundary date → `F3_MATURITY_NOT_ON_OPERATING_BOUNDARY`.
- Grace longer than the tranche's own window → `F3_GRACE_EXCEEDS_MATURITY`.
- Draw dates outside construction → `F3_DRAW_OUTSIDE_CONSTRUCTION`.
- Duplicate fee kinds on one instrument → `F3_DUPLICATE_EFFECTIVE_FEE`.
- Two tranches with the same instrument id → `F3_DUPLICATE_INSTRUMENT_ID` (schema).
- Mixed repayment modes across tranches (level + bullet) → **allowed** (released tests already mix).
- Equal maturity dates across tranches → allowed (pari-passu wall; pro-rata rule = O-3).
- Non-finite / negative commitments → schema-level `F3_NON_FINITE_VALUE` / `F3_NEGATIVE_VALUE`.
- Empty construction (draws present, no construction periods) → `F3_DRAW_OUTSIDE_CONSTRUCTION`.
- CFADS missing for an operating period with contractual service → `F3_CFADS_EVIDENCE_MISSING` (Correction A: a missing value is never treated as 0 CFADS or as a pass); an invalid value → `F3_CFADS_EVIDENCE_INVALID`; omitting the CFADS map entirely fails closed. CFADS is only ever compared, never used to resize.

## 9. Interface proposal for WF-06 (out of scope here, no code)

`SeniorDebtPolicy` gains an optional per-tranche decoration seam
(`tranche_id` on facility schedules — already present as `instrument_id`);
LLCR/PLCR target sizing would consume per-tranche senior-axis windows
(`repayment_start/maturity` per facility) instead of the single window; the
senior sweep would operate on the aggregate residual after rank-1 service.
**No implementation** in this candidate; recorded for WF-06 design review.

## 10. Unchanged-baseline evidence (this PR)

- Branch diff touches ONLY: `app/model_v2/financing_f31_multitranche_candidate/**`
  (new), `tests/test_financing_f31_multitranche_candidate.py` (new),
  `tests/test_financing_f3_canonical_legacy.py` (+1 allow-list path, additive),
  `docs/model_v2/financing_f3/F31_*.md` (new). **Zero diff** under
  `financial_engine/`, `finco_core/`, `domain/` → V10/V11 protected-namespace
  chain intact → Solar/Wind/DataCenter/EV canonical outputs bit-identical by
  construction; additionally verified locally:
  `test_reference_canonical_last_run.py`, model-validation contracts,
  `test_financing_f3_multisenior*.py` (released authority untouched),
  `test_financing_f3_governance.py`, `test_financing_f35b_release_closed.py`,
  `test_f39_four_vertical_acceptance.py`.
- No V10/V11 protected path, release-surface file, or historical authority
  module is modified (verified against `v11_stage3_successor.py` lists).

## 11. Estimated release-integration size (post-review, Gate R)

Swap-in of the candidate validator + N-tranche schedules into the released
multisenior path (new blobs at the two pinned paths + pin-chain successor +
owner record): ≈ 400–600 lines + governance PR. NOT in this PR.
