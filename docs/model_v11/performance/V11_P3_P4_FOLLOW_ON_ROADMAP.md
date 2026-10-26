# V11 — P3/P4 follow-on roadmap (investigation only; nothing implemented)

Numbers: Solar, this host, from `FINCO_V11_PROFILE_RESULTS.md` and this session (M unless noted).

## P3 — response/application overhead (isolated post-Run response ≈0.46 s before P2a, ≈0.35 s after)
| Rank | Hotspot | Measured | Calls | Why | Option / upper bound (estimate) | Risk |
|---|---|---|---|---|---|---|
| 1 | Remaining History decode (8 columns × 25 entries, 5.7 MB) | ≈0.12 s | 208 loads | list view reads identity and summary only | decode lazily by column or store a summary projection; ≤ ≈0.10 s | persistence contract, fail-closed semantics must stay (separate approval) |
| 2 | `PostRunRequestContext.capture` incl. recursive `_freeze` | ≈0.076 s | 1 | immutable snapshot of workspace/projection | share read-only views; ≤ ≈0.05 s | consistency semantics; `validate_current()` must stay |
| 3 | Smart panel + insight + health | ≈0.053 s | 1 | UI | defer via lazy views; ≤ ≈0.05 s | UX |
| 4 | Debt/trust/result surfaces/overview | ≈0.05 s | — | UI | lazy sheets | UX |
| 5 | Jinja total | ≤ ≈0.04 s | 17 renders | — | little to gain | low |
`validate_current()` (second authority read, ≈0.011 s) is required and stays. Event-loop blocking by synchronous response work is a throughput finding (not measured).

## P4 — Python/engine (warm worker 1.06 s; native kernels 0.062 s)
| Rank | Hotspot (cProfile inclusive, ranking only) | Why | Option | Estimate | Governance |
|---|---|---|---|---|---|
| 1 | V11 per-evaluation glue (`_serve_plain/_serve_shl` ≈ 77 % of profiled time) | marshalling and Python-side input/output assembly around 68 evaluations | reduce conversions, reuse geometry | up to ≈0.2–0.4 s | `native_v11/stage3.py` sealed ⇒ new exact-content approval |
| 2 | Canonical fingerprints (`compute_*_fingerprint`, ≈ 17 % profiled; 151 calls) | identity evidence | cache by input identity | ≈0.1–0.3 s | identity evidence ⇒ owner approval, bit-identity |
| 3 | `run_operating_model` ×30 (≈ 12 %) | canonical Python | native or algorithmic | ≈0.1–0.2 s | engine paths protected |
| 4 | Model-input assembly ×68 (≈ 10 %) | per-evaluation rebuild | memoise | ≈0.1 s | protected |
| 5 | SHL/tax plan/geometry (≈ 15 %) | per evaluation | reuse across fixed-point iterations | ≈0.1–0.2 s | protected |
Serialization/IPC are not hotspots (≤ 10 ms). Cold-start remains the largest user-visible item and is P1.

Not recommended now: V12, infrastructure upgrade. A separate implementation PR per P4 item is warranted only after re-profiling on the approved baseline.
