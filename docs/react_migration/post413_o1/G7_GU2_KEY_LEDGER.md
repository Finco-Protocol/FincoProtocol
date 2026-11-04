# G7 i G-U2-1 — pravila i ledger ključeva (Draft)

## G7 — nova CAPEX/OPEX linija
`add_capex_line` / `add_opex_line` (rute `/v2/capex/line/add`, `/v2/opex/line/add`): `amount_keur` je **obavezan** (nedostaje/prazno ≠ 0), **konačan**, **>= 0**; izričita `0` dopuštena; negativ, NaN, ±Inf, tekst, Unicode znamenke, prelijevanje → tipizirani 422 **prije** transakcije (nula promjena u bazi). Preciznost kEUR nepromijenjena (parsiranje isto). Ažuriranje postojećih linija zadržava dosadašnje pravilo (samo konačno) — povijesne vrijednosti se ne prepisuju.

## G-U2-1 — generirani ključevi profila `C.NN.U###`
Sintaksa: `fullmatch`, samo ASCII (nema završnog `\n`, nema Unicode znamenki). **Sintaksa nikad nije dovoljna.** Ključ vrijedi samo ako:
| Provjera | Gdje | Rezultat inače |
|---|---|---|
| ključ imenuje **aktivni** redak u `capex_sub_lines` **ovog projekta** (učitano po `project_id`) | `runtime.bind_inputs` (Save i Run) | `CAPEX_PROFILE_LEAF_UNKNOWN` (typo, tuđi projekt/tenant, povučena, hard-deleted) |
| `NN` ključa = kategorija u koju ga ledger sprema (`CAPEX_CATEGORY_TO_FIELD`) | `_verify_generated_keys` | `CAPEX_PROFILE_LEAF_CATEGORY_MISMATCH` |
| povijesni ključevi (`C.NN.NN`, `base:*`) | nepromijenjeni | — |
Težine: broj = broj mjeseci gradnje, konačne, ne-negativne, zbroj 100 % (`contract.build_weights`, nepromijenjeno); zadani end-of-period ostaje. Scenarijski profil ostaje odbijen. Nativne formule motora nisu dirane.

**Ostatni rizik (NOT_VERIFIED / OWNER_PENDING):** dokument čuva šifru, ne `sub_line_id`. Aplikacija nema hard-delete puta i brojač šifara preskače sve postojeće (i povučene) retke, ali ručno hard-delete-an redak najviše šifre može biti ponovno dodijeljen drugoj liniji i profil bi se vezao uz nju. Zatvaranje traži perzistiranje `sub_line_id` u dokumentu (promjena perzistirane sheme → posebna Financial Owner odluka).
