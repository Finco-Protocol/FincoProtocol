# PR #320 Correction A — handoff (work in progress, NO MERGE, keep Draft)

Verified at start: main `5be8c4b1…` unchanged; PR head was `a1a1f4e6…` (16 ahead, 0 behind, draft, no reviews).
CI on `a1a1f4e6`: `mandatory-browser-evidence` FAILED, `safety-and-smoke / tests` was still running; all other checks green.
Actions logs/artifacts are blocked by the sandbox egress policy (403 on the blob host), so the exact failing browser assertion is NOT verified.
Locally the browser roles grid, q4, import, consolidation and outputs pass; `protocol` fails 2 NVDA tests identically on pristine main (environmental).

## Corrections in this commit
1. Removed my own RC-7B recognition wiring from `tests/finance_integrity_governance.py` and `tests/rc3_authority_states.py`
   (restored to main bytes). It broke 5 pinned negative controls and turned live gate `test_this_branch_stays_within_the_governance_contract`
   green without independent approval. The removed diff is the proposal for independent governance review.
2. `tests/test_rc7_quarterly_research_isolation.py`: replaced the loosened `or` assertion with an exact typed code per variant.
3. 3/3 financing binding is now verify-only: the saved selection (contract v2) records the exact `excluded_structure`
   (funding mode, SHL amounts, DSRA months); `apply_config` refuses any other structure with `QUARTERLY_FINANCING_STRUCTURE_MISMATCH`
   instead of overwriting SHL/DSRA. The endpoint reads the real Working Copy structure and dry-runs `apply_config` at save time.
   Typed failure rules added. `tests/test_rc7b_quarterly_run_workspace.py` updated (47 pass).

## Open items for the next agent
* `tests/test_rc7b_quarterly_production_acceptance.py::test_a_selection_written_by_another_writer_...` (2 params) FAILS:
  `app/v2/router.py::_classify_senior_authority` calls `to_projectinputs()` and the new `SnapshotInputError` escapes, so the Run/page path
  does not surface the typed refusal. Make that call site fail closed with the typed code (page must still render; no committed Run).
* Re-run the governance set and classify the remaining failures A–E (previous list: 29 of the 32 reproduced; after item 1 several more
  become red, which is correct). Classification so far: pin-at-HEAD guards (WF04, WF07, F3 multisenior/junior, M7 successor/boundaries,
  rc7a compat, rc3 inventory/post-merge) = checkpoint mismatch needing independent-reviewed reconciliation; live-diff gates
  (`test_ci_acceptance::test_frozen_financial_namespaces_unmodified`, parallel_stream_frozen_diff, ppa01 anchor, research isolation,
  `test_this_branch_stays_within_the_governance_contract`) = missing independent approval. No unlisted protected paths were found.
* Check exact-head CI on the new head; do not rerun without a source change.
* D-01..D-12 remain OPEN; ACTIVATION_ENABLED stays False. Verdict: NO MERGE.
