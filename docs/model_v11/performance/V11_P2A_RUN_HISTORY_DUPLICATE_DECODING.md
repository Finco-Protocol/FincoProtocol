# V11 P2a — Run History duplicate JSON decoding

**Classification: AUTHORIZED_AND_SAFE → implemented.**
Source: `app/persistence/run_history_repository.py`, blob `a943ff61…` (identical at `main` 8944aca3 and staging SHA 93c549e1) → `98645761…`. No governance pin on this blob was found (`v10`/`v11` successor modules, trust-readiness pins and rc2/rc3 manifests reference the *path* in negative or scope tests only). New test: `tests/test_v11_p2a_run_history_single_decode.py`, blob `c69f97dd…`.

## Confirmed finding (S + M)
`_decode_entry` validated each of the eight object columns with `_load()` and then called `_load()` again for each column when building `RunHistoryEntry`: 16 parses plus one separate `last_runtime_identity_json` parse = **17 `json.loads` per entry** (counted: 425 for 25 entries).

## Change
The validation loop keeps the decoded object in a local dict and the entry is built from it (`objects[column]`). Order of checks, first-failure semantics, the `RUN_HISTORY_PAYLOAD_MALFORMED` messages, the identity decode/validation, required-column and non-empty checks, ordering/scoping/immutability are untouched. No cache, schema, index or projection was added. Result: **9 loads per entry** (8 + identity; 8 when the identity is NULL).

## The "≈566 loads" (M)
Counting every `json.loads` during one `build_coherent_post_run_ui_state` replay on `main` with a 26-row history: 634 loads / 12.57 MB. History accounts for 416 object-column loads + 26 identity loads (11.7 MB, 91 % of bytes). Others: 69 `itsdangerous` cookie payloads (8 KB), 62 CAPEX sub-line rows (13 KB), 56 workspace `_from_json` (550 KB), 5 identity/config. So the double decode explains the 208 *extra* history loads; the remaining 208 history loads (5.7 MB) are single decodes of columns the list view does not display (a separate finding → P3, not changed here). After P2a: 426 loads, 6.67 MB.

## Tests (all synthetic, disposable DB)
Old-vs-new equivalence on 0/1/10/25/55 entries incl. NULL/V2-bound identities and 300 KB × 8 payloads; `json.loads` call counts (17 legacy vs 9 new; 225 for a 25-entry listing; 9 for the latest entry); each of 8 columns × 7 corrupt values (invalid JSON, arrays, string, number, true, null, empty) fails closed with the *same message* as the verbatim legacy decoder; NULL via a foreign mapping row; multi-corruption first-failure order; invalid identity documents; missing required column; empty required text fields; newest-first order with `history_id` tie-break; user/project scoping; read-only listing (rows byte-identical, count unchanged); concurrent append during listing. The three call-count tests fail on the old decoder (verified). Existing `tests/test_model_v2_run_history.py` and 6 related modules: 275 passed (4 m 57 s).

## Measured effect (base = `main`, candidate = P2a; 2 interleaved rounds; 60-row history of one real Solar Run payload, 227 KB JSON per row, newest 25 read; n=50 per metric; ms median / p95)
| Metric | Base r1 | P2a r1 | Base r2 | P2a r2 |
|---|---|---|---|---|
| `json.loads` per entry | 17 | 9 | 17 | 9 |
| `get_run_history(limit=25)` | 254.7 / 312.2 | 140.1 / 172.1 | 236.3 / 303.3 | 126.1 / 155.6 |
| decoder only, 25 rows | 243.6 / 334.5 | 123.6 / 141.9 | 228.1 / 277.0 | 112.6 / 129.9 |
| one entry | 9.44 / 12.54 | 5.07 / 6.67 | 9.23 / 11.59 | 4.82 / 5.94 |
| post-Run history fragment (`_build_run_history_oob`) | 240.7 / 279.2 | 137.2 / 157.3 | 237.9 / 266.5 | 135.7 / 171.5 |
| `GET /v2/workbook/run-history` (n=25) | 253.7 / 284.0 | 160.0 / 240.5 | 243.1 / 280.8 | 148.8 / 168.3 |
≈ −43 to −47 % of history decoding; ≈ −0.10 s on the post-Run response (not the whole 0.23–0.25 s: the single remaining decode of eight columns still costs ≈0.12 s). Full-response replay (single sample): 449 → 315 ms. CPU ≈ wall (single thread). Raw: `data/p2a_*.json`.

## D-029 / shared-file note
`run_history_repository.py` is **not** in PR #383 or #384 changed-file lists (checked live; #384 adds `run_intent_repository.py`/`run_intent_service.py`). Recheck before merge.
