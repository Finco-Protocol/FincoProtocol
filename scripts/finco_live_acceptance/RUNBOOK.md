# Operator runbook

## Prerequisites

Use the same Python environment and Playwright/Chromium dependencies as the existing repository browser acceptance. There is no new dependency, browser service or install/build hook. In a prepared checkout, run the explicit manual self-check command in README. Use the managed environment's proxy/CA settings; never disable TLS verification.

Output must be a fresh private directory outside the checkout. The runner refuses overwrite/reuse to preserve evidence and creation-intent ledgers. Keep output permissions private. Neither output nor storage-state/session/reference ZIP files belong in Git. No deployment implicitly invokes this tool.

## Anonymous production read-only

```
python -m scripts.finco_live_acceptance run --base-url https://app.finco.one \
  --mode read-only --technology solar,wind --viewports 1440,1024,390,320 \
  --route-timeout 15 --global-timeout 600 \
  --evidence-dir /private/release-unique-id
```

Only the static JS/CSS and stateless login route are safe without an already authenticated session. FINCO auto-provisions demo identities on anonymous application GET, so those routes are refused, not casually browsed. Expect BLOCKED_AUTH/NOT_CAPTURED for protected routes and BLOCKED_UNSAFE_TARGET for live functional writes. No credentials are assumed or requested in chat.

By default, expected bundle bytes come from `static/react/finco-react.js` and CSS in this checkout. Alternatively specify **both** `--expected-js-sha256` and `--expected-css-sha256` from the approved release artifact. Never use a guessed asset version, observed host environment variable or Git branch name as byte proof.

## Existing isolated synthetic session

An operator supplies a private Playwright storage-state file outside the evidence directory. Do not perform login through this runner. A separate private specification contains exactly:

```json
{
  "storage_state": "/private/synthetic-storage-state.json",
  "account_scope_sha256": "<64-lowercase-hex-from-verified-synthetic-account>",
  "synthetic_account": true,
  "projects": {
    "solar": {"code": "<existing-synthetic-code>", "name": "ZZ-SYNTH-ONACCEPT01-example-solar"}
  }
}
```

Add Wind independently when available. The runner reads the existing authenticated-only setup-drafts scope endpoint, checks the account hash, verifies all paginated owned projects have the tool prefix and are not protected, and proves each selected project's technology/owner capability/name. Missing proof blocks navigation/screenshots. Existing protected/reference projects are not mutated or treated as owned.

Pass `--session-spec /private/spec.json` for authenticated read-only navigation. The specification is never copied into output; only identity hashes are recorded. Screenshots are synthetic-only and mask input fields. Reference packets can be supplied with repeated `--reference-zip /private/prior.zip`; their hashes/old finding references are recorded, never treated as commands.

## Nonproduction synthetic mode

Only an explicit-port loopback React deployment is allowlisted in V1. Legacy staging and arbitrary preview hostnames are not approved by a flag. If no controlled React deployment/session exists, retain BLOCKED_ENV and deliver the tool without claiming functional live acceptance.

```
python -m scripts.finco_live_acceptance run --base-url http://127.0.0.1:8765 \
  --mode synthetic-writable --allow-synthetic-writes \
  --session-spec /private/isolated-session.json \
  --technology solar,wind --viewports 1440,1024,390,320 \
  --evidence-dir /private/isolated-unique-id --global-timeout 600
```

The operator must control this local deployment, its database and account; do not tunnel production through localhost. Exact frontend proof and server identity guards precede creation. Project names carry a generated execution prefix. Canonical Save/Run/CSRF/CAS and original browser controls remain authoritative. No flags, tax activation or existing data are changed. Unsupported seed/label/template/authority contracts stop with explicit reasons.

A stale/unknown creation is never blindly retried. Preserve `PROJECT_LEDGER.private.json`; reconcile its own synthetic names with the isolated owner. Do not rerun with another output directory to evade an unresolved creation. No production writable mode exists. Fault-injection and BESS claims remain untested/unverified unless a separately controlled fixture proves them.

## Collection, cancellation and cleanup

Each output has route/viewport matrix, L01–L10 comparison, release provenance, functional matrix, TEST_REPORT and SHA256 manifest. Two screenshots are required per visited row; NOT_CAPTURED remains visible. Validate with `python -m scripts.finco_live_acceptance validate-evidence <directory>`. Store the private directory/ZIP with its manifest; no raw production API responses or auth data are retained.

Ctrl-C produces cancellation evidence and closes the browser. Route and total timeouts are finite. An outer worker watchdog allows at most 10 seconds for normal teardown, then bounded signal escalation; it reuses the existing Linux subreaper cleanup and stores only sanitized teardown counts. A hard timeout is exit 124, never PASS. Review blocked/failed rows before declaring acceptance. A copied historical PASS is never a current PASS.

No documented per-project disposal API was found. No forced delete, reference reset or terminal shared-session cleanup is implemented. Protected cleanup refusal is CLEANUP_REFUSED_PROTECTED. Preserve the reconciliation ledger; an owner must handle its own nonproduction records through an approved disposal contract. Tool rollback means abandoning the isolated branch/uninstalling the CLI; it has no app/engine/configuration/deployment hook to disable.

## CI and release gates

Run manually after a release only when an operator requests it. Do not add to workflows, nightly jobs, deployment hooks, required browser roles, pytest discovery or normal FINCO Run. Existing ordinary CI validates this PR once. CI_NEUTRAL_CONFIRMED additionally requires measured unchanged test/job selection and no material recurring governance overhead; otherwise leave CI_IMPACT_UNVERIFIED or CI_REGRESSION_BLOCKED, keep Draft and give the owner the bounded blocker.
