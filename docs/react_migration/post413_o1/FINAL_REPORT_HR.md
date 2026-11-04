# Workstream B — završni izvještaj (Draft PR, ništa nije merge-ano ni deployano)

Oznake: `LOCAL_GREEN` / `HOSTED_GREEN` / `OWNER_PENDING`; izvori `SYNTHETIC_ONLY`, `NOT_VERIFIED`, `PASS`/`FAIL`. Nema tvrdnji o financijskoj paritetnosti.

## Stanje po fazama
| Faza | Opseg | Lokalno (disposable DB, sintetika) | Hosted | Owner |
|---|---|---|---|---|
| 1 O1 | server-izveden `contracts_base_token` (Save All, samostalni PPA, legacy, BESS, klijent, bundle) | `LOCAL_GREEN` — `test_o1_contracts_base_token` (8), `test_o1_bess_contracts_token` (3), TS editing testovi (35), `tsc` čist | nije pokrenuto | OD-B1 `PROPOSED` (strogi prekidač isključen) |
| 2 G7 | obavezan, konačan, >= 0 `amount_keur` za nove linije | `LOCAL_GREEN` — `test_g7_add_line_amount` (26) + postojeći add-line paketi | nije pokrenuto | O-G7 `PROPOSED` |
| 2 G-U2-1 | ledger-verificirani `C.NN.U###` ključevi profila | `LOCAL_GREEN` — `test_g_u2_1_generated_profile_keys` (19) + postojeći RC-7/WF-09 profil paketi (175 zajedno) | nije pokrenuto | O-G-U2-1 `PROPOSED` |
| 3 D7 | Save All: ćelije + linije + CAPEX profil, jedna transakcija, token profila | `LOCAL_GREEN` — `test_d7_save_all_profile_atomic` (18, četiri verticale, fault injection, dva pisca, replay) | nije pokrenuto | OD-B2 `PROPOSED`; kod **not enabled** (`FINCO_SAVE_ALL_PROFILE_ENABLED` isključen) |
| D13 | — | nije implementirano | — | `NOT_APPROVED` (čeka dodatak) |

Regresija lokalno: `test_save_all_atomic_v1`, `test_wf04_save_all_integration`, `test_r1_ppa_stale_document_replay`, `test_cost_batch_save_v1`, `test_model_react_rcm_capex_profile_v1`, `test_m7_bess_workflow` — **PASS** (75 + 23).

## Nalazi tijekom rada
- Sintaksa ključa profila dopuštala je završni `\n` i Unicode znamenke (`$` + `\d`); stegnuto na ASCII `fullmatch`. Ledger ih je i prije odbijao (`LEAF_UNKNOWN`).
- Dodavanje linije u kategoriju bez baznog iznosa, pa profil, pada u generičkoj izvedbi vremenskog plana (`PR9_CAPEX_WEIGHTS_SUM`). To je postojeće ograničenje, nije mijenjano.
- Ostatni rizik G-U2-1: profil čuva šifru, ne `sub_line_id` (vidi `G7_GU2_KEY_LEDGER.md`).
- Privatni `O1_SERVER_CONTRACT.md` nije dostavljen → `NOT_VERIFIED`; ugovor je izveden iz koda.

## Blokada (OWNER_PENDING / koordinacija)
**Governance composite je CRVEN na ovoj grani** (`tests/fin_v2_cohorts.valid()` = False): izmijenjeni su zaštićeni/pinirani izvori (wsv2/R1/U2 pinovi) i nova datoteke nisu u nijednom cohortu. Novi O1 cohort traži izmjenu `tests/fin_v2_cohorts.py` i `tests/u1_scope.py`, a oba (kao i svi `post413_*` moduli) su pinirana u `docs/ci_v4/SOURCE_SUCCESSOR.json`, koji ovaj tok ne smije mijenjati. Vlasnik je odabrao: **čekati merge CI V4**, pa ga ordinarnim mergeom uvesti i napraviti jedan zajednički literalni successor (O1 cohort + repin zajedničkih blobova + V4 pinovi) i jedan završni CI. Do tada: bez CI pokretanja, PR ostaje Draft, nikakav `HOSTED_GREEN` se ne tvrdi.

## Što NIJE učinjeno
Klijentsko spajanje profil-tokena u React Save All; governance successor; hosted CI; ZIP privatnih dokaza ne sadrži ništa vlasničko (nema ulaznih podataka).
