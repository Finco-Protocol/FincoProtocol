# D-029 exact-head CI report

This is a partial engineering Draft, not an independently approved release. Published HEAD/tree and fresh
workflow receipts will be captured after push in the review package. Do not substitute main's/#381's green CI
for the D-029 commit, or treat #383's reported results as D-029 validation.

Locally executed (Python 3.12):

```text
PYTHONUTF8=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
python -m pytest -p pytest_asyncio.plugin tests/test_d029_run_intent_ledger.py -q
32 passed in 8.56s

python -m pytest -p pytest_asyncio.plugin tests/test_d029_run_intent_ledger.py tests/test_react_mvp_rc_sec.py tests/test_model_mutation_request_security_v1.py tests/test_rc_sec_csrf_successor.py tests/test_trust_readiness_controls.py -q
151 passed, 11 warnings in 145.57s
(This combined run preceded the two additional live-stalled-process test cases; the final 32-case ledger run includes them.)

python -m pytest -p pytest_asyncio.plugin tests/test_model_workspace_consolidation_browser.py -k rapid_repeated_activation -q
1 passed, 72 deselected, 13 warnings in 26.40s
```

The system Python has an unrelated incompatible web3 pytest entry-point (`eth_typing.ContractName` import).
Local runs disable global plugin autoload and explicitly load the repository-required asyncio plugin; no
test assertions, mandatory workflow or CI manifest is changed. Browser run used actual installed Chromium.
Existing browser fixture is HTTP; this baseline does NOT claim new HTTPS idempotency browser acceptance.

Additional financial regression command: FIN-VAL B1, Golden Flow correction A/B/B-guard, P3 Run Certificate;
**125 passed, 11 warnings in 90.29s**. Result counts are also in `evidence/D029_LOCAL_TEST_RESULTS.json`.

Required after publication: inspect exact-head Public Safety (all five workers), Browser (all six roles),
Q4 candidate, Compile/Safety, Governance history and Dependency consistency, including native exit/JUnit/source
attestation. New local focused ledger tests are not automatically evidence of five ASGI workers in hosted CI.
No CI manifests or test roster are altered in this foundation. End-to-end Run idempotency remains deferred.

## Status boundary

Implemented: isolated reservation, lookup/reconciliation, schema audit, fencing and cursor finalization helpers.
Proven: the executed persistence-only and released-baseline checks listed in `evidence/D029_LOCAL_TEST_RESULTS.json`.
Proposed policy: `D029_OWNER_DECISION_REGISTER.md`; no production rollout is enabled.
Deferred integration: canonical HTTP Run, financial commit hook, startup migration and real clients, after FIN-VAL #383 merges.
Owner decisions: retention, expiration/retry and compatibility semantics remain open.
Residual risk: the currently released Run route still permits duplicate commits; isolated tests do not prove end-to-end idempotency.
