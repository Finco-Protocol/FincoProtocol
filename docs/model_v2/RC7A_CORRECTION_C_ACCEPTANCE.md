# RC-7A Correction C: integration evidence, not release approval

## Provenance and scope

Verified main and merge-base: `05183b2a96c74fd4b3976903c593a61402cab7b3`.
Branch: `integrate/model-rc7-credit-revenue-capex-reporting-v1`.
Draft PR: https://github.com/Finco-Protocol/FincoProtocol/pull/319.

Four source histories were normally merged, in the requested order:

| Source | Included exact source HEAD | Correction |
|---|---|---|
| #314 Credit V4 | `ee5290c7ed8d567490a88d10e029e4633b84bd22` | Existing source fix preserves short IDs and asserts both committed identities. |
| #315 Revenue/PPA | `675ad74b2dd8aed84791b07a36ee8df1ed15c2d5` | Existing source relocation to the app-layer read-only ledger retained. |
| #316 Reporting V2 | `7bd63058ada7ca59f910b16ca947b6e5335ebc1a` | Existing source statement-label and failed-Run export corrections retained. |
| #317 Monthly CAPEX | `4ba8c32d51725b5aaa4af3326ece636de4994a12` | Path portability correction `cff3301b` plus normal merge of isolated shared refresh fix `eccde424`; financial and CSRF content unchanged. |

Local merge commits initially: `fd16deaf`, `1905467e`, `12ccf33a`,
`b0cbafa1`. The source #317 test correction was normally merged as `735f85bd`.
During validation another agent published the same requested branch as #319 at
`84196fc7c268735a301d29823804cfdd41af1c31`. Its complete history and additional
reporting test were preserved by normal merge `7007d761`; no history was replaced.
Final publication HEAD/tree and exact-head CI belong in the PR checkpoint,
not a self-referential commit hash inside this document.

No conflict resolution or production integration edit was required. The merged
router retains Revenue evidence plus CAPEX Run, sensitivity and Goal Seek binding.
No branch-side diff exists under `financial_engine/`, `finco_core/`, `domain/`
or `.github/`. Historical pins, goldens, tolerances and release flags are unchanged.
Public Safety retains timeout 130 minutes, pytest budget 6000 seconds and exit
grace 240 seconds. Browser selection retains six mandatory roles and includes
the three CAPEX preview/mobile/Save-Reset nodes inherited from #317.

## Quarterly isolation

#313 at `03ee3aee54e9f6fea3eb6e849a440ba1ebb7307b` is not an ancestor.
Its new `financial_engine/quarterly/` files are absent. Existing protected blobs:

| Path | Main and integration Git blob |
|---|---|
| `financial_engine/adapters/project_inputs.py` | `14bd759a9958515a7796626f93c1bd2233d69150` |
| `financial_engine/orchestrator.py` | `be7ac31c6c4fed43b5fd7ca49fe53bfd1cc54c03` |

#313 remains unchanged, Draft, release-closed and financially unapproved.
Its source Public Safety run `39103456006` actually completed with 49 failures,
12729 passed, 100 skipped; pytest rc=1 and supervisor child exit=1. These are
preserved authority/scope failures, not permission to relax frozen guards.
D-01 through D-12 remain open. #318 is preserved Draft, superseded for release
planning; no reversion or rewrite of its five-source history was performed.

## Independently executed local evidence

Windows / Python 3.12.10. Disposable SQLite test storage. Private logs, event traces,
full numeric capture and JUnit remain outside the repository.

- Initial bounded source ring: 321 passed, 1 failed, 2 skipped in 469.83s, rc=1.
  The sole failure was the Windows relative-path spelling in #317's folding
  inventory. Isolated reproduction confirmed eight already classified files
  were compared with backslash paths. Source correction changes only path
  normalization; the complete five-test module then passes with normal rc=0.
- Reporting/credit/output regression ring: 51 passed; the newly authored combined
  test initially failed an incorrect CURRENT-versus-HISTORICAL byte-equality
  assumption. Existing application behavior was not changed to satisfy it.
- Corrected cross-stream test plus folding module: 6 passed, rc=0. The test
  distinguishes legitimate state-label changes from immutable financial data,
  compares financial XLSX rows and evidence digests, then requires repeat
  HISTORICAL exports to be byte-identical.
- The reporting regressions include the failed-Run export immutability node,
  both F3.8 XLSX variants and four-vertical output/XLSX parity. No golden changes.
- The two existing skips in the initial ring were a PPA `None`-share parameter
  explicitly covered by schema tests, and unavailable LibreOffice. They were
  neither introduced nor converted into passing checks.
- Complete canonical result objects and input identities for Solar, Wind,
  Data Center and EV equal independently captured main results exactly.
  Maximum before/after change is zero; no fixture or financial tolerance changed.
