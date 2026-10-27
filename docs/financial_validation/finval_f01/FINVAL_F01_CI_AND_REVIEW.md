# FIN-VAL F01 CI and review status

Disposition at draft publication: **CORRECTION REQUIRED — SAME PR** until the complete final exact-head hosted CI and independent review evidence are available. Local results do not constitute Financial Owner self-approval.

Verified local acceptance on the complete source:

- Focused rate/Save/Run: 78 passed (`evidence/rate-complete.xml`).
- Additive source/governance/security negatives: 195 passed (`evidence/governance.xml`).
- Chromium four verticals × both 0.056 and 5.60 edit/Save/reload: 4 passed, zero skips (`evidence/browser.xml`).
- Approved GCC 13 / Python 3.12.3 native exact identity: 20 passed, zero skips (`evidence/native-final.xml`).
- All sixteen actual HTTP Run outcomes plus direct independent-interest/history acceptance: 50 passed (`evidence/lifecycle.xml`).
- Standalone Solar/Wind creation, final legacy persistence and scope negatives: 26 passed (`evidence/creation-and-persistence.xml`).

Selections overlap; do not sum these counts as distinct tests. The broad finance/workbook/CSRF/D-029/scenario/reference regression is recorded separately when complete. Exact source blobs are in the scope manifest. The final hosted financial workflow reruns focused financial, actual HTTP lifecycle, standalone creation, real browser and native tests at the exact PR head; the existing required workflows remain unchanged.

Reproduction and execution commands: `python -m pytest tests/test_finval_rate_contract.py tests/test_finval_rate_run_acceptance.py tests/test_finval_f01_complete.py -q`; `python -m pytest tests/test_finval_f01_http_lifecycle.py tests/test_finval_rate_run_acceptance.py -q`; `python -m pytest tests/finval_f01_browser_acceptance.py -q`; `python -m pytest tests/test_finval_f01_creation.py tests/test_finval_f01_complete.py tests/test_finval_f01_scope.py -q`. Native uses the unchanged `docs/ci_v3/phase4/runtime/Dockerfile`, offline test execution, `PYTHONPYCACHEPREFIX=/tmp/f01-pycache`, and `python -m pytest tests/test_finval_f01_native_identity.py -q -rs`.

The isolated bytecode cache matters when sharing a bind-mounted tree between host Python 3.12.14 and container Python 3.12.3: reusing host bytecode first produced a genuine provenance refusal. The successful run rebuilt interpreter-specific bytecode; no engine, kernel or provenance guard was changed. JUnit proves no native skips.

No merge, deployment, historical migration, release activation or self-approval is permitted. RC-M UI/wizard integration has a separate staged acceptance and is not declared released by this correction.
