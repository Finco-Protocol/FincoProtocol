# RC-3 / Correction C2 — PPA-01 exact-content candidate recognition (NOT an approval)

Scope: PR #294 (`integration/finco-rc3-model-radar-sc34-r6`). Test-side governance only; no calculation, workflow, pin, tolerance or production file changed.

## Root cause of the inherited failures

The PPA-01 candidate (source PR #293, reviewed source head `153a00384b2e4658863a967eec2184b5c5417eb4`) changes exactly three protected files. The repository has two
families of guards that look at `merge-base(origin/main, HEAD)..HEAD`:

1. **Historical stream guards** (Crypto, Radar, Opus, Staging, P-series, cost templates, XLSX, data center, run certificate, …) ask "did THIS old stream change
   financial authority?". On the integrated RC `HEAD` also contains PPA-01, which none of those streams own. They already use `tests/rc3_historical_anchor.py` for
   exactly this; its only tip (the pre-M7 tip) had landed on `main`, so it fell back to `HEAD` and attributed the candidate to every old stream.
2. **Current-authority gates** (`test_ci_acceptance` slice check, `finance_integrity_governance.strictly_frozen_changes`, WF07/V2/V3 exact pins, M7 content facts)
   judged `HEAD` content as if it were the historically released blob, or saw the candidate as an unlisted change.

## Mechanism

* `tests/rc3_historical_anchor.py` — a second immutable tip, `PPA01_PRE_INTEGRATION_TIP` (`30473e36…`, the #292 merge: Radar R6, Radar closeout, Statements — and no
  protected-path change). Historical guards evaluate that tip. Any missing provenance (unknown commit, not an ancestor, no `origin/main`) falls back to `HEAD`, i.e. the
  guard then sees the whole current tree and fails closed. Once the RC lands on `main` the tip is contained there and the original behaviour returns.
* `tests/ppa01_candidate_authority.py` — three **separate** questions, never one boolean:
  `candidate_content_matches_exactly` (exact three blobs, reviewed source head is an ancestor, protected diff is exactly these three paths),
  `candidate_is_financially_approved` (separate independent acceptance record — `docs/rc3/PPA01_FINANCIAL_ACCEPTANCE.json` — does **not** exist),
  `candidate_is_released` (approval **plus** explicit release authorization — unavailable). `frozen_scope_exempt` exempts a path only while **all three** blobs are
  exact.
* Current-authority gates: `test_ci_acceptance` accepts exactly this three-path slice at exactly these blobs; `strictly_frozen_changes` has one additive clause;
  `rc3_authority_states.authority_state` reports `INTEGRATED_RELEASE_CLOSED_CANDIDATE` (never released, never activated); WF07 / Revenue V2 / Revenue V3 pins are judged at
  their own checkpoint (`6fc77de9…`), the M7 eleven blobs are unchanged and coexist (the exact PPA-01 slice is excluded from M7 facts only while exact).

## Unchanged

`tests/model_v2_governance.py` and `tests/radar_authority_governance.py` are byte-identical to the checkpoint; every pin map, allow-list and activation flag is unchanged;
`approved_frozen_path` does **not** include the candidate (it is not a released exemption). The M7 acceptance record is not created or implied.

| Path | main blob | candidate blob |
|---|---|---|
| `domain/revenue/multistream_runtime.py` | `83beda4eb296b02baf2ebd6659fec243ab196206` | `b1896bdb156a53c8371286bb4198381d0c7904fe` |
| `domain/revenue/revenue_config.py` | `d5b2e2f6c5b513a6a4d1428bf00fa32d500419b4` | `d62fc2c7d97986d2c0aed6c0ac9068759011e1ef` |
| `finco_core/revenue/generation.py` | `35670dc7b5ab4ce01177f9df817a4776c10569ab` | `8e23a949e72acc6422a6c7cd46f034b31f81fdfb` |

## Still required before any merge

Independent technical review of the three blobs, a recorded financial-owner approval and a separate release authorization. Status: **FINANCIAL_OWNER_APPROVAL_REQUIRED — NO MERGE.**
Any further byte in any of the three blobs invalidates candidate recognition.
