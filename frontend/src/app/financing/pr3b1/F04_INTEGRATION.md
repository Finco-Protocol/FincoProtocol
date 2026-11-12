# F04 financing evidence handoff

Status: integrated source candidate; exact-head CI required. This source candidate extends the existing Financing home and Bankability editor. It preserves the canonical configuration writer and Save All CAS path; no financial engine or policy changes.

The existing sizing selector explains its repayment consequence and keeps unsupported frozen/minimum modes disabled. The new quantity panel identifies aggregate Requested gearing, Sized debt, absent independent Committed, the FC/COD-only Drawn amount, and Outstanding at an explicitly identified closing period. Construction draws remain in their original period table. No browser sums, allocations or monthly interpolation are introduced.

The native repayment table requires the existing selected committed Run fence plus matched source axes, unique contiguous indices, valid ordered dates and consistent supplied amounts. Its tolerance follows the canonical 1e-6 kEUR accounting tolerance, with machine precision allowance. Unknown operands remain absent. This is a display consistency check, not a replacement Integrity verdict. A monthly native aggregate series additionally requires consecutive source month identities and calendar months; no monthly per-instrument contract is claimed. STALE and HISTORICAL retain their source labels. Cross-view assurance remains MITIGATED_NOT_PROVEN.

Local checks:

```sh
npm --prefix frontend ci --ignore-scripts --no-audit --no-fund
npm --prefix frontend run typecheck
node --test frontend/src/app/financing/pr3b1/__tests__/*.test.mjs frontend/src/app/financing/pr3b2/blockContract.test.mjs
python -m pytest -q tests/test_f02_financing_period_evidence.py tests/test_model_financing_bankability.py
FINCO_TEST_CHROMIUM_PATH=/usr/bin/chromium python -m pytest -q tests/test_f04_financing_browser.py
```

Browser proof builds into a temporary directory and intercepts only local test JS/CSS requests. It does not modify the served static bundle. Fixtures use synthetic projects and the canonical local server.

The F04 correction regenerates the shared static JS from this source and adds one finite exact-source successor after accepted R03 main. Static CSS remains byte-identical. The eight current maps move only their existing registry and JS keys; historical manifests and CI selection policy remain preserved. Every changed byte/mode/base/ancestry and closed diff is checked, with negative source/map/registry/mode tests. All required workflows must pass on the same final HEAD before review readiness. No merge or deployment is authorized.

Independent lender commitments, individual instrument Run allocations, construction opening/closing balances, reserve draw/target/top-up ledger and benchmark-reset schedules remain unavailable. G1 warning-only financial proof, G2 floating canonical Save, G3 construction ledger, and G4 expected fixed-source refusal retain their existing statuses. Staging and production acceptance require the integrated revision.
