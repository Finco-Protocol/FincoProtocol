# RC-7B Gate R — deterministic, non-circular review process

Status: PROPOSAL. Nothing in this document is an approval. No record, signature or review has been created by the author of this change.

## What Gate R is — and is not

Gate R authorizes exactly one thing: carrying the twelve reviewed RC-7B financial/core blobs as a **release-closed integration candidate**
(`ACTIVATION_ENABLED` stays a literal `False`). It never approves D-01..D-12, Gate P, activation of the quarterly Run, a financial-policy change,
product admission, release or a merge. D-06 and D-07 stay DEFERRED.

The states are kept apart and never collapsed into one boolean:

| State | Question | Answered by |
|---|---|---|
| HISTORICAL_VERIFIED | Did an accepted stream change a protected path in its own source range? | `tests/stream_scope_proof.py` (immutable per-stream ranges, fail closed) |
| CANDIDATE_RECOGNIZED | Are the twelve paths exactly the reviewed blobs, with complete protected inventory, ancestry, M7 supersession and a literal-False flag? | `rc7b_quarterly_candidate_authority.content_violations` |
| INDEPENDENTLY_REVIEWED | Did a distinct human review exactly this content and mechanism on GitHub? | `gate_r_review_violations` (live GitHub evidence) |
| GATE_R_ACTIVE | Is the candidate boundary authorized by the Financial Owner? | `gate_r_active` (all of the above plus the signed record) |
| FINANCIALLY_APPROVED / PRODUCT_ADMITTED / RELEASED | Financial policy, admission, release | Separate decisions. **Not granted by Gate R; unavailable.** |

## Where recognition is consumed

Only the Finance Integrity frozen-scope helpers (`unapproved_engine_changes`, `strictly_frozen_changes`), the candidate-state classifier and the
current-authority guards use `superseded_by_gate_r` / `current_expected_blob`. `approved_frozen_path`, `released_engine_authority_matches`, every pin
map and `rc3_historical_anchor.anchored_head()` are untouched. A superseded path is a release-closed candidate: never released, never an approved
frozen path. Without an active Gate R every guard evaluates exactly as before and fails closed.

## Order of events (no hash cycle)

1. The change under review is the twelve blobs plus the Gate R mechanism files (`GATE_R_GOVERNANCE_FILES`). Commit **R** is the head the reviewer sees.
2. The independent reviewer (a GitHub account that is not the PR author, not the Financial Owner and not a bot, with OWNER/MEMBER/COLLABORATOR
   association) submits an **APPROVED** review on pull request #320 *at commit R*. GitHub assigns the review a numeric `review_id`.
3. The Financial Owner confirms the candidate boundary and a record `docs/model_v2/RC7B_GATE_R_AUTHORIZATION.json` (from the unsigned template) is
   committed **after** R. The record cites `review_id` only — never a commit hash that would include the record itself.
4. `gate_r_active` fetches the review from GitHub (it is not read from the repository) and requires: state APPROVED, the named reviewer, the review's
   commit is an ancestor of the evaluated ref, the twelve blobs at that commit equal the accepted blobs, and the four mechanism files (`GATE_R_GOVERNANCE_FILES`) are
   byte-identical between the reviewed commit and the evaluated ref.

Consequences: later commits that only touch documentation or unrelated files keep the approval valid. Any change to a reviewed financial blob or to
the Gate R mechanism files makes the review **stale** and Gate R inactive. A missing, unsigned, unverifiable, stale or mis-granting record is rejected.

## Approvals still outstanding (none exist)

1. Independent financial review of the twelve blobs (an APPROVED GitHub review by a human who is neither author nor owner).
2. Financial Owner signature of the Gate R candidate-boundary record.
3. Governance-owner acceptance of this successor mechanism (the Gate R validator and its wiring).

Even with all three, quarterly financial policy (D-01..D-12), Gate P, activation, admission, release and merge remain separate, unmade decisions.
