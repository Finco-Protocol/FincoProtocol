# RC-7 Quarterly Financial Authority Successor Proposal

**PROPOSAL ONLY. NOT AN ACCEPTANCE RECORD OR AN ACTIVE GOVERNANCE EXCEPTION.**

## Verified authority conflict

Baseline main: `78e4c0edcc1bdb5013df79f11b3ba7b9c2151013`.
Candidate source: `03ee3aee54e9f6fea3eb6e849a440ba1ebb7307b`.
Normal compatibility integration: `31cada62a9fe17474995acc7d03bab4296122b4c`.

The baseline has zero financial_engine/finco_core/domain diff relative to the
candidate's original main `05183b2a96c74fd4b3976903c593a61402cab7b3`.
The main merge preserved all five candidate blobs:

| Exact path | Candidate Git blob | Predecessor |
|---|---|---|
| financial_engine/adapters/project_inputs.py | d54e35dac6b45b490c16bde8b49c158d83f56047 | M7 14bd759a9958515a7796626f93c1bd2233d69150 |
| financial_engine/orchestrator.py | fcffca1074dfd62143fa4c3d55240b4bb1a0b7ec | M7 be7ac31c6c4fed43b5fd7ca49fe53bfd1cc54c03 |
| financial_engine/quarterly/__init__.py | 027b4fc206f4e3be564c89ca3e53dc95e720359c | New, no released predecessor |
| financial_engine/quarterly/calendar.py | 1ba36e59590386023dc6f475fe383203a36b7dce | New, no released predecessor |
| financial_engine/quarterly/runtime.py | 12848fd6787719d42e7588120c6ce72d717fee81 | New, no released predecessor |

These SHA values are an inventory of code to review, NOT self-issued release
pins. No map or guard is edited in Correction B.

Prior exact-head Public Safety run **39103456006**, job **117604365939**, completed
with **49 failed, 12729 passed, 100 skipped**; pytest rc=1, supervised interpreter
child exit=1. Failures are financial scope/content/provenance assertions, not
failed numerical assertions. Examples: frozen namespace rejects all five paths;
M7 exact eleven-blob HEAD assertions reject the two successors; PPA combined
scope rejects the new unlisted financial files; historical WF07 precedence still
expects the M7 adapter blob. The failure is real and must remain blocking until
the appropriate independent authority exists. It is not solved by skipping tests.

## Five separate states

| State | Required proof | Does it authorize production? |
|---|---|---|
| Historical released financial content | Existing immutable historical map/ref and exact bytes | Only its already released semantics |
| Integrated release-closed candidate | Existing M7/PPA source ancestry, manifests and closed flags | No |
| New prepared quarterly candidate | Exact five blobs, source/tree, explicit scope, numerical evidence | No |
| Independently accepted quarterly content | Actual independent review plus owner decisions tied to exact content | No automatic product admission |
| Production-authorized quarterly functionality | Complete financial consumers, security/CAS/history/export, release decision and exact-head acceptance | Only explicitly approved scope |

Do not repurpose `release_approved:false` into a boolean allowing the engine.
Technical preparation and successful pytest do not create an independent review.

## Smallest legitimate future governance extension

1. Keep all historical maps and their original SHA values unchanged in
   `tests/model_v2_governance.py`. Preserve WF04/WF07, F3, Developer Economics,
   M7 and PPA negative semantics.
2. Introduce a separately reviewed exact-five-path quarterly successor contract,
   with original candidate head, accepted source tree, compatible main ancestry,
   exact blobs and explicit predecessor mapping for the two overlapping paths.
   New filenames or namespaces alone must never satisfy it.
3. Keep historical M7 verification at its immutable reviewed source and RC2/RC3
   integration checkpoints. At new HEAD, verify the nine non-overlapping M7
   blobs unchanged and the two overlaps through the independently accepted
   successor chain. Never pretend the new HEAD still equals the old eleven blobs.
4. Preserve the three PPA-01 exact blobs unchanged. Keep its historical ancestry,
   source bytes, contract policies and activation restrictions separate from
   quarterly content acceptance. PPA acceptance must not authorize quarterly.
5. Central classification should compose explicit accepted successor records
   rather than adding exemptions independently to approximately thirty tests.
   Callers must distinguish candidate-recognized from released. Historical
   checkpoint tests stay anchored; current HEAD tests validate the accepted chain.
6. Any independent acceptance record must identify the real independent reviewer
   and financial-owner decision, exact reviewed source/tree/blobs, policy
   decisions, evidence provenance and retained closed flags. Missing records,
   invalid Git refs, wrong ancestry, extra paths or one-bit mutations fail closed.
   No agent-generated human identity or HEAD-derived expected SHA is permitted.
7. Authorize the exact helper/test edit paths separately before implementing
   this extension. Then review its diff and run all guards; no broad scope edit
   follows from this proposal.

## Existing control points requiring coordinated review

- `tests/model_v2_governance.py`: exact authority classification/precedence.
- `tests/finance_integrity_governance.py`: engine diff and frozen-path predicates.
- `tests/m7_rc3_candidate_successor.py`: historical anchor versus HEAD successor.
- `tests/ppa01_candidate_authority.py`: preservation/coexistence scope.
- `tests/test_m7_rc3_candidate_successor.py`,
  `tests/test_rc3_integration_inventory.py`,
  `tests/test_rc3_post_merge_authority_states.py`,
  `tests/test_ppa01_candidate_authority.py`,
  `tests/test_wf07_revenue_governance.py`: historical content and negative proof.
- Other frozen namespace callers must still reject unrelated paths. A full
  reviewed inventory of necessary test-only expectation changes must precede
  implementation; this list is not an authorization envelope.

## Mandatory successor negative tests (not a release gate implemented here)

- Alter each of the five blobs independently; reject all five mutations.
- Reject an extra financial/core/domain file, even a newly named quarterly file.
- Reject missing file, missing ref, forged source head/tree and wrong ancestry.
- Reject changing any of the nine other M7 or three PPA blobs.
- Reject changed BESS, Revenue V3, Junior or quarterly activation flags.
- Reject fabricated/absent independent review, incomplete owner decision pack,
  wrong candidate version and approval for a different blob.
- Preserve all permanent hard-deny and historical changed-blob tests.
- Assert accepted research content still cannot invoke production quarterly
  Save/Run/History/export until the separate complete-consumer gate passes.

## Stop gate

Correction B supplies evidence and policy choices only. Independent financial
content acceptance, financial-owner D decisions and exact governance-change scope
are still required. Full monthly-to-quarterly accounting, reserves/distributions,
returns, product writers/history/export are not complete. No approval, activation,
merge or deployment is requested by pretending otherwise.
