# RC-7 Quarterly / RC-7A Compatibility Review

**Historical Correction B measurements, retained as evidence.** Correction C
preserves these financial/compatibility results through isolated research and
restores production blobs exactly to main. Read the Correction C report for
current scope, governance and frequency-admission status; the additional
candidate adapter rejection no longer exists.

## Provenance and controlled scope

Verified main `78e4c0edcc1bdb5013df79f11b3ba7b9c2151013` contains merged #319.
Original candidate `03ee3aee54e9f6fea3eb6e849a440ba1ebb7307b` was 2 ahead / 33
behind, OPEN/DRAFT, mergeable with no submitted review or inline review threads.
Its original merge-base was `05183b2a96c74fd4b3976903c593a61402cab7b3`.

Before integrating main, protected namespaces and historical governance helpers
were compared. Main introduced no changes to financial_engine/, finco_core/ or
domain/ since that base, or to the historical financial helper maps. The normal
merge was necessary to test the actual new CAPEX binder, persisted evidence,
Revenue/Credit and reporting contracts, not an automatic approval step.

Integration commit `31cada62a9fe17474995acc7d03bab4296122b4c` has parents
`03ee3aee54e9f6fea3eb6e849a440ba1ebb7307b` and
`78e4c0edcc1bdb5013df79f11b3ba7b9c2151013`; no conflicts. All five protected
candidate blobs are unchanged. Correction B adds tests/documents only. No app,
financial equation, historical authority, golden, tolerance or workflow changed.

## Independently recomputed numerical evidence

Fresh Windows/Python 3.12.10 captures used actual canonical engine executions,
not previous timings/results. Each legacy baseline ran in a detached private
worktree at the exact RC-7A main with a cold policy cache; the candidate ran the
same inputs on the integrated branch. Complete unrounded dataclass structures
and input fingerprints compare exactly, not only displayed KPIs.

| Legacy vertical | Main/candidate exact result SHA-256 | Maximum change |
|---|---|---|
| Solar | a24ac63a228a63e9ddecf6c2f7bbe094d4633f56edc0cdb9c6c5f1af92e0f481 | 0 |
| Wind | b8f2dee7eaa64272f209a9e554e64bfb06d3f702d7d08151060ac0e93c696333 | 0 |
| Data Center | bfbdd3d64bfccb36242fe5a78172e24d9f9dcb03e98c375629b729a738217bed | 0 |
| EV Charging | 45b428a84725864fb39e6d15f37c2a0b79c85ac5081b2e8c0192e3e704e4f545 | 0 |

Sixteen fresh quarterly cases cover Solar/Wind, December/April COD, ACT/360 and
ACT/365, scalar and stepped DSCR. Independent 50-digit Decimal arithmetic
recomputes dated production, revenue, OPEX, depreciation, Bank CFADS, debt PV,
opening/interest/principal/service/closing and cash conservation. Maximum actual
residuals: production **4.931506849315069e-13 MWh**; debt size
**7.436140340893606e-13 kEUR**; all financial components
**9.775342465753425e-13 kEUR** (debt service). No tolerance changed.
Existing tests separately prove calendar tax/FIFO loss timing, full-year sums,
one-day stubs, actual dated maturity, impossible-gearing refusal and unsupported
inputs. None proves full quarterly project statements or sponsor/project returns.

## Actual monthly construction -> future quarterly contract

| Boundary | Actual evidence / implementation | Current result |
|---|---|---|
| Monthly profile -> typed construction | Existing app.capex_profiles runtime binds actual current CAPEX leaves and monthly dates | Executed Solar/Wind real workbook Save/Run |
| Typed construction -> funding/IDC | Unchanged Stage B2, allocator and financing fixed point | No second allocator or IDC calculation |
| Independent IDC | Opening drawn Senior * rate * inclusive actual days / contractual 360 or 365 | Decimal comparison on every actual construction month |
| Persisted period dates | runtime_summary.financing_evidence.construction_funding periods | Start/end/draws match the completed Run; separate cashflow_date is absent, not invented |
| Sources/Uses | Every month, cumulative audit and separate non-construction FC uses | Existing 1e-6 checks retained; financing costs counted once |
| Funded Senior at COD | Monthly Senior draws PLUS separate non-construction FC/COD Senior allocation | Must reconcile to final commitment; monthly draws alone are not total funded debt |
| Quarter opening liability | Candidate currently refuses positive opening_debt_balance_keur | BLOCKED, not silently replaced by isolated re-sizing |
| Monthly funding -> full quarterly statements | Explicit blocked_consumer in candidate result | BLOCKED; no fabricated construction cash/BS |
| Quarterly CFADS / sponsor/project returns | Partial candidate operating/Senior evidence only | No overwrite of construction cash; full returns unavailable |

