# V11 — Financial and security regression

## Scope of the change
P2a touches only the decode of already-persisted Run History rows. It does not touch `financial_engine/`, `finco_core/`, `domain/`, native binaries/loaders, `v2_atomic_run_commit`, History append, CAS, tokens, CSRF, or the post-Run context. Engine and runtime sources are byte-identical between the staging SHA 93c549e1 and `main` (`git diff --stat` over `financial_engine finco_core domain app/runtime app/api/project_runner.py app/services/production_financial_authority.py` is empty).

## Evidence
| Property | Result |
|---|---|
| Decoded values | Old (verbatim copy) and new decoders return equal `RunHistoryEntry` objects and `to_dict()` for 0/1/10/25/55 entries, NULL and bound identities, 300 KB payloads |
| Fail-closed contract | 8 columns × 7 corrupt values (+ NULL via a foreign row) give identical exceptions and messages; identity corruption, missing columns and empty required fields identical; multi-corruption first-failure order identical |
| Append-only / no writes | listing leaves rows byte-identical; row count unchanged; no writes |
| Isolation | cross-user/cross-project reads return nothing |
| Ordering | newest first, `history_id DESC` tie-break; concurrent append during listing stays ordered |
| Existing suites | `test_model_v2_run_history`, `test_model_run_workspace_v3`, `test_post_run_request_context`, `test_portfolio_monitoring_real_runs`, `test_demo_history_retention`, `test_sc34_statements_drilldown`, `test_financing_f38_trace`: 275 passed with the new tests |
| Financial output identity (canonical / V10 / V10+V11) | Not affected by the diff. Re-observed this session on the unchanged engine: the result digest was identical across arms for every sample (Solar n=60, Wind n=60 pool/in-process; earlier report) and V11 served 68/80 models with 0 declines |
| Security | no change to SEC-01/02 controls, CSRF, composite CAS, `validate_current()` (not touched) |

Not run locally: the browser acceptance roles and the five Public Safety workers (CI-only); see the exact-head CI report.
