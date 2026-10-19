# Quarterly candidate — canonical current governance state (RC-7B merged, RC-7C candidate)

**This is the single current-state document for the quarterly candidate governance. It is not an approval.** No Financial Owner key, signature, registry
entry, record, review or GitHub approval is created or implied by it. Older RC-7B documents are retained as historical evidence and link here.

Live facts (verified from GitHub and Git):

| Fact | Value |
|---|---|
| PR #320 (RC-7B integration) | **MERGED** as a normal merge commit `bf0167a036a6e30d3225b901aeda1b353681171a` (parents: predecessor `5be8c4b149712dd39b38b54c6fabcf3fcf47ef0d`, PR head `e9c3326a9f8b7791cd8032102347a735c12178e4`) |
| PR #326 (post-merge governance recovery) | **MERGED** 2026-10-19T20:36:08Z as `162a3d70ea0cf5b15024ecbe5f7dec33f447a48d` (head `8dd1b4f0`) |
| PR #325 (RC-7C) | Draft; synchronised by a normal merge of `162a3d70` (no rebase/squash/force-push) |
| `ACTIVATION_ENABLED` | literal `False` (unchanged since RC-7B) |

## 1. States (never one boolean)

| State | RC-7B as merged (main `162a3d70`) | RC-7C candidate (this PR) |
|---|---|---|
| Historical PR #320 integration verified (merge ancestry + parents) | TRUE | TRUE |
| Exact content verified | TRUE (twelve RC-7B blobs) | TRUE (eight RC-7B blobs + four pinned RC-7C blobs) |
| Release-closed candidate recognised | TRUE (`rc7b_postmerge_successor`) | TRUE (`rc7c_candidate_successor`) |
| Financial Owner approval of the blobs | FALSE | **FALSE** — the PR #320 owner decision does **not** cover the four RC-7C blobs |
| D-01…D-12 financial-policy approval | FALSE | FALSE |
| Gate R active (pre-merge mechanism) | FALSE (historical; never active) | FALSE |
| Gate P / product admission / activation / financial release | FALSE | FALSE |

## 2. Modules (current controls)

| Module | Role |
|---|---|
| `tests/rc7b_postmerge_successor.py` (PR #326) | Recognises **only** the twelve original RC-7B blobs. **Not widened.** |
| `tests/rc7c_candidate_successor.py` (new) | Separate, explicitly scoped RC-7C successor (contract below). Every approval/admission/release state is a constant `False`. |
| `tests/quarterly_candidate_recognition.py` (new) | The single import point for the current-authority guards: `recognized_state()` → `"RC7B"` / `"RC7C"` / `None` (mutually exclusive by blob identity), `candidate_blobs()`, `scope_exempt`, `superseded`, `current_expected_blob`, `without_superseded`. Replaces per-guard wiring and the misleading `candidate_recognized as gate_r_active` aliases. |

## 3. RC-7C candidate-boundary contract

`rc7c_violations()` is empty only while **all** hold (every uncertainty is a rejection):

1. authentic ancestry: the PR #320 merge commit (with its two parents) and the PR #326 merge commit `162a3d70…` exist and are ancestors of the evaluated ref; the PR #320 merge carries the twelve RC-7B blobs (immutable predecessor content);
2. the **eight** RC-7B blobs RC-7C does not touch are the exact RC-7B blobs; the **four** RC-7C blobs are the exact pinned blobs below;
3. the protected-namespace (`financial_engine/`, `finco_core/`, `domain/`) diff against the RC-7B predecessor is exactly the twelve candidate paths, and against the PR #320 merge exactly the four RC-7C paths — no other financial/core/domain file differs;
4. historical authority files (`model_v2_governance.py`, `m7_rc3_candidate_successor.py`, `radar_authority_governance.py`) and the isolated quarterly research reference are byte-identical to the predecessor; `ACTIVATION_ENABLED` is a literal `False`; the exact policy version literal `rc7c-quarterly-candidate-v2` is present in `calendar_policy.py`.

| Path (the only four RC-7C changes) | RC-7B blob (main) | RC-7C blob |
|---|---|---|
| `finco_core/engine/calendar_policy.py` | `91f55f9b8356ae0b8b1ca635b28d008949a8146f` | `7021648c8a354b928a1e6bd45a0c7b8c897cc8cc` |
| `finco_core/engine/period_engine.py` | `465c172d5d7176f294872fd2e9542315e3027db2` | `d72de84d082962d9c49a840178211602495c027a` |
| `financial_engine/orchestrator.py` | `07aa1e18cc72a1422fcf7fc779dd72ee835c8096` | `b6dc102ea18be4d40adc4a7ad08f187af17c5076` |
| `financial_engine/senior_debt/project_adapter.py` | `b2302be9d9760ab7a663ff873e95415a4bf18842` | `7ffbf1a6de79f46a38f5bf58190b8a7d6e573a8b` |

Recognition is **bytes only**: `approved_frozen_path` and `released_engine_authority_matches` never consult it, no historical pin map was rewritten, and no
predicate named approve/admit/release exists. Approving the four RC-7C blobs (and D-03/D-03-b etc.) needs a genuine, separate Financial Owner
authorization and independent review; no file in the repository can switch it on.

## 4. Historical evidence retained (not deleted, not weakened)

PR #320 and its merge; the twelve original RC-7B blob identities and `RC7B_PREDECESSOR_BLOBS`; the historical M7 / F3 / WF-04 / WF-07 / PPA-01 pin maps; the Gate R
mechanism (`rc7b_quarterly_candidate_authority.py`, `rc7b_owner_attestation.py`, registry, template, review process) and its 150 negative controls; the PR #326
successor, its recovery document and its 13+ negative controls; the PR #320 reconciliation and RC-7B correction reports; the original financial/numerical acceptance
evidence. Tests of the RC-7B mechanisms now run against the immutable RC-7B state (main `162a3d70`), not against a moving HEAD, so they stay valid after later
candidates.

## 5. Cleanup performed in this correction

* All current-authority guards use `quarterly_candidate_recognition` (one canonical wiring) instead of per-guard imports of the PR #326 module; `gate_r_active`/`superseded_by_gate_r`/`rc7b_candidate_exempt` aliases that actually meant "release-closed candidate recognised" were renamed (`candidate_recognized`, `candidate_superseded`, `quarterly_candidate_exempt`; `rc7b_gate_r_candidate_matches` → `quarterly_candidate_matches`); the duplicated `superseded` predicate is a plain alias of `scope_exempt`.
* Stale test comments that described "an ACTIVE Gate R" as the recognition path were corrected to the real recognition rule.
* Historical documents carry a banner pointing here; stale statements ("#320 stays Draft", `QUARTERLY_ADMISSION_ENABLED`) were corrected; the D-03 note says RC-7B did not change the horizon and RC-7C addresses it.
* Nothing was deleted; no governance test was removed, skipped or weakened; no CI workflow, pin map, registry or owner record was edited.

