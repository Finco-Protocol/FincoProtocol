# Owner post-merge activation checklist — V5 gate alongside V4

Status when this file was written: **`ACTIVATION_PREPARED_NOT_VERIFIED`** at best, and **`FULL_PROVENANCE_BLOCKED`** today. Nothing below has been done by an agent; nothing may be done by one. A green run of the gate workflow is not enforcement.
Every step lists the evidence that proves it. If a step cannot produce that evidence, stop and keep the V5 gate OUT of the required checks.

## 0. Preconditions (all must hold before step 1)

- [ ] This PR is merged by YOU (ordinary merge commit) after the six V4 checks are green at the exact head you reviewed. Evidence: the merge commit and the check-run list at that head.
- [ ] `docs/ci_v5/epoch.json` does NOT exist on `main` (this PR ships no trust anchor): the gate reports `NO_TRUSTED_EPOCH` and will `BLOCK` everything until a separate, isolated, owner-approved promotion PR adds an epoch whose FULL witness is a green run that the gate itself verifies against GitHub.
- [ ] A green **CI V4 FULL** run exists for the accepted tip. Today it does not: the unsharded FULL step exceeds its 19,200 s budget (run 43828509961: 2,242 of 25,406 tests; one module, `tests/test_ci_v3_outcome_reconciliation.py`, used 16,008 s; at least two `F` results also appeared). Fixing that is a separate V4 change (it touches frozen V4 control files and test timing) and is NOT part of this PR. Evidence: a run id whose `sha` equals the epoch's `base_commit` and whose conclusion is `success`.

## 1. Read the real settings (read-only)

GitHub → Settings → Branches → `main` (and Settings → Rules → Rulesets). Save the JSON the owner/admin token can read:

```bash
gh api repos/Finco-Protocol/FincoProtocol/branches/main/protection > protection.json
gh api repos/Finco-Protocol/FincoProtocol/rules/branches/main > rules.json
python tools/ci_v5_shadow.py enforcement --protection-json protection.json --rules-json rules.json
```

The integration used to prepare this PR got **HTTP 403** on the first call and `[]` on rulesets: that proves nothing in either direction. If YOU also get 403, use an admin-scoped token or read the UI and fill `protection.json` by hand; do not infer.

## 2. Choose and configure an independent approver (D3)

The repository's `.github/CODEOWNERS` names one identity (`@FincoProtocol`) that authors and merges PRs; GitHub does not count an author's approval of their own PR. Pick one:

- **Option A — a second human/app identity.** Add its login to `POLICY.APPROVERS` in `tools/ci_v5_epoch.py` through a reviewed PR (with the V4 ownership successor that edit needs), make it a code owner of the guarded classes, and enforce code-owner review.
- **Option B — an owner-signed approval commit.** Generate an ed25519 SSH key on YOUR machine (the private key never leaves it, never given to an agent or CI). Put the public key in `POLICY.ALLOWED_SIGNERS` as `("owner-signer", "ssh-ed25519 AAAA…")` through a reviewed PR. To approve a PR, add an empty commit signed with that key as the PR head (`git -c gpg.format=ssh -c user.signingkey=<key>.pub commit -S --allow-empty -m approve`) and re-run the gate. The signature binds the exact commit; any later push invalidates it.

Evidence: a synthetic PR where the gate reports `authorization: AUTHORIZATION_APPROVED` for the approver and `AUTHORIZATION_BLOCKED` for the author.

## 3. Promote an epoch with a green FULL witness (owner decision, separate from this PR)

Only after step 0's FULL condition: `python tools/ci_v5_candidate.py candidate --commit <accepted tip> --output docs/ci_v5/epoch.json --full-run-id <FULL run id>` in a PR that changes only the epoch (+ the V4 successor V4 needs). Its verdict is `PROMOTION_REQUIRES_OWNER`; it takes effect for the NEXT PR only. V4's exact-source ownership may block even that narrow PR (`PROMOTION_GOVERNANCE_BLOCKED`) and then needs its own V4 successor. Evidence: the next PR's gate record shows `epoch_state: TRUSTED_BASE` and `full_witness: FULL_WITNESS_VERIFIED_AGAINST_GITHUB`.

## 4. Add the gate to the required checks — ADDITIVE ONLY, V4 untouched

Settings → Branches → `main` → Require status checks to pass → add **`V5 gate (trusted base)`** (the job name in `.github/workflows/ci_v5_gate.yml`; it only appears after the gate has run once on a PR; exactly ONE job in the repository produces this name, so no skipped duplicate can satisfy the requirement). Keep every existing required check. Also confirm:
- [ ] "Require branches to be up to date before merging" ON (strict)
- [ ] "Do not allow bypassing the above settings" / "Include administrators" ON; no bypass actors in rulesets
- [ ] "Require review from Code Owners" ON; "Dismiss stale pull request approvals when new commits are pushed" ON; "Require approval of the most recent reviewable push" ON; ≥ 1 approving review
- [ ] The six V4 checks are all still required: `CI V4 gate`, `mandatory-browser-evidence`, `rate-contract-native-and-browser`, `authoritative-history`, `dependency-audit`, `compile-and-safety`

