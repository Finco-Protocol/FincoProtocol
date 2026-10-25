# F3.1 Multi-Tranche Candidate — GPT-6.1 Architecture Review Packet

Purpose: structured input for the follow-on independent architecture review
(GPT-6.1) of the release integration of the F3.1 multi-tranche candidate.
**No self-approval is claimed**; every open decision in §6 requires an
explicit Financial Owner / independent-review resolution before Gate R.

Review target: branch `feat/financing-f31-multitranche-candidate`
(candidate slice PR against main), design document
`docs/model_v2/financing_f3/F31_MULTITRANCHE_CANDIDATE_DESIGN.md`.

---

## 1. Verified context (reviewer: re-verify, do not trust)

- Analyzed main at slice authoring: `93c549e160772acd8258c26556bd46ff9ca29156`
  (PR #360, V11 Stage 3a+3b + V10 Stage 1+2 released). **Main advanced during
  the work to `b72942f22f1d3a8dcce351b56b96fdba0e6b9cdd`** (PR #363, Revenue
  V4 candidate); the branch was re-synced onto the new main per the mandatory
  live-preflight rule and the full battery re-run there (691 passed / 0
  failed, including `tests/test_revenue_v4_candidate.py`).
- Released two-Senior authority: `finco_core/inputs/multisenior.py` +
  `financial_engine/financing/multisenior.py`, blob-pinned
  (`F3_2_4_FINANCING_AUTHORITIES`), production-reachable
  (`app/workbook/multisenior_config.py` `ACTIVATION_ENABLED=True` → v2 run
  routes → serialization → exports), enforced byte-exact by
  `tests/test_financing_f3_multisenior_governance.py`.
- V10/V11 chain: `tests/v11_stage3_successor.py`
  `PROTECTED_PREFIXES = ("financial_engine/", "finco_core/", "domain/")`;
  the protected diff from the V10 checkpoint must be exactly the recognized
  slices → new files under those prefixes are impossible without a
  governance PR; new files under `app/` are chain-safe (proven: the chain
  test passes on this branch).

## 2. What the candidate slice IS

A non-authoritative package `app/model_v2/financing_f31_multitranche_candidate/`
(`NON_AUTHORITATIVE = True`, authority string
`F31_MULTITRANCHE_CANDIDATE_V0`, imports ONLY
`finco_core.inputs.financing_instruments` + stdlib + dateutil; no route, no
persistence, no activation surface), providing:

1. `validate_multitranche_collection` — the released two-Senior per-
   instrument rules verbatim (same stable `FinancingError` codes),
   generalized to N ≥ 2 pari-passu senior tranches (new count code
   `F3_MULTITRANCHE_COUNT_UNSUPPORTED`; the released exactly-2 validator is
   untouched and still enforced).
2. `build_candidate_facility_schedules` — N-tranche contractual ledgers
   (level-principal/bullet, grace via canonical op[0] + relativedelta,
   two-pass principal-plan → interest-on-profile → final roll, per-draw
   construction IDC from own draw date, undrawn-integral commitment fees,
   upfront once) on plain date inputs, mirroring the released math.
3. `reconcile_multitranche_sources_uses` — aggregate = Σ commitments; gearing
   cap as constraint (`F3_AGGREGATE_GEARING_CAP_EXCEEDED`); contractual dated
   senior draws fund uses first, equity allocator fills the residual
   (share capital → premium → other → additional); `F3_PERIOD_OVERFUNDING`,
   `F3_CONSTRUCTION_USES_DO_NOT_RECONCILE`, `F3_SOURCES_USES_UNRECONCILED`,
   required canonical-CFADS coverage of the TOTAL contractual service of all
   tranches per operating period (`F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL`;
   missing / invalid evidence: `F3_CFADS_EVIDENCE_MISSING` / `_INVALID`).

One governance test edit: **+3** candidate paths (`validation.py`, `schedules.py`,
`reconciliation.py`) in the `test_financing_f3_canonical_legacy.py` AST import
allow-list (that file is NOT in the V11 `HISTORICAL_AUTHORITY_MODULES` pin set —
verified; the F3.5-A stream used the identical additive pattern). Correction A
reduced the original +4 to +3: the package `__init__.py` imports no
`financing_instruments` module and was dropped (least privilege).

## 2a. Correction A (post independent review) — what changed and why

1. **Equity funding commitments (defect):** `reconciliation.py` offered the FULL
   share-capital / premium / other / additional commitment to EVERY construction
   period, so a commitment already drawn could be drawn again (reproduced: share
   capital drawn 200 against a commitment of 100, additional equity under-drawn
   200 of 300, while sources still equalled uses). The four commitments are now
   DEPLETING pools across all periods in the released waterfall order, and the
   aggregate actual draws per source, the senior draws and the total uses are
   reconciled (`F3_EQUITY_COMMITMENT_EXCEEDED`, `F3_SOURCES_USES_UNRECONCILED`,
   `F3_DRAWDOWN_EXCEEDS_COMMITMENT`, `F3_MULTITRANCHE_INPUT_INVALID`).
   Equivalence with the released `allocate_construction_sources_per_period` is
   tested (multi-period synthetic cases) and with the released engine on Solar and
   Wind (N=2, 1e-9).
2. **Contractual CFADS coverage (defect):** the check compared EACH tranche's
   service with the full CFADS, so three tranches of 40 passed against a CFADS of
   100 (aggregate 120). It now compares the TOTAL service of all tranches in each
   operating period (the released rule compares the aggregate senior service).
   CFADS evidence is REQUIRED: a missing value for a period with service raises
   `F3_CFADS_EVIDENCE_MISSING`, an invalid one `F3_CFADS_EVIDENCE_INVALID`
   (previously `.get(idx, 0.0)` turned a missing value into a mislabelled
   shortfall, and omitting `cfads_by_period` skipped the check entirely).
3. **Import-ownership allow-list review:** the extension is per file (no
   directory wildcard), consistent with the F3.5-A precedent, and the original
   purpose (only narrowly owned modules import the F3 financing contract) is
   preserved. Two gaps were closed: the unneeded `__init__.py` entry was removed,
   and the reverse direction — the allow-list lets the candidate import the
   contract, so nothing outside the package may import the candidate — is now
   pinned by `test_no_other_module_imports_the_candidate_package`. Negative
   controls prove that an unlisted sibling file, the package `__init__.py`, a
   look-alike package and a nested module are still rejected. No import
   restriction, protected pin or the released exactly-two-Senior validator was
   weakened.

## 3. Evidence produced (exact-head, reviewer re-run commands)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/test_financing_f31_multitranche_candidate.py`
  → **78 passed after Correction A** (19 originally; the Correction A additions
  are listed in §2a: depleting equity pools with an exact-rational oracle, N=3
  hand cases, aggregate CFADS coverage, missing/invalid CFADS, N=2 equivalence
  with the released allocator and with the released engine on Solar and Wind,
  and the reverse-direction import guard; 53 of them fail against the previous
  reconciliation source and all 14 guard mutations are caught). Original
  contents: isolation pins (AST: no engine/persistence/route imports),
  released-rule matrix at N=3, hand-computed 3-tranche schedules (ACT_365,
  exclusive-end day counts, per-draw IDC, undrawn-integral fees), **N=2
  equivalence with the released engine on Solar and Wind at 1e-9**, released
  validator still exactly-2, reconciliation matrix, scenario combinations
  (SHL/mezzanine/construction-facility/bond/PIK/reserves/quarterly all fail
  closed with the released codes).
- Correction A validation: **1002 passed / 3 skipped** over every F3 financing
  suite (the multisenior governance pins included), `test_ci_acceptance.py`,
  `test_revenue_v4_candidate.py`, Finance Integrity / WF07 / PPA-01 governance and
  the API reference runs; `test_financing_f3_junior_governance.py` cannot be
  collected in a shallow clone (it `git show`s a historical commit) and fails
  identically on pristine main. Public safety scan PASS.
- Full battery on the previously synced branch (before Correction A): **691 passed / 0 failed** incl. all F3
  governance suites, `test_ci_acceptance.py` (V10/V11 chain),
  `test_reference_canonical_last_run.py` (Solar/Wind/DC/EV canonical Last
  Run equivalence), public engine smoke, `test_revenue_v4_candidate.py`.
- Protected-namespace diff (`financial_engine/`, `finco_core/`, `domain/`)
  vs main: **empty** — unchanged-baseline evidence by construction plus the
  equivalence suites above.

## 4. Architecture questions for the reviewer (priority order)

Q1. **Aggregate-contract integration seam.** The released path composes
facilities → `build_aggregate_contract` → canonical `EXPLICIT_SCHEDULE`
solver → handshake. The candidate stops before that seam (it would require
importing `financial_engine`). Reviewer: is the proposed Gate-R integration
(candidate validator + schedules replace the exactly-2 validator + released
builder behind the same `run_multisenior_financing` entry, handshake codes
unchanged) the minimal-risk path, or should the aggregate contract move into
the candidate first?

Q2. **Interest-on-profile two-pass.** Tranche interest accrues on the
principal-plan opening profile (released semantics; no interest
capitalisation between periods). For 3+ tranches with staggered maturities,
is per-tranche independent rolling correct even when a shorter tranche
retires while longer ones persist (aggregate opening = Σ live tranches)?
The N=2 equivalence test covers staggered maturities (16/20); is an
explicit golden for a 3-tranche staggered case required before Gate R?

Q3. **Same-maturity shortfall pro-rata.** Candidate default: contractual
service inside rank 1 is never resized (released
`F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL`); pro-rata by commitment inside a
same-maturity wall is listed as owner decision O-3. Reviewer: confirm the
released fail-closed rule composes correctly for N tranches, or flag cases
where waterfall slotting (§7.1 of the design doc) needs a different rule.

Q4. **DSRA/DSRF exclusion boundary.** Reserves stay fail-closed
(`F3_RESERVE_INTEGRATION_NOT_RELEASED`). Design §8 proposes a payment-aware
forward debt-service lookup for a later reserve slice. Reviewer: confirm
that multi-tranche reserve sizing should be specified against the AGGREGATE
next payment (not per-tranche), before any implementation.

Q5. **Serialization/activation surface.** When promoted, the new authority
string must satisfy three gates consistently (workspace CAS
`apply_state`, payload deserialization `serialization.py:1429`, run/export
evidence binding). Reviewer: is a **separate** activation payload schema
(`{authority, proposal_digest, sponsor_funding_mode, reserve_support_mode}`)
with the new string sufficient, or should the F3.1 collection digest move
into the activation payload at promotion time?

Q6. **WF-06 interface.** LLCR/PLCR target sizing + senior sweep stay out of
scope (design §9 records the per-tranche senior-axis window seam). Reviewer:
validate that per-facility `(repayment_start, maturity)` windows are the
right WF-06 interface handoff.

## 5. Known limitations (declared, not hidden)

- No aggregate contract through the canonical solver inside the candidate
  (engine-import isolation); the N=2 equivalence + released handshake codes
  are the bridge evidence.
- Candidate reconciliation takes `total_project_uses_keur` /
  `period_uses_keur` / `additional_equity_keur` as SUPPLIED canonical
  outputs — it never sizes uses or equity itself.
- Reserved-but-unimplemented instrument types (mezzanine, bond,
  construction facility, preferred, OTHER family) fail closed; only
  SENIOR_TERM_LOAN tranches compose.
- SEMESTRIAL axis only; the quarterly candidate chain is orthogonal and its
  own activation remains closed.

## 6. Decisions required before Gate R

O-1 authority promotion; O-2 staggered-maturity policy; O-3 shortfall
pro-rata rule; O-4 reserve sizing basis; O-5 junior/mezz ranking vs N
seniors; O-6 SHL coexistence; O-7 bond conventions; O-8 quarterly ×
multi-tranche; O-9 WF-06 handoff confirmation; O-10 export granularity.
(Full table with rationale: design doc §7.4.)

## 7. Reviewer verification checklist

1. Re-run the two commands in §3 at the PR exact head; compare counts.
2. `git diff <merge-base> HEAD --name-only -- financial_engine/ finco_core/ domain/`
   → must be empty.
3. Confirm the allow-list edit is the ONLY governance-adjacent change and is
   additive (3 explicit candidate paths, comment-marked, file not in
   `HISTORICAL_AUTHORITY_MODULES`), that the new negative controls reject
   unlisted candidate files, and that nothing outside the package imports the
   candidate.
4. Read `build_candidate_facility_schedules` against the released
   `build_facility_schedules` side-by-side and confirm rule-for-rule
   equivalence (the N=2 test is the executable proof).
5. Answer Q1–Q6; resolve O-1…O-10 ownership.
