# CODE_PREPARED_NOT_FULL_PROVEN

Correction D — pripremni presjek 2026-11-17. **PERFORMANCE_TARGET_NOT_MET; P0 posao ostaje otvoren.**

Accepted main je i dalje `955952c1bc16b21ce342121c5224a19d3e105aa7`, tree `7bb70e037bae0cdef62ac3f6115d420089ad0d7d`. Ulazni PR #457 head je `775350c13d0e3ed383bfcc461e084170285424c1`, tree `e6e26af99668d6e134afbd4c20dd7bd5ac406832`. Završni SHA/tree ove izmjene i provjera bilježe se u Git objektima, PR opisu i zasebnom Correction D evidence paketu; ovaj dokument ne sadrži kružni self-hash.

## A — ispravak četiri povijesna governance testa

Na ulaznom headu sva četiri prijavljena testa iz `test_ci_v4_perf_scope.py` lokalno su reproducirala hosted padove (4 FAIL / 17.28 s). Pripremljeni ispravak proširuje samo postojeći P0-owned testni put i njegove literalne handoff/source pinove. Nema 49. kohorte: ostaju 48 registriranih kohorti, 57 source pinova i 35 nepromijenjenih predecessor pinova.

Provjera izvodi cijeli 47-cohort prefix iz izvornog BESS02 registra i literalnog nastavka te ga uspoređuje s nepromjenjivim prihvaćenim mainom. Prihvaća samo jedan P0 terminal, uz exactness svih prethodnika. Handoff očekivanje izvodi se iz starog autentificiranog literala, accepted-base bytes i P0 literalnih zamjena; disk bytes nisu izvor očekivanja.

Prva lokalna provjera izmijenjenih bytes: **4/4 izvorna testa + 8 novih adversarial slučajeva PASS (210.75 s)**. Novi negativi obuhvaćaju missing/duplicate/reordered/inserted/forged registry, pogrešan pin, krivotvorene registry bytes i krivi handoff. Svaka mutacija/restoration ulazi u novi scope. To nije konačan hosted dokaz. Puni moduli, State C/Trust i centralni gate obvezni su prije pusha.

Dodatno su četiri čiste Perf enumeracije dobile jedan vanjski read-only scope, a 13 susjednih read-only blokova spojeno je bez prijelaza preko mutacije/restorea. AST provjera potvrđuje iste assertione u istom redoslijedu, iste funkcije, argumente i parametrizacije. Prvi puni lokalni pokušaj namjerno je prekinut radi ove izmjene nakon 25 prolaza / 382.14 s; nije prikazan kao puni PASS. Cijeli paket mora se ponoviti na konačnom commitu.

Hosted ulazni run [44089140023](https://github.com/Finco-Protocol/FincoProtocol/actions/runs/44089140023): shard-0 i shard-1 PASS; shard-2 892 PASS / 4 FAIL u 2968.26 s; aggregate FAIL. Šest pratećih workflowa PASS. V5 trusted-base ostaje odvojeno blokiran; nema promocije.

## B — FULL i cilj 40 minuta nisu završeni

Stari prihvaćeni-main FULL [44047601863](https://github.com/Finco-Protocol/FincoProtocol/actions/runs/44047601863) završio je kao **FULL_TIMEOUT_AT_2656_OF_26035**: supervisor 19200 s, exit 124, record FAIL, F01 PASS. Preostalih 23379 nodeova nema konačan rezultat. Workflow creation do završetka record joba: **19295 s (321 min 35 s)**.

Reference-admission modul potrošio je 13362.6 s na dovršene slučajeve: 4434.0 / 4459.2 / 4469.4 s; četvrti je pri prekidu trajao dodatnih 3622 s. Outcome-reconciliation modul 1291.6 s. Ovo su stvarni hosted progress logovi, bez tvrdnje o punom JUnit-u.

Kandidat i dalje nema aktivan paralelni FULL controller, neovisnu autentifikaciju/extraction svih servisnih artefakata niti inventory-bound release-compatible record. Postojeći V3 route na dispatch/schedule bira sequential. P0 sadašnja zatvorena lista ne posjeduje CI/runtime entrypointove, a V4 FROZEN provjere ih izričito zamrzavaju. Zeleni governance PR ne rješava taj opseg.

Zaseban laboratorijski pokus na nepromijenjenom accepted-main izvoru mjeri postojeći call_scope oko konkretnih read-only funkcijskih poziva; ne instalira plugin u CI, ne mijenja assertione i ne predstavlja hosted FULL. Plan potrebne konačne integracije i točne barijere su u DESIGN_AND_SAFETY.md / NEXT_OWNER_ACTIONS.md te Correction D evidence paketu. Nije dokazana tehnička nemogućnost V4 sukcesije; implementacija aktivne putanje i njena neovisna provjera još nedostaju.

Nema mergea, novog PR-a, rebasea, force-pusha, reruna/cancellation starog FULL-a, promjene epoch/approvera/required checks, financijskog ili produktnog koda. Ovaj Draft nije spreman za merge kao dovršeno 40-minutno rješenje.
