# D7 — one atomic save of lines and the CAPEX profile: design and oracle

Status: `CONTRACT_BLOCKED_R1_OR_FINANCIAL_AUTHORITY`. Save All is not changed by U2 (mandatory addendum); the parallel R1 PR owns its wire.

## Today (proved by `tests/test_u2_save_atomicity_oracle.py`)
| Writer | Transaction | CAS | Scope |
|---|---|---|---|
| Save All (`POST /v2/workbook/save-all`) | one `BEGIN EXCLUSIVE` | one composite hash (`check_identity_in_tx`) + scenario id; idempotent by request id | cells, PPA contracts, CAPEX/OPEX lines |
| Save profile (`POST /v2/capex/spending-profiles/save`) | own transaction | composite hash + scenario id | the one document `capex_monthly_profiles_json` |

* T1: a profile save on a hash older than a committed Save All is refused (`CAPEX_PROFILE_STALE`), and nothing changes.
* T2: a Save All on a hash older than a committed profile save is refused (stale identity), and nothing changes.
* T3: two fresh sequential writes both persist.

So there is no lost update in either order. "Save both" is two commits, each atomic, and a crash between them leaves a consistent state (one saved,
one dirty).

## Proposed combined save (for R1 / Financial authority to accept)
1. Add an optional `capex_profile` section to `SaveAllInput` holding the full document (no patch), validated by `config.parse` and bound by
   `binding.materialize` inside the same exclusive transaction, after the cost-line section (so leaves reflect the new lines).
2. The same single composite CAS covers every section. There is no second token and no `contracts_base_token`.
3. Any section failure rolls back every section, the hash, the dirty flag and the idempotency ledger. This is the existing Save All rule, extended to
   one more section.
4. The canonical body and idempotency key include the document bytes.
5. The separate profile route stays for the Studio's own Save, with an unchanged contract.

## Oracle for the combined save (to be written with the implementation)
* C1: lines + profile in one request → both persisted, one hash change, one ledger row.
* C2: a valid line edit + an invalid profile (sum 99 %) → nothing persisted (lines unchanged).
* C3: a profile naming a line retired in the SAME request → refused; nothing persisted.
* C4: a replay with the same request id → identical result, no second write.
* C5: T1–T3 still hold between the combined save and the standalone profile route.

## Why blocked
The Save All wire, `saveAll.ts`, `pendingEdits.ts` and `ChangesProvider.tsx` are R1-owned while R1 (the PPA lost update after a stale 409) is open.
Adding a section changes the persisted request contract and needs R1 merged and validated first.
