# Post-RC-3 hotfix A - restore main CI (financial authority states)

Status: **PROPOSAL FOR INDEPENDENT REVIEW. NOTHING HERE IS A FINANCIAL APPROVAL.**
M7 manifest `release_approved:false`; BESS / M6 / Junior / Revenue V3 `ACTIVATION_ENABLED = False`. No financial calculation, golden, tolerance,
workflow, CI budget, pytest selection or historical pin map is changed.

## 1. Main-run diagnosis (the exact merge commit, not PR #284's results)

`main` = `4527ceadea7a5b9a8c3e2e63eb9fb3395ef9b66e` (normal two-parent merge of `6fc77de` and PR #284 head `b17d334`).
Public Safety and Model Smoke on `push: main`: run `38582702375`, test job `115916463979`, full unsharded, no timeout, supervisor and pytest rc=1,
**7 failed, 11,408 passed, 73 skipped, 3952.78 s** (budget 4800 s). `source-safety` success; `mandatory-evidence` job `115950606919` failed only because
the control job exited 1. Dependency Security Audit and Protocol Verification Corpus: success.

| # | Failing node | Cause |
| --- | --- | --- |
| 1 | `test_finance_integrity_governance::test_approved_engine_paths_are_allowed` | asks "is it released?" of content that is the release-closed M7 candidate |
| 2 | `test_finance_integrity_governance::test_stream_guard_exemption_covers_only_allow_listed_engine_files` | same |
| 3-5 | `test_wf07_revenue_governance::{test_exact_seven_content_pins_only, test_every_further_edit_invalidates_authorization[project_inputs.py], [orchestrator.py]}` | judge the historical pins against HEAD instead of the checkpoint where they were accepted |
| 6-7 | `test_rc3_integration_inventory::{test_the_integrated_head_is_exactly_the_documented_union_of_the_five_sources, test_missing_source_wrong_ancestry_or_wrong_merge_order_is_rejected}` | **defect in the RC-3 inventory itself**: it assumed a pre-merge branch; on main the first-parent chain holds only the single PR merge |

Differences from PR #284's run (`38580355299`): `test_ci_acceptance::test_frozen_financial_namespaces_unmodified` and
`test_finance_integrity_governance::test_this_branch_stays_within_the_governance_contract` now PASS on main (their diff is taken against
`merge-base(origin/main, HEAD)`, which is HEAD itself on main); the two inventory tests are new.

## 2. Three states, never one boolean

`tests/rc3_authority_states.py` classifies a protected path as exactly one of:
* **HISTORICAL_RELEASED** - the blob is in a released pin map (WF07, F3.5, Developer Economics, Revenue V2/V3, ...), judged at its own checkpoint;
* **INTEGRATED_RELEASE_CLOSED_CANDIDATE** - the exact M7 blob from PR #284, byte-identical to the reviewed M7 source head, valid only while every
  release flag is a literal `False` and the manifest says `release_approved:false`;
* **ACTIVATED_FINANCIAL_AUTHORITY** - needs a separate independent financial and production-release approval; **no code path can return it for M7**;
* anything else is **UNAUTHORIZED**.
`released_engine_authority_matches`, `approved_frozen_path` and `unapproved_engine_changes` are untouched and still reject the M7 candidate.

## 3. Corrections

* WF07: the seven historical pins are verified at the RC-2 checkpoint (`6fc77de`); the five paths that are still released are verified at HEAD; the two M7
  paths are asserted to be the exact candidate, NOT released, NOT exempt; the released-authority guard must still list exactly those two. The synthetic
  mutation test now builds its "released" repo from the checkpoint content, and a new synthetic test proves one extra byte (or the historical blob) is not
  the candidate. Unknown future edits inherit no M7 permission.
* Finance Integrity: the approved-paths assertions separate released paths from the two candidate paths; a new test proves the candidate never enters
  `APPROVED_FINANCE_INTEGRITY_ENGINE_PATHS` (`bess.py` is not listed) and that unreviewed engine/core changes stay rejected.
* RC-3 inventory: the integrated candidate is the pinned immutable commit `b17d334`; current HEAD is bound to it (ancestor, normal two-parent PR merge,
  the eleven M7 blobs unchanged, flags closed, manifest/workflow unchanged). Post-merge mutations are rejected.
* New `tests/test_rc3_post_merge_authority_states.py`: every released pin map is byte-identical to its checkpoint, the central governance files are
  byte-identical to the checkpoint, activation is unreachable, an opened flag or forged manifest removes the candidate state.

## 4. Still open (not resolved by this hotfix, by design)

Independent financial acceptance of the eleven M7 blobs (`docs/rc3/M7_FINANCIAL_ACCEPTANCE.json` does not exist; `tests/m7_rc3_candidate_successor.py`
reports `APPROVAL_REQUIRED`), and separate production-activation approval. Candidate presence on main is not either of those.
