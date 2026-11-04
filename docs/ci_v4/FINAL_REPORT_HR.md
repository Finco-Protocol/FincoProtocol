# #419 Correction K + CI V4 — završni izvještaj (HR)

## 0. Exact stanje

| | SHA | tree |
|---|---|---|
| `main` (base) | `2c63750929477c618444e9d056030e054cc3a41c` | `e7869fc8f4775b5ae62a5c75be60f2efef2cfd79` |
| #419 prije (stari HEAD) | `800395fd25a9296baab6366719f09e92ea920ac1` | `fd37d718117587b300286320c080dcbf45e65cad` |
| #419 poslije (novi HEAD) | vidi commit poruku / PR (ovaj dokument je dio tog commita) | — |

Običan commit na `integration/post413-data-integrity`, bez rebasea/squasha/force pusha. Nema merge/deploya.

## 1. Stvarni padovi na 800395fd (run 41782498276) — 8, ne 5

Svih 8 workera pročitano iz originalnih JUnit artefakata (23.770 nodeova, 603 skipa). Worker-6 (koji je bio u tijeku) dodao je **3 pada** istog uzroka kao #4.

| # | Test | Root cause | Ispravak |
|---|---|---|---|
| 1–2 | `test_saas_revamp_entry::test_clone_unexpected_error_{htmx,non_htmx}_returns_500_with_safe_body` | R18 je unkeyed kanonski clone preusmjerio s javnog `project_library_service.create_working_copy` na atomarni `_create_working_copy` (CREATING→COMPLETE). Monkeypatch na javnoj funkciji više ne pogađa aktivnu putanju → clone **stvarno uspije** (204/303, ne lažni success). Route 500/safe-body ugovor je netaknut. Negativ: injekcija samo na staroj točki → 204. | Greška se injektira na **aktivnoj** putanji (`_create_working_copy`, koju javna funkcija omata). Isti ugovor (500, sanitizirano, bez `private-payload-marker` u odgovoru i logu, strukturirani log) + **novo**: nema `HX-Redirect`/`Location` i **nijedan projekt nije kreiran**. Produkcijski kod nepromijenjen (`project_library_service.py` je F01-pinan). |
| 3 | `test_cost_batch_save_v1::test_single_row_command_still_works_after_a_batch_with_the_returned_token` | Nedeterminističan izbor: "prvi" red po `sub_line_id` (random UUID). C.13 Construction Contingency je izračunata linija pod contingency-% autoritetom, bez single-row amount forme (isto na `main`). Pad ~1/31 runova. Nije gubitak podataka ni pristupa. | Deterministički izbor ne-C.13 reda + **novi assert**: svaki ne-C.13 aktivni CAPEX red ima single-row editor nakon batcha, C.13 nema; završna provjera iznosa sada čita **isti red po `sub_line_id`** (ranije opet "prvi po random UUID" → `7.0 == 42.0`). Single-row update nakon batcha izmjeren za svaku kategoriju C.01–C.16 (osim C.13): 200, bez greške. **Nije defekt spremanja.** Save ugovor (token/CSRF/row-version/hash) nepromijenjen; 0/12 padova u ponavljanju. |
| 4 | `test_rcm_governance::test_layer_is_exactly_six_additive_paths…` | R1 (two-tab) je aditivno promijenio browser role `tests/test_model_workspace_consolidation_browser.py` (blob `2d0b5c1a`); R1 kohorta ga supersedira (git-verificiran BASE `bf53a54e`), ali RC-M guard pita samo U1-ov vlastiti `SUPERSEDED`. | Eksplicitni chain of custody `_later_state`: samo točan pin **registrirane i exact** kasnije kohorte koja supersedira tu putanju, i samo ako je njen BASE blob stanje koje stari lanac (RC-M/WS/RC-UX, WF-04, WF-03, WF-06B) već prihvaća. One-byte drift negativ. Bez wildcarda/repina. |
| 5–7 | `test_wsv2_core_scope::{test_correction_e_d029…, test_original_presentation…, test_browser_registration…}` | Isti uzrok kao #4 (WS-V2 guard). | Isti chain of custody; za role i dalje **samo aditivno** (`_additive_only`). |
| 8 | `test_u2_scope::test_the_u1_successor_assertion_admits_only_a_registered_exact_u2` | `tests/test_wf06b_scope.py` je dijeljena reviewed governance datoteka (Correction J) koju sve četiri kohorte potpisuju istim blobom `77d12d33`; nedostajala je u zatvorenom popisu dijeljenih putanja. | Literalni `SHARED_REVIEWED` + dokaz da **svi vlasnici potpisuju isti blob = stablo**; novi test negativa: one-byte drift, krivotvoren pin u jednom vlasniku, extra unowned path, same-cardinality zamjena, zaštićeni prefiks. |

