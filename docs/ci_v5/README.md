# CI V5 — evaluator schema V2, trust checkpoint and gate (V5-2B merged; V5-2C + V5-3 candidate) — SHADOW LANE STAYS OBSERVATIONAL

**Status (Correction A, PR #455): the V5 SHADOW lane stays observational; this PR adds the production-candidate GATE (its own `pull_request_target` workflow) and NO trust anchor: `docs/ci_v5/epoch.json` is deliberately NOT part of it (no `epoch.json` ships here; the FULL witness is `FULL_PROVENANCE_BLOCKED`).
Nothing here is a required check, selects, skips, moves or demotes a test, or changes V4. V4 stays authoritative. The gate becomes a *required* check only when the owner adds its
name in GitHub settings AFTER this PR is merged (`OWNER_POSTMERGE_ACTIVATION_CHECKLIST.md`). A green workflow run is never evidence of enforcement.**

## What changed in V5-2B (closes the V5-2A audit findings)

| Audit finding | Closed by |
|---|---|
| F-02/F-03 — 1,917 tracked paths (1,059 high-risk) outside the guard; new root files / top-level folders passed | **`ALL_TRACKED`** guard: every tracked path is evaluated (add / modify / delete / rename = delete+add / mode / symlink / gitlink / unsafe UTF-8 / case-fold collisions, also between directory components). Classes S/P/X/D change the *review*, never the *visibility*. A path with no class is `S` / `UNCLASSIFIED`. |
| F-04 — base chosen by the caller (`merge-base`, any fork, any branch) | The base is the **current tip of the protected ref** (`trusted_ref_tip`) and the head must contain it (merge-tree identity). Anything else is `UNKNOWN`, never authoritative (T1, T2a). |
| F-05 — `EPOCH_STALE_AT_BASE`, replayed / inherited delta, silent revert | **Base-relative delta V2**: `guarded(head) == guarded(base tip) ⊕ declared changes`, bound to `base_sha`, `base_tree` and `result_inventory_sha256`. The epoch is a milestone *checkpoint*; it need not equal the base inventory (T3c, T3e). A delta file inherited unchanged from the base declares nothing. |
| F-07 — semantic list was data inside the epoch | The class map and the semantic registry are **trusted code** (`POLICY` in `tools/ci_v5_epoch.py`, archived from the trusted base). Empty/unreadable registry = `UNKNOWN` for every path (S1b). Existing tests under `tests/` that are modified or deleted are semantic (never better than `UNKNOWN`). |
| F-09/F-10 — ignored files, `.pyc`, `skip-worktree`, `git replace` | `GIT_NO_REPLACE_OBJECTS=1` + `--no-replace-objects`, scrubbed environment (no inherited `GIT_*`), `refs/replace` / grafts / shallow clone are reported, tracked files are **re-hashed from disk** (independent of index flags), ignored/untracked importable or served material anywhere is a failure (W3–W7, T5b). |
| F-06 — the verdict job also ran PR-head Python | **Split by trust boundary**: `verdict` (Git objects only, trusted-base tools) / `v4-comparison` (PR-head code, isolated) / `compare` (trusted code, artifacts as data). |
| bare `PASS` | `integrity: INTEGRITY_PASS \| INTEGRITY_FAIL \| UNKNOWN` is separate from `authorization` (always `NOT_EVALUATED` here) and `enforcement` (`SHADOW`). No bare `PASS`/`FAIL` string exists in any verdict JSON. |

An `INTEGRITY_PASS` needs **all** of: tool source `TRUSTED_BASE` (archived from the base tip), trusted epoch read from the base, base == protected tip and contained in
the head, no failure and no unknown. Everything else is `INTEGRITY_FAIL` or `UNKNOWN`. In this PR no trusted epoch exists (none ships here), so **every verdict here is
`UNKNOWN` or `INTEGRITY_FAIL`, by construction**; hosted runs prove the failure paths and the plumbing, not an approved pass.

## V5-3 (this PR): gate, authorization, enforcement - and what each can and cannot prove (V5-2C trust-anchor promotion is NOT in this PR)

| Piece | What it is | State after merge |
|---|---|---|
| Trust anchor `docs/ci_v5/epoch.json` | **NOT in this PR.** A trust anchor is a promotion; it may only be created by a separate, isolated, owner-approved PR (`PROMOTION_REQUIRES_OWNER`; mixed with anything else `PROMOTION_NOT_ISOLATED`) AFTER a green FULL run exists. No epoch ships here, no untrusted candidate of the V2 shape either; regenerate on demand with `python tools/ci_v5_candidate.py candidate --commit <tip> --full-run-id <id>`. | absent: every verdict stays `UNKNOWN` (`NO_TRUSTED_EPOCH`) |
| FULL witness | A witness is only a JSON field until it is checked against the REAL GitHub run. `verify_full_witness` (run by the gate, trusted base) reads `GET /repos/{repo}/actions/runs/{run_id}` and accepts only a run of THIS repository's `ci_v4_full.yml` on `main`, event `schedule`/`workflow_dispatch`, `completed`/`success`, at EXACTLY the epoch's commit; a self-declared PASS with a missing, red, timed-out, other-sha, PR or fork run is rejected (`FULL_WITNESS_NOT_VERIFIED_AGAINST_A_REAL_GITHUB_RUN`). The nightly `CI V4 FULL` is red today (run `43828509961`: 19,200 s supervisor timeout, 2,242 / 25,406 tests; `tests/test_ci_v3_outcome_reconciliation.py` = 16,008 s), so no witness exists. | `FULL_PROVENANCE_BLOCKED`; a later promotion needs a green FULL |
| Gate job `V5 gate (trusted base)` | The only job of its OWN workflow `.github/workflows/ci_v5_gate.yml` (`pull_request_target` only). GitHub reads that file from the protected base, so a PR cannot rewrite the gate that judges it; and because no `pull_request` event shares the file, no SKIPPED same-named check run exists (a skipped check counts as passing for a required status check). Checks out the BASE, fetches the head as Git objects only, read-only token, no secrets. | exists; runs on later PRs; **not required by any setting** |
| Authorization | `AUTHORIZATION_APPROVED` needs an APPROVED review at the EXACT head by an allow-listed login that is not the PR author (repo association OWNER/MEMBER/COLLABORATOR, not dismissed), or an owner-signed head commit verified against `POLICY.ALLOWED_SIGNERS`. `POLICY.APPROVERS` and `ALLOWED_SIGNERS` are EMPTY in trusted code: nobody can approve until the owner names an independent identity in a reviewed edit (`AUTHORIZATION_BLOCKED / NO_APPROVER_CONFIGURED`). | blocked by construction |
| Decision | `INTEGRITY_PASS_AUTHORIZED` (integrity + authorization), `DEFERRED_TO_V4_VERIFIED` (the ONLY unknown is a recorded semantic gap AND all six V4 checks are `success` at the SAME head AND authorization), else `BLOCK`. Never opens on `UNKNOWN`, a promotion, a stale/foreign head, an untrusted tool or epoch, or a skipped/missing/red V4 check. | - |
| Enforcement | `ENFORCEMENT_VERIFIED` only from the OWNER's read of branch protection / rulesets (`python tools/ci_v5_shadow.py enforcement --protection-json ...`): the gate AND all six V4 checks required, strict, enforced admins, code-owner review, stale dismissal, last-push approval, >=1 approval. The gate itself always reports `ENFORCEMENT_UNVERIFIED`. | `ENFORCEMENT_UNVERIFIED` |

After approving, re-run the gate job (reviews are read when it runs). Rollback: remove only the gate name from the required checks (or delete `ci_v5_gate.yml`); every V4 requirement stays.

## Files

| File | Role |
|---|---|
| `tools/ci_v5_epoch.py` | Evaluator V2 + trusted `POLICY` (class map, semantic registry, gate policy: approvers, signers, the six V4 check names, the gate check name). Stdlib only, Git objects only. |
| `tools/ci_v5_candidate.py` | Generators: ALL_TRACKED epoch candidate of an accepted commit; base-relative delta of a head. Never promotes. |
| `tools/ci_v5_b5.py` | B5 test-admission report (warn-only). JUnit statuses only with an attestation from a `TRUSTED_BASE` lane that binds sha + digests. File/function deltas and *collected* nodes are reported separately (`collected_nodes: UNAVAILABLE` without a SHA-bound `--collect-only`). |
| `tools/ci_v5_shadow.py` | `verdict` / `v4` / `compare` / `gate` / `enforcement` entry points, one per workflow job (the gate and enforcement logic is pure: data in, decision out). The gate lives here, not in a new `tools/` file, so no new CI path needed V4 admission. |
| `.github/workflows/ci_v5_shadow.yml` | The non-required `pull_request` shadow lane (3 jobs, `contents: read`, no secrets). Delete it to remove V5 shadow entirely. |
| `.github/workflows/ci_v5_gate.yml` | The `pull_request_target`-only gate (read-only permissions, no secrets, head read as Git objects only). Delete it to remove the gate. |
| `tests/test_ci_v5_foundation.py` | The A/B/A hostile matrix (synthetic repos): audit cases G1–G24, GA3, T1, T2a, T3c–e, T4a–k, T5b, W1–W11, S1b, R1–R8, A1–A4 + promotion attacks. |
| `tests/test_ci_v5_hardening.py` | Lane separation, B5 / comparison vocabulary, generators, workflow structure. |
| `docs/ci_v5/delta.json` | This PR's finite base-relative delta (exempt from the guard; bound by its own `result_inventory_sha256`). |
| `docs/ci_v5/epoch.candidate.json` | Legacy V1 candidate (epoch state `CANDIDATE_UNTRUSTED`): still readable, reported as `LEGACY_NARROW_GUARD`, never an approved FULL guard. |
| `docs/ci_v5/OWNER_POSTMERGE_ACTIVATION_CHECKLIST.md` | Exact owner steps after the merge (settings, approver, signer, probes, rollback). |
| `tests/test_ci_v5_gate.py` | Gate logic, authorization / enforcement / V4-linkage / FULL-witness / gate-check-ambiguity attacks, end-to-end gate on synthetic repos, workflow structure. |

## Delta V2

```
schema                  FINCO_CI_V5_DELTA_V2
base_sha, base_tree     the protected tip this PR was evaluated against (stale/replayed delta => DELTA_BASE_MISMATCH)
result_inventory_sha256 digest of the guarded inventory of the head (exempt files excluded)
changes[]               {op: add|modify|delete, path, blob, mode, class}   - finite, no wildcard, no same-value change, class recomputed from trusted code
```

Generate it **last** (any later byte change of the PR invalidates it): `python tools/ci_v5_candidate.py delta --base-sha <tip> --head-sha <head> --output docs/ci_v5/delta.json`.
The delta cannot contain its own blob (exempt). A V4 exact-source manifest that *pins* the delta bytes cannot be listed inside it either (hash cycle), so literal
`POLICY.V4_BOUND_EXEMPT` paths are exempt from the delta but never invisible: a change to one is reported and forces `UNKNOWN`.

## Deliberate strengthening vs the V5-2A draft

* **A4** (delete `tests/conftest.py` + exact delta) is `UNKNOWN` here, not `INTEGRITY_PASS`: modifying/deleting any existing file under `tests/` is a possible neutering or
  retirement (owner decision D5: F01 / financial / Save-CAS / tenancy / CSRF / browser / mutation tests must not be disabled), and V5 proves bytes only.
* A new top-level path or root file, once declared, is `UNKNOWN` (class `S`/`UNCLASSIFIED`), not a pass.

## Trust transitions (owner-gated)

1. **Promotion (NOT in this PR).** `docs/ci_v5/epoch.json` is a V2 `ALL_TRACKED` snapshot of an accepted base. A PR that adds/edits it is verdict `transition: PROMOTION_REQUIRES_OWNER` and can never be an integrity pass; mixed
   with any other guarded change it is `PROMOTION_NOT_ISOLATED`. It must be a separate isolated PR, judged by V4 and the owner, and becomes a trusted-base artifact only for the NEXT PR. V4's exact-source ownership rules may still block even that narrow PR (`PROMOTION_GOVERNANCE_BLOCKED`: it then needs its own V4 successor).
2. **FULL witness.** An epoch is a trusted checkpoint only with a green FULL run for its own commit, validated against the real GitHub run (`verify_full_witness`), never a self-declared field. Today `FULL_PROVENANCE_BLOCKED`.
3. **Authorization (D3).** Option A: a distinct approver identity with enforced code-owner review (named in `POLICY.APPROVERS`). Option B: an owner-signed approval commit (key never given to an agent; public key in `POLICY.ALLOWED_SIGNERS`). Neither is configured.
4. **Dual-required pilot.** V5 is added ALONGSIDE V4, never in place of it, only after the owner configures and verifies the settings. Status of this repository: `ACTIVATION_PREPARED_NOT_VERIFIED` at best.

## V4 coexistence

V4 requires every path changed since its `PARENT` to be owned by a registered exact-source cohort. V5-2B added the successor `tests/ci_v5_hardening_scope.py`; this PR adds ONE more finite, terminal exact-source successor (`tests/ci_v5_gate_scope.py`, manifest `docs/ci_v5/gate_3/SOURCE_SUCCESSOR.json`, own test `tests/test_ci_v5_gate_scope.py`) in the literal
one-step chain `C06 -> B1 -> B2 -> B3 -> V5_BOOTSTRAP -> V5_2B -> V5_3`. It binds every owned blob and mode to the immutable accepted base, supersedes only literal paths, and changes no V4 selector, scheduler,
aggregator, policy, weight, node split, required workflow, financial or UI byte. Every further V5 change needs another such successor until V4 changed-path ownership is delegated to V5 for owner-approved
classes (a later, separate owner decision).

## Running it

```bash
python tools/ci_v5_epoch.py --repo . --head-sha <40hex> --base-sha <protected tip> --trusted-ref-tip <protected tip> --tool-source TRUSTED_BASE --check-worktree
python -m pytest tests/test_ci_v5_foundation.py tests/test_ci_v5_hardening.py tests/test_ci_v5_gate.py -q      # FINCO_V5_AB_OUT=<csv> records the A/B/A matrix with exact shas
```

## Residual risks (not claimed away)

* A reviewer who approves a delta without reading it defeats integrity; classes exist to keep the reviewed surface small.
* Test *execution* is untouched by V5: a declared, approved edit that neuters a test is caught only by V4 selection, no-skip rules, FIN-VAL and browser acceptance. V5 never attests that a test ran or passed.
* A `pull_request` workflow can be rewritten by the PR it judges; V4 shares that property today. This is why V5 stays shadow until an immutable lane is configured by the owner.
* The V4-bound exempt manifest is judged by V4's exact pin, not by V5's delta.

## Rollback

Delete `.github/workflows/ci_v5_shadow.yml` (shadow stops; V4 untouched) or revert this PR. No required check, branch protection, policy, scheduler, selector, aggregator, product, financial or UI byte is touched.