- Governance, exact-blob negative tests and preserved concurrent reporting test:
  144 passed in 128.61s, rc=0. Browser-selection/CI and shared navigation tests:
  102 passed in 60.88s, rc=0. Normal process completion observed for both.
- Changed-file source scan and compilation passed before publication.

## Combined evidence contract

The additional cross-stream test executes a real default Solar Run, saves a
front-loaded profile, then commits its real monthly-funded Run. It verifies:

1. Fourteen persisted construction periods, not the default three.
2. Credit V4 reads the two distinct committed identities and retains explicit
   unavailable contractual-covenant semantics.
3. Read-only Credit and exports perform no engine calls.
4. The old Last Run input-reconstruction exporter refuses a profiled Run with
   `CAPEX_PROFILE_UNBOUND_SURFACE`, rather than exporting unprofiled economics.
5. Historical XLSX uses the actual persisted monthly funding totals, with
   unchanged old financial rows and unchanged evidence digest.
6. Both history records and the composite Working Copy hash remain unchanged.

## Browser blocker: observed baseline behavior

Source #315 browser run `39107418172`, attempt 2, job `117616687238` failed:
Capacity expected 150.0, displayed 100.0; 100 passed, 1 failed, 1 deselected;
pytest rc=1 and supervisor exit=1. It was already rerun unchanged, so no further
blind retry was dispatched here.

Unmodified main reproduced the original test with private event observation:
1 failed in 58.83s, rc=1. The same unchanged test on the clean integration failed
in 58.33s, rc=1. Events show a Project Setup presentation refresh in flight,
input value 150 while its view state is `pending`, HTTP 200 for the read-only
refresh, transition to `error`, and a Save click without a Save POST. Persisted
capacity remains 100. No CAS mutation was attempted in these two reproductions.

The original #319 publication also failed browser run `39112364754`, job
`117631006842`: response timeout, 100 passed, 1 failed, 1 deselected, 93.74s;
pytest rc=1 and supervisor exit=1. That is prior-head evidence, not final-head CI.
This establishes a shared baseline failure for the observed no-POST lifecycle,
not a complete causal explanation of every prior 100-versus-150 response case.
No acceptance assertion, timeout, test selection or application UI was altered.
A separately scoped shared-refresh correction remains required.

## Remaining review gates

NO MERGE. Source and combined final-head CI must be freshly checked. A previous
green #317 head is not acceptance of its new test-only successor. Full Public
Safety, normal process exit, uploaded evidence and all browser roles remain
mandatory. CAPEX preview/Save exact-content CSRF successor still requires
independent review. No financial, Junior, Revenue V3 or BESS activation is granted.

## Shared browser correction after owner coordination confirmation

The owner confirmed no other agent owns the shared correction. A two-file fix
was isolated directly on the verified main as commit `eccde424`, then normally
merged into source #317 and this integration. No extra PR, cherry-pick or history
rewrite was used. The previous failure inventory above is retained as provenance,
not a claim that the corrected exact HEAD has already failed.

The original V7 contract deliberately preserves drafts and refuses obsolete
forms. Project Setup nonetheless accepted typing while its replacement read was
pending. In the independently traced failures the draft was kept behind the
stale-form rejection and no Save was sent. Earlier CI also showed a 100-versus-150
response symptom, whose full event sequence was not captured independently.
The correction in
`static/js/model_view_refresh.js` temporarily disables only Project Setup's
interactive controls while its view is pending/error. A successful authorized
refresh unlocks them. Pre-existing disabled controls are not unconditionally
enabled, the explicit refresh action remains available, and the identity/CAS,
dirty-draft and out-of-order response guards are untouched. Other editors retain
their existing behavior.

Deterministic held-response test before the correction: FAIL, because the old
Capacity input remained enabled. After the correction:

- New pending/failed-read/explicit-retry/real-Save tests and existing V7
  pending-CAPEX/out-of-order/read-refresh tests: 6 passed on the integration
  (63.06s) and separately 6 passed on clean main plus the isolated fix (68.63s).
- Original `test_reference_driven_correction_a_23_capture_journey`, unchanged:
  three independent disposable databases, 3/3 PASS (26.22s, 23.56s, 22.95s), rc0.
- The new positive test proves exactly one Capacity Save, persisted 150 MW,
  unchanged Last Run identity and history, and no mutation by pending or failed
  presentation reads.
- Node syntax, Python compilation and unchanged source-safety checks pass for
  the two added/modified files. The prior full Git-byte safety scan covered all
  2437 staged files; local Swagger CRLF conversion was its only checkout issue.

The unchanged six-role mandatory CI still needs to validate the new exact HEAD;
local browser results are not a replacement for it. Full Public Safety and the
independent CAPEX CSRF successor review remain mandatory. NO MERGE / DEPLOY.
