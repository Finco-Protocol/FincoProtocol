# PR-U2 open gaps

| Id | Gap | Status | Next step |
|---|---|---|---|
| G-U2-1 | Profiles for user-added lines (`C.NN.U###`): the document key regex rejects them, although the projection lists them as eligible | `CONTRACT_BLOCKED_OWNER` | a persisted-schema successor that widens `config._KEY`, plus binding tests |
| D13-Q1 | Dormant vs refused profile of a retired line | `CONTRACT_BLOCKED_OWNER_Q1` | owner answer, then `D13_PROFILE_LIFECYCLE_CONTRACT.md` |
| D7 | One atomic save of lines + profile | `BLOCKED_BY_R1` | after R1 merges: `SAVE_ALL_ATOMICITY_CONTRACT.md` option B |
| G-2 / D8 | No project-wide OPEX escalation input | `CONTRACT_BLOCKED_OWNER` | owner decides whether such an input exists |
| G-10 | All-in OPEX by year | `CONTRACT_BLOCKED_OWNER` | `G10_DECISION_PACKET.md` |
| G-7 | Add-line routes accept a missing amount (defaults to 0) and negative amounts | `NOT_VERIFIED` (open) | a router successor: the routes are pinned by `tests/model_mutation_security_successor.py`; the UI requires an amount today |
| G-3 | Unused `InputStudios.tsx` / `CostSummaries` kept | open | own successor for deletion |
| G-8 | COD / duration still editable in the Assumptions grid and the timing planner | kept | follow-up; Project & Timeline stays canonical |
| G-9 | Excel numeric parity and live (staging) app acceptance | `NOT_VERIFIED` | separate gates; U2 has local real-Chromium acceptance only |
| T-1 | The `.mjs` unit suite and the client/server oracle run only where `frontend/node_modules` exists. CI V3 Python workers do not run `npm ci`, so in CI these tests skip | `LOCAL_PASS` | CI workflow change is out of scope (no workflow edits) |
