# CI V5 — evaluator schema V2 (V5-2B hardening) — SHADOW ONLY

**Status: observational shadow. Nothing here is a required check, selects, skips, moves or demotes a test, or changes V4. V4 stays authoritative and is the
automatic fallback. This PR is V5-2B only: it adds no trusted epoch, no required check and no authorization input.** The later transitions (trusted-epoch
promotion V5-2C, dual-required pilot V5-3) are separate, owner-gated PRs/settings; their exact steps are at the end of this file.

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
the head, no failure and no unknown. Everything else is `INTEGRITY_FAIL` or `UNKNOWN`. In this PR no trusted epoch exists, so **every verdict here is
`UNKNOWN` or `INTEGRITY_FAIL`, by construction**; hosted runs prove the failure paths and the plumbing, not an approved pass.

## Files

| File | Role |
|---|---|
| `tools/ci_v5_epoch.py` | Evaluator V2 + trusted `POLICY` (class map, semantic registry). Stdlib only, Git objects only. |
| `tools/ci_v5_candidate.py` | Generators: ALL_TRACKED epoch candidate of an accepted commit; base-relative delta of a head. Never promotes. |
| `tools/ci_v5_b5.py` | B5 test-admission report (warn-only). JUnit statuses only with an attestation from a `TRUSTED_BASE` lane that binds sha + digests. File/function deltas and *collected* nodes are reported separately (`collected_nodes: UNAVAILABLE` without a SHA-bound `--collect-only`). |
| `tools/ci_v5_shadow.py` | `verdict` / `v4` / `compare` entry points, one per workflow job. |
| `.github/workflows/ci_v5_shadow.yml` | The non-required `pull_request` shadow lane (3 jobs, `contents: read`, no secrets). Delete it to remove V5 shadow entirely. |
| `tests/test_ci_v5_foundation.py` | The A/B/A hostile matrix (synthetic repos): audit cases G1–G24, GA3, T1, T2a, T3c–e, T4a–k, T5b, W1–W11, S1b, R1–R8, A1–A4 + promotion attacks. |
| `tests/test_ci_v5_hardening.py` | Lane separation, B5 / comparison vocabulary, generators, workflow structure. |
| `docs/ci_v5/delta.json` | This PR's finite base-relative delta (exempt from the guard; bound by its own `result_inventory_sha256`). |
| `docs/ci_v5/epoch.candidate.json` | Legacy V1 candidate (epoch state `CANDIDATE_UNTRUSTED`): still readable, reported as `LEGACY_NARROW_GUARD`, never an approved FULL guard. **No `epoch.json` ships here.** |

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

## Trust transitions (owner-gated; none is performed by this PR)

1. **Promotion (V5-2C).** Only after this PR is accepted into `main` and the six V4 required checks are green on that tip: generate a candidate for the accepted tip
   (`ci_v5_candidate.py candidate --commit <tip> --full-run-id <FULL run id>`), review it, and add it as `docs/ci_v5/epoch.json` in a PR that changes nothing else guarded.
   Such a PR is verdict **`transition: PROMOTION_REQUIRES_OWNER`** (never a pass): the epoch must be a V2 ALL_TRACKED snapshot of exactly the accepted base and nothing else guarded
   may differ (`PROMOTION_NOT_ISOLATED`). It becomes trusted only for the **next** PR whose trusted base contains it; no promotion is needed after every PR; removing the anchor is
   an intentional, owner-gated rollback.
2. **Authorization (D3).** Integrity is not authorization. Either (A) a separate agent identity + human code-owner approval **with enforced GitHub protection**
   (required review from code owners, dismiss stale approvals, require approval of the most recent push, no bypass), or (B) an owner-signed ledger whose private key is never
   given to an agent, verified by trusted code. Neither exists yet; `.github/CODEOWNERS` names a single identity that also authors and merges PRs, so **no enforcement is claimed**.
3. **Dual-required pilot (V5-3).** V5 is added **alongside** the still-required V4 checks. Status: `READY_FOR_OWNER_CONFIGURATION` at best; see the owner steps below.

### Owner-executable steps for the pilot (read-only for you to verify first; this PR changes no setting)

1. Verify the current protection (Settings → Branches → `main`, and Settings → Rules → Rulesets): which checks are required, "Require branches to be up to date", "Do not allow bypassing"
   / "Include administrators", code-owner review, "Dismiss stale pull request approvals", "Require approval of the most recent reviewable push". The integration used for V5-2B could
   not read branch protection (HTTP 403) and saw `[]` rulesets: that is **not** proof that none exist.
2. The authoritative lane must not be a workflow the PR can edit. Choose one (a security review is part of the decision): an organization/ruleset **required workflow** pinned to a ref of a
   trusted repository, or a carefully constrained privileged-trigger workflow that checks out only the *base* and reads the head as Git objects (never runs head code, no write token).
   `on: pull_request` (this PR) is shadow only.
3. Intended rule diff (additive only): add the V5 verdict check name (e.g. `V5 verdict`) to the required status checks of `main`; keep every existing required check; keep "up to date" strict.
4. Probe before relying on it: one benign no-op PR (expect `INTEGRITY_PASS` + independent approval) and one malicious PR (undeclared change / tampered workflow / unapproved delta) — the second must be
   red or cancelled, never green. `UNKNOWN` on a semantic path may be green only as `DEFERRED_TO_V4_VERIFIED` when the exact same head is independently verified by V4 and the owner's authorization exists.
5. Rollback: remove only the V5 check from the required list; the V4 requirements stay in force.

## V4 coexistence

V4 requires every path changed since its `PARENT` to be owned by a registered exact-source cohort. V5-2B edits files owned by the one-time V5 bootstrap cohort, so it carries **one more finite,
terminal exact-source successor** (`tests/ci_v5_hardening_scope.py`, manifest `docs/ci_v5/hardening_2b/SOURCE_SUCCESSOR.json`, own test `tests/test_ci_v5_hardening_scope.py`) in the accepted literal
one-step chain `C06 -> B1 -> B2 -> B3 -> V5_BOOTSTRAP -> V5_2B`. It binds every owned blob and mode to the immutable accepted base, supersedes only literal paths, and changes no V4 selector, scheduler,
aggregator, policy, weight, node split, required workflow, financial or UI byte. Every further V5 change needs another such successor until V4 changed-path ownership is delegated to V5 for owner-approved
classes (a later, separate owner decision).

## Running it

```bash
python tools/ci_v5_epoch.py --repo . --head-sha <40hex> --base-sha <protected tip> --trusted-ref-tip <protected tip> --tool-source TRUSTED_BASE --check-worktree
python -m pytest tests/test_ci_v5_foundation.py tests/test_ci_v5_hardening.py -q      # FINCO_V5_AB_OUT=<csv> records the A/B/A matrix with exact shas
```

## Residual risks (not claimed away)

* A reviewer who approves a delta without reading it defeats integrity; classes exist to keep the reviewed surface small.
* Test *execution* is untouched by V5: a declared, approved edit that neuters a test is caught only by V4 selection, no-skip rules, FIN-VAL and browser acceptance. V5 never attests that a test ran or passed.
* A `pull_request` workflow can be rewritten by the PR it judges; V4 shares that property today. This is why V5 stays shadow until an immutable lane is configured by the owner.
* The V4-bound exempt manifest is judged by V4's exact pin, not by V5's delta.

## Rollback

Delete `.github/workflows/ci_v5_shadow.yml` (shadow stops; V4 untouched) or revert this PR. No required check, branch protection, policy, scheduler, selector, aggregator, product, financial or UI byte is touched.
