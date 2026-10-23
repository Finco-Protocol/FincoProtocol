# V9-P2a / OD-R — Stage 2 governance successor

**Status:** release-closed exact-content successor on PR #332 (Draft). This is not a merge authorisation, product activation or
financial release. The canonical default is unchanged, and no product path selects OD-R.

## Authorisation basis

| Item | Value |
|---|---|
| Independent financial review | Coordinator verdict *FINANCIAL CONTENT APPROVAL RECOMMENDED* (Correction F final candidate `2764f21a`) |
| Financial Owner exact-content decision | Given explicitly in the Stage 2 session for exactly the four blobs below. It covers that content only, not future changes, merge or activation. It is recorded as provenance (`RECORDED_NOT_AUTHENTICATED`); no authenticated GitHub attestation is claimed. |

| Path | Approved blob |
|---|---|
| `financial_engine/shl/maturity_authority.py` | `b5fc2715cf4fb769878eb0534c95eb150479328f` |
| `financial_engine/financing/generic_product_policy.py` | `b7df63cd5be886d5971213c03f9bfff046913ae1` |
| `financial_engine/financing/project.py` | `3bc6c097b218d27be216cdd86133f2772a82ad70` |
| `financial_engine/shareholder_waterfall/model.py` | `9520b09b135c7fe39d3d4fac6a0c2462b7c1c4ca` |
| `financial_engine/orchestrator.py` (carried, previously accepted) | `85c8008f2b4a656fd28eea1169689b19131576e4` |
| `financial_engine/shl/production.py` (carried, previously accepted) | `9bb852c235a988bff994c4327b3b63dd6d77ae20` |
| `app/services/production_financial_authority.py` (application provenance, carried) | `89083cd41a4de029ae3c57ee0a4f4a871c7863bd` |

## Successor contract (`tests/v9p2a_odr_successor.py`)

`odr_violations()` returns `[]` only when every condition below holds:

- **Authentic chain:**
  - RC-7C main `5996453b`, its #333 integration `96e58164` (with exact parents) and the reviewed candidate `2764f21a` are ancestors.
  - RC-7C is still recognised at both RC-7C checkpoints.
- **Exact blobs:**
  - The six paths match the table above at `2764f21a` and at the evaluated ref.
  - The other nine RC-7C paths keep their exact RC-7C blobs.
- **Scope:** the protected (`financial_engine/`, `finco_core/`, `domain/`) diff from `96e58164` is exactly the six paths.
- **Pinned files:**
  - The application provenance blob is exact.
  - The nine pin-carrying historical authority modules are byte-identical to RC-7C main.
  - The wiring hub `tests/quarterly_candidate_recognition.py` is exactly `5ebee89a…`. The hub does not pin the successor, so the pin is not circular.
- **Release closed:**
  - The M7, Revenue, Junior and quarterly flags are literal `False`.
  - The OD-R selector default is canonical.

The hub has a third, mutually exclusive state, `"ODR"`. In that state:

- `candidate_blobs()` is the twelve RC-7C paths with the OD-R replacements, plus the three OD-R paths outside the twelve.
- `CANDIDATE_PATHS` stays the twelve.
- `approved_frozen_path` and `released_engine_authority_matches` never consult recognition.
- RC-7B and RC-7C validators are not widened, so neither recognises the OD-R tree as its own state.

## Resolution of the 27 governance failures

| Group | Nodes | Resolution |
|---|---|---|
| Current-state guards consuming the hub (finance integrity ×2, F3 junior, F3 multisenior, WF-04, WF-07, RC-3 post-merge ×2, RC-7 RC7A compatibility, PPA-01 m7-coexistence, M7 boundaries) | 11 | `"ODR"` state in the hub; no test change, except that the PPA-01 and M7 slice exclusion now uses `candidate_blobs()` instead of the literal twelve |
| Historical RC-7C contract assumed HEAD = RC-7C (`test_rc7c_candidate_successor` ×7) | 7 | judged at `historical_subject()`, which is HEAD, or `96e58164` only while HEAD is the complete OD-R successor; negative controls clone that checkpoint; added an assertion that RC-7C and RC-7B never recognise the OD-R tree |
| Correction B proposal assumed HEAD = proposal content | 2 | judged at its own checkpoint `dddfff4e`; HEAD is asserted *not* to be the proposal; no-approval states asserted at both refs |
| F3 governance state tuple | 1 | accepts `"ODR"` only together with RC-7C at its checkpoint and closed OD-R states |
| Finance-integrity stream guard | 1 | exact, documented exception: `shl/production.py` has a pre-existing path-only allow-list exemption (P0 / Runtime V4, no content pin), so `approved_frozen_path` was already True on main |
| M7 / PPA-01 content-violation slices | 3 | the recognised slice (`candidate_blobs()`) replaces the literal twelve; shared M7 paths are asserted to be still exactly the two RC-7B ones |
| Windows only (cp1252 decoding of git output, CRLF working tree) | 4 (+ the M7 manifest hash) | also fail on unmodified main on Windows; no code change; validated with an LF checkout and `PYTHONUTF8=1` (Linux CI semantics) |

No historical pin map, approved blob, tolerance or negative-control expectation was changed. The changed test files are `test_finance_integrity_governance.py`, `test_financing_f3_governance.py`, `test_m7_rc3_candidate_successor.py`, `test_ppa01_candidate_authority.py`, `test_rc7c_candidate_successor.py` and `test_v9p2a_odr_candidate_proposal.py`. `test_v9p2a_odr_successor.py` is new.

## OD-R negative controls (`tests/test_v9p2a_odr_successor.py`)

Each of these is rejected, and recognition, the candidate map and every scope exemption are revoked:

- a one-byte change to each of the six blobs;
- the superseded Correction A content;
- removal of `maturity_authority.py`;
- an extra `financial_engine/`, `finco_core/` or `domain/` path;
- a change to an unrelated RC-7C path;
- a change to each historical authority module;
- a widened hub;
- changed application provenance;
- each opened activation flag;
- exact bytes without ancestry;
- a missing, altered or substituted checkpoint;
- a manifest naming unreviewed content;
- shallow history.

## C-1

C-1 is out of scope and unchanged. See `V9P2A_C1_CANONICAL_U2_DECISION_NOTE.md`. Option A needs its own separately governed task.
