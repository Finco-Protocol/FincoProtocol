# D7 — decision packet

Status: `CONTRACT_BLOCKED_R1_OR_FINANCIAL_AUTHORITY`.

Question: should one Save commit CAPEX/OPEX line edits and the CAPEX monthly profile atomically?

| Option | What changes | Risk | Prerequisite |
|---|---|---|---|
| A — keep two saves (today) | nothing | the user can leave one of the two unsaved. Mitigated by two labelled Save buttons and the dirty indicators | none |
| B — add a `capex_profile` section to Save All | `SaveAllInput`, canonical body, Changes drawer, `saveAll.ts` | touches the R1-owned wire and the idempotency body | R1 merged and validated, plus an owner sign-off on the request-contract change |
| C — profile save also carries pending line edits | the profile route gets a lines section | duplicates Save All logic in a second writer | not recommended |

Recommendation: A now, B after R1 merges, using the design and oracle in `SAVE_ALL_ATOMICITY_CONTRACT.md`. The no-lost-update property holds today
(T1–T3).
