# CI normalization: before / after (measured)

Before = accepted main `707e68b290694c57b470f4a112c190abb3d02ac9`. After = Finco-Protocol/FincoProtocol#476.

| Metric | Before | After |
|---|---|---|
| Workflow files (lines) | 42 (7,220) | 3 (≈330): `model_ci.yml`, `model_known_defects.yml`, `release_gate.yml` |
| Bespoke CI tool code | 67 `tools/ci_*` + governance gate (13,586 lines) | `scripts/ci/` 5 small scripts (≈300 lines) + two conftest hooks (≈70 lines) |
| Governance test helpers + modules | 231 files (70,562 lines) active | 0 active (archived under `archive/ci_governance_2026_11/`) |
| Governance nodes inside functional modules | ≈6,400 lines in 59 modules | removed (original bytes archived) |
| **Bespoke governance code, total** | **≈97.8k lines** | **≈0.8k lines (−99 %)** |
| Required status contexts on PRs | ≈7 (V4 gate, F01, dependency audit, compile/safety, governance history, browser roles, performance budget status) + V5 `pull_request_target` gate | 1: `Model CI / required` |
| Collected pytest nodes | 26,493 (Playwright absent: browser modules skipped) | 20,621, every browser module collected and executed with real Chromium; governance nodes archived |
| Browser tests executed on PRs | 0 in V4 shards (24+ skip reports per run); only the 6 browser roles and F01 | all of them (groups 1–16) + F01 + outputs acceptance; 65 pre-existing failures (2 of them flaky on main) tracked as known defects |
| Shard abort risk on zero-node modules (FINCO33 B1) | yes (trusted node plugin, exit 4) | none (plain pytest discovery) |
| Per-PR successor / manifest / pin edits for ordinary changes | required (exact-source cohorts, tail registry) | none |
| PR wall time | ≈38–40 min, budget judge failing (shards 2,144–2,251 s > 2,040 s cap; node 1,094 s > 600 s) | ≈26 min critical path (single 1,385 s goal-seek node); other groups ≈11–19 min; static 4 min, finance 5 min |
| Unique finance controls | F01 browser 4 + native 20, oracle workbook, functional finance suites | same F01 4 + 20 (exact counts enforced), oracle workbook, all functional finance suites in the groups |
| Unique security controls | CSRF / tenancy / mutation behaviour tests + successor-gated inventories | behaviour tests unchanged; CSRF call-site inventory and financial activation flags as current-policy tests; CODEOWNERS |

Hosted runs on #476 (head SHA in each run):

* 45083207403: first run on the original layout; harness and leftover-governance failures exposed.
* 45088427832: round 2. `static`, `finance`, `boot-smoke` and `acceptance` green; 8 of 16 groups green.
* 45094080461: round 3. 13 of 16 groups green; the remaining failures are fixed in round 4.
* Final run: see `00_EXECUTIVE_VERDICT_HR.md` in the evidence package.
