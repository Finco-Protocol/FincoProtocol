# Portfolio Monitoring V1 - Correction A

## Provenance and scope

Base: `5996453b8d5bbfaa48bc06922fc6963cf94d2f84`.
Original published feature: `256d2a808a1f4286be3139122513dd1baee2d29d`, Draft PR #330.
The RC coordinator approved the existing minimal router registration. Correction A
does not change that hook, Compare, the shared workbook shell or PR #329 exports.

Validated historical project capital and initial financing are now summed across
different construction dates when currency, units and financial evidence scope
match. These are nominal historical amounts, not current outstanding exposure or
an as-of valuation. No FX, dates, inflation adjustments or amounts are invented.
Missing dates reduce date coverage, not otherwise valid monetary coverage.
Separate strict construction-date cohorts remain available. Unavailable evidence
does not become zero. Individual returns and credit ratios are not aggregated.

## Read-path correction

The dedicated read adapter captures one query-only SQLite snapshot. A bulk latest
history query uses canonical ordering and the existing history decoder, with both
history and project owner restrictions. Malformed newest history never falls back
to an older Run. Existing composite identity and freshness authorities are reused
once per matching project inside the snapshot.

A fresh owner/archival check precedes the response. A SQLite data-version change
triggers one bounded reconciliation snapshot; changed identities become UNKNOWN,
while a proved unrelated tenant write need not invalidate unchanged evidence.
Continued changes fail closed. Read/coherence failure returns 503 rather than an
apparently empty portfolio. There is no cross-request cache or read-time Run.

## Measured HTTP acceptance

Windows, Python 3.12.10; authenticated TestClient `GET /v2/portfolio`, including
projection, rendering and response generation. Disposable synthetic storage holds
100 real canonical committed Runs across Solar, Wind, Data Center and EV; the
20-project database was backed up after the first 20 commits. Identical databases
and instrumentation were used before/after. Five warmed requests per size were
measured sequentially. These are local observations, not Linux/production SLAs.

| Projects | Before median | Correction median | Before p95 | Correction p95 | Median reduction |
|---|---:|---:|---:|---:|---:|
| 20 | 2.362532 s | 0.618211 s | 3.402877 s | 0.640306 s | 73.83% |
| 100 | 13.844562 s | 3.056205 s | 14.316465 s | 3.155364 s | 77.93% |

Raw warmed wall-clock samples in seconds:

- Before 20: 2.251961, 3.252001, 2.362532, 3.402877, 2.254080.
- After 20: 0.484744, 0.618211, 0.640306, 0.623180, 0.595371.
- Before 100: 13.408290, 14.316465, 13.466882, 14.121072, 13.844562.
- After 100: 3.033443, 3.056205, 3.057067, 3.155364, 2.960403.

First GETs are reported separately: before 20/100 = 5.045282/14.198844 s;
after 20/100 = 16.640814/3.220149 s. Process and OS-cache conditions were not
normalized: the baseline process had just prepared fixtures. **No cold-start
improvement is claimed**, and the slow first corrected request remains an
acceptance limitation. Sampling is small; five-sample p95 is the sample maximum.

| Per GET, 20 / 100 projects | Before | Correction |
|---|---:|---:|
| Connections | 141 / 701 | 1 / 1 |
| Latest-history query executions | 40 / 200 | 1 / 1 bulk |
| Composite identity assemblies | 40 / 200 | 20 / 100 |
| Workspace table reads | 80 / 400 | 20 / 100 |
| SELECT executions | 261 / 1301 | 83 / 403 |

SQL tracing starts after the existing connection initialization; wall time includes
that initialization. One connection is observed for these fixtures; rare legacy
freshness reconciliation may still invoke existing additional authorized reads.
No universal constant-query or constant-time claim is made.

The reproducible tool is `tools/benchmark_portfolio_monitoring.py`. It refuses to
overwrite fixtures, checks rendered project counts and compares full project,
Workspace and immutable history data digests outside the timed requests.
Before/after digests were identical for both databases. Private SQLite files,
screenshots and full logs remain outside Git.

Measured final production source SHA-256 values (raw local bytes):

| Path | SHA-256 |
|---|---|
| app/v2/portfolio_reads.py | ca33fbdf7d912e4c488412e3fc6783bb25748a67455ba15773133a7c7d854feb |
| app/v2/portfolio_projection.py | 107411ff2ecba86b1bdc25ecd981465fde981000a25d567a78e6505c9e76373d |
| app/templates/portfolio_monitoring.html | 7e6fc815512763bc901716f174d59335d549dac42034528ba4b6bea3680531a9 |

## Local regression

Combined focused acceptance: **247 passed, zero failures, zero skips**, pytest
rc=0 and normal process return, 421.47 seconds. This includes portfolio contracts,
real four-vertical committed Runs, independent Decimal aggregation, real Chromium,
existing Compare/Decision Support, Run History, Credit V3, Sources & Uses,
Trust/CSRF and workbook consolidation tests.

Correction tests cover mixed funding dates, missing dates, separate cohorts,
incomplete coverage, zero versus unavailable, deterministic 20/100-project totals,
and actual concurrent Save, scenario, CAPEX and atomic Run changes. Owner transfer
removes a row; unrelated tenant changes can be proved irrelevant. Query-only
writes are rejected. Invalid newest history cannot substitute an older valid Run.
Real Chromium covers 1440x900, 1366x768 and 390x844, light/dark, filters, reload,
Back, horizontal table scrolling and actual history/Credit Decision navigation.

No financial engine/core/domain, writer, persistence schema or implementation,
financial pin, activation, export, CI or tolerance/golden changes are included.
This is not independent review or merge approval. Fresh exact-head GitHub CI is
required after publication; prior green checks belong only to the original HEAD.
