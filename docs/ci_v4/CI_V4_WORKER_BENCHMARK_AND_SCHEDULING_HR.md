# CI V4 — broj workera i raspored (HR)

Oznake: **[IZMJERENO]** = stvarni GitHub run ili lokalno izvršenje; **[PROJEKCIJA]** = LPT simulacija nad izmjerenim težinama (predikcija, ne hosted dokaz). P50/P95 za CI V4 **još ne postoje** (nema dovoljno hosted uzoraka); prvi hosted RISK run je onaj na exact HEAD-u ovog pusha.

## 1. Izvor težina

`docs/ci_v4/module_weights.json` — JUnit `native.xml` svih 8 V3 workera iz runa **41782498276** (HEAD `800395fd`), artefakti 13301027713, 13301557025, 13301809315, 13302907177, 13302108520, 13302441866, 13302584009, 13302064367. **23.770 nodeova, 696 modula, 603 skipa, 23.003 s** zbroja testcase vremena (uključuje setup/teardown testa; ne uključuje checkout/instalaciju/runner overhead). Stari `tools/ci_module_weights.json` (312 modula, 2.415 s) više se ne koristi za plan.

Najteži nedjeljivi moduli: `test_model_react_rcux_goal_seek_targets_v1.py` 1.265 s, `test_model_mutation_security_successor.py` 1.217 s, `test_wf06b_scope.py` 994 s, `test_fin_v2_wf06a_scope.py` 840 s, `test_finance_integrity_governance.py` 817 s. Modul se nikad ne dijeli (izolacija DB/worktree/fixtures nije dokazana za split) → pod (floor) kritičnog puta.

## 2. V3 prije — [IZMJERENO]

