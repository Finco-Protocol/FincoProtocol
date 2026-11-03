# PR-U2 acceptance matrix

States: `SHIPPED` (in this PR), `TESTED` (automated test in this PR passes), `LOCAL_PASS` (passes locally; skipped by CI V3 workers for lack of the
frontend toolchain), `NOT_VERIFIED`, `CONTRACT_BLOCKED_OWNER`, `BLOCKED_BY_R1`.

| # | Requirement | Solar | Wind | Data center | EV charging | Evidence |
|---|---|---|---|---|---|---|
| A1 | Import % (paste row/column, file, decimal comma, ambiguity prompt) | SHIPPED, TESTED (browser) | SHIPPED, TESTED (browser) | SHIPPED | SHIPPED | `u2_browser_role.py::test_u2_import_percent_exact_check_and_save` |
| A2 | Exact 100 % check = backend tolerance; Save blocked, Preview allowed | TESTED | TESTED | same code path | same code path | browser test + `test_u2_profile_import.py` (LOCAL_PASS) |
| A3 | Month-by-month entry | SHIPPED | SHIPPED | SHIPPED | SHIPPED | manual (screenshot) |
| A4 | Stale construction length detected, explicit fixes | SHIPPED, LOCAL_PASS (unit) | ← | ← | ← | `profileImport.test.mjs` |
| A5 | Lines → Monthly link focuses the item | SHIPPED | SHIPPED | SHIPPED | SHIPPED | NOT_VERIFIED in browser (manual) |
| A6 | User-added line: truthful "model default" | SHIPPED | SHIPPED | SHIPPED | SHIPPED | G-U2-1 `CONTRACT_BLOCKED_OWNER` |
| A7 | D13 disclosure + confirmation | SHIPPED | SHIPPED | SHIPPED | SHIPPED | `CONTRACT_BLOCKED_OWNER_Q1` for semantics |
| A8 | D13 current behaviour proved (L1–L5) | TESTED | — | — | — | `test_u2_d13_profile_lifecycle.py` (solar reference) |
| B1 | OPEX Years per saved line, independent oracle | TESTED | TESTED | TESTED | TESTED | `test_u2_opex_lines.py` |
| B2 | Group rows / totals equal the existing projection; lines reconcile | TESTED | TESTED | TESTED | TESTED | same |
| B3 | Bases apart (Year 1, used by Run) | TESTED | TESTED | — | — | same + browser |
| B4 | Technology-driver row labelled (power expenses) | — | — | TESTED | — | same |
| B5 | Owner scoping, flag off, read changes nothing | TESTED | TESTED | — | — | same |
| B6 | No business code on the surface; no horizontal overflow at 390 px | TESTED | TESTED | NOT_VERIFIED | NOT_VERIFIED | browser test |
| D7 | Two-writer no-lost-update (T1–T3) | TESTED | — | — | — | `test_u2_save_atomicity_oracle.py` |
| D7c | One combined atomic save | BLOCKED_BY_R1 | ← | ← | ← | `SAVE_ALL_ATOMICITY_CONTRACT.md` |
| G10 | All-in OPEX by year | CONTRACT_BLOCKED_OWNER | ← | ← | ← | `G10_DECISION_PACKET.md` |
| U1 | U1 browser acceptance (regression) | TESTED (local) | TESTED (local) | — | — | `u1_browser_role.py`: 10 passed; axe audit not run (no axe-core locally) |
| GOV | U2 cohort exact; older cohorts exact; tamper negatives | TESTED | | | | `test_u2_scope.py` + existing governance suites |

Verdict ceiling: `U2_IMPLEMENTED_CI_GREEN_REVIEW_PENDING`, reached only after full CI is green on the exact final head.