The existing construction schedule is inclusive; operating periods are half-open.
The last construction day is COD minus one day. A future handoff must preserve
both conventions explicitly, along with reserve-related FC/COD funding. It must
not spread existing six-month cash across quarters or rerun construction on a
quarterly axis. The separate non-construction allocation is already approved
accounting, not a residual plug introduced by this work.

Observed real committed synthetic cases:

| Case | Months | Construction Senior | Separate FC/COD Senior | Total funded Senior | Capitalized IDC | Sources = Uses |
|---|---:|---:|---:|---:|---:|---:|
| Solar | 14 | 6285.06369669151044 | 573.6496746293979 | 6858.71337132090834 | 207.51058936246713 | 9144.951161761212 |
| Wind | 20 | 11075.90163600858929 | 1004.0578683206139 | 12079.95950432920319 | 536.6565392338043 | 16106.612672438936 |

All amounts are kEUR. The construction DTO persists actual monthly start/end
dates, but its separate `cashflow_date` is **None in all 14/20 rows**. This is
preserved exactly, not converted into a guessed settlement date. A future
quarterly cash-eligibility bridge must explicitly adopt/prove the existing
end-date settlement contract or obtain source settlement evidence. Period dates
alone do not establish intraperiod cash availability. This is an additional
admission requirement, not authorization to change the current constructor.

Tests use a wrapper observing the **one real canonical Run** to compare saved
evidence. The wrapper does not substitute financial output, alter the engine or
execute a second calculation. Prior Run records are compared in full after Save
and the subsequent Run. This is synthetic disposable SQLite evidence, not staging.

## Revenue compatibility

- RC-7A's Revenue/PPA V3 product UI is not equivalent to activating release-closed
  Revenue V3 advanced financial products. Those remain separately gated.
- Existing dated Revenue V2 PPA/Merchant/CfD composition is exercised unchanged
  for Solar and Wind. Physical PPA + Merchant MWh equals generation; CfD is a
  separate notional settlement overlay, not extra produced energy.
- The exact same explicit contract input is refused by the quarterly entry with
  `QUARTERLY_REVENUE_CONTRACT_HANDOFF_REQUIRED`. This is truthful unsupported
  status, not a quarterly financial acceptance failure to conceal.
- Dated PPA review/expiry and hierarchical OPEX remain refused where unproven.
  No annual or six-month contractual amount is interpolated into quarterly cash.
- PPA-01's three reviewed candidate blobs are byte-identical to main. No PPA,
  Revenue V3, Junior or M7 release/activation authority changed.

## Credit V4 compatibility and remaining interval requirement

Current `app/v2/credit_v4_evidence.py::_periods` validates committed period-end
dates, index order and metric shapes; `build_credit_v4` intersects end dates.
It does NOT establish equal interval starts or frequency between Runs.

Concrete future counterexample: 31 March -> 30 June 2029 is 91 days; 31 December
2028 -> 30 June 2029 is 181 days. Same end date does not make CFADS/service
windows comparable. All currently admitted released Runs remain 6/6, and the
quarterly candidate cannot become a committed Run, so this is an **upstream
requirement before quarterly admission**, not an attributed released UI defect.

The future credit owner must either require equal start/end/frequency and eligible
cash basis, or make unsupported comparisons UNAVAILABLE. It must not average
DSCR, relabel six-month evidence, invent LLCR/PLCR or promote a sizing target into
a contractual covenant. This branch does not change the Credit projection.

## Reporting/history and release status

