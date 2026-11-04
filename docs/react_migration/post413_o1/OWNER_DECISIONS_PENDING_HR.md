# Workstream B — Owner decisions (PENDING, nijedna nije odobrena ovim PR-om)

Status: **DRAFT PR, ništa nije merge-ano niti deployano.** Svaka odluka je zasebna i ima vlastiti status.

| ID | Odluka | Status | Što kod radi dok je odluka neodobrena |
|---|---|---|---|
| OD-B1 | **O1 strogi `contracts_base_token`** (server traži token uz svaki zapis cijelog PPA/BESS dokumenta) | **PROPOSED** | Token se izdaje i **uvijek provjerava kad je poslan**; izostanak tokena je dopušten (lenient) dok je `FINCO_CONTRACTS_BASE_TOKEN_REQUIRED` isključen (zadano). Uključivanje prekidača = aktivacija odluke OD-B1. |
| O-G7 | **G7** — nova CAPEX/OPEX linija mora imati `amount_keur` (obavezan, konačan, >= 0; izričita 0 dopuštena; negativ odbijen) | **PROPOSED** | Kod je u PR-u (tipizirani 422, nula promjena u bazi). Mijenja ponašanje klijenata koji su izostavljali iznos (do sada = 0). Ne dira ažuriranje postojećih linija. |
| O-G-U2-1 | **G-U2-1** — generirani ključevi `C.NN.U###` smiju vlasnika profila samo ako postoje u ledgeru aktivnih linija tog projekta | **PROPOSED** | Kod je u PR-u. Ne mijenja nijedan postojeći ključ ni dokument, ne dira nativne formule. **Ostatni rizik:** profil čuva samo šifru, ne `sub_line_id`; ponovna dodjela iste šifre nakon ručnog hard-delete retka ne može se razlikovati bez promjene perzistirane sheme (odvojena odluka). |
| OD-B2 | **D7** — jedan Save All piše linije + šest OPEX baznih ćelija + CAPEX profile dokument atomarno | **PROPOSED** | Ako se implementira, kod je isporučen **"not enabled"** (zastavica isključena); trenutni dvostruki Save (Option A) ostaje istinit i dokumentiran. |
| D13 | Profil lifecycle / Run vezanje | **NOT_APPROVED** — nije implementirano | Čeka odvojeni Owner dodatak. |

Svaka promjena potpisane ekonomike Runa, perzistirane sheme ili wire ugovora treba zasebnu izričitu Financial Owner odluku prije merge-a/deploya.