Then re-run step 1: `ENFORCEMENT=ENFORCEMENT_VERIFIED` is the only proof. Keep the output.

## 5. Probe on real PRs (needs your permission to open them; they are disposable)

- [ ] **Benign:** a PR changing only a prose/non-semantic file with an exact delta (`python tools/ci_v5_candidate.py delta --base-sha <tip> --head-sha <head> --output docs/ci_v5/delta.json`, generated LAST) and an independent approval at the head → gate `INTEGRITY_PASS_AUTHORIZED`, the six V4 checks green.
- [ ] **Semantic:** a PR touching a semantic path → gate `BLOCK` until independent authorization AND the same head's six V4 checks are green, then `DEFERRED_TO_V4_VERIFIED` (never labelled as an integrity pass).
- [ ] **Malicious:** an undeclared change / a new root file / a deleted test / a replayed delta / an edited workflow → gate `BLOCK` (red). Author self-approval → `BLOCK`.
- [ ] With the gate required, GitHub refuses the merge button for the malicious PR.

Only when steps 2–5 all have their evidence may anyone write `DUAL_REQUIRED_ACTIVATED_VERIFIED`.

## 6. Rollback (owner approval needed; V4 stays in force)

Remove only `V5 gate (trusted base)` from the required checks (Settings → Branches → `main`), or delete `.github/workflows/ci_v5_gate.yml`. Do not rewrite accepted `main`;  Evidence: PRs merge again under the six V4 checks alone.

## Known residual risks

- A reviewer who approves a delta without reading it defeats integrity; V5 proves bytes and declared changes only, never that a test ran or passed (V4 + FULL + browser own execution).
- `pull_request_target` is security-sensitive by nature: this job never checks out or executes the head and has read-only permissions, but any future edit that does would break that. The gate's structure is asserted by `tests/test_ci_v5_gate.py`.
- The gate only evaluates on `opened / synchronize / reopened / ready_for_review`; after approving, re-run it.
- The repository is **public**: nothing in this checklist or the evidence may contain secrets, private keys or client data.


## CI runtime acceptance

The trusted default-branch workflow publishes `CI Performance Budget` for the exact PR head. Require that commit status in strict mode bound to the GitHub Actions app, alongside all six V4 checks. The 2,100 s target is informational. The hard cap remains 2,400 s. The effective rules endpoint omits bypass actor information. Supply administrator-enforced branch protection and review settings when running the enforcement verifier.

Both FULL witness consumers require the original GitHub attempt and all jobs for the exact source. Measure from GitHub run creation through the completed record job, including queue, planning, shard setup, independent recollection and F01. A fresh complete dispatch on accepted main is needed after a failed or incomplete attempt. A successful run above 2,400 s is ineligible for release or promotion.

## Deferred private T01-B/C tax dataset reconciliation

Owner decision 2026-11-20: the private T01-B/C 34-jurisdiction / 634-row reconciliation is DEFERRED until after V5 activation. This is an informed acceptance of the limited risk that FULL and release may run without validating those private tax-reference input rows. It is **not** a pass, not an inventory change, and not a weakening of any other gate.

- The only accommodation is ONE runtime skip, count 1, in `docs/ci_v4/full_skip_baseline.json`: `tests.tax_reference_registry.test_private_dataset::test_private_34_634_reconciliation`, reason `PRIVATE_T01_BC_DATASET_DEFERRED_POST_V5`, reported everywhere as `SKIPPED_NOT_PASSED`. Any second occurrence, any other tax/browser/financial skip, a missing, failed or incompletely executed node, or a changed test still blocks FULL and the release gate. The 67 collection skips are a separate category and are unchanged.
- The baseline schema has no expiry field and none was added. The allowance is therefore tracked here as an owner-owned obligation: it ends no later than the first post-activation tax-dataset validation workstream and must not become permanent.
- [ ] Locate the authentic source CSV in the T01-B/C/D/E or Fable Phase 1B private evidence and validate its provenance and checksum. No synthetic or summary-derived reconstruction may be presented as the original. Evidence: the recorded checksum and the provenance note.
- [ ] Confirm 34 jurisdictions and 634 rows (documented rejected rows included). Evidence: the loader's own counts.
- [ ] Provide the file to the approved runner so `TAX_REF_PRIVATE_DATASET` is an actual file path, never publishing the CSV, a secret or a private artifact on GitHub. Run the unmodified test with the real data. Evidence: a JUnit in which `test_private_34_634_reconciliation` is `passed`, not `skipped`.
- [ ] Remove the baseline entry in a new reviewed, V4-governed PR with independent reviewer sign-off, and record the closure. Evidence: the merged PR and the sign-off.
