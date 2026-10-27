# Exact-source CI compatibility recovery

Source checkpoint: `4ab372c40c78f364f86c5da6083aefbe2369df09`.
The complete current cohort and parent blobs are in SOURCE_SUCCESSOR.json.
No historical pin map, scan rule, workflow selection or financial tolerance was
relaxed. Final hosted checks must execute the publication HEAD; earlier green
checks do not substitute for them.

## Diagnosed failures on f19e310368676b0515bebd11f541a032da638775

- Public CI run 40525714183, worker 3: the existing sensitivity isolation test
  requires `{"kpis": ...}` for legacy results without financing evidence. The
  new worker had also returned `regime: null`. The correction omits that optional
  member when no regime exists; canonical financial candidates retain it. The
  original failing test is unchanged and passes locally.
- The same run, worker 2: the historical WF-10 tax candidate isolation guard
  rejected every changed financial engine path. Its additive successor admits
  only the complete FIN-V2-3 committed exact-source cohort, bound to the actual
  repository and HEAD. Other financial changes still fail. Tax source,
  activation and economic expectations are unchanged; all 97 candidate tests
  pass.
- Mandatory browser run 40525714131: 104 of 106 consolidation cases passed.
  The responsive test's Run helper could observe a previous CURRENT while the
  new Run or scenario projection was still pending. It now awaits the actual
  POST response, admits only COMMITTED/REPLAYED, and waits for the resulting
  page navigation and fresh workflow bar. The pre-existing one reload/retry is
  retained only for the definitive stale-draft redirect; unknown or failed
  outcomes cannot create a new attempt. The Run-history identity case now waits
  for the complete canonical row count before retaining all exact count,
  snapshot, history ID and accessibility assertions.

Browser helpers are separate from the React-owned product source and bundles;
those remain untouched. Their reviewed successor is finite and exact. All
original browser node IDs and assertions of financial, identity, ownership,
CSRF and CAS behavior remain in place. Historical source blobs stay pinned and
individually admissible; one-byte drift remains rejected.

## Local correction evidence

- Original execution / Goal Seek regression: 81 passed, no skips.
- Focused worker / new Goal Seek: 10 passed, no skips.
- Committed source successor / security / browser governance: 233 passed,
  no skips. Every one of the 48 owned paths has a one-byte/deletion negative.
- WF-10 candidate: 97 passed, no skips.
- Final exact-source responsive and history Chromium cases: 2 passed, no skips.
- Complete final-source consolidation Chromium: 106 passed, no skips,
  337.30 seconds. BROWSER_CONSOLIDATION.xml records the complete result.
  The supported local system Chromium override uses Chromium 154.0.8037.57
  with Playwright 1.62.0; hosted CI retains its existing pinned browser setup.

Final full hosted results are authoritative in Draft PR #391 Checks. This
recovery does not authorize a merge, deployment or independent financial
self-approval.
