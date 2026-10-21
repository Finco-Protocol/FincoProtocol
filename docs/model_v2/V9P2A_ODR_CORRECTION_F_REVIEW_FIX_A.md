# V9-P2a / OD-R — Correction F, Review Fix A: final evidence contract hardening

**Status: UNAPPROVED financial candidate, local only (`local/v9p2a-correction-e`).** Not pushed; no governance wiring or
repin; no owner approval claimed; canonical default unchanged; OD-R release-closed.

Preflight (live): main `82fb309cede335303e3632fc4dfb0e2ad7f9263b` (no financial-path change since `591ea192`; 12 commits ahead
of the candidate's base — recorded as Stage 2 drift, not synchronised); PR #332 head `32b9478f`; local chain
`32b9478f → db92728d → a32ad575 → 971aa4f1 → 7f6a2e6d → (this fix)`.

## 1. Confirmed issues and corrections (`financial_engine/shl/maturity_authority.py` only)

| Issue | Defect at `7f6a2e6d` (reproduced, real engine) | Correction |
|---|---|---|
| G2A role cardinality | two distinct evidence tokens with valid passes under one required role were both accepted | exactly one authoritative registration per required role; more → `ODR_FINAL_EVIDENCE_CONTRADICTORY: <role> registered N times`; token re-registration still `DUPLICATE`; provisional / superseded evidence still diagnostic |
| Waterfall schedule identity | float `==` (`+0.0 == -0.0`), dictionaries silently collapsed duplicate indices, `zip` truncated misaligned vectors, coverage limited to indices present on both sides, registration maturity trusted | registration rejects misaligned vectors, non-int / non-strictly-increasing (duplicate or reordered) indices and non-float values; rows stored as exact IEEE-754 binary64 bytes; returned **operating** rows (construction rows excluded by their `is_construction` flag) with a duplicated period are contradictory; match requires registration maturity = the returned state's contractual SHL maturity (`return_summary.terminal.shareholder_loan`), complete ordered coverage of every operating period up to it on both sides, and bit-exact closing / gross interest / principal |
| State identity completeness | `required_final_checks` returned no G2A role for a `ProjectFinancingResult` with positive SHL liability but no final SHL schedule (inferred inapplicability) | such a state is `ODR_UNSUPPORTED_FINANCING` (structurally inconsistent); digest scope unchanged (no counterexample showed a digest gap) |

Before / after (same final controls; `tests/test_v9p2a_odr_finalization_contract.py::test_rfa_*`):
at `7f6a2e6d` **7 failed** — every one `DID NOT RAISE` (accepted): duplicate final role, checked `-0.0`, reordered rows,
mismatched maturity, duplicate returned row, returned `-0.0`, liability without schedule; duplicate index, missing row and
truncated vector were already rejected (incidentally). After the fix **14 / 14 pass**, including the unchanged valid
schedule and the legitimate identical repeat.

Real-engine shape found while fixing: the returned waterfall legitimately contains construction row 4 and operating
period 4 (different numbering domains). Duplicate detection is therefore scoped to operating rows, never collapsed.

## 2. Numerical acceptance and tests (fix commit `5751c9fb`)

| Suite | Result |
|---|---|
| 112-case matrix + P8, canonical and OD-R | 62 / 17 / 27 / 4 / 2, zero defects; every case identical to Correction F `7f6a2e6d` (verdict, financial / Integrity / full-object digests, Integrity verdict, exact error text, OD-R metadata, final checks); no new admission or rejection |
| Contract module (`test_v9p2a_odr_finalization_contract.py`) | 50 passed (incl. 14 Review Fix A controls) |
| OD-R modules (contract, final-state authority, Run-to-commit safety, proposal) | 106 passed; 2 expected: the standalone Correction B proposal refuses the unapproved content (`content_matches_proposal() is False`) — not repinned |
| 33 focused real-engine regression suites | failure set identical to Correction F: only the four exact-content guards beyond the unmodified-main baseline |
| Governance ring | 27 failed / 535 passed / 10 skipped; failure set identical to Correction F (original 25 blocking nodes + 2 proposal refusals) — known unapproved-content blocks, no genuine regression |
| Python compilation | OK |
| Public source-safety scan | single finding in untouched `static/vendor/swagger-ui/swagger-ui-bundle.js` (Windows CRLF breaks its exempt SHA; fixed on main by `329cbc68`, not in this base) — pre-existing environment artefact |

Protected blobs (Git SHA-1 / SHA-256 of blob content) at `5751c9fb`:

| File | Git blob | SHA-256 |
|---|---|---|
| `financial_engine/shl/maturity_authority.py` | `fc8ae6e715aa47f81dd18b5d1b06ffb859cd357d` | `851ded9fd1d6166b5466ae619f5ffe2f89a80654452a28518028b6d197d110b9` |
| `financial_engine/financing/generic_product_policy.py` | `b7df63cd5be886d5971213c03f9bfff046913ae1` | `41a94a1629703727bf32fe801b488e45fa5211f593453362a13a94a523648b53` |
| `financial_engine/financing/project.py` | `3bc6c097b218d27be216cdd86133f2772a82ad70` | `27dff26bac3486240c02f678a089156c2f6872d98cb9e868234abeceb56acbad` |
| `financial_engine/shareholder_waterfall/model.py` | `9520b09b135c7fe39d3d4fac6a0c2462b7c1c4ca` | `21014fb9b600a2c9d7f8e8fc65b99622bed2e751cf1a37a72f6e84bbf5e797c0` |

Unchanged: `orchestrator.py` `85c8008f`, `shl/production.py` `9bb852c2`, app `production_financial_authority.py` `89083cd4`.

## 3. Unchanged

Senior sizing / sculpting, SHL economics and the maturity predicate, IDC / construction funding, DSRA / DSRF, tax / CFADS /
waterfall economics, cash sweep, tolerances, canonical default, OD-R release-closed status, historical guards and accepted
hashes, the Correction B proposal module. Only `maturity_authority.py` and its contract tests changed in this fix.
