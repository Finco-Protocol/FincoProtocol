# D-029 exact-head CI report

This is a partial engineering Draft, not an independently approved release. Published HEAD/tree and fresh
workflow receipts will be captured after push in the review package. Do not substitute main's/#381's green CI
for the D-029 commit, or treat #383's reported results as D-029 validation.

Locally executed (Python 3.12):

```text
PYTHONUTF8=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
python -m pytest -p pytest_asyncio.plugin tests/test_d029_run_intent_ledger.py -q
34 passed in 10.49s

python -m pytest -p pytest_asyncio.plugin tests/test_d029_run_intent_ledger.py tests/test_react_mvp_rc_sec.py tests/test_model_mutation_request_security_v1.py tests/test_rc_sec_csrf_successor.py tests/test_trust_readiness_controls.py -q
155 passed, 11 warnings in 223.78s
(Combined run preceded the static parameter-identity correction; all final 34 ledger cases were rerun afterward.)

python -m pytest -p pytest_asyncio.plugin tests/test_model_workspace_consolidation_browser.py -k rapid_repeated_activation -q
1 passed, 72 deselected, 13 warnings in 26.40s
```

The system Python has an unrelated incompatible web3 pytest entry-point (`eth_typing.ContractName` import).
Local runs disable global plugin autoload and explicitly load the repository-required asyncio plugin; no
test assertions, mandatory workflow or CI manifest is changed. Browser run used actual installed Chromium.
Existing browser fixture is HTTP; this baseline does NOT claim new HTTPS idempotency browser acceptance.

Initial published HEAD `e8e33afba3c1fdf43c3c5abfef10aa78a255f3a2` failed Public Safety run `40342419780`.
All five worker artifacts were authenticated and inspected: exactly two planned/fresh node IDs differed, both
random UUID parameter labels in the new negative-key test. Other inventory identities matched. The correction
uses fixed invalid UUID examples; no roster, manifest, CI verifier or assertions change. Two independent fresh
collections now return the SAME 34 identities. Evidence: `D029_INITIAL_CI_COLLECTION_FAILURE.json` and
`D029_COLLECTION_STABILITY.json`. Fresh corrected-head CI must be inspected separately; initial green jobs
and failed-worker artifacts are not acceptance proof for a later source tree.

Additional financial regression command: FIN-VAL B1, Golden Flow correction A/B/B-guard, P3 Run Certificate;
**125 passed, 11 warnings in 90.29s**. Result counts are also in `evidence/D029_LOCAL_TEST_RESULTS.json`.

Required after publication: inspect exact-head Public Safety (all five workers), Browser (all six roles),
Q4 candidate, Compile/Safety, Governance history and Dependency consistency, including native exit/JUnit/source
attestation. New local focused ledger tests are not automatically evidence of five ASGI workers in hosted CI.
No CI manifests or test roster are altered in this foundation. End-to-end Run idempotency remains deferred.

## Status boundary

Release state: **RELEASE CLOSED**. See the release-state matrix in `D029_EXECUTIVE_REVIEW.md`.
Implemented and tested on PR #384 head: the canonical `POST /v2/workbook/run` intent lifecycle, the single-transaction
commit, startup schema, the React and Legacy clients and the governance successor. Not owner-approved, not activated:
the owner policies in `D029_OWNER_DECISION_REGISTER.md` remain candidates, `RELEASE_POLICY.enabled` is false, nothing is
deployed or merged. A request without `run_intent_id` keeps the released, non-idempotent behaviour.
