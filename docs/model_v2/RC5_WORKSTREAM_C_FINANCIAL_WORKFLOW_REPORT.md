# RC-5B / Workstream C: Financial Workflow Reliability

## Provenance And Ownership

- Base: `97de3833449d91f3febc450c7e163287b63e208d` (independently fetched main).
- Branch: `fix/model-rc5-financial-workflow-reliability`.
- No individual PR, merge, deployment, release activation or full-CI claim.
- The open-PR inventory contained no competing Model implementation PR at preflight.
- No scenario writers, composite identity/freshness authority, Run Compare, sensitivity,
  shared workbook router or engine/core/domain files are changed.
- The only change in the shared `app/services/export_service.py` is download naming;
  scenario materialization and persisted Run resolution are untouched.
- Final fetch still reports the same main. The subsequently published
  `fix/model-rc5-run-compare-sensitivity-integrity` branch has zero changed-path
  intersection with Workstream C.

## Reproductions And Corrections

| Finding | Before | Candidate | Authority boundary |
| --- | --- | --- | --- |
| S6-12 B.13 | Controlled 550 base, 5% applied: parent subtotal 0, although contingency vector is 27.5 and total 577.5 | Parent, calculated read-only row and annual projection read the existing contingency vector | No engine input, OPEX fold or total calculation changes; reference-only estimates remain excluded |
| S6-13 validation | Hidden required source reference triggers native validation before submit, with no durable field feedback | Opens advanced terms, identifies contract/row/field, focuses and scrolls to field, displays inline error; no Save request, draft retained | Canonical validation, CSRF, CAS and writer remain authoritative |
| S6-14 Quick Add | Default start plus assumed term can produce an invalid period-boundary end | Default start remains the actual operating-axis start; term/end are explicitly incomplete until chosen | No automatic date rounding, invented term, pricing change or timeline override |
| S6-09 export | Owned Working Copy artifact carries template project name/key; internal skeleton filename; absent execution metadata defaults to a misleading classification | Record name/code/id, run-bound scenario/snapshot/time, owner context and readable results filename; missing execution evidence says NOT_RECORDED | Same authorized persisted Run, no export-time engine added, no fabricated Run UUID |
| S6-07 reference cards | Old persisted KPIs have no visible Run date or engine currency | Saved-reference label, recorded date (or explicit unknown), engine evidence, no-recalculation disclosure | No new Run, reference reseeding or golden update |

The XLSX OPEX sheet reuses the existing OPEX view-model budget projection to show
550 / 27.5 / 577.5 explicitly. A percentage-based OPEX item's stored zero is no
longer presented as its effective cash cost. The annual budget is labelled as such,
not misrepresented as the first partial financial period's cash amount.

The initial new presentation tests on base reproduced three failures and two passes:
B.13 subtotal, missing reference provenance, and template identity in the owned export.

### Scope Already Correct On Main

- Applied OPEX total and reference-only estimate exclusion already worked.
- Canonical export already bound scenario and financial values to Last Run and used a
  single workspace snapshot; existing safeguards are preserved, not reimplemented.
- Rejected server-side revenue Saves already retained the browser draft.
- Existing Quick Add boundary validation already refused invalid dates and offered
  explicit choices. This change removes an invalid assumed default, not those guards.

### Controlled Fixture And Numeric Presentation

The real Chromium Wind acceptance uses an explicit disposable cost decomposition:
one constant annual cost of 550 kEUR and zero other annual costs, then a real 5%
contingency Save. These are synthetic fixture inputs, not claims about default Wind
economics at an arbitrary capacity. Parent display keeps the existing whole-kEUR
convention (28); the authority panel retains 27.5, and total display is 578 for 577.5.

XLSX numeric cells retain the existing writer's 16-significant-digit serialization.
The export assertion compares that exact serialization, not a widened financial
tolerance. Persisted full-precision Run data is compared without rounding.

## Independent Canonical Financial Parity

Fresh processes executed Solar and Wind reference Runs in the detached base worktree
and candidate. Complete selected financial payloads were compared, not just headline
KPIs: KPIs, Sources & Uses, financial statements, debt, tax, distributions, sponsor
schedules and integrity evidence. Both payloads are bit-exact; maximum delta is zero.

| Case | Identical base/candidate SHA-256 |
| --- | --- |
| Generic Solar Reference | `aa0aed44e823460753c41bea6aa4995ffc07a2c3466188b7eebb5c663b49d2d6` |
| Generic Wind Reference | `f2ceace49999bc609c18f55473f2257116f69ce76dc5bdf85355a32a1e1cd60f` |

