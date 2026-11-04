# O1 + D7 — kombinirani ugovor (Draft, neaktivirano)

Status: LOCAL_GREEN (kod + testovi), HOSTED_GREEN nije dokazan, OWNER_PENDING (OD-B1, OD-B2). Privatni `O1_SERVER_CONTRACT.md` **nije dostavljen** → NOT_VERIFIED; ovaj dokument je izvedeni ugovor iz koda.

## 1. Token (jedan primitiv za O1 i D7)
`revenue_contracts_service.document_token(field_id, project_id, scope, text)` = SHA-256( domenska oznaka ‖ field_id ‖ project_id ‖ scope ‖ **perzistirani bajtovi** ).
- `scope` = `base` ili `scenario:<id>`; token je vezan uz projekt, polje, scenarij i točne pohranjene bajtove (ne re-serijalizaciju).
- Klijent nikad ne izvodi token: poslužitelj ga vraća uz isti read koji vraća dokument (`contracts.base_token`, legacy skriveno polje `contracts_base_token`, BESS skriveno polje).
- Usporedba `hmac.compare_digest`; greška ne sadrži ništa iz tuđeg dokumenta.

## 2. O1 — PPA i BESS cijeli dokument
| Put | Gdje se provjerava | Odbijanje |
|---|---|---|
| Save All (`/v2/workbook/save-all`, `contracts_base_token`) | u istoj `BEGIN EXCLUSIVE`, nakon idempotency lookup + složenog CAS + provjere scenarija, **prije bilo koje mutacije** | 409 `CONTRACTS_BASE_TOKEN_STALE` / `CONTRACTS_BASE_TOKEN_REQUIRED`, `reload:true`, `section:"contracts"` |
| Samostalni PPA (`/v2/workbook/revenue/contracts`, polje `contracts_base_token`) | `save_contracts_in_tx` nakon CAS-a, prije mutacije | 409 `{error, code, reload:true}` |
| Legacy forma | isti ruta (skriveno polje u `revenue_contracts.html`) | isto |
| BESS (`/v2/workbook/bess/save`, opcionalni ključ `contracts_base_token`) | isti `save_contracts_in_tx` s `field_id=project_setup.bess.configuration` | 409 |
| Izravni HTTP | ista pravila (nema zaobilaznice) | isto |

- **Strogi način** `FINCO_CONTRACTS_BASE_TOKEN_REQUIRED=1` (čita se pri svakom pozivu): izostanak/prazno = odbijeno. **Zadano isključeno** dok OD-B1 nije APPROVED; poslani token se **uvijek** provjerava.
- Idempotentni replay odgovara iz ledgera **prije** CAS-a/tokena (isti `request_id` + isti kanonski sadržaj; drukčiji sadržaj = 409).
- Čisti Save All bez PPA dokumenta ne treba token čak ni u strogom načinu.
- Klijent: `DocumentSource.baseToken` se hvata zajedno s dokumentom (`PPAEditorView`), ostaje vezan uz R1 izvor, šalje se uz Save All (samo uz dokument) i samostalni PPA save. Svježi composite hash **ne** zamjenjuje token.
- Neriješeno (ostaje): O1 nije aktiviran na hostanom okruženju; ne-idempotentni retry bez ključa (D13 granica) nepromijenjen.

## 3. D7 — jedan Save All za ćelije + linije + CAPEX profil (kod, **not enabled**)
- Prekidač `FINCO_SAVE_ALL_PROFILE_ENABLED` (zadano isključeno, čita se po pozivu). Isključeno ⇒ `profile_json` se odbija **prije** transakcije (`SAVE_ALL_PROFILE_NOT_ENABLED`, 422). Trenutno dvostruko spremanje (Option A) ostaje istinito.
- Redoslijed unutar jedne `BEGIN EXCLUSIVE`: idempotency → CAS → token(i) → ćelije → ugovori → linije → **profil** → završni identitet → ledger → COMMIT.
- Profil se dokazuje vezivim protiv **završnih, nepotvrđenih** linija i ćelija preko postojećeg zajedničkog-konekcijskog šava (`db._LIFECYCLE_TRANSACTION`), ne druge konekcije.
- Token profila: isti primitiv, polje `capex_monthly_profiles`, Base scope. Tipizirano: `STALE_PROFILE_DOCUMENT` (409, `reload:true`, `section:"profile"`), `PROFILE_DOCUMENT_TOKEN_REQUIRED`.
- Svaki neuspjeh vraća sve sekcije na prethodne bajtove (ćelije, linije, ugovor, profil, hash, dirty, ledger).
- Bez F3 financiranja, bez automatskog Runa, bez dodira potpisane Run povijesti; scenariji naslijeđuju profil (scenarijski profil ostaje odbijen).
- **Nije napravljeno:** klijentsko spajanje profil-tokena u React Save All i read-echo profila (zahtijeva OD-B2).

## 4. D13
NOT implemented. Čeka Owner dodatak.