Institutional Reporting V2 consumes committed evidence. Its existence does not
establish a quarterly statement/BS/returns bridge. No quarterly Last Run, CAS
writer, export or comparison admission is added. Historical Runs are not rewritten.
The research wrapper always refuses `require_complete_project_run()` and has no
production consumers. Correction C restores baseline ProjectInputs adaptation,
which can discard frequency at this low-level boundary. Existing construction,
tax and Senior contracts still refuse complete non-semiannual production Runs;
this is separately tested, not claimed to preserve the removed adapter guard.

See `RC7_QUARTERLY_OWNER_DECISION_PACK.md` for all twelve OPEN decisions and
`RC7_QUARTERLY_AUTHORITY_SUCCESSOR_PROPOSAL.md` for exact successor requirements.
No new numerical candidate defect has been confirmed by the scoped evidence.
This is technical preparation for independent financial review, not release
acceptance or a claim of fully green CI.

## Correction B local acceptance

Windows, Python 3.12.10; disposable test SQLite, no staging access/mutation.
All processes below terminated normally; no successful process is inferred from
100% output alone. Existing pytest plugin-autoload disabling produces one
`asyncio_mode` configuration warning; it does not suppress any selected tests.

| Validation | Result / actual process exit |
|---|---|
| Candidate calendar + financial + new compatibility modules | 84 passed, rc=0 (28.56s) |
| Final compatibility module after evidence reporting/opening-liability assertion | 9 passed, rc=0 (47.82s); these nine overlap the 84, not extra unique coverage |
| Original failing real Chromium 23-capture journey | 1 passed, rc=0 (31.28s), visual capture enabled, no skip |
| Wider 14-module regression including complete governance modules | 283 passed, 10 failed, 1 existing skipped, rc=1 (484.84s) |
| Full public repository safety, canonical Git bytes | PASS, rc=0, 2450 tracked files; scanner/vendor pins unchanged |
| Python compilation and staged diff hygiene | PASS |

The wider result is **not GREEN**. All ten failures are the known authority
conflict: three WF07 successor expectations, three M7 content/coexistence tests,
four PPA content/coexistence tests. No test was removed, xfailed, weakened or
excluded from these complete modules. The one pre-existing skip is the
`volume_share=None` invalid-PPA parameter (merchant-residual spelling; schema
coverage is elsewhere), not a new quarterly exception.

Per-module wider results:

| Module family | Passed | Failed | Skipped |
|---|---:|---:|---:|
| Monthly CAPEX binding / real profile Run / binding surfaces | 47 | 0 | 0 |
| Revenue/PPA V3 economics and workspace | 42 | 0 | 1 |
| Credit V4 pure and real committed Runs | 20 | 0 | 0 |
| Reporting/profile historical consistency | 1 | 0 | 0 |
| F3 canonical legacy | 58 | 0 | 0 |
| Run Integrity, including corrupt-evidence negatives | 36 | 0 | 0 |
| WF04 exact-content and negative governance | 9 | 0 | 0 |
| WF07 governance | 21 | 3 | 0 |
| M7 successor governance | 16 | 3 | 0 |
| PPA successor governance | 33 | 4 | 0 |

Monthly IDC maximum actual Decimal residual: Solar
**4.332222222222222e-15 kEUR**, Wind **9.066666666666667e-15 kEUR**.
The actual first operating Senior opening liability also reconciles to the
construction plus separate FC/COD draws. Neither financing cost nor reserve
funding is counted twice.

Source safety is evaluated on canonical Git-index bytes because this Windows
checkout applies CRLF conversion to a hash-pinned vendor file; no vendor bytes,
hash rules or scanner exemptions were changed. New files also passed direct
working-copy scanning. Private JSON/log/JUnit evidence remains outside Git.

The publication is one legitimate main-sync/evidence checkpoint, not an attempt
to rerun CI repeatedly until an unapproved financial candidate appears green.
Fresh exact-head GitHub workflow IDs/conclusions belong in the PR delivery
comment; pending or authority-blocked checks are never claimed successful.

**READY FOR INDEPENDENT FINANCIAL APPROVAL** of the bounded research content.
Financial governance and the complete quarterly project admission remain pending.
All D decisions remain OPEN; no merge, deploy or activation approval is implied.
