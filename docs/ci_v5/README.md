# CI V5 — epoch foundation + B5 admission report (SHADOW ONLY)

**Status: observational shadow. Nothing here is a required check, selects, skips, moves or demotes a test, or changes V4. V4 stays authoritative and is the
automatic fallback. Activation is a separate, owner-approved PR (V5-2) after demonstrated parity.**

## What this adds

| File | Role |
|---|---|
| `tools/ci_v5_epoch.py` | The evaluator (stdlib only). Proves `guarded inventory(HEAD) == epoch (+) delta` and `guarded inventory(trusted BASE) == epoch` from Git **objects** (one `ls-tree` per commit; 8–11 Git children measured, no cache). |
| `tools/ci_v5_candidate.py` | Generates the `CANDIDATE_UNTRUSTED` epoch + source atlas from the real V4 guard scope, and the explicit per-PR delta. Never promotes, commits or pushes. |
| `tools/ci_v5_b5.py` | **B5**: public-safe JSON + concise job summary over the accepted B3 `test_admission_report` (loaded from a path; logic reused, not cloned). |
| `tools/ci_v5_shadow.py` | Orchestrator: V5 verdict, V4 one-pass central gate for comparison, B5, comparison record, summary. |
| `.github/workflows/ci_v5_shadow.yml` | ONE non-required, read-only, no-secret `pull_request` lane. Delete this file to remove V5 shadow entirely. |
| `docs/ci_v5/epoch.candidate.json` | Epoch snapshot of accepted `main` `c8b7e81…` (2,364 guarded entries + atlas). **`CANDIDATE_UNTRUSTED`.** |
| `docs/ci_v5/delta.json` | This PR's finite, explicit protected delta (reviewed by a human; see below). |
| `tests/test_ci_v5_foundation.py` | One bounded A/B/A harness (31 synthetic tamper classes) + ref/shell-injection, mutation-between-evaluations, trust-source, B5 provenance and comparison-rule tests. |

## Model in one paragraph

An **epoch** is a reviewed snapshot of the protected source `(path, Git blob SHA, mode)`, bound to a commit SHA and its tree SHA, schema-versioned,
canonical bytes, with a content digest (integrity, not authenticity — authenticity is *where it is read from*). A PR carries a finite **delta**
(`add` / `modify` / `delete` with the exact new blob and mode; no wildcards; a rename is an explicit delete + add). The verifier rejects anything not
named: undeclared byte / mode / symlink / deletion / rename / addition, path traversal, duplicates and case collisions, a delta that widens the guard,
a delta bound to another epoch, a forged or non-canonical epoch, a pinned SHA that does not own its tree or is not accepted history, a stale epoch, a
wrong or symbolic ref, a dirty or untracked guarded worktree, and any PR edit of the trust anchor.

## Trust bootstrap (tested)

1. **This PR (bootstrap).** `docs/ci_v5/epoch.json` does not exist at the trusted base. The epoch is read from the PR head as
   `docs/ci_v5/epoch.candidate.json` → state **`CANDIDATE_UNTRUSTED`**. It is evaluated for comparison only; `authoritative=false`; a PASS is reported as
   `NON_AUTHORITATIVE_PASS` and can never authorise the PR that carries it (a head can always self-authorise its own candidate — which is exactly why it is
   non-authoritative).
2. **Promotion (owner-reviewed PR).** Regenerate a candidate from the then-accepted `main`, review it, and move it to `docs/ci_v5/epoch.json`. The
   promotion PR must change nothing else guarded; a PR that adds or edits `epoch.json` is `TRUST_ANCHOR_MODIFIED` for V5.
3. **Later PRs.** The epoch and the evaluator are read from the **trusted base commit only** (`git archive <merge-base>`), never from the PR head → `TRUSTED_BASE`.

