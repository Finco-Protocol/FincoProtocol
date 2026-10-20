# Institutional Workspaces RC Integration

Draft PR: #333. Branch: `integrate/model-rc-institutional-workspaces-v1`.
Base and merge-base: `5996453b8d5bbfaa48bc06922fc6963cf94d2f84`.

**INTEGRATION CANDIDATE - NO MERGE / NO DEPLOYMENT / NO SELF-APPROVAL.**

The owner's later instruction explicitly requested immediate integration branch
and Draft PR publication to start CI before source CI finished. This changes the
publication sequence, not the acceptance requirements: pending/red source CI,
integrated CI, independent review or missing owner approval still block merge.
The initial Draft was opened at `74709dc1c51b8b28c44d3ed5aa1a5e3cc3a8aff1`.
It was not represented as a completed or independently approved integration.

## Source and merge provenance

| Source | Exact source HEAD | Verified source acceptance |
|---|---|---|
| #329 Reporting V3 | b7fa656b829d088efdf7910507ccfb8388975c19 | Six workflows SUCCESS; Public 39407978655 artifacts inspected: 15294 passed, 107 skipped, zero failures/errors, pytest rc=0, child exit=0, normal_exit=true |
| #330 Portfolio V1 | 986af400ad25f0a0a646a8a197f4a9bd89e44941 | Six workflows SUCCESS; Public 39421674602 artifacts inspected: 15292 passed, 108 skipped, zero failures/errors, pytest rc=0, child exit=0, normal_exit=true |
| #331 Run Workspace V3 | 9c55fca91a3e93b2c991502ebfed1fc177e740a1 | Local correction and dedicated Chromium passed; fresh Public 39442061279 and other exact-head checks pending at preparation |

Normal merges, in requested source order:

1. `baa53c529331f5e49be5fc4478687831791c05ab`: main + #329.
2. `98cdcb26bd4b2500454e3269ee5dbb7522e99c32`: prior integration + #330.
3. `74709dc1c51b8b28c44d3ed5aa1a5e3cc3a8aff1`: prior integration + #331 Correction B `07fbd864101a74063589ab88d37775ad9bcd8eb1`.
4. `96d9dc24e2a21871909e59e161661a3318a0b624`: prior integration + #331 test-only Chromium follow-up `9c55fca91a3e93b2c991502ebfed1fc177e740a1`.

Every exact source HEAD is an ancestor. No rebase, squash, cherry-pick, amended
published commit or force push was used. The only merge conflict was the
end-of-file `app/v2/router.py` registration hook: Portfolio and Run Workspace
registrations are both retained once. Reporting's separate historical export
route was retained unchanged. Existing workbook/HTMX routes were not redesigned.

All 31 source-owned changed files outside the shared router match their exact
source Git blobs. The shared router adds only the three source hooks/route.
Additive integration-only files are this report and
`tests/test_rc_institutional_workspaces_integration.py`.

## Correction B evidence

Original Public run 39424492571, job 118634056548: 15258 passed, 108 skipped,
9 errors. Full logs and uploaded JUnit/process evidence independently inspected:
all nine were missing-`seeded_db` setup errors; pytest rc=1 and child exit=1.
The artifact records normal_exit=false, so it is not successful termination.
The mandatory aggregate failure was downstream of that failed control.

Isolated unmodified modules reproduced 4 and 5 setup errors. Importing the
existing `seeded_db` alongside `two_runs` preserves the original per-test
temporary DB and monkeypatch cleanup rather than adding a second fixture.

Executing the previously unreachable test bodies exposed two additional V3
read-view defects: an unavailable period grid has no pagination key, and the
Integrity schema check examined a presentation copy while evaluation used the
committed history entry. The minimal fixes leave unavailable periods without
pagination and bind both schema validation and evaluation to the same existing
entry. No Integrity evaluator, financial calculation or stored evidence changed.

