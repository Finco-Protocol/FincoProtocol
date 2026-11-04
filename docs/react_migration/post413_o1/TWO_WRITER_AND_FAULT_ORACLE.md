# Two-writer i fault-injection oracle (Draft)

Sintetički, disposable DB; bez Runa; nijedan test ne tvrdi financijsku paritetnost.

| Scenarij | Test | Očekivano |
|---|---|---|
| A i B, B sprema PPA H2; A osvježi composite hash ali drži H1 dokument → Save All | `test_o1_contracts_base_token` | 409 `CONTRACTS_BASE_TOKEN_STALE`, H2 bajtovi nepromijenjeni, nema ledger/povijest redaka |
| isto, samostalni PPA / legacy | isti | 409 typed |
| lažni / prazan / izostali token, strogi način | isti | 409 `…REQUIRED` / `…STALE` |
| token drugog projekta, drugog scenarija, drugog polja | isti | odbijeno (token vezan) |
| replay istog `request_id` | isti | pohranjeni ishod, bez novog zapisa |
| BESS A/B | `test_o1_bess_contracts_token` | 409, bajtovi nepromijenjeni; shema forme ostaje zatvorena |
| D7 A/B profil (svježi composite, stari profil-token) | `test_d7_save_all_profile_atomic` | 409 `STALE_PROFILE_DOCUMENT`, ni ćelije ni linije A-a nisu primijenjene |
| D7 neuvezivi profil | isti | 422 `section:"profile"`, sve sekcije bajt-identične prije/poslije |
| D7 fault nakon linija / nakon profila (`finalize`) | isti | 500, prethodni bajtovi svih sekcija vraćeni, prethodni profil vraćen |
| D7 četiri verticale (Solar, Wind, Data Center, EV) | isti, parametrizirano | commit zajedno, token rotira, povijest Runa nepromijenjena |
| D7 isključen prekidač | isti | 422 prije transakcije |
| D7 replay / tuđi korisnik | isti | stored outcome / 403-404 |
