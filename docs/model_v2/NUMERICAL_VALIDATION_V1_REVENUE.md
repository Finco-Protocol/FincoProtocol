# Synthetic Revenue V2 numerical validation

Base: `607db110928859bf37f6dde1195e50c4b80cde12`.
Scope: tests and this report only. No production financial, persistence, schema,
export, UI or workflow changes. No deployment or reference recalibration.

## Coverage gap

Existing domain tests cover two PPAs and residual Merchant arithmetic. Existing
WF07 tests reconcile one PPA plus Merchant and a CfD overlay, test signed
settlements, and exercise two-Senior financing. Existing Last Run tests cover
immutable historical evidence. These tests are preserved, not replaced.

The new module joins the previously separate checks in a real canonical
operating run: two dated, independently priced PPAs plus explicit-share Merchant,
non-default capture, merchant-only balancing, a per-period independent Decimal
pricing/allocation oracle, and canonical EBITDA.

## Synthetic fixture

| Primary stream | Physical share | Base price (EUR/MWh) | Indexation case |
| --- | ---: | ---: | ---: |
| PPA alpha | 28% | 43.20 | 1.3% |
| PPA beta | 32% | 61.70 | 2.1% |
| Merchant | 40% | 69.90 | 3.4% |

Merchant capture is 0.82. Balancing deducts 1.7% of captured Merchant revenue
only. Baseline indexation is explicitly zero. Settlement is SAME_PERIOD.
Start/end dates come from the Generic Solar canonical operating boundaries,
not an external model. All values are independently synthetic.

The three canonical tests execute four runs: baseline, indexed, zero-price PPA,
and changed-price PPA. Each checks all 50 operating periods. Two additional
arithmetic-only oracle tests are counted separately, not as engine validation.

## Authority and independent boundary

Contracts pass through `apply_config`, typed `ProjectInputs`, the canonical
adapter and `financial_engine.orchestrator.run_operating_model`. Tests require
the canonical run-path ID, input fingerprint and production/revenue/OPEX/EBITDA
derivation evidence. There is no model mock or substitute production calculator.

The oracle independently derives allocated MWh, three prices, indexation,
Merchant capture, three revenues, gross revenue, balancing and net revenue.
It uses actual canonical production as an explicit input; it does not prove
generation physics. Canonical OPEX is an explicit boundary for the independent
EBITDA subtraction, not independent OPEX validation. These are operating tests,
not new assertions of source financial parity, tax, debt or return accuracy.

Actual result year indices are whole-valued floats (1.0, 1.0, 2.0, 2.0, ...),
not Python ints. The fixture refuses fractional year indices before integer
conversion. No calendar year, annual row or period date is reconstructed.

The tests reject duplicate/missing stream evidence, verify conservation and
actual capture, and check the entire previous immutable result after a new run.
Changed inputs must produce a distinct fingerprint and changed revenue.

## Local numerical evidence

Python 3.12.10, isolated disposable storage. The original prepared module passed
unchanged: 3 canonical tests plus 2 arithmetic-only tests, zero failures/skips,
normal interpreter exit 0. Public test assertions additionally lock integral
year indices, exact evidence identities, volume/capture and whole-result
immutability; no numerical tolerance or economic assumption changed.

| Case | Max net revenue residual (kEUR) | Max EBITDA residual (kEUR) |
| --- | ---: | ---: |
| Baseline | 7.44713488e-13 | 6.79907376e-13 |
| Indexed | 3.517873766184e-12 | 3.257873766184e-12 |
| Zero price | 3.92467376e-13 | 4.05341020e-13 |
| Changed price | 4.63341020e-13 | 5.2531464e-13 |

Maximum checked monetary residual is 3.517873766184e-12 kEUR. Maximum individual
quantity residual is 3e-12 MWh; decimal reconstruction of the sum of actual
float quantities differs from production by at most 6e-12 MWh. The runtime
unallocated-volume audit is exactly zero in every checked period. Capture
matches exactly. Maximum indexed price residual is 2.207276525138e-13 EUR/MWh.
These are observed machine-precision differences, not balancing adjustments.
The fixed abs=1e-9 / rel=1e-12 thresholds were not widened.

## Existing regressions

| Launcher suite | Passed |
| --- | ---: |
| WF07 Revenue V2 multi-stream | 54 |
| RevenuePlan domain | 30 |
| Model V2 revenue runtime parity | 55 |
| F0-B numerical precision | 32 |
| Canonical reference Last Run | 45 |
| Total | 216 |

The exact launcher ring completed in 455.59 seconds with zero failures/errors/
skips and normal process exit 0. An earlier supplemental ring also passed
immutable Model V2 Run History (23 cases). No full Public Safety suite was run
locally; exact-head GitHub acceptance remains required.
The final public test plus the three reused Revenue modules also passed:
144 tests, zero failures/skips, normal exit 0 (31.13 seconds). There are 221
distinct cases across the prescribed launcher ring and the five new tests;
overlapping reruns are not added to that unique count.
The unchanged repository safety scanner returned PUBLIC_REPOSITORY_SAFETY_SCAN_PASS,
exit 0. Targeted new-file source isolation, Python compilation and staged diff
hygiene also passed before publication.

Publication is limited to independently synthetic test code and this neutral
report. No external provider identity, source input, private evidence, original
case or harvested artifact belongs in this PR. Exact-head CI results and the
final commit SHA are recorded in its description after publication.
