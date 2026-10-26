# V11 P0 — Evidence reconciliation

Legend: **M** directly measured in this session · **S** source verified · **R** agent-reported earlier, raw data available and statistics recomputed here · **I** inferred · **U** unmeasured.

## Evidence availability
| Item | State |
|---|---|
| `FINCO_V11_PERFORMANCE_ANALYSIS_2026-10-26.md`, `…MAIN_AGENT_PROMPT…`, `…MAIN_AGENT_HANDOFF…` | **Not present on this host.** Not used. |
| `FINCO_V11_SAME_HOST_BENCHMARK.md`, `…PROFILE_RESULTS.md`, `…OPTIMIZATION_ROADMAP.md` and `v11_bench_data/` (raw `abc_*`, `exec_*`, `http_*`, `profile_*`, `cprofile_*`, `monitor.log`) | Present (`/root/.openclaw/workspace`). Produced earlier by this same agent family; they are not independent. Headline statistics were **recomputed from the raw observations** (below). |
| Raw per-Run staging journal lines | Present in `journalctl` (web-worker PID only; executor PID is not logged). |
| Browser click-to-visible timings | **Not available.** |

Recomputed from raw arrays (Solar, seconds; n=20 unless noted): in-process A 3.671 / B 2.111 / C 1.082 (p95 4.106 / 2.273 / 1.196); process pool A 3.669, B 2.128 (n=14, 6 memo hits excluded), C 1.084; HTTP C total 1.631 (p95 1.873), model 1.079, response 0.463. Wind: C 1.278 (in-process), 1.263 (pool), HTTP total 2.045. All agree with the earlier report to ±0.001 s. Cold and warm populations and memo hits were never mixed (first calls reported separately; memo-hit samples excluded).

## Findings table
| Finding | Status | Evidence |
|---|---|---|
| V11 faster than V10 on the same VPS (≈1.95× Solar, 2.06× Wind) | **Confirmed (R, recomputed)** | in-process 2.111→1.082, 2.633→1.278; identical result digests across arms |
| First native use per executor PID costs ≈ +0.5–0.6 s | **Confirmed (M)** | this session, 28 first-per-PID runs: median 1.935 s vs 1.057 s later runs (prewarm of Python modules only) |
| Native libraries not preloaded by the existing probe | **Confirmed (S)** | `_worker_warmup_probe` imports Python modules only |
| Native kernel compute ≈6 % of a warm worker | **Confirmed (R)** | wrappers around the three ctypes entry points: 62 ms of 1.012 s (Solar) |
| Duplicate JSON decoding in `_decode_entry` | **Confirmed (S, M)** | 17 `json.loads` per entry on `main`; now 9 |
| Run History is ≈0.23–0.25 s of the response | **Confirmed (M, this session)** | `_build_run_history_oob` 240 ms (base) vs 136 ms (P2a) on a real-size 25-entry history |
| The "≈566 loads" figure | **Explained (M)** | whole post-Run response on `main`: 634 loads, 12.57 MB; 416 object-column + 26 identity loads (≈11.7 MB, 91 % of bytes) come from history; 69 itsdangerous cookie, 62 capex sub-lines, 56 workspace `_from_json` (550 KB) are the rest |
| Isolated residual A (≈0.3–0.4 s) | **Partial** | it is the difference between live first-call Runs and the isolated first-call measurement. Part is covered by P1 (first call 1.935→1.473 s in this session's prototype). The remaining ≈0.4 s first-call premium after prewarm (1.473 vs 1.069) is lazy imports/caches outside the native libraries (I) |
| Real staging 3–4 s (residual B) | **Partial / unverified end to end** | see `V11_REAL_VS_ISOLATED_LATENCY_GAP.md` |

## Measurement reconstruction
Hardware: 4 vCPU KVM guest, AMD EPYC family 17h (Zen 1), no CPU quota, steal 0 (S/M). Topology: staging = 2 Uvicorn workers × 2 spawned executors; production on the same VPS has the same shape (S/M). Native state is visible per executor in `/proc/<pid>/maps`: on 2026-10-26 three of four staging executors and one of four production executors had loaded the native libraries (M). Executor PID is not logged, so a given historical Run cannot be assigned to a cold or warm PID (U). `nice 19` was applied to every benchmark process; host load stayed ≤1.8 (M).

## Limits
Synthetic projects; one host and one session; the PR #360 harness is not in the repository; hypervisor-level contention is invisible from the guest. No claim of fully reproduced VPS performance is made.