Authentication coverage now distinguishes an invalid session (401) from a
newly provisioned demo lacking project access (404); POST remains 405.
This preserves canonical demo middleware rather than weakening access control.
An explicit missing-period response regression was added.

Source local acceptance, Windows / Python 3.12.10:

- V3 module independently: 12 passed; rc=0, normal return.
- Correction A module independently: 16 passed; rc=0, normal return.
- V3 + existing Decision Support, Run History, Integrity and RC5 regression:
  115 passed; rc=0, normal return (includes the V3 module again).
- Feature-specific real Chromium: 3 passed, no skips; rc=0, normal return,
  48.81 seconds. Test selectors now identify actual select controls and history
  table rows, including three unique history IDs. Exact counts and HISTORICAL
  states are awaited after HTMX; no sleeps or reduced assertions.
- Changed-file source safety, compilation and diff hygiene: PASS.

## Integrated acceptance

Combined-tree local results are independently executed, not inferred from source CI:

| Ring | Observed result |
|---|---|
| Combined focused ring, default Windows encoding | 301 passed, 2 encoding failures, 1 existing skip; rc=1, process returned, 594.30 s |
| Exact two failed AST nodes, Python `-X utf8` | 2 passed, rc=0, normal return, 4.07 s |
| Feature-specific V3 + Portfolio real Chromium | 4 passed, zero skips/failures, rc=0, normal return, 60.83 s |
| All 34 changed files: source safety and Python compilation | PASS |
| Whitespace hygiene, exact source blob union and source ancestry | PASS |

Both initial failures were `UnicodeDecodeError` in unchanged AST test code using
`Path.read_text()` with the machine's cp1252 default on UTF-8 source. No application,
financial, assertion or dependency change was needed: those exact nodes passed
under explicit Python UTF-8 mode. The 301 other tests were not unnecessarily
rerun; this is not a claim that the original invocation exited successfully.
The existing LibreOffice-open test skipped because LibreOffice is not installed.
That coverage gap is not described as PASS, and no skip/xfail was introduced.

The dedicated joint test proves route uniqueness in one application and checks
exact selected historical XLSX snapshot, deterministic bytes, Portfolio history
and Credit Decision links, historical/historical comparison, foreign owner
refusal and unchanged project/Workspace/history rows. Read-time engine execution
and atomic Run commit are guarded against.

The integrated ring includes Reporting V2/V3, Portfolio monetary/date coverage,
real four-vertical committed fixtures, concurrency, V3 Integrity/period/selector
tests, existing Compare and workbook navigation. Dedicated Portfolio and V3
Chromium tests are separate from the standard six-role Browser workflow.
Viewport coverage includes 1440x900, 1366x768 and 390x844, with light/dark Portfolio
presentation. No test asserts a staging deployment or production compatibility.

All test storage, logs, screenshots and downloaded CI artifacts are disposable
private evidence outside the Git tree. An unrelated installed Web3 plugin has
an import conflict, so local pytest uses PYTEST_DISABLE_PLUGIN_AUTOLOAD=1;
repository dependencies, pytest configuration and CI selection are unchanged.

## Boundaries and outstanding acceptance

ZERO DIFF to financial_engine, finco_core, domain, persistence implementations
and schemas, financial writers, release maps, activation flags, financial
goldens/tolerances and CI workflows. No OD-R, V9-P2, quarterly activation,
Replit prototype or Excel Migration branch was merged.

Reporting remains a reader of committed evidence. Portfolio sums comparable
historical capital/initial financing, not current outstanding debt, FX-adjusted
exposure, portfolio IRR or weighted DSCR. Run Workspace does not reconstruct
missing periods, recalculate financial statements or promote history to CURRENT.

Fresh source #331 CI and integration exact-head full Public Safety/aggregate,
Browser, Governance, Security, Compile and Q4 checks remain required. No pending
check is PASS. No complete Linux integrated acceptance is claimed until those
finish, with pytest rc=0, supervisor exit=0 and uploaded mandatory evidence.
Independent final review and explicit owner merge authorization are outstanding.
