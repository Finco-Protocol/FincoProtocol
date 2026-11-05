# CI V4 — dijeljenje teških modula po pytest node ID-u (Correction A, PR-A)

Oznake: **[IZMJERENO]** = autentificirani GitHub artefakt (SHA-256 zip-a = digest iz GitHub API-ja) ili lokalno izvršenje; **[PROJEKCIJA]** = LPT nad
izmjerenim težinama; **[CENZURIRANO]** = prekinut uzorak (nije završeno trajanje).

## 1. Dijagnoza (#421, run 41912154663, HEAD `113aca38`)

* Plan (trusted base selektor): RISK, 233 modula, 4 workera, predviđeni kritični put 3.854 s. Shard-0 = **samo** `tests/test_wf06b_scope.py`.
* Shard-0: **[CENZURIRANO]** — GitHub anotacija „The job has exceeded the maximum execution time of 2h30m0s“ (`timeout-minutes: 150`);
  korak testova 21:02:44 → 23:32:25 (≥ 8.981 s), artefakt nije učitan. API zaključak je `cancelled`, uzrok je timeout (nije ručno otkazano).
* Ostali shardovi: SUCCESS (44–77 min). Najteži moduli **[IZMJERENO]**: `test_rcux_governance` 2.169 s / 41 node, `test_post413_o1_scope` 474 s / 54,
  `test_u2_scope` 456 s / 76, `test_u1_scope` 388 s / 100.
* #421 je mergan unatoč crvenom gateu jer `main` **nema zaštitu grane ni ruleseta** (API: `protected: false`, `required_status_checks.contexts: []`,
  `rules/branches/main: []`). Zaštita nije mijenjana.
* Pohranjena težina `test_wf06b_scope.py` = 3.673,631 s (V4 run 41833710956, #419). Završeni V4 uzorak **[IZMJERENO]**: run 41856777361 (#420,
  `9e7746f9`): **8.197 s**, 108 node, svi PASS.

### Glavni nalaz: nedjeljivi pod (floor)

