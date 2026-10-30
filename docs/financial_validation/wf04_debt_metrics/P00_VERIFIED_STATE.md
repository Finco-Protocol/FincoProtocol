# WF-04 — P00 verified state (2026-10-29)

All values were read from live sources by this execution; none is inherited from a handover. Synthetic inputs only.

## Repository and pull requests

| Item | Verified value | How |
|---|---|---|
| `main` HEAD | `b76ac65c99e7fc9b486a557ae3c5ba9a711f50b3` | `git fetch origin main`; unchanged between the first and last check of this execution |
| `main` tree | `a948fd18ad74a4d8c87523900ab86c585fcc6b41` | `git rev-parse origin/main^{tree}` |
| PR #398 | MERGED 2026-10-29T08:38:08Z, normal merge; parents `b1a58681e41af9f1b4d52b176f0001725720b15c` and `99a1d9f2f7416e9959c84cb6d6e08c4d484eeeda` | GitHub PR + `git rev-list --parents` |
| CI at `main` exact head | Protocol Verification Corpus ✔, Dependency Security Audit ✔, Public Safety and Model Smoke ✔ (completed 2026-10-29T09:56:56Z) | GitHub Actions |
| PR #397 | OPEN, **DRAFT**, `mergeable_state: dirty`, head `92b3150cb04201936a34ca0dfc059ce9943e2b21`, base `b1a58681…`, 35 changed files, 0 review threads; merge-base with `main` = `b1a58681…`; `main`-only 9 commits, #397-only 7 | GitHub PR + `git fetch refs/pull/397/head` |
| WF-04 branch | `claude/new-session-w64bc1`, created from `main` `b76ac65`; #397's branch is never read-modified or pushed to | git |
| Full history | the clone started shallow (478 commits); deepened to full history (2,502 commits) because many exact-source governance checks need historical SHAs | `git fetch --unshallow` |

## Overlap with PR #397

None of the WF-04 **new** files overlaps #397's 35 files. Files WF-04 **modifies** that #397 also modifies: `app/persistence/workspace_repository.py` (hunks in different functions: #397 edits the batch-update region from line ~1391; WF-04 adds ~10 lines in `v2_atomic_run_commit`, line ~1130) — a textual merge is expected to be clean. WF-04 does **not** touch `save_all_commands.py`, `grid_router.py`, `react_workspace_router.py`, the `editing/**` UI, the Changes drawer, the idempotency ledger or `mutation_csrf.py`. The two inputs reach #397's Save All through the existing scalar-cell batch writer without any code (see `TWO_DSCR_CONTRACT_MAPPING.md` §2).
Both PRs rebuild `static/react/finco-react.{js,css}`; whichever merges second must rebuild once from the merged sources (the build is byte-reproducible: a clean build of unmodified `main` equals the committed bundle).

## Environment

Python 3.13 venv (`requirements.txt` + pytest, pytest-xdist, playwright); Node 22.22 / npm 10.9 with `npm ci` from the committed lockfile; Chromium from `/opt/pw-browsers`. Engine arm: canonical Python, `FINCO_MODEL_EXECUTION_MODE=thread`. V10/V11 native arms were **not run** (`runtime_compilation_authorized: false`).

## Inputs received

`FINCO_WF04_OWNER_APPROVED_SONNET_WITH_DEBT_METRICS_2026-10-29.zip` (SHA-256 `56a70cc37e7fff68721efa36cdc2bc9bbfbe99941c020e0e546d42b695ba3361`) containing the authorised prompt, `01_WF04_REVIEW_PACKAGE.zip` (byte-identical to the package produced earlier in this session; its 50-entry `SHA256SUMS.txt` verified 50/50), `02_DSCR_EXCEL_EOD_OWNER_V3.zip` (V3 decision; `.md` identical to `.txt`) and three private layout-reference images (viewed for layout only; **not** copied, quoted or committed).
The original XLSM workbooks are **not** in the bundle: "V3 forensic report supplied; original workbook not independently rechecked."

## Pre-existing baseline failures (not caused by WF-04)

Recorded in `WF04_ACCEPTANCE_MATRIX.md` (governance baseline of clean `main` vs this branch, same full-history clone).