`V5 PASS` means *"HEAD equals the epoch plus the declared delta"*. It does **not** mean *"the delta is approved"*: approval of `docs/ci_v5/delta.json`
is human review (owner decision: CODEOWNERS / required review on that path — not configured here).

## Guard scope and the atlas (COVERED / GAP / UNKNOWN)

The guard is derived from V4, not invented: union of every cohort manifest pin (741) + RC-UX presentation paths (322) + mutation-security `BLOBS` (112) +
the composite's untracked scope `app/ financial_engine/ finco_core/ domain/ .github/ main_web.py` (1,393) + the policy's `control_paths` (275) →
**2,364 guarded paths**. All five path-scope rows are `COVERED`. The invariant rows are explicit **GAP / UNKNOWN** and V4 keeps them:
changed-path ownership of the **1,913 unguarded tracked paths** (V4 owns every path, V5 only the guard — a deliberate narrowing and an owner decision),
mutation-security AST semantics, successor-chain semantics, gitignored files, and test **execution** (F01 / native / browser / security / tenancy /
Save-CAS stay in V4 and FULL). A delta touching a semantic-invariant path yields `UNKNOWN`, never PASS.

## B5 (inside the same shadow lane)

Per PR, automatically: added/removed/renamed/changed test modules; `AST_FUNCTION_DELTA` only (exact node ids need a SHA-bound `--collect-only` of both
trees → `UNKNOWN`); admission fields with UNKNOWN-for-missing; new skip/xfail vs base; duplicate **candidates** only; FAST/RISK/FULL selection from a
*supplied* trusted-base plan else `UNKNOWN`; JUnit seconds/status only with a matching `hosted_run` attestation (SHA + digests), otherwise
`UNVERIFIED_INPUT` and withheld. Status vocabulary `PASS / FAIL / NOT_SELECTED / SKIPPED / CANCELLED / UNKNOWN`; a module with one skipped node is
never PASS. A failing reporter is rendered as `UNAVAILABLE` and fails the harness step visibly — never a fabricated empty PASS. No token, no network, no
pytest run. Local cost is dominated by B3's duplicate scan (≈850 Git children for a PR that adds a test module).

## Running it

```bash
python tools/ci_v5_epoch.py --repo . --head-sha <40hex> --base-sha <40hex> --check-worktree
python tools/ci_v5_candidate.py candidate --repo <clean checkout of ACCEPTED main> --commit <its sha> --output docs/ci_v5/epoch.candidate.json
python tools/ci_v5_candidate.py delta --repo . --epoch docs/ci_v5/epoch.candidate.json --head-sha <40hex> --output docs/ci_v5/delta.json
python -m pytest tests/test_ci_v5_foundation.py -q        # FINCO_V5_AB_OUT=<csv> records the A/B/A matrix
```

Regenerate `delta.json` after any change to a guarded file of this PR (`tools/ci_*`, `tests/test_ci_*`, `.github/`); `delta.json` itself is not guarded.

## `LEGACY_GOVERNANCE_BLOCKED` (read this before reviewing)

V4 requires **every** path changed since its `PARENT` to be owned by a registered exact-source cohort. Measured: one inert one-line new file under `tools/`
makes 40 of 43 cohorts non-exact and the composite `False`. A V4-compatible successor of the previous kind (B3: 32 files, +2,194 / −79 lines) was
**deliberately not written** (stop rule: no new ~2,000-line closure to ship a tool whose purpose is to end that closure; no forged pins, no loosened
frozen scopes). Consequently **the required V4 governance gate is expected to be RED on this PR** and this PR is not merge-ready. Owner decision:
see `07_GAPS_AND_OWNER_DECISIONS.md` in the evidence packet (one-time V4 successor vs an owner-approved exception for this bootstrap PR only).

## Rollback

Delete `.github/workflows/ci_v5_shadow.yml` (shadow stops; V4 untouched) or `git revert` this PR. No required check, branch protection, policy, scheduler,
selector, aggregator, product, financial or UI byte is touched.
