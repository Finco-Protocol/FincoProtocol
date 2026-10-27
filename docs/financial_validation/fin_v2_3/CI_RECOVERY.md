# Exact-source CI compatibility recovery

Browser/production source checkpoint: `4ab372c40c78f364f86c5da6083aefbe2369df09`.
Final CI compatibility source checkpoint: `5f66eae25ea2decfb39247131280f28da3b51987`.
The subsequent test-only correction adds the two exact macro DOM row hashes.
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
- The same run, worker 0: the historical macro DOM inventory omitted the two
  editable/protected presentations of `debt.valuation.configuration`. Its
  additive successor records exactly those two new row keys and their exact
  normalized SHA-256 hashes, gated by the complete source cohort. Every old
  golden hash, normalization rule, CSRF/read-only assertion and DOM mutation
  negative remains unchanged.
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
- Committed source successor / security / browser governance: 234 passed,
  no skips. Every one of the 49 owned paths has a one-byte/deletion negative.
- Final complete layout and WF-10 candidate selection: 204 passed, no skips
  (107 layout and 97 tax tests).
- Final exact-source responsive and history Chromium cases: 2 passed, no skips.
- Complete final-source consolidation Chromium: 106 passed, no skips,
  337.30 seconds. BROWSER_CONSOLIDATION.xml records the complete result.
  The supported local system Chromium override uses Chromium 154.0.8037.57
  with Playwright 1.62.0; hosted CI retains its existing pinned browser setup.

The old aggregate and mandatory proof correctly refused the failed worker
results; their guards remain unchanged.

Final full hosted results are authoritative in Draft PR #391 Checks. This
recovery does not authorize a merge, deployment or independent financial
self-approval.


## Correction B — F01 historical fixture integrity vs FIN-V2-3 exact DOM additions

On post-#390 exact head `0bf3ba2e5ab49f235167f359fa8bc8d172d734de`, F01 financial/browser workflow `40537734829` ran 140 tests: 139 PASS, 1 FAIL. The sole failure is `test_authority_mock_has_only_its_missing_unit_added`: original F01 asserted the exact original productivity test source plus one interest-rate unit label, while FIN-V2-3 added exactly two reviewed valuation macro DOM hashes. This is a competing historical governance expectation, not an observed numerical regression.

Correction B preserves F01's original baseline, original unit marker, original source comparison and all old DOM/security/hash tests. It admits a single *literal* FIN-V2-3 valuation assertion block with two reviewed exact hashes only when the entire repository-bound FIN-V2-3 cohort matches its exact source manifest. No wildcard, skip, changed old DOM golden, altered rate conversion or broadened source allowance. The protected F01 test is itself a new pinned owned path with its original #390/main parent SHA; the existing parametrized one-byte/missing-file negative test automatically covers it. Four-vertical browser 139 other tests passed previously; full new exact-head acceptance pending.


## Correction C — integrated #388 and post-#390 lifecycle evidence (2026-10-27)

Main advanced to `f79e251903621c1a5c88501d51d6971960b612d3` through approved PR #388. Prior exact HEAD `8835385565529335b56c0cbe5a9769578af61b44` had all mandatory checks GREEN except Public Safety CI V3 (`40543293268`), where worker 0 executed 3,518 original test cases: 3,510 PASS / 8 FAIL / 71 skipped; every failing node was a FIN-V2-3 lifecycle `single`/`batch` for Solar, Wind, Data Center or EV Charging. The test expected `DEBT_EVIDENCE_NOT_AVAILABLE`, a true *pre-#390 isolated-source* result, but after the accepted #390 Senior evidence was attached first, the actual persisted coverage result was `OK`. This is a real test contract that must evolve, not a reason to hide tests or change engine math.

The lifecycle test now verifies the Senior evidence is canonical/RECORDED with the exact maturity/payoff index/date sources, coverage `OK` and consistent ratios/horizons/rolling minimum, preserved Run History and report binding. Added four explicit counterfactual negative cases across the four verticals: absent evidence stays `DEBT_EVIDENCE_NOT_AVAILABLE`, tampered payoff date returns `DEBT_EVIDENCE_MISMATCH`. Historical economic oracles are unchanged.

RC-M #388 immutable main is integrated by ordinary merge ancestry and the exact reviewed main tree. Four shared governance sources keep RC-M's six exact pinned presentation successors, F01 atomic-create pins, and FIN-V2-3's finite source successor fallback. No arbitrary financial paths are exempt: RC-M protected source test admits only FIN-V2-3 exact owner-blobs, and FIN-V2-3 scope diffs the accepted main tree, requiring all non-owned main paths to remain inherited byte-for-byte. Original historical BASE stays `128bf0c2...`. The RC-M guard becomes FIN-V2-3's fifty-first protected owned source; source manifest records its original main blob and all corrected source hashes. The seven independently pinned #390 dependency blobs remain unchanged.

**Tests pending on this integrated source:** new exact-head F01, browser, FIN-V2-3 Oracle, strict numerical/identity, Governance Full History, 5-worker Public Safety. Previous success cannot be inherited. No release, merge, activation or deploy authorization.
