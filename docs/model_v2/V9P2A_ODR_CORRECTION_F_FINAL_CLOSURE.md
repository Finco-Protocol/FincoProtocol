# V9-P2a / OD-R — Correction F final contract closure

**Status: UNAPPROVED financial candidate, local only.** Not pushed; no governance change, repin or main sync; no owner
approval claimed; canonical default unchanged; OD-R release-closed.

Chain: `32b9478f` (PR #332) → `db92728d` → `a32ad575` → `971aa4f1` → `7f6a2e6d` → `5751c9fb` → `722d53b8` → `d72e867d`
(closure fix) → docs/evidence commit. Main `82fb309c` (no financial-path change since `591ea192`) recorded as Stage 2 drift.

## 1. Waterfall schedule identity — suspected bypasses and outcome

| Suspected bypass at `722d53b8` | Mechanism in source | Demonstration | Outcome |
|---|---|---|---|
| G1 unexpected / off-axis row in the **checked** schedule | `_rows_match` filtered registered rows to the operating set | source function `_rows_match` returned `True` for a registration with an extra row at period −1; real engine (row inserted, order preserved) **accepted** | **confirmed → fixed**: checked rows within maturity must equal the model period axis in model order |
| G2 extra off-axis **returned** operating row | `_returned_rows` skipped non-construction rows not in the operating set | real engine (non-construction row at period −1) **accepted** | **confirmed → fixed**: every non-construction row must be an operating model period |
| G3 reordered **returned** operating rows | dict + `sorted()` reconstructed order | real engine (two operating rows swapped) **accepted** | **confirmed → fixed**: returned operating rows must equal the model operating order exactly |
| Unexpected rows before / at maturity | covered by G1–G3 | — | closed by the same checks |
| Reordered **checked** rows | — | already rejected at registration: strictly increasing int indices (`record_final_waterfall`, Review Fix A, control `test_rfa_…[reordered_rows]`) | already enforced; unchanged |

Kept: exact IEEE-754 binary64 values, duplicate detection, construction rows with overlapping numbering (real shape:
construction row 4 and operating period 4), legitimate identical repeats, changed-input repeats contradictory, stale schedules
rejected, post-maturity rows presence/order only (approved semantics), economic failure precedence.

Before/after: the three real-engine controls fail as acceptances at `722d53b8`
(`before_after/controls_at_722d53b8_BEFORE.txt`) and pass at `d72e867d`.

## 2. Evidence-pack correction

`controls_AFTER.txt` in the Review Fix A package (48 passed / 2 failed) was captured after the first Review Fix A code
change but **before** the two signed-zero controls were retargeted from construction rows to operating rows; it is
superseded (kept unaltered under `superseded/`). The authoritative evidence is the fresh standalone run
`contract_module_final_clean.txt` (command, HEAD, blobs, clean-tree flag, unabridged summary, pytest exit code).

The two Correction B proposal failures are **not** financial passes or regressions: the standalone proposal correctly refuses
the unapproved content as the approved six blobs (`content_matches_proposal() is False`); it is not repinned.

## 3. Results

Filled in from the final validation run (see the package README for the exact figures).
