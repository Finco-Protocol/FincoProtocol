# V11 P1 (V2) — native readiness at worker start: evidence and BLOCKER

**Status: NOT part of this PR.** The change was implemented, tested and measured, but it cannot pass the existing V11 activation-surface guard without a change to a protected governance file that the Financial Owner has not authorized. The patch and its evidence are preserved here so the decision can be made on facts. Evidence legend: **MEASURED / INFERRED / UNMEASURED**.

## 1. Where the first-Run cost is (MEASURED)
Existing Runtime V2 prewarm imports the Python engine graph only. The first Run in a fresh worker pays, once per process, the V10 stage 1/2 and V11 stage 3 loaders: library `dlopen`, ABI/layout, build ID, SHA-256 of artifact and approved manifest, and the canonical-source authentication (`provenance.authenticate*`). Measured inside prewarmed workers (stage 1 0.187 s, stage 2 0.024 s, stage 3 0.154 s; ≈0.4 s per worker).

## 2. The change (preserved as `data/p1_native_prewarm_v2.patch.txt`)
Worker initializer calls only the existing public loaders `get_native`, `get_stage2`, `get_stage3` for the stages the Run-time settings enable (modes, kill switches read exactly as `native_activation` reads them); records readiness per confirmed PID; state `complete` only if every confirmed PID reported every configured stage; evicts only *failed* loader-cache entries so the first Run retries as before; `FINCO_MODEL_EXECUTION_NATIVE_PREWARM=off` disables it; no project executed; per-Run admission unchanged. Tests: `data/test_p1_native_prewarm.py.txt` (13 tests incl. real workers, replacement workers, kill switch, pin mismatch, failure never reported complete).

## 3. Benchmark (MEASURED; this host, NOT the VPS)
Host: Intel Xeon family 6 model 85 @2.8 GHz, KVM, 4 vCPU, CPython 3.12.3 + CI pins, kernels rebuilt bit-identical to the committed manifests, V10 stage 1+2 and V11 on, executor concurrency 2, spawn pool. 10 pool lifecycles per variant and asset, variants alternated, first Run on each of the 2 new PIDs (n = 20 per variant), 4 later warm Runs (n = 40), then a cold replacement pool. Paired by lifecycle; 95 % bootstrap CI. Raw: `data/bench_{solar,wind,dc,ev}.json`, analysis `data/p1_analyze.py.txt`.

| Asset | first Run per new PID: off → on (median) | paired Δ | warm Run Δ | startup Δ | replacement-pool first Run Δ | RSS/worker | native counters |
|---|---|---|---|---|---|---|---|
| Solar | 0.827 → 0.632 s | **−0.193 s** (−0.219…−0.167; 10/10) | +0.011 s (−0.013…+0.019) | +0.169 s | −0.225 s | +2.4 MB | 68 / 139, 0 declines |
| Wind | 1.130 → 0.894 s | **−0.201 s** (−0.301…−0.157; 10/10) | +0.028 s (−0.035…+0.053) | +0.227 s | −0.303 s | +2.4 MB | 82 / 164 |
| Data Center | 0.748 → 0.567 s | **−0.200 s** (−0.263…−0.151; 10/10) | +0.007 s (−0.014…+0.027) | +0.218 s | −0.251 s | +2.4 MB | 44 / 90 |
| EV | 0.856 → 0.668 s | **−0.171 s** (−0.248…−0.154; 10/10) | +0.024 s (−0.007…+0.054) | +0.204 s | −0.320 s | +2.4 MB | 68 / 139 |
Worker CPU at readiness +0.2 s. No warm-Run difference distinguishable from zero; no admission outcome changed; no leaked admission slots.

Against the stop/go gate (≥ 0.25 s per new PID, preferred): **0.17–0.20 s on this host**. This host runs the same Solar engine ≈1.9× faster than the Zen 1 VPS, and the earlier V11 prototype measured −0.46 s there; scaling gives **≈0.32–0.37 s on the VPS (INFERRED)**. **VPS measurement: UNMEASURED** — the session has no SSH client or credentials, so none of the requested VPS items (CPU model, worker/executor counts, host memory, deployed SHAs, VPS cold/warm behaviour, oversubscription) could be collected. HTTP click-to-result with and without P1: **UNMEASURED**.

## 4. BLOCKER (exact finding)
With P1 applied, `tests/v11_stage3_successor.py::v11_violations()` reports `V11_STAGE3_ACTIVATION_SURFACE: ['app/runtime/model_execution.py']` (30 governance tests fail, none on `main` or on the P0-only head). The guard rejects any file under `app/`, `main_web.py`, `deploy/`, `.github/`, `tools/` whose text mentions `native_v11`, `Stage3Config` or `stage3_run`, other than the five paths released by `tests/v11_stage3_release_authority.py`. P1 must call the V11 stage 3 loader, so it needs one of: (a) a reviewed successor that adds `app/runtime/model_execution.py` to the released surface (edits `tests/v11_stage3_release_authority.py` and its record, outside the authorization given), or (b) an owner decision to prewarm V10 stage 1/2 only (≈ half the benefit; stage 3 is 0.154 s of 0.4 s). Dodging the string match (indirect import names) was rejected as circumvention of a security control.

Requested decision: authorize the exact paths for (a), or accept (b), or drop P1. P0 is independent and complete.
