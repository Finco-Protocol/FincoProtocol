# RC-7 integration (PR #318) - quarterly candidate financial-governance blocker

Status: **NO MERGE - APPROVAL REQUIRED.** Documentation only; no governance helper, pin, allowlist or test was changed.
Integration base: `main` = `05183b2a96c74fd4b3976903c593a61402cab7b3`. Candidate source: PR #313 @ `03ee3aee54e9f6fea3eb6e849a440ba1ebb7307b`.

## Protected blob inventory (verified against `docs/model_v2/RC7_QUARTERLY_CANDIDATE_BLOB_MANIFEST.json`: all five match)

| Path | `origin/main` blob | #313 candidate blob | Existing pin |
|---|---|---|---|
| `financial_engine/orchestrator.py` | `be7ac31c6c4fed43b5fd7ca49fe53bfd1cc54c03` | `fcffca1074dfd62143fa4c3d55240b4bb1a0b7ec` | main blob == the M7 RC-3 release-closed candidate blob; older WF07 released pin `67f9ec6a...` |
| `financial_engine/adapters/project_inputs.py` | `14bd759a9958515a7796626f93c1bd2233d69150` | `d54e35dac6b45b490c16bde8b49c158d83f56047` | main blob == the M7 RC-3 candidate blob; older WF07 released pin `fe09548f...` |
| `financial_engine/quarterly/__init__.py` | absent | `027b4fc206f4e3be564c89ca3e53dc95e720359c` | none (new) |
| `financial_engine/quarterly/calendar.py` | absent | `1ba36e59590386023dc6f475fe383203a36b7dce` | none (new) |
| `financial_engine/quarterly/runtime.py` | absent | `12848fd6787719d42e7588120c6ce72d717fee81` | none (new) |

## Precise conflicting contracts

Sweep of the 44 test files that reference the protected paths on the integrated tree: **43 failed, 1458 passed**.

1. **M7 eleven-blob contract.** On main, `orchestrator.py` and `adapters/project_inputs.py` are two of the eleven exact M7 RC-3 candidate blobs. #313 changes both, so the exact-content contracts reject it:
   `test_m7_rc3_candidate_successor.py` (3), `test_wf07_revenue_governance.py` (exact-seven pins; M7-never-inherits for both paths),
   `test_rc3_post_merge_authority_states.py` (2), `test_m7_bess_boundaries.py`, `test_ppa01_candidate_authority.py` (4, M7/PPA-01 coexistence).
2. **Per-stream zero-diff guards on `financial_engine/`** (each has its own diff logic and does not consult any shared exemption), in unrelated streams:
   crypto, RWA, tokenized, stock-token, yield, radar, multi-source, market-bridge, run-certificate, data-center A3, cost-templates, P1.2/P1.3 XLSX and `test_parallel_stream_frozen_diff.py`.
3. **Finance-integrity allow-list** (`tests/finance_integrity_governance.py`): the three `quarterly/*` files are not on it, and the two shared files fail their exact-blob test.

A recognition-only successor (the PPA-01 pattern) would not clear (2), because those guards do not consult the shared helper. Clearing them would mean editing roughly 35 historical test files, which is prohibited. **The candidate cannot be made compatible with the historical authority contracts without an independently approved successor and a coordinated governance change.** No such approval exists; none is invented here.

## Review notes for the independent reviewer (not an approval)
- Quarterly paths are gated by `type(inputs) is QuarterlyOperatingModelInput`; `ACTIVATION_ENABLED = False`; no app/route/writer/scenario module imports `financial_engine.quarterly` (grep-verified).
- The released adapter now raises `CLEAN_CALENDAR_FREQUENCY_UNSUPPORTED` for any non-SEMESTRIAL input - a behaviour change on a released-path file.
- `_is_quarterly_candidate` imports the quarterly module on every released-path call (no numerical effect; reviewer should confirm).
- D-01 through D-12 financial-policy decisions remain OPEN. Candidate-content approval is not release approval.
- Required: an identifiable human independent reviewer and the financial owner; Claude/agent identities do not qualify.

## Option for the owner (needs explicit authorization; nothing done here)
Separate #313 from the four other workstreams (#314, #315 incl. ledger relocation, #316, #317): open a fresh integration branch from `main` with those four, via normal merges, leaving #313 as its own unmerged release-closed candidate PR. Avoid `git revert -m 1` of the #313 merge on #318 (it complicates a later re-merge). The four-way branch has not been verified separately.