| Node | Vrijeme (#420) | Udio |
|---|---|---|
| `test_no_path_outside_the_superseded_set_is_ever_admitted_by_supersession` | **6.718 s** | 82 % |
| `test_matches_accepts_exactly_the_successor_bytes_and_the_historical_pin` (2) | 1.152 s | 14 % |
| ostalih 105 nodeova | 327 s | 4 % |

Uzrok **[IZMJERENO lokalno]**: taj test zove `D.matches(path, raw + b"\n")` za 120 putanja; jedan poziv izvodi cijelu kompozitnu validaciju
(**3.255 git poziva, 24 s lokalno**), jer `matches()` provjerava `valid()` prije usporedbe bloba. 120 × 24 s ≈ 48 min lokalno, ≈ 6.700 s na runneru.
**Dijeljenje po nodeovima ne može skratiti taj jedan node.** Za #421-tip PR-a kritični put ostaje ≈ 1 h 55 min + overhead i nakon dijeljenja.
Stvarno rješenje poda je izmjena governance testa/kohorte (vidi §6, zasebna odluka vlasnika) — ovaj PR je ne radi.

## 2. Što PR-A implementira (CI-only)

* `tools/ci_v4_nodes.py` — pytest plugin (`-p tools.ci_v4_nodes`, inertan bez env varijabli): kolekcija stvarnih `item.nodeid` (redoslijed + SHA-256),
  dodjela po nodeovima (prije izvršenja puna kolekcija split modula mora biti identična inventaru, inače `UsageError`, nijedan test ne krene),
  evidencija po nodeu (faze, ishod, trajanje, exit status, profil pluginova/conftesta). CLI: `collect`, `plan` (shadow), `calibrate`.
* `tools/ci_v4_schedule.py` — `apply_node_split`: nakon selekcije, samo za module iz zatvorenog allowlista; LPT nodeova u dijelove (unutar dijela
  izvorni redoslijed), node teži od cilja dobiva vlastiti dio; zatim LPT jedinica s istim pravilom broja workera (+1 worker samo ako štedi ≥ 300 s, cap 8).
  Selekcija (`pytest_modules`, tier, suiteovi) se ne mijenja. Kad je politika isključena, plan je **isti objekt** (bez promjene).
* `tools/ci_v4_shard.py` — plan po modulima radi kao prije (bez plugina); plan po nodeovima: cijeli moduli + točni nodeovi u jednom pytest procesu,
  evidencija `nodes-shard-N.json`. `--tmp disk|auto|tmpfs` (default `disk` = nepromijenjeno; `auto` = privatni direktorij na `/dev/shm` ako postoji,
  upisiv i ≥ 2 GiB slobodno, inače disk; izbor se bilježi).
* `tools/ci_v4_aggregate.py` — za plan po nodeovima `verify_node_split`: **neovisna re-kolekcija** (drugi job, nakon shardova) = planirani inventar
  (ids, digest, profil); izvršeni nodeovi = **disjunktna unija** jednaka kolekciji (nema missing / duplicate / foreign / misassigned); JUnit
  (pytestova vlastita `classname`/`name` derivacija) 1:1 s evidencijom i ishodom; evidencija potpuna, vezana uz plan/SHA/tree/shard, isti profil i
  exit status kao zapis sharda. Plan po modulima: postojeća logika i negativi nepromijenjeni.
* `docs/ci_v4/node_split_policy.json` — `enabled_in_required_pr_gate: false`; allowlist s presudom i dokazom izolacije.
* `docs/ci_v4/node_weights.json` — izmjerena vremena po nodeu s provenijencijom (run, SHA, artefakt, SHA-256) i cenzuriranim uzorkom odvojeno.
* `.github/workflows/ci_v4_shadow_split.yml` — **shadow benchmark, nije required**: read-only token, bez tajni; HEAD kod nad fiksnim popisom teških
  modula; verify job sam re-kolektira i agregira; kalibracija disk vs tmpfs klon (isti SHA, isti kod).

## 3. Presude po modulu

| Modul | Presuda | Razlog |
|---|---|---|
| `tests/test_wf06b_scope.py` | SPLIT_SAFE_FLOOR_LIMITED | `_tree` worktree po procesu, `wt` reset+clean nakon svakog testa; floor 6.718 s |
| `tests/test_rcux_governance.py` | SPLIT_SAFE | bez fixturea, samo čitanje; 41 node, max 284 s → 3 dijela ≈ 720 s |
| `tests/test_u1_scope.py` | NOT_BENEFICIAL | jedan node 337 / 388 s |
| `tests/test_post413_o1_scope.py` | NOT_BENEFICIAL | jedan node 445 / 474 s |
| `tests/test_u2_scope.py` | NOT_BENEFICIAL | jedan node 402 / 456 s |

Financijski/Goal Seek moduli nisu na popisu (nema dokaza izolacije).

## 4. Projekcija za #421 skup teških modula [PROJEKCIJA]

| Plan | Workeri | Kritični put | Runner-min |
|---|---|---|---|
| po modulima (stare težine) | 2 | 3.854 s predviđeno — stvarno ≥ 8.981 s [CENZURIRANO] | — |
| po nodeovima (izmjerene težine) | 2 | ≈ 6.898 s (floor 6.718 s + overhead) | ≈ 185 |

Treći worker ne skraćuje kritični put (floor) pa ga pravilo ne dodaje. Cilj 25–40 min **nije dostižan** samo dijeljenjem dok taj jedan node traje ~1 h 50 min.

## 5. Aktivacija u dva koraka (bez chicken-and-egg)

1. **PR-A (ovaj)**: required „CI V4 gate“ radi kao i prije (trusted-base selektor i agregator s `main`, plan po modulima). Glavni trusted agregator na
   `main` svaki plan u kojem je modul raspoređen na više shardova **odbija** (isti modul u više shardova → FAIL), pa se dijeljenje ne može tiho aktivirati prije mergea.
   Novi kod se dokazuje lokalno i u shadow benchmarku (oznaka NOT REQUIRED).
2. **PR-B (nakon mergea PR-A, zaseban review)**: plan job nakon selekcije poziva `collect` + `apply_node_split` (politika `enabled_in_required_pr_gate:
   true`); gate job instalira ovisnosti, izvodi neovisnu re-kolekciju i poziva **trusted** agregator s `--inventory`. Prvi PR nakon PR-B je kanarinac:
   provjeriti da je trusted agregator s `main` (već PR-A kod) dao PASS s „collected == disjoint union“ za svaki split modul.

## 6. Preporuka izvan opsega (zasebna odluka vlasnika)

Pod od ~1 h 50 min je u governance testu, ne u CI-ju. Opcije (svaka mijenja pinirani governance izvor, pa traži odobrenje i re-pin kaskadu):
(a) u `tests/test_wf06b_scope.py` cijelu petlju izvesti unutar jednog vanjskog `scoped()` poziva (memo jedne vanjske provjere koji kohorte već imaju);
(b) u kohortnim `matches()` usporediti blob prije skupe `valid()` provjere (isti ishod, bez 3.255 git poziva po putanji);
(c) „epoch seal“ iz ranijeg izvještaja.

## 7. Što nije izmjereno u ovom dokumentu

Hosted shadow rezultati (stvarno najsporiji shard, runner-min, disk vs tmpfs) — vidi završni izvještaj PR-A; dok ne postoje, svi brojevi u §4 su projekcije.
