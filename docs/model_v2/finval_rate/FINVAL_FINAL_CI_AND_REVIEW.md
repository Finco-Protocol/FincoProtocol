# FIN-VAL — local acceptance and independent-review disposition

**BLOCKED — EXACT FINANCIAL / GOVERNANCE FINDING**

The source correction is isolated; it is not approved for activation. Existing unversioned records require a Financial Owner provenance/migration disposition. The legacy `main_web.py` producer has been identified outside the currently authorized five application paths and awaits separate exact-path authorization. The requester subsequently clarified that PR handling should be revisited later: no new PR, push, merge, deployment or release activation is performed.

## Baseline and exact source identity

Live main was reverified at `6f10f3927b33a5715ac6313da200d0f96c023524`, tree `62e70c3bfda7a91280c8c16acc89eeef9f780d6b`. PRs #383/#384/#385 are merged. Current merge-base and original blobs for all intended files are in `evidence/preflight.json`. Full history is available and the additive historical security/governance checks passed locally. No historical pin value is replaced.

The final committed local candidate SHA/tree and worktree status are reported in the delivered external exact-head manifest to avoid a self-referential commit hash in this file. Hosted exact-head PR CI is **not claimed**: PR/push handling was deferred by the requester. Baseline CI success is not candidate CI success.

## Executed test batches

Each row is an actual execution record. Some batches overlap, so rows must not be summed as unique tests. Earlier failing reproductions are deliberately retained; they are not final-pass claims.

| Evidence | Passed | Failed | Skipped |
|---|---:|---:|---:|
| adapter-complete.xml | 537 | 10 | 0 |
| adapter-regression.xml | 161 | 5 | 0 |
| baseline-rate.xml | 4 | 9 | 0 |
| browser.xml | 20 | 0 | 0 |
| ev-rate-final.xml | 53 | 0 | 0 |
| financial-security.xml | 313 | 0 | 0 |
| governance.xml | 186 | 0 | 0 |
| native-identity.xml | 0 | 0 | 10 |
| provenance-fixtures.xml | 22 | 0 | 0 |
| rate-and-b2.xml | 120 | 0 | 0 |
| rate-contract-final.xml | 44 | 0 | 0 |
| rate-contract.xml | 32 | 4 | 0 |
| rate-final.xml | 64 | 0 | 0 |
| rate-run.xml | 21 | 3 | 0 |

- The baseline rate failures reproduce the original defect.
- The first numerical matrix expected all valid rates to yield feasible projects; three failures exposed unchanged funding/SHL refusals. Final tests now require those exact refusals and record no fabricated result. No engine tolerance/golden change was used.
- The broad adapter batch initially found unversioned manually assembled test fixtures. Explicit known percent provenance was added to non-golden EV fixtures; the Wind OPEX fixture now serializes the same factory economics as human percent rather than relying on the removed dual-format heuristic. Financial assertions/expected outputs remain unchanged. The targeted fixture rerun is recorded separately.
- Native executing checks are skipped because local GCC 14.2 does not match the approved GCC 13.3 build. No compiler check was bypassed and no unapproved binary was generated. Candidate exact-head native/hosted CI remains required before acceptance.
- Browser acceptance covers canonical Save/Run, six statements, scenarios, protected references and React D-029 response-loss/original-binding paths on an isolated local app, not hosted customer data.

## Source and security boundary

No diff to `financial_engine/`, `finco_core/`, React components/bundles, solvers, tolerances, the atomic workspace persistence authority or historical Run schema. No database migration, historical Run mutation, reference mutation, release activation or CI bypass was performed. New application logic is limited to the explicitly authorized files. Additive successor tests preserve original SEC-02/B2C1/D-029 blobs and continue structural negative gate tests.

## Remaining independent decisions

1. Approve the rate contract and inspect new numerical evidence, including infeasible input combinations and undefined return cases.
2. Decide treatment of existing unversioned/ambiguous records; no value-based inference or automatic repair is acceptable.
3. Resolve the legacy producer's exact-path scope before treating the correction as covering every application creation path.
4. Resume the single governed PR workflow when directed, run exact-head hosted CI and approved-toolchain native identity, and obtain independent financial/security review.
5. Treat SHL timing as a separate governed design mission and sponsor-return display changes as Overnight B work. This branch changes neither economics nor SHL formulas.

Committed XML evidence copies normalize trailing whitespace only; raw execution artifacts remain in the delivered evidence package. Test outcomes and numeric payloads are unchanged.
