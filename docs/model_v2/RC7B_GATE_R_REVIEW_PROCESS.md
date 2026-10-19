> **Historical (retained evidence).** Gate R was the pre-merge authorization mechanism for PR #320. PR #320 was merged through GitHub as a normal merge
> commit (`bf0167a0`); Gate R never became active and is not the current control. Current state: `docs/model_v2/RC7C_GOVERNANCE_STATUS.md` (see also `RC7B_POSTMERGE_GOVERNANCE_RECOVERY.md`).

# RC-7B Gate R — authentication, revocation and review process

Status: PROPOSAL (mechanism implemented and tested; **no authorization exists**). Nothing in this document is an approval. No owner key, registry entry,
signature, record or GitHub review has been created by the author of this change.

## What Gate R is — and is not

Gate R authorizes exactly one thing: carrying the twelve reviewed RC-7B financial/core blobs as a **release-closed integration candidate**
(`ACTIVATION_ENABLED` stays a literal `False`). It never approves D-01..D-12, Gate P, user activation of the quarterly Run, a financial-policy change,
product admission, release or a merge. D-06 and D-07 stay DEFERRED. D-03 (economic horizon) is an unresolved owner decision — see
`RC7B_QUARTERLY_DECISION_MATRIX.md`.

The states are kept apart and never collapsed into one boolean:

| State | Question | Answered by |
|---|---|---|
| HISTORICAL_VERIFIED | Did an accepted stream change a protected path in its own source range? | `tests/stream_scope_proof.py` (immutable per-stream ranges, fail closed) |
| CANDIDATE_RECOGNIZED | Are the twelve paths exactly the reviewed blobs, with complete protected inventory, ancestry, M7 supersession and a literal-False flag? | `content_violations` |
| OWNER_AUTHENTICATED | Did the human Financial Owner, holding a key the implementation agent does not have, authorize exactly this record and mechanism? | owner attestation (below) |
| INDEPENDENTLY_REVIEWED | Did a distinct human review exactly this content and mechanism on GitHub, with no later or competing decisive review? | `gate_r_review_violations` (live, complete GitHub history) |
| GATE_R_ACTIVE | All of the above, right now. | `gate_r_active` |
| FINANCIALLY_APPROVED / PRODUCT_ADMITTED / RELEASED / MERGED | Financial policy, admission, release, merge | Separate decisions. **Not granted by Gate R; unavailable.** |

## Why a JSON record is not an authorization

`"status": "SIGNED"`, a GitHub login, a commit author field or an ordinary Git commit are all text that anyone with write access — including the
implementation agent — can produce. The first design accepted such a record; an independent review demonstrated a forged owner and a modified owner
record both passing. Authority now comes **only** from a cryptographic signature.

### The Financial Owner attestation

* The owner signs **offline**, with an `ssh-ed25519` key that never exists in the implementation environment, using OpenSSH's standard signature format
  (`ssh-keygen -Y sign`), namespace `finco-rc7b-gate-r-owner-v1`.
* The signed bytes are the canonical JSON of the **whole record** (every field except the signature itself) bound to the repository, pull request,
  namespace and the **blob of every Gate R mechanism file** (`GATE_R_GOVERNANCE_FILES`: the validator, the signature verifier, the guard wiring, the
  historical-provenance mechanism, the Gate R tests, the owner registry and the two workflows that define token permissions and run the guards). Editing any record field, substituting another record's signature,
  changing the mechanism, or replaying a signature from another namespace, repository or pull request makes the signature fail.
* **Who may be the Financial Owner is pinned in a reviewed registry**, `RC7B_GATE_R_AUTHORITY_REGISTRY.json` (login → permitted SSH key fingerprints). It is
  **empty today**, so no attestation can verify and Gate R cannot open. The registry is part of the reviewed mechanism and of the bytes the owner signs.
* The key must **also be registered, right now, among the owner's GitHub SSH signing keys** (`GET /users/{login}/ssh_signing_keys`). Removing it from
  GitHub revokes the authorization at the next evaluation. An attestation has a random `attestation_id`, a signing time and an expiry of at most 90 days.
* The signature is verified by a small dependency-free Ed25519/sshsig implementation (`tests/rc7b_owner_attestation.py`) that is checked against the RFC
  8032 vectors, an independent implementation and real OpenSSH in both directions.
* Owner authorization is separate from the independent review (different person, different mechanism) and from merge authorization.

The owner may be the same GitHub account as the PR author: GitHub account control proves nothing here, only the private key does. This is why a
login, a comment, a review or a commit made through credentials available to the implementation agent can never substitute for the signature.

### Operational prerequisites (human actions)

1. The Financial Owner generates an ed25519 key on a device the implementation agent cannot reach (ideally a hardware key), and registers it as an **SSH
   signing key** on their GitHub account.
2. A human adds `{"login": ..., "ssh_signing_key_fingerprints": ["SHA256:..."]}` to the registry in a reviewed change (before the independent review).
3. The independent reviewer **confirms the fingerprint with the owner out of band** — the registry is reviewed content, not self-evidently true.

## Order of events (no hash cycle)

