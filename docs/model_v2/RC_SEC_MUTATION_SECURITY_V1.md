# FINCO SEC-01 / SEC-02 correction — review and handoff

Status: implementation complete locally; publication and exact-head CI evidence recorded separately in `results/publication.json` and `results/ci-status.json` when available. Draft review only. No merge, deployment, activation, or Financial Owner self-approval.

## Reproduction and fix

The original private-db route reproduction completed 42 cases. Canonical protected Solar and Wind Base selection each returned 303 and changed only `workspace_states` (two confirmed protected metadata writes). Engine calls were zero. This observation does not establish a change to financial results.

All six scenario handlers now refuse protected references after access resolution and before writes. Foreign resources remain 404. Real owned working copies retain their workflow. Reference Last Run bootstrap snapshots independently verify refusal without any table, timestamp, history, or financial payload drift.

SEC-02 adds 21 explicit operation domains using the existing HMAC issuer/validator, bound to the exact actor session and project code. It covers scenario mutations, ordinary scalar saves, grid and batch saves, CAPEX/OPEX and export audit requests. This is project-level request binding; it is neither a row capability nor a one-time token. CAS and row versions remain separate checks. Legacy and React callers send each operation's own issued token, including distinct cost button and batch tokens.

Run, Clone and Capital Stack token domains remain unchanged. Revenue's released plain signed token contract remains unchanged. Export remains POST and records its existing audit row; invalid requests do not write, valid XLSX export adds one audit row and preserves immutable history. A failed export response cannot promise that no audit append occurred.

No financial-engine/formula, registry, persistence schema, signing/KID, production financial authority, certificate or Trust computation changes were made. Run, history-export, Trust-fragment and library Clone handler source bodies remain identical to the original main. No Origin enforcement is introduced without actual deployment configuration. D028/D029 and export redesign remain deferred.

## Historical governance

Original released SOURCE_HEAD and four blob constants remain literal and are independently verified against historical Git objects and ancestry. A strict successor admits only source commit `1800bf6092af650f18aa6ae70e9df221797090fd`, its exact source/caller/test blob inventory and declared consumer inventory; drift or missing history fails closed. The old router blob is `a5a3874acd71074863e38036ed18951fd7dd6297`; corrected router blob is `cbff734453400269589d9fcc5cec702cbc239b55`.

The exact proposed five-file governance diff is `SUCCESSOR_PROPOSAL.diff`, SHA256 `44e9b0720910f8d8d96cf9c0c701c7ba24ef8092cce8364115ad9e530c34f951`. `results/successor-proposal.json` preserves the proposal-time status; `results/owner-publication-authorization.json` records subsequent direct publication authorization. Owner messages: implementation “odobravam sve”; after being told a successor remained before push, publication “napravi pr u pushaj”. Neither grants merge/deploy/activation authority.

## Validation evidence

| Evidence | Result |
|---|---|
| Final targeted mutation + released Run/Clone + Capital Stack | 88 tests, 0 failures, 0 errors, 0 skipped |
| Fixed caller modules and cases | 98 tests, 0 failures, 0 errors, 0 skipped |
| Previously unexecuted regression tail | 44 tests, 0 failures, 0 errors, 0 skipped |
| Real Chrome HTTPS cookie / Legacy form check after merge | 1 tests, 0 failures, 0 errors, 0 skipped |
| Strict successor / historical governance | 166 tests, 0 failures, 0 errors, 0 skipped |

Earlier broad caller runs recorded 676 pass / 13 fail / 2 errors in group 0, and 567 pass / 4 fail in group 1. All 17 reported failures were followed by passing focused checks; the remaining 44 nodes also passed. These runs overlap, so counts must not be added as unique tests or described as one green exact-head suite. Old logs with failures are retained and superseded by named rechecks.

Two Windows pytest errors arise from an unchanged codec test's 70,000-character generated node ID exceeding Windows environment-entry limits. The clean original main reproduces them. The exact unchanged assertions pass by direct invocation; this is not a substitute for canonical Linux pytest. See `results/windows-codec-node-limitation.json` and baseline XML/log. No skip, input reduction, node-id replacement, CI-role or required-gate change was introduced.

233 existing positive request calls were migrated explicitly. 3,746 existing assert ASTs remained identical after normalizing only the helper-call transport syntax. The helper signs from the effective real request cookie; negative requests remain direct. Capital Stack requests are passed through without manufacturing a token. Pure markup fixtures receive an inert display-only string, not an authenticated capability.

The actual browser used explicit isolated HTTPS, Secure=true, HttpOnly=true, SameSite=Lax. Same-origin missing-token and same-site cross-origin requests carried cookies, returned 403 and left the full DB unchanged. Cross-site requests omitted the Lax cookie and returned 401 unchanged; valid same-origin returned 303 and wrote. Native Legacy Add/Duplicate/Deactivate serialization was exercised. Production proxy, host and cookie settings were not audited; this is a controlled configuration result, not production validation.

Local runtime: Windows CPython 3.12.10, installed FastAPI 0.136.3 (repository pin 0.136.1). React TypeScript and Vite build passed again after merging current main. Exact-head Linux CI, browser/source-safety and five-worker attestation must be verified on the published commit before readiness is asserted.

## Current-main integration

Initial reproduction base: `d745b69bbb491525bbc90d10aafff3b8d5f26f82` (PR #378 merged). Main advanced to `80dbe67b42052ba7797f1466eb66e466aa1e3896` (PR #380); integrated with a normal merge, preserving both histories. Only generated React JS conflicted; resolved by a full build of merged sources. No rebase, squash, cherry-pick or force-push.

## Continuation

Inspect the Draft PR and exact published head. Verify mandatory CI, all workers 0–4, immutable source/coverage/phase/cleanup attestations, browser acceptance and public source safety. Download and independently inspect evidence rather than relying only on green job labels. If a gate fails, correct it normally and rerun for the new head. Keep one Draft PR; do not merge, deploy or activate. Preserve historical pins and require renewed source review for further security-source changes.

The review ZIP contains source changes, diffs, tests, evidence and the supplied audit input. Private databases, runtime cookies/tokens, local TLS keys/certificates, node_modules, caches and .git are excluded. ZIP parts are each capped at 30,000,000 bytes and individually readable.