Nijedan od 8 testova nije deselected/skipped/preimenovan; nijedan financijski/sigurnosni assert nije oslabljen.

## 2. CI V4

Implementirano (vidi `CI_V4_OWNER_DECISION_AND_RISK_MATRIX_HR.md`, `CI_V4_WORKER_BENCHMARK_AND_SCHEDULING_HR.md`):
`.github/workflows/ci_v4_pr.yml` (FAST/RISK, required check ime **`CI V4 gate`**), `ci_v4_f01_job.yml`, `ci_v4_full.yml` (nightly/manual, nepromijenjeni V3), `ci_v4_release_gate.yml`; `tools/ci_v4_{select,schedule,shard,aggregate,full_record,release_gate}.py`; `docs/ci_v4/ci-v4-policy.json`, `module_weights.json` (izmjereno), `full_skip_baseline.json`; governed successor `tests/ci_v4_scope.py`. Postojeći V3 workflowi **nisu mijenjani**.

#419 po CI V4 politici: **RISK** (89 putanja; governance + app + financijski UI + CI) → 229 modula (uključujući svih 8 gornjih modula, R1 two-tab, R17, R18, U2), F01 browser, 8 workera (projekcija ~32 min).

## 3. Lokalni acceptance (exact commit prije finalnog dokumenta)

Na commitu prije finalnog dokumenta (stablo `07608165`), **djelomično** — vlasnik je zatražio push bez čekanja punog lokalnog acceptancea:

| Modul | Rezultat |
|---|---|
| `test_saas_revamp_entry.py` | 13 passed |
| `test_rcm_governance.py` | 31 passed |
| `test_ci_v4_{select,schedule,aggregate,release_gate}.py` | 66 passed |
| `test_cost_batch_save_v1.py` | ispravljeno u f8fbb728+1: uzrok bio završni assert na `[0]` (random UUID), ne defekt; 12/12 ponavljanja PASS |
| `test_u2_scope.py` | ispravljeno u f8fbb728: 76/76 |
| `test_u1_scope.py` | ispravljeno u f8fbb728: oba testa PASS (+ negativi za V3 workflow/alat i engine) |
| `test_wsv2_core_scope.py`, R17/R18/R1/U2, security, finance smoke, stari governance | **nije dovršeno lokalno** |

"Prije" na 800395fd lokalno reproducirano: clone 500 ×2, rcm, u2, wsv2 ×3 FAIL; cost-batch prolazi izolirano (intermitentan u CI-ju).

## 4. Hosted CI

Nakon ovog pusha pokreću se postojeći V3 workflowi i novi `CI V4 PR` (bootstrap: base nema CI V4 → selektor iz PR-a, prisilno RISK). Rezultati se prate na exact HEAD-u.

## 5. Nepotvrđeno / otvoreno

* Branch protection: **nije pročitan ni promijenjen** (nema dozvole/alata). V3 ostaje required dok vlasnik ne izvede korake iz §6 rizik-matrice. CI V4 na #419 radi u shadow/dual načinu.
* Hosted P50/P95 za FAST/RISK ne postoje (jedan run nakon ovog pusha); benchmark tablice su projekcije nad izmjerenim težinama.
* FULL: `ci_v4_full.yml` se može pokrenuti tek s default grane (schedule/dispatch) — dakle nakon mergea; FULL record parser JUnit artefakata V3 nije hosted-verificiran.
* Release gate nema deploy workflow na koji bi se spojio (ne postoji u repozitoriju).
* Governance kaskada: dodavanje kasnije kohorte traži izmjene 6 starih guardova i 5 manifesta; preporučen zaseban "epoch seal" rad.
* **Nalaz (prije postojeći, nije uzrokovan #419):** browser moduli `test_cost_editing_ux_v2_browser`, `test_cost_grid_editing_browser_v1`, `test_workflow_c_browser_v1` (i drugi s modulnim skipom) V3 **nikad ne izvršava** (skip u svih 8 workera, nisu ni u jednoj browser roli). Prvi CI V4 RISK run s Chromiumom (`7f0abe6f`) pokazao je da su zastarjeli: mutacijski POST bez CSRF-a → 403, scroll/timeout asercije. CI V4 shard zato za sada ima isto okruženje kao V3 (bez Chromiuma, skip = SKIPPED, ne PASS); popravak tih testova i uključivanje Chromiuma je zaseban zadatak.
* O1/D7/D13/G10/D8 nisu dirani.

## 6. Status

**NOT READY** dok hosted CI na exact HEAD-u ne prođe i dok vlasnik ne promijeni required checkove. Poznati lokalni padovi ispravljeni; puni lokalni acceptance (WS-V2, R17/R18/R1/U2, security, finance) nije dovršen. Bez merge/deploya.
