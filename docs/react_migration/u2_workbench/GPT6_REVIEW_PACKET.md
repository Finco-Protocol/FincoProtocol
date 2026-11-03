# PR-U2 — independent review packet

Scope: UI and read-only routes on top of `main` `2c63750`. There is no engine, schema, Save All, PPA or Run change. Review against `P00_U2.md` §0
(the mandatory addendum).

## What to verify
1. `app/v2/react_opex_lines.py` adds no arithmetic: every number is `OpexLineVM.year_values` / `year_rows` passed through. The only computed field
   is `reconciles`, a boolean comparison.
2. `frontend/src/app/capex/profileImport.ts::checkExplicit` agrees with `contract.build_weights` (exact BigInt sum; tolerance 1e-7 percentage points,
   which equals the server's 1e-9 of the whole). It is never stricter or looser. Oracle: `tests/test_u2_profile_import.py`.
3. D13: no semantic change. The UI only discloses and asks for confirmation. The proofs are read-only.
4. D7: no Save All wire change; R1 files are untouched and refused by the cohort.
5. Governance: `tests/u2_scope.py` is low level (never imports U1 or the registry). The U1 hooks follow U2 only at U1's own recorded pins. Tamper
   negatives: `tests/test_u2_scope.py`.

## Owner questions
| Id | Question |
|---|---|
| D13 Q1 | On retire of a profiled line: dormant profile (A, contract ready) or keep refusing the Run (B, today)? |
| O1 | Server token for a combined save: one composite CAS over all sections (proposed), or a second token per section? (No `contracts_base_token` is introduced by U2.) |
| OPEX aggregation | How does the Run escalate the six base scalars, and may an all-in OPEX-by-year be shown from the draft (G-10 options A/B/C)? |
| Profile granularity | Should user-added lines (`C.NN.U###`) accept a monthly profile (widen the document key: G-U2-1)? Should profiles stay per leaf, or move to per group? |
| Financial truth | Changed: **none**. Unchanged: every signed Run, the history, the profile document format, the D6 default, the six bases' Run treatment. Please confirm. |

## Known limits
* The `.mjs` unit suite and the client/server oracle skip on CI V3 workers (no frontend toolchain); they pass locally.
* The axe accessibility audit was not run locally.
* There is no staging or live verification.
