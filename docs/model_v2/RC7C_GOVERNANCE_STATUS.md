# RC-7C — governance status of the changed pinned blobs (outstanding release blocker)

**Not an approval; nothing here weakens, bypasses or edits a historical pin, a registry, a CI workflow or an owner key.**

RC-7C changes four files that the RC-7B / Gate R machinery pins by exact Git blob. The exact-content guards therefore go red until an owner-reviewed
successor adopts the new blobs. Candidate successor blobs (inert, informational; computed by `git hash-object` at the PR head):

| File | `main` blob (`bf0167a0`) | RC-7C blob |
|---|---|---|
| `finco_core/engine/calendar_policy.py` | `91f55f9b8356ae0b8b1ca635b28d008949a8146f` | `7021648c8a354b928a1e6bd45a0c7b8c897cc8cc` |
| `finco_core/engine/period_engine.py` | `465c172d5d7176f294872fd2e9542315e3027db2` | `d72de84d082962d9c49a840178211602495c027a` |
| `financial_engine/orchestrator.py` | `07aa1e18cc72a1422fcf7fc779dd72ee835c8096` | `b6dc102ea18be4d40adc4a7ad08f187af17c5076` |
| `financial_engine/senior_debt/project_adapter.py` | `b2302be9d9760ab7a663ff873e95415a4bf18842` | `7ffbf1a6de79f46a38f5bf58190b8a7d6e573a8b` |

(If a later commit on this branch touches these files the blobs change; recompute with `git hash-object`.)

## Governance ring result (Python 3.12, test files that mention the changed blobs, plus all `test_rc*`, `test_m7_*`, `*governance*`, `*manifest*`, `*authority*`)

* 2,720 passed, 12 skipped. Failures were classified against a detached worktree of `main` `bf0167a0`:
  * **15 governance guards fail identically on `main`** (RC-3/M7/PPA-01/WF-04/WF-07/F3 historical pin guards, `test_approved_engine_paths_are_allowed`, …): pre-existing, not caused by RC-7C.
  * **4 browser tests fail identically on `main`** (`debt_equity_journeys` ×1, `construction_timing` ×1, `m7_bess_workflow` ×2): pre-existing.
  * **New red guards caused by RC-7C (the changed blobs):**
    * `tests/test_finance_integrity_governance.py::test_this_branch_stays_within_the_governance_contract` (lists `orchestrator.py`, `project_adapter.py` as unapproved engine changes);
    * `tests/test_rc7b_quarterly_candidate_authority.py` — `test_current_content_is_recognised_but_not_approved_admitted_or_released`, `test_even_a_valid_record_neither_admits_nor_releases`, `test_exemption_is_path_exact_and_never_a_released_authority` ("not the exact reviewed candidate blob");
    * `tests/test_rc7b_gate_r_authorization.py` — 53 of 150: every test whose fixture needs the exact twelve RC-7B blobs (all 150 pass on `main`).
* A first parallel run showed ~40 browser failures with `address already in use` (two test runs overlapping on the same ports); they pass when re-run alone and are not RC-7C.

## What this means

The 57 new red guards are the intended tripwire: the pinned financial mechanics changed, and only the owner-controlled successor process
(`RC7B_GATE_R_REVIEW_PROCESS.md`: independent review of the exact blobs → owner-signed record) may re-pin them. The implementing agent does not edit those pins,
the registry, the template or the CI workflows to turn them green. **This PR is therefore not mergeable until a Gate R / RC-7C successor is completed by the
Financial Owner and an independent reviewer.** Financial results are not in question: 6/6 is bit-identical to `main` and the quarterly oracle, reconciliation and committed-Run suites pass.
