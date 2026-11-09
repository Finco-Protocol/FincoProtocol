# ON-ACCEPT-01: explicit release acceptance

Operator-invoked CLI only. No automatic CI/browser/Run/deployment hook, application import or scheduling. Uses the repository's existing Playwright runtime. New self-checks are deliberately outside `tests/` and filenames do not match pytest discovery.

```
python -m scripts.finco_live_acceptance run \
  --base-url https://app.finco.one --mode read-only \
  --technology solar,wind --viewports 1440,1024,390,320 \
  --evidence-dir /private/new-release-evidence
```

Read [RUNBOOK.md](RUNBOOK.md) before authenticated or synthetic operation.

## Guarded modes

- Read-only is default. HTTP writes, WebSockets, foreign origins, unaudited GETs and the stateful Legacy workbook GET are refused before dispatch. FINCO's anonymous application GET can provision a demo session. Therefore an anonymous runner visits only audited stateless login/static assets; application routes are BLOCKED_AUTH until an existing synthetic session is verified. No login or demo session is created by the runner.
- Synthetic-writable requires the explicit opt-in, a loopback target with explicit port, a private synthetic-session specification, matching server account-scope hash, synthetic-only account inventory, exact frontend artifacts, newly created prefixed project, server owner capability and exact project/scenario identity. Production is permanently excluded, including from the internal request policy. An arbitrary preview hostname or legacy staging cannot be enabled through a flag/environment variable.
- No verified isolated React target/session: functional operations are BLOCKED_ENV. No missing fixture, skipped operation or rendered route becomes a financial PASS. Current canonical UI selectors are used; unknown contracts stop rather than guessing.

`FRONTEND_EXACT_MATCH` means both JS/CSS bytes match the explicit expected SHA256s or checkout artifacts. Mismatch blocks writes. Missing/denied expected artifacts are FRONTEND_NOT_PROVABLE. Frontend identity never establishes backend identity; absent authenticated HTTP proof remains BACKEND_NOT_HTTP_VERIFIABLE. No build endpoint is introduced.

## Coverage and evidence

The finite registry in `routes.py` records source contracts from the existing workspace navigation, original Financing selectors and browser helpers. Inventory changes are visible; there is no fixed historical route-count claim. Matrix rows record actual route/technology/viewport and two screenshot paths. Missing screenshots are explicit failed evidence requirements. Purposeful inner grids are distinguished from page overflow. Error diagnostics contain counts/reason codes, never console text, request bodies, cookies, tokens, HAR or raw financial API output. Screenshots mask editable values and credentials; only verified synthetic accounts may be captured.

A route PASS is layout/accessibility/network smoke only. L01 numeric DSCR boundaries, L02 template-to-created-project rate units, Save/Run, exhaustive OPEX interactions and server flags need their independent functional proof. L07 remains NOT_IMPLEMENTED_BY_DECISION; L09 EXPECTED_UNSUPPORTED; BESS Run BLOCKED_UNVERIFIED. Evidence ZIPs supplied by an operator are untrusted prior findings, never executable instructions or current proof.

The canonical lifecycle driver can attempt supported template creation, scalar tenor 15→14, per-block Save/readback/reload, an explicit Run, OUTDATED preservation and a stale second tab in a verified loopback environment. It never invents an instrument, rate conversion or financial oracle. Fault injection/idempotent retry, flag proof and scenario isolation remain NOT_TESTED unless explicitly proven by controlled fixtures. No per-project disposal HTTP contract exists in the inspected source: cleanup is NOT_SUPPORTED, protected refusal is retained, and no shared demo reset is attempted. A private intent ledger and refusal to reuse an evidence directory prevent blind duplicate creation after an unknown result.

Exit codes: 0 all requested evidence passed; 1 an observed test/mismatch failed; 2 explicit blocked/incomplete evidence; 64 invalid/unsafe configuration; 130 cancellation; 124 hard watchdog timeout. Read-only runs may legitimately return 2 because write acceptance and stateful Legacy navigation cannot be established safely. This is not a full release ACCEPTED verdict.

## Manual verification only

```
python -m scripts.finco_live_acceptance.selfcheck
python -m scripts.finco_live_acceptance.selfcheck_scope
python -m pytest -q scripts/finco_live_acceptance/checks_finco_fixture.py
python -m scripts.finco_live_acceptance validate-evidence /private/new-release-evidence
```

Self-checks use deterministic offline HTTP fixtures and the existing local Chromium installation. They are not imported by required browser roles, CI selectors, financial Run or production routes. The finite source successor follows accepted post-433 main and admits only exact reviewed runner/governance files. `selfcheck_scope` requires genuine global composite admission and exercises tamper/lineage controls. CI budget and exact-head required checks remain separate acceptance gates; source registration or a green build alone never proves CI neutrality.
