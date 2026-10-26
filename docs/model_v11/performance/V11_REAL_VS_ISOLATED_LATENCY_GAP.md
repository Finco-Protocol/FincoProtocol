# V11 — Real staging (3–4 s) versus isolated warm HTTP (1.63 s)

**Status: PARTIAL.** The gap is largely, but not completely, explained. Nothing here was measured by running new Runs on staging.

## What the existing correlated evidence shows (S/M)
Server-side `run_stages` totals for V11 Runs on staging/production are 2.96–3.71 s (4 fully-timed Runs) and the worker `wall_s` of 68-model Solar Runs is 1.81–3.23 s (n=5, median 2.05). The browser's 3–4 s is therefore already contained in the server request time; browser and network add little to the stated figure (browser click-to-visible was not measured, U).

## Stage-by-stage view
| # | Segment | Evidence |
|---|---|---|
| 1–3 | click, network, proxy/TLS | **U** — the isolated HTTP arm used an in-process ASGI client. Logged server totals leave little room (≤0.3 s) |
| 4 | ASGI admission | **M** ≤ 13 ms (`model_entered`) |
| 5 | executor dispatch / PID selection | **M** pool round trip − worker wall = 9–10 ms; PID not logged (U) |
| 6 | native readiness + worker execution | **M** steady 1.06 s; first Run on a PID 1.94 s (n=28); prewarmed (prototype) 1.47 s |
| 7 | persistence + final CAS | **M** 0.04–0.08 s (logs 0.037–0.139 s) |
| 8 | post-Run response | **M** 0.46 s isolated (history ≈0.24 s, context ≈0.08, panel ≈0.05); live 0.22–1.26 s |
| 9–10 | transfer, DOM processing | **U** (response body 0.58 MB with lazy views, 0.80 MB without) |

## Explanation and its limits
- Live V11 Runs match the **first-call-per-executor** time (1.7–2.1 s model stage) rather than the steady 1.06 s. Supporting facts: `/proc/maps` shows 3/4 staging and 1/4 production executors have ever loaded the native libraries; each executor served ≤2 V11 Runs since the last restart. This is an inference (I), because the PID of each historical Run was not logged. An idle gap alone does not create a cold Run: a warm PID after 240 s idle ran at 0.99–1.06 s (M).
- The response stage varies with history length (≈ proportional to up to 25 stored Runs; ≈0.24 s at 25 entries here) and cold first renders, which fits the live 0.22–1.26 s range (I).
- Unexplained: live first-call Runs are 0.1–0.8 s slower than the isolated first-call Run (1.9 s); candidates are different real inputs and co-resident processes (U). Predicted from isolated pieces, a cold Run is ≈ 1.94 + 0.05 + 0.46 + 0.1 ≈ 2.6 s; live totals 3.0–3.7 s leave ≈0.4–1.1 s unattributed (honest residual).

## What would close it (needs separate approval)
Log the executor PID, native-ready flag and first-use flag in `run_stages`/`native_v1x run` lines (additive logging); capture browser Resource Timing for one Run; a staging window with no other traffic.
