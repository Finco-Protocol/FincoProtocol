# V11 Stage 3: native senior-debt model evaluation (Stage 3a native tax + Stage 3b)

**Status:** research candidate, release-closed. **Default OFF.** No production or staging activation path, no
deployment, no runtime compilation. Production enablement needs a separate Financial Owner release decision.

## What it is

An exact-replay native candidate for `financial_engine.orchestrator.run_senior_debt_model` (both the plain and
the shareholder-loan (SHL) fixed-point paths). It is reached only through the explicit hook
`financial_engine.financing.project._senior_debt_model` (the three G2A call sites: capacity, funded, strict
re-solve), and only while the current Run has entered `stage3_run(Stage3Config(mode="candidate"))`
(Run-local `contextvars`, immutable per Run). It returns the canonical `ProjectModelResult` (pickle-identical) or
`None`; on `None` the canonical orchestrator runs unchanged and decides — and raises — itself.

It is a separately identifiable, versioned capability:

| | V10 Stage 1 | V10 Stage 2 | **V11 Stage 3** |
|---|---|---|---|
| source | `native_v10/kernel_v10.c` | `native_v10/kernel_v10_stage2.c` | `native_v11/kernel_v11_stage3.c` |
| ABI | 10001 | 20001 | **30001** |
| artifact | `_fk_v10.so` | `_fk_v10_stage2.so` | `_fk_v11_stage3.so` |
| build manifest | `fk_v10_manifest.json` | `fk_v10_stage2_manifest.json` | `fk_v11_stage3_manifest.json` |
| sealed source manifest | `approved_canonical_blobs.json` | `…_stage2.json` | `approved_canonical_blobs_stage3.json` |
| configuration | `NativeConfig` | `NativeConfig(stage2_experimental)` | `Stage3Config` |

The approved V10 Stage 1/Stage 2 sources, artifacts and manifests are not modified, resealed or loaded by Stage 3;
V10 keeps working independently (and a Stage 3 decline falls back to whatever V10 configuration the Run selected).

## Boundary (one compiled step per iterative block)

* **SHL path:** the entire SHL -> tax -> CFADS -> senior fixed point — every iteration's senior solve (DSCR loop
  with backward capacity, damping, convergence on all fields, finalisation handshake, feasibility, COMBINED
  minimum with the gearing finalisation), both iteration tax evaluations (financing-tax merge components, lean
  calendar-year tax, loss carry-forward, cash-tax timing), the post-senior cash vector, the SHL operating roll and
  the closing / interest / limitation convergence tests — plus the final senior solve, in **one** kernel call.
* **Plain path:** the senior solve in one kernel call.
* **Stage 3a:** each full `calculate_tax` of the final recomputation (tax-year bases and periodisation, ATAD
  annual capacity and chronological period allocation, taxable income, FIFO loss series, CIT, cash-tax payment
  allocation incl. terminal unpaid tax, normalised per-period tax-year allocations) is one kernel call.

Every iteration of every loop is executed: same iterates, same dependency chain, same termination tests. Nothing
is skipped, merged, reordered or approximated (this is not the rejected V9 joint solver).

Everything else runs as the canonical functions themselves, in canonical statement order: operating models,
axis contracts, typed merges of the final inputs, contract and final-state validation, DSRA, the handshake and
final SHL schedules, schedule assembly, fingerprint and provenance. Python objects are materialised only where
the canonical caller consumes them: the final senior schedule is rolled by the canonical `_forward_roll` /
`_to_schedules`; full tax results become real `TaxAnnualResult` objects with the canonical
`run_annual_fifo_ledger` entries where the result stores them, and lightweight rows read by the canonical
assembly helpers otherwise. Strings and tuples placed in results are the canonical code's own constant objects,
so even object sharing (pickle bytes) is identical.

## Admission (else decline with a recorded reason; the canonical evaluation runs)

* verified artifact (SHA256, build ID, ABI 30001, struct layouts, builtin `sum` canaries) and authenticated
  canonical region: approved git blobs of every module whose logic is reproduced, code fingerprints against those
  sources, live identities re-checked before every admission; validated runtime (Linux x86-64 CPython 3.12/3.13);
* exact `float` / `int` / `bool` types for every value crossing the ABI;
* tax: non-pairing tax basis, `TAX_YEAR_LAST_PERIOD` or `MODEL_YEAR_PAYMENT_PERIOD` cash timing, ATAD on or off,
  either loss gate, any carry-forward window and lag, opening vintages, adjustments, admitted financing income;
  no SHL deductible override, no dynamic interest limitation, no bank tax-periodisation override;
* senior: `DSCR_SCULPTED` or `COMBINED_MINIMUM`, authentic forward roll;
* SHL: `BULLET` or `CASH_SWEEP` on the period-axis day count, construction prefix;
* OD-R maturity context: none, `AUTHORITATIVE`, or `PROVISIONAL` with its ledger (see effects).

Every canonical raise predicate on the success path is evaluated natively; any hit declines. Canonical
rejections (non-convergence, infeasible schedules, invalid inputs, fail-closed maturity residuals) therefore
always decline and the canonical code raises its own exception.

## Effects

The only state the canonical evaluation writes (besides Run-scope memo caches, reproduced by calling the same
memoised canonical functions) is the OD-R maturity ledger of a `PROVISIONAL` context, written by the handshake
and final SHL schedules. Stage 3 evaluates every pure statement of the canonical post-handshake sequence first
(using a context-free probe of the same schedule — the context changes no value), so every decline happens
before any effect; from the handshake on it runs the canonical calls in canonical order and their exceptions
propagate unchanged.

## Evidence (reproduced by the tests)

* `tests/test_native_v11_stage3_identity.py` — production Runs, both SHL maturity authorities, arms
  off / V10 1+2 / Stage 3 / Stage 3 on 1+2: identical verdicts, errors, financial / full / Integrity / final-check
  digests.
* `tests/test_native_v11_stage3_tax.py` — Stage 3a against `calculate_tax` over the perturbed tax space.
* `tests/test_native_v11_stage3_fuzz.py` — Stage 3b against `run_senior_debt_model` over perturbed policies,
  SHL terms and maturity contexts: pickle-identical results and ledgers, or a decline without effect.
* `tests/test_native_v11_stage3_safety.py` — default OFF, separation from V10, loader / provenance fail-closed,
  admission declines, canonical rejections, region replacement, build-ID pin, reproducible build.
* `tests/test_native_v11_stage3_sanitizers.py` — ASan/UBSan build serving Runs and fuzz cases, malformed and
  mutated plans; allocation-failure injection.

## Build

`python -m financial_engine.native_v11.build_stage3 [--out DIR] [--variant release|asan|alloc]` (offline only;
never at runtime). The binary is git-ignored and never committed.
