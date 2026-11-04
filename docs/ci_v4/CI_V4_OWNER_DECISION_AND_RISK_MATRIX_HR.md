# CI V4 — odluka vlasnika i rizik-matrica (HR)

Status: **implementirano na grani `integration/post413-data-integrity` (PR #419, Correction K)**. Required status check u branch protectionu **NIJE promijenjen** (agent nema pravo čitanja/izmjene pravila zaštite) — vidi §6.

## 1. Tri režima

| Režim | Kada | Što se izvršava | Cilj (projekcija) |
|---|---|---|---|
| **FAST** | svaki PR | exact HEAD attest + synthetic merge-tree guard (jedan centralni prolaz), compile, public safety/secret scan, `pip check`, React typecheck + build + identitet servisiranog bundlea, `fast_baseline` (smoke engine/UI, Save All atomic, CSRF/secret negativi, CI V4 samotestovi), promijenjeni test-moduli | 1 worker, ~7 min |
| **RISK** | automatski kad promjena dira kritičnu površinu ili nepoznatu putanju (fail closed) | FAST + suite po matrici (§2) + ovisni test-moduli (statički import-graf, dubina 2, cap 200) + F01 browser (4 vertikale) i native V10/V11 (20 slučajeva) kad matrica traži | adaptivno 1–8 workera, ~15–40 min |
| **FULL** | nightly (`ci_v4_full.yml`, 01:23 UTC), `workflow_dispatch`, **obavezno prije releasea** | **nepromijenjena** puna CI V3 regresija (`ci_v3_required_job.yml`, >21k nodeova, svi povijesni negativi/exactness) + F01 s native identitetom; FULL record vezan uz SHA+tree | 8 workera (V3 harness) |

Semantika rezultata: FAST/RISK izvještavaju **SELECTED / NOT SELECTED / PASSED / FAILED / SKIPPED (not PASS)**. Neizvršeni test nikad nije PASS; FAST/RISK JUnit se nikad ne uspoređuje s punim korpusom kao da je potpuna regresija. Skip u `no_skip` suiteu (baseline, security, save-integrity, F01) ili u promijenjenom test-modulu PR-a = FAIL.

## 2. Rizik-matrica putanja → obvezni suiteovi (`docs/ci_v4/ci-v4-policy.json`)

Pravilo se bira prvim podudaranjem po putanji; razina PR-a = maksimum svih putanja. Nepoznata putanja → RISK s proširenim skupom (`unknown_path`, fail closed). Promjena CI/governance kontrolnih putanja → najmanje RISK + `risk_governance`, a selektor i politika uzimaju se iz **trusted BASE** commita; politika PR-a smije samo proširiti selekciju (inače FAIL).

| Pravilo | Putanje | Razina | Dodatni suiteovi |
|---|---|---|---|
| docs_only_markdown | `README.md`, `*.md` u `docs/`, `OPUS_V1_REVIEW/**` … | FAST | — (samo baseline + source safety) |
| test_module_self | `tests/test_*.py` | FAST (+ sam modul, no-skip) | — |
| radar_yield_non_financial | `finco_radar/**`, `finco_yield/**`, `finco_protocol/**`, `research/**`, `examples/**` | FAST | ovisni moduli (eskalacija u RISK ako >60) |
| financial_ui | `frontend/src/app/**`, `static/react/**` | RISK | security, ui_build, **F01**, save_integrity |
| frontend_non_financial | ostali `frontend/**`, `static/**` | RISK | security, ui_build |
| financial_core | `financial_engine/**`, `finco_core/**`, `domain/**` | RISK | finance (goal seek, DSCR, bankability, PPA, rate), **F01 + native V10/V11**, security, save_integrity |
| application_surface | `app/**`, `main_*.py`, `finco_app/**`, `utils/**` | RISK | security, finance, **F01**, save_integrity |
| deploy_and_deps | `deploy/**`, `requirements*.txt`, `constraints.txt`, `pyproject.toml`, `pytest.ini` | RISK | security, finance |
| ci_control | `.github/**`, `tools/**`, `docs/ci_v3|ci_v4|ci/**`, `tests/conftest.py`, registri/scope moduli, `*governance*.py` | RISK (control) | governance, security |
| governance_manifests | `docs/**/*.json|*.txt`, `evidence/**` | RISK (control) | governance |
| test_support_files | ostali `tests/**` | RISK | security, finance |

Ne mogu se zaobići: validacija politike odbija pravilo koje šalje `financial_engine/`, `finco_core/`, `domain/`, `app/`, `.github/`, `tools/ci_*` ili `main_web.py` u FAST; unknown default mora biti `risk`/`full`; `force_tier` smije samo podići razinu; path traversal je odbijen.

## 3. Što ostaje required na svakom PR-u, što ide u nightly/release

| Provjera | Prije (V3) | CI V4 |
|---|---|---|
| Source attest + merge-tree | više puta (svaki workflow) | jednom u CI V4 `plan` (+ postojeći workflowi dok vlasnik ne promijeni required) |
| Public safety/secret scan, compile | `source-safety`, `compile-and-safety` | CI V4 `static` (FAST) |
| Cijeli V3 korpus (23.770 nodeova na 800395f) | **svaki PR** (77–158 min wall, 410–610 runner-min) | **FULL**: nightly + manual + release gate |
| Povijesni exactness/governance negativi (100 scope/governance/successor/CI modula, 11.087 s od 23.003 s JUnit = 48 %) | svaki PR | RISK kad PR dira governance/CI (kao #419), inače FULL |
| F01 4-vertical browser + native | svaki PR (17 min) | RISK za financijski kod/Run/rate/financijski UI/app; FULL uvijek |
| Browser role (`mandatory-browser-evidence`, 35 min) | svaki PR | nepromijenjen (vlasnik odlučuje; preporuka: RISK za UI/app) |
| Q4 / oracle / dependency / governance-history | path-filtrirani ili brzi | nepromijenjeni |

**Ništa nije uklonjeno** iz repozitorija ni iz FULL-a. Nijedan assert nije oslabljen; nijedan test nije obrisan; nema `if: false`, `continue-on-error` ni always-pass wrappera.

## 4. Release / deploy gate

`.github/workflows/ci_v4_release_gate.yml` (workflow_call + dispatch) i `tools/ci_v4_release_gate.py`:
* traži najnoviji **uspješan** `ci_v4_full.yml` run za **točan 40-hex SHA** (nikad "latest green" druge grane);
* preuzima njegov `ci-v4-full-record`, provjerava SHA **i git tree**, PASS, nula fail/error, broj nodeova ≥ 21.000, executed == collected, re-derivira brojeve i SHA-256 iz samih JUnit datoteka, starost ≤ 30 dana;
* **neovisno pita GitHub API** za run iz recorda (isti repo, ne fork, `ci_v4_full.yml`, event schedule/dispatch, `conclusion=success`, isti attempt) — krivotvoreni artefakt ne prolazi;
* skipovi: samo node-id iz reviewed baselinea (`docs/ci_v4/full_skip_baseline.json`, 603 prirodna skipa iz runa 41782498276, kao multiset); svaki novi/dodatni skip blokira release.

U repozitoriju trenutačno **ne postoji deploy/release workflow**; budući deploy mora imati `needs:` na `ci_v4_release_gate.yml` s točnim SHA-om koji isporučuje. Nema bypassa.

## 5. Governed successor i centralizacija

`tests/ci_v4_scope.py` je zatvorena exact-source kohorta (literalni popis putanja, `CI_PATHS` = jedine dopuštene `.github/`/`tools/` putanje, nikad engine/core/domain/app). Uspostavljena je kao **later cohort** U1-a; postojeći stari guardovi (U1, U2, R1/R17/R18, WF-06B, Integration-409) dobili su **jednu istu ograničenu iznimku**: literalna CI V4 putanja samo dok je CI V4 kohorta exact. Negativi: nepoznata `.github`/`tools` datoteka, izmjena postojećeg workflowa ili V3 alata, promjena enginea, drift vlasničke datoteke, krivotvoren manifest (pin, base, dodatna putanja), izvršni bit, supersession izvan točnog pina.

**Nalaz (važan za vlasnika):** postojeća governance arhitektura zahtijeva da svaka nova kasnija kohorta dodiruje 6 starih guard modula i re-pinira 5 manifesta (kaskada tranzitivne exactness). JUnit mjerenje (run 41782498276) pokazuje da 100 scope/governance/successor/CI modula troši 11.087 s od 23.003 s cijelog korpusa (48 %). Preporuka (zaseban, odvojeno odobren rad): **epoch seal** — jednokratno potvrđeno stanje svih kohorta na immutable commitu, nakon kojeg se stare kohorte provjeravaju na tom commitu (cache po object ID-u), a nove promjene samo protiv registra epohe. Ovo NIJE izvedeno u ovom PR-u.

## 6. Branch protection — točni ručni koraci za vlasnika

Agent **nije mogao pročitati ni izmijeniti** pravila zaštite (nema API alata za branch protection). Ne tvrdi se da je required gate promijenjen. Do vlasnikove promjene, V3 ostaje required → stanje je fail-closed (ništa nije oslabljeno).

1. GitHub → Settings → Branches (ili Rules → Rulesets) → pravilo za `main` → *Require status checks*.
2. **Dodati** required check: `CI V4 gate` (job `gate` u workflowu „CI V4 PR“).
3. Nakon barem jednog zelenog CI V4 runa na PR-u (shadow/dual) **ukloniti** iz required: `safety-and-smoke / tests`, `mandatory-evidence` (V3 full po PR-u). Ostale (npr. `source-safety`, `compile-and-safety`, `rate-contract-native-and-browser`, `mandatory-browser-evidence`, `q4-canonical-financial`, `authoritative-history`, `dependency-audit`, `independent-oracle`) zadržati ili zamijeniti prema §3 — svaki uklonjeni mora biti pokriven CI V4 matricom.
4. Kad je V3 uklonjen iz required: u zasebnom, odvojeno odobrenom PR-u promijeniti `public_safety_and_smoke.yml` da na `pull_request` više ne poziva puni V3 (inače i dalje troši ~400–600 runner-min po pushu, iako nije required). **Ovaj PR namjerno ne mijenja postojeće V3 workflowe.**
5. Release: svaki budući deploy workflow mora `needs:` `ci_v4_release_gate.yml` sa SHA-om koji isporučuje.
