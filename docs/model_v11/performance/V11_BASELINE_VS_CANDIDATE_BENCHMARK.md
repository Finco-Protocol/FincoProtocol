# V11 — Baseline versus candidate

Baseline = `main` 8944aca3. Candidate (P2a) = branch `perf/v11-p2a-run-history-single-decode`. P1 = prototype only (gated). Host: 4 vCPU KVM (AMD EPYC Zen 1), same host and Python 3.12.3 for all rows, `nice 10`, one benchmark at a time, background services untouched. Inputs: synthetic Solar (`generic_solar_reference`, 64 MW). Cache-miss for every Run. Scripts and raw data: `data/`.

| Metric | Baseline | Candidate | Improvement | n / method |
|---|---|---|---|---|
| JSON loads per history entry | 17 | 9 | −47 % | counted, 25-entry listing 425 → 225 |
| History listing `get_run_history(25)` p50 / p95 | 254.7 / 312 ms (r1), 236.3 / 303 (r2) | 140.1 / 172 (r1), 126.1 / 156 (r2) | −45 % / −47 % | 50 per round, 2 interleaved rounds |
| Single-entry decode p50 | 9.44 / 9.23 ms | 5.07 / 4.82 ms | −46 % / −48 % | 200 per round |
| Post-Run history fragment p50 / p95 | 240.7 / 279 ms; 237.9 / 266 | 137.2 / 157; 135.7 / 172 | −43 % | 50 per round |
| Whole post-Run response replay (26 rows, one sample) | 449 ms | 315 ms | −30 % | 1 (indicative) |
| Warm Solar HTTP p50/p95 | **NOT MEASURED** on `main` (only the history component and a replay were re-measured). Earlier same-host figures at staging SHA 93c549e1 (pre-SEC): 1.631 / 1.873 s, n=20 | NOT MEASURED | expected ≈ −0.10 s from the history fragment | — |
| Warm Wind HTTP p50/p95 | NOT MEASURED on `main` (earlier: 2.045 / 2.291 s) | NOT MEASURED | expected ≈ −0.10 s | — |
| First native Run per PID p50 / p95 | 1.935 / 2.156 s | P1 prototype 1.473 / 1.701 s | −0.46 s (−24 %) | 28 per variant (prototype, not in PR) |
| Worker prewarm duration | 1.594 s | P1 prototype 2.037 s | +0.44 s | 14 per variant |
| Startup memory per executor | 93.5 MB | P1 prototype 97.8 MB | +4.3 MB | 28 per variant |
| Warm worker Run | 1.057 s | P1 prototype 1.069 s | none | 28 |
| Run after idle (240 s) on warm PID | 0.99–1.06 s (earlier session, n=3) | — | no idle penalty | — |
| Run after worker replacement | 2.70 s | 2.61 s (prototype; replacement not prewarmed) | none | 14 |

Interpretation: P2a measurably removes half of the history decoding; it does not remove the whole Run History cost (the other eight columns are still decoded). P1's value is the cold-PID Run, not the warm median; the prototype does not alter warm Runs.
