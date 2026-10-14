# Diagnostics V2 — exact-content Trust / governance authorisation PROPOSAL (for independent review)

**This is a proposal, not an authorisation.** This branch changes no Trust pin, governance test, release manifest, security control or CI
workflow, and does not move or disguise any registration. The RC-1 protected-scope successor and the RC-2 exact-content manifest
(`tests/test_trust_readiness_registry.py`, `tests/test_rc2_integration_manifest.py`) are expected to report the application paths below as
"not part of the reviewed integration" until an exact-content successor is authorised on the RC integration branch.

## 1. Application paths (blob SHA-1 at this head; recompute with `git hash-object`)

| Path | Status | Git blob SHA-1 |
| --- | --- | --- |
| `app/v2/diagnostics_dx_checks.py` | new | `4984dfb5f906012b6768a0f9f208e1199cf876eb` |
| `app/v2/diagnostics_v2_projection.py` | new | `e55fac296c4f20f2b19ff03bf83be8fc8f4ea6fa` |
| `app/v2/diagnostics_projection.py` | modified (adds one optional `evidence` argument and an additive `v2` key; V1 behaviour unchanged) | `784eb831b186ff6fde2d3bc03791b7f9e0ace053` |
| `app/v2/insight_quality_projection.py` | modified (one call-site argument: `evidence=evidence`) | `7b1b1b6a8dbb1140e8a652efa9e5a4967d7ae16d` |

Already free paths: `app/templates/v2/partials/sheet_diagnostics.html`, `app/templates/v2/workbook.html` (two asset links), `static/css/model_diagnostics_v2.css`,
`static/js/model_diagnostics_v2.js`, tests, docs.

## 2. What is deliberately NOT changed

`app/v2/router.py` (no router statement, no new route), `app/model_quality/**` (registry, scorer, evaluators, the 30 stable `QM-*` identities),
`app/run_integrity/**`, Q4 / Goal Seek writers, CSRF call sites, financial engine / core / domain, tolerances, goldens, workflows.
No GET executes the engine and none writes (asserted by tests). The only new HTTP surface is none: Diagnostics V2 rides the existing
`GET /v2/workbook/diagnostics` and the Insight/Overview read path.

## 3. Existing isolation tests honoured (not edited)

`tests/test_model_quality_q1.py::TestIsolation` forbids the string `app.model_quality` in any `app/` module outside an exact allow-list. The new modules
therefore live under `app/v2/` and never import or mention that package (they receive the Quality evidence object through the existing adapter
arguments). `tests/test_model_diagnostics_v1.py` still requires `diagnostics_projection.py` to import only `app.model_quality.contracts`.

## 4. Requested exact-content successor (to be performed by the independent integration reviewer)

1. Authorise exactly the four blobs of section 1 (any later byte change re-opens review).
2. Authorise no router change, no new route, no CSRF call-site change.
3. Keep every historical Trust assertion and mutation-negative test effective; the successor must be additive, exact-content and never a path/prefix wildcard.

## 5. Evidence

`tests/test_model_diagnostics_v2.py`, `tests/test_model_diagnostics_v2_real_runs.py`, `tests/test_model_diagnostics_v2_browser.py`; existing Diagnostics V1,
Quality Q1, Insight Q3 and Run Integrity suites pass unchanged (249 tests). See `docs/model_v2/MODEL_DIAGNOSTICS_V2.md`.