These are comparison evidence, not runtime targets or replacement golden authorities.

## Acceptance Evidence

Environment: Windows, Python 3.12.10, Chromium 151.0.7922.34. Plugin autoload was
disabled for reproducible local pytest execution; every listed final process
returned rc=0 normally, with zero failures and zero skips.

| Local acceptance command / coverage | Result | JUnit evidence name |
| --- | --- | --- |
| Presentation, B.13, F06, F07/F07B, U2.1 export, reference Last Run, Model Home, Revenue V2 routes | 187 passed | `regression-2.xml` |
| Workspace consolidation, Trust CSRF inventory, RC-4 financial acceptance | 75 passed | `governance-1.xml` |
| RC-5 + existing Quick Add, PPA dates and draft preservation in real Chromium | 49 passed | `browser-final-2.xml` |
| Cost templates, OPEX mobile/layout and presentation | 39 passed | `presentation-final-3.xml` |
| Final-byte B.13 Run/export and U2.1 export after XLSX budget correction | 60 passed | `export-final.xml` |
| Final-byte six RC-5 real Chromium scenarios, including exact XLSX budget cells | 6 passed | `browser-release.xml` |

These overlapping rings are not summed as distinct tests. The 187/49 rings were
followed by the narrower final-byte export/browser reruns after the final scoped
presentation changes. Full public CI was not run or claimed; the coordinator's
integrated candidate remains its acceptance authority.

The existing F08 layout tests hard-code a Linux browser path. On Windows they
initially failed before opening a browser. A private local pytest launcher changed
only the collected module's Chromium executable location to the installed Windows
binary. All 39 assertions then executed and passed; no repository fixture,
assertion, test selection or skip policy was changed for this environment adapter.

Earlier new-test iterations corrected the synthetic cost setup, reading a browser
download through a byte stream, and asserting the exact existing XLSX numeric
serialization. No financial expected value, golden or tolerance was changed.

- Public repository safety scanner: PASS (full scan, normal rc=0).
- Final changed-file safety rescan: PASS (15 files, including this report).
- Python compilation, Node syntax check and diff hygiene: PASS.
- Zero diff in engine/core/domain, workflows, pin maps, release flags and shared
  scenario/Compare/router ownership.

The browser ring explicitly exercises Chromium against a disposable local server,
desktop/light and 390x844/dark validation, actual Save and Run, a renamed Working
Copy, selected child scenario, binary XLSX download, and a later 6% draft edit that
must not change the exported historical 5% Run or its immutable history.

No arbitrary older-history full-workbook selector is added. Historical evidence
coverage concerns the committed Last Run after subsequent draft changes and the
existing immutable-history preservation contract, not a newly invented export API.

## Changed-File Ownership

- `app/ui/opex_sheet_projection.py`: derived B.13 display vector only.
- `app/templates/v2/partials/sheet_opex.html`: calculated B.13 row source.
- `static/js/model_revenue_contract_editor.js`: invalid-field feedback/focus only.
- `static/css/model_revenue_contract_editor.css`: field error presentation.
- `app/templates/v2/partials/revenue_contracts.html`: explicit incomplete term.
- `app/library/model_home.py`: persisted reference provenance projection.
- `app/templates/library/project_library_list.html`: saved-reference disclosure.
- `app/services/v2_export_service.py`: owned artifact identity and filename.
- `app/services/export_service.py`: legacy institutional download filename only.
- `app/export/institutional_workbook.py`: record identity and truthful disclosures.
- `app/export/filename.py`: shared filename sanitization, no financial authority.
- `tests/test_rc5_workflow_presentation.py`: focused arithmetic/identity regressions.
- `tests/test_rc5_workflow_browser.py`: genuine local Chromium acceptance.
- `tests/test_u2_1_v2_export.py`: replace only obsolete skeleton-filename assertion.
- This report.

## Deferred / Coordinator Acceptance

- Broad language, styling, mobile navigation and framework changes await V3.7.
- Lazy sheet loading, scenario overrides/freshness, Compare and sensitivity remain
  with their designated workstreams; no overlapping implementations are introduced.
- The observed OPEX contingency normal-post redirect can lose the selected sheet;
  this navigation issue is not changed through a shared writer in this workstream.
- No staging acceptance or exact-head integration CI is claimed. The coordinator
  must integrate the branch normally and run the consolidated acceptance gates.

## Disposition

READY FOR INTEGRATION REVIEW. No financial-authority blocker was introduced by
this application-only branch. This is not final merge, staging or release approval.