1. Commit **R** contains the twelve blobs, the mechanism files and the registry entry. R is what the reviewer reads.
2. The independent reviewer (a GitHub account that is not the PR author, not the Financial Owner and not a bot, with OWNER/MEMBER/COLLABORATOR association)
   submits an **APPROVED** review on pull request #320 *at R*. GitHub assigns the numeric `review_id`.
3. The Financial Owner fills in the record from the template (citing `review_id` only), runs
   `python tests/rc7b_quarterly_candidate_authority.py owner-payload <record.json> > payload.bin`, signs it with
   `ssh-keygen -Y sign -n finco-rc7b-gate-r-owner-v1 -f <owner key> payload.bin`, puts the armoured signature in `owner_attestation.signature`, and the
   record is committed **after** R as `docs/model_v2/RC7B_GATE_R_AUTHORIZATION.json`. Neither signature nor review needs the record's own commit hash.
4. `gate_r_active` re-derives everything from Git and GitHub on each evaluation (see below).

Later commits that only touch documentation or unrelated files keep both the review and the attestation valid. Any change to a reviewed financial blob,
to a mechanism file or to the registry makes the review **stale** and the attestation **invalid** until properly re-reviewed and re-signed.

## What `gate_r_active` requires

* Exact content: the twelve blobs, reviewed source ancestry, no other protected change, explicit M7 supersession, literal `ACTIVATION_ENABLED = False`.
* Record: schema v2, `SIGNED`, scope `CANDIDATE_BOUNDARY_ONLY`, grants exactly "release-closed integration true, everything else false", D-06/D-07
  DEFERRED, no other decision made.
* Owner attestation: valid signature, registered owner and key, key currently on the owner's GitHub account, not expired, not future-dated.
* Review evidence (live, **complete**): the referenced review is APPROVED by the named non-author, non-owner, non-bot reviewer with an authorized
  association; its commit is an ancestor and carries the same twelve blobs and mechanism bytes; **no later decisive review** (CHANGES_REQUESTED,
  DISMISSED, newer APPROVED) by that reviewer; **no unresolved CHANGES_REQUESTED** from any authorized reviewer. Review ordering must be establishable.
* Anything unverifiable — GitHub unavailable, rate limited, unauthorized, malformed, incomplete pagination, missing record, missing registry — **rejects**.

## Revocation and caching

* There is **no process-lifetime positive result**. Facts derived from immutable Git objects are memoised per commit (they cannot go stale).
* Live GitHub evidence is cached for at most `GATE_R_EVIDENCE_TTL_SECONDS` (20 s); failures are never cached; a clock that runs backwards is never trusted.
* At every approval or merge decision boundary call `gate_r_violations(fresh=True)` / `gate_r_active(fresh=True)`: the cache is bypassed and the review
  and owner key are re-fetched.
* A dismissed or superseded review, a revoked owner key or an unavailable API rejects at the next evaluation.

## Complete review history

The reviews are read page by page (100 per page) until a short page proves completeness; more than 30 pages, a non-list page, an owner with a full page
of signing keys or inconsistent ordering is an error and rejects. A `CHANGES_REQUESTED` review as the 101st review is therefore seen. GitHub branch
protection (required reviews, dismissal of stale reviews, code-owner review) is separate, is **neither read nor changed** by this mechanism, and its
actual settings are not visible to this repository's tests; Gate R is deliberately stricter than merge protection for change requests.

## GitHub API access in CI (verified behaviour)

* The required test job (`ci_public_job.yml`) declares `permissions: contents: read` and passes **no token** to the test step. With no committed Gate R
  record (today) the validator performs **zero** GitHub calls, so CI is unaffected.
* Once a record exists, the validator reads public pull-request reviews and the owner's public signing keys **unauthenticated** (about 60 requests per
  hour per runner IP, shared on hosted runners). Exhaustion is reported as `RATE_LIMITED` (distinct from `UNAUTHORIZED`/`FORBIDDEN`/`NOT_FOUND`) and
  **fails closed**. The validator uses `GITHUB_TOKEN`/`GH_TOKEN` read-only when present and never prints it.
* A reliable CI would pass `env: GITHUB_TOKEN: ${{ github.token }}` (read-only; `contents: read` already suffices for public data) to the test step. This
  was **not** done here: the workflow files are blob-pinned by the RC-5 CI governance, so a change needs its own owner-approved CI successor. It is a
  separate decision, not a security prerequisite (the current behaviour is safe).

## Consumers of the recognition (and only these)

`strictly_frozen_changes`, `authority_state`, and the 17 current-authority guards via `superseded_by_gate_r` / `current_expected_blob` /
`without_gate_r_superseded`. **Unchanged:** `unapproved_engine_changes`, `approved_frozen_path`, every pin map, `rc3_historical_anchor`. A superseded path
is never `released` and never an `approved_frozen_path`.

## Approvals still outstanding (none exist)

1. A human-authored registry entry and key registration for the Financial Owner (operational prerequisite above).
2. Independent review of the twelve blobs and of this mechanism (an APPROVED GitHub review by a human who is neither author nor owner).
3. The Financial Owner's signed attestation.
4. Governance-owner acceptance of the Gate R mechanism.

Even with all four, quarterly financial policy (D-01..D-12, in particular D-03), Gate P, activation, admission, release and merge remain separate,
unmade decisions.