| Run | Ishod | Wall | Workeri (trajanje joba) | Runner-min |
|---|---|---|---|---|
| 41659357730 (#418, d2a12b76) | PASS | **158 min** od kreiranja (17 min čekanja prije starta; w1/w2 čekali **40 min** na runner; aggregate čekao 20 min) | 8: 50,2–93,4 min | **≈ 607** (8 workera 591 + route/source/plan/aggregate/mandatory 16) |
| 41782498276 (#419, 800395fd) | FAIL (8 pravih padova) | **76,5 min** | 8: 23,4–68,9 min (JUnit 1.258–3.992 s → loš balans starih težina) | **≈ 414** |

Dodatni required checkovi na 800395fd [IZMJERENO]: browser 35,4 min, F01 17,1 min, compile 6,3 min, q4 2,2 min, governance 0,7, dependency 0,7, oracle 0,2.

Zaključak: V3 PR trošak ≈ **480–670 runner-min i 77–158 min** po pushu; red čekanja na runnere (concurrency limit organizacije) dodaje i do 60 min — više workera ≠ brže kad se PR-ovi preklapaju.

## 3. Fast — [lokalno IZMJERENO + PROJEKCIJA]

`fast_baseline` (10 modula) lokalno, jedan proces: 5,4 + 0,7 + 19,9 + 13,5 + 12,8 + 1,2 + 10,5 (CI V4 samotestovi) ≈ **64 s** testova.

| Workeri | Kritični put [PROJ] | Runner-min [PROJ] |
|---|---|---|
| **1** | **~6 min** (plan 1,5 + shard ~2,5 instalacija + ~1,1 testovi + gate ~1; `static` ~6 min paralelno) | **~12** |
| 2 | ne skraćuje (testovi < overhead jednog workera) | ~15 |

Odluka: **Fast = 1 worker** (shard), plus paralelni `static` job. 8 workera bi bilo 8× checkout+install za ~1 min testova.

## 4. RISK — [PROJEKCIJA nad izmjerenim težinama]

Primjeri selekcije (trusted policy, stvarni import-graf):

| Promjena | Modula | 1w | 2w | 4w | 6w | 8w | Izabrano |
|---|---|---|---|---|---|---|---|
| `frontend/src/app/CostWorkbench.tsx` | 25 | — | ~9 min | | | | 2 (pravilo +300 s/worker) |
| `app/auth.py` | 224 (cap ovisnih) | | | ~29 min | | | 4 |
| `financial_engine/cfads.py` | 223 | | | ~35 min | | | 4 |
| **#419 (89 putanja, governance+app+UI)** | **229** | 237 min | 120 min | **61 min** | **42 min** | **32 min** | **8** |

Runner-min za #419: 1w 237 → 8w 251 (+6 %), jer je overhead po workeru mali u odnosu na testove. Pravilo (deterministički): dodaj worker samo dok smanjuje kritični put za ≥ 300 s; cap 8. Floor: 1.217 s (mutation-security successor). RISK cilj 15–35 min za #419 je postižan **samo s 8 workera** i samo zato što #419 dira governance; običan app/engine PR je ~30–35 min s 4 workera.

Za Fast/RISK shard + F01 job rade paralelno; F01 (17 min izmjereno) nije na kritičnom putu kad je max shard > 17 min.

## 5. FULL — [PROJEKCIJA nad izmjerenim težinama]

LPT nad 23.003 s (overhead: plan 5,7 min, worker ~1 min, aggregate/mandatory ~4 min, izmjereno u V3 runovima):

| Workeri | Max shard | Kritični put | Runner-min |
|---|---|---|---|
| 4 | 95,8 min | ~107 min | ~397 |
| 6 | 63,9 min | ~75 min | ~399 |
| **8** | **47,9 min** | **~59 min** | **~401** |
| 10 | 38,3 min | ~49 min | ~403 |
| 12 | 31,9 min | ~43 min | ~405 |

V3 s 8 workera danas: 69 min najsporiji shard zbog zastarjelih težina. **Preporuka: FULL ostaje 8 workera**; svježe težine u V3 planeru (zasebna, odobrena izmjena governed `tools/ci_v3_*`) skratile bi ga ~20 min. 10/12 daju ≤10 min uz isti runner-min, ali povećavaju izloženost concurrency limitu (izmjereno čekanje 40 min) — ne preporučuje se dok se limit ne poveća.

## 6. Što nije izmjereno

* Hosted CI V4 Fast i RISK: prvi run je na exact HEAD-u ovog pusha (vidi FINAL_REPORT_HR.md).
* Kontrolirani hosted runovi za 1/2/3/4/6/8 workera nisu pokrenuti (namjerno, radi troška); tablice gore su projekcije.
* Chromium instalacija u RISK shardu (~1–2 min) procijenjena iz V3 browser joba.

## 7. Pravila v2 (nakon mergea #419) — zašto je RISK trajao 1–2 h i što je promijenjeno

**Izmjereno** (CI V4 run `41833710956`, head `ad9fce94`, 6 od 7 shardova): stvarno vrijeme 28.776 s naspram 11.113 s V3 težina za iste module (×2,6). **87 %** vremena otpada na povijesne exactness/governance module; `test_model_mutation_security_successor.py` sam 6.447 s (1,8 h, nedjeljiv), `test_fin_v2_integration_409_scope.py` 3.866 s, `test_wf06b_scope.py` 3.674 s, `test_fin_v2_wf06a_scope.py` 2.571 s. Selektor ih je povlačio kroz import-graf (svaka promjena u `app/` „ovisi“ o njima).

**Pravila v2 — dva koraka.** Trusted selektor s `main`-a (namjerno) odbija PR čija vlastita politika bira manje od bazne. Zato:
1. **Korak 1 (ovaj PR):** centralna governance provjera, izmjerene težine i nova semantika: PR s užom politikom više ne pada nego izvršava **uniju** baznog i svog plana (ništa što baza bira nije preskočeno) i označen je `head_policy_narrower`. Selekcija se u ovom koraku ne mijenja (`history_governance_proposal` je neaktivan).
2. **Korak 2 (aktivno):** `history_governance` je uključen u politici; trusted selektor iz koraka 1 tada izvrši uniju (jednom, sporije), a nakon mergea vrijedi brza selekcija.

**Pravila v2 (aktivna nakon koraka 2)** (`docs/ci_v4/ci-v4-policy.json` → `history_governance`):
* povijesni exactness/governance moduli (`tests/test_*_scope.py`, `*governance*`, `*successor*`, `tests/test_ci_v3_*`) više se **ne povlače kroz ovisnosti**; to su FULL kriteriji (nightly + release gate), izvještavaju se kao `NOT SELECTED (FULL)`;
* na **svakom PR-u** umjesto njih radi **jedna centralna provjera** `tools/ci_v4_governance_gate.py` (static job): svi registrirani kohorti exact + kompozit valjan + mutation-security inventar bez povrede; lokalno 83 s; fail closed;
* modul se ipak bira kad ga PR **sam mijenja** ili mijenja **njegov kohort-modul** (`tests/X_scope.py` → `tests/test_X_scope.py`);
* težine: 167 modula zamijenjeno izmjerenim vremenom plain-runnera iz istog runa.

**Projekcija nad izmjerenim težinama** (ne hosted dokaz):

| Vrsta PR-a | Razina | Modula | Workera | Kritični put |
|---|---|---|---|---|
| samo dokumentacija | Fast | 11 | 1 | ~7 min |
| React UX | RISK | 20 | 1 | ~13 min |
| engine / DSCR | RISK | 27 | 2 | ~10 min |
| `.github` politika | RISK | 18 | 1 | ~11 min |
| governance registar | RISK | 22 | 1 | ~12 min |
| `app/auth.py` (sigurnost) | RISK | 219 | 4 | ~27 min |
| PR koji **sam mijenja** mutation-security successor test (kao #419) | RISK | 236 | 4 | ~110 min — pod je jedan nedjeljiv modul od 1,8 h |

Preostalo ograničenje: modul `test_model_mutation_security_successor.py` (1,8 h) i dalje se izvršava kad ga PR mijenja. Ubrzanje tog modula (ili sigurno dijeljenje po nodeovima) je zaseban prijedlog; ovdje se ne mijenja nijedna asercija.

**V3 na PR-ovima** ostaje dok vlasnik u GitHub postavkama ne isključi workflow „Public Safety and Model Smoke“ i ne zamijeni obvezne checkove s `CI V4 gate` (§5a rizik-matrice) — to je jedini korak koji kod ne može napraviti.

### 7a. Ispravak: zaštita grane

Vlasnik je 2026-11-04 potvrdio: `main` **nema** branch protection ni ruleset. Ni jedna provjera (pa ni CI V3) nikad nije bila obvezna za merge; ranije formulacije „V3 ostaje required“ bile su pretpostavka. Isključivanje workflowa „Public Safety and Model Smoke“ u GitHub Actions dovoljno je da V3 nestane s PR-ova. Preporuka: ruleset za `main` koji traži `CI V4 gate`.

### 7b. Izmjereno na #420 (korak 1)

Centralna governance provjera na GitHub runneru: 5,8 min (lokalno 83 s). `test_wf06b_scope.py` sam: > 100 min na runneru (prije izmjereno 61 min uz druge module) — upravo takvi moduli s ovim korakom odlaze u FULL.
