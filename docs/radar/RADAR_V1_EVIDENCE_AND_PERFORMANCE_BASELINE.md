# Radar V1 — Canonical Evidence and Offline Performance Baseline

**Evidence state:** source inventory verified against main 540e1f4bb54d53ad6d2c1628074b94fdb0c9eb06. **Offline timing results:** NOT MEASURED in this delivery environment. No deployment, operator DB or provider access has been used. This is a reproducible measurement protocol, not a fabricated baseline.

## Canonical authority inventory

| Economic/evidence concept | Single authoritative implementation | Closeout audit treatment |
|---|---|---|
| Exact market identity | finco_radar/venues/registry.py + approved policy records | Only exact ACTIVE registry representation; no ticker fuzzy matching |
| Immutable observation, digest, clocks | finco_radar/venues/observations.py and venues/store.py | Read-only snapshot; original ts and collected_at independently reported |
| Robinhood R-LIVE evidence normalization | finco_radar/venues/robinhood_live.py | Clock-contract version counted, never reinterpret a legacy timestamp |
| Official reference and basis | venues/basis.py plus venues/intelligence.py | Canonical basis_from_observation; rejection reasons retained |
| Market freshness | venues/intelligence.effective_observation_state | Source-observed age; distinct source-specific oracle age for V2 |
| Collector liveness | venues/health.read_tokenized_collector_health | Last actual attempt/success and derived read-only liveness |
| Own-history basis distribution | venues/relative_value.compute_basis_distribution | 8 usable observations and 3600s source-clock span, both unchanged |
| Dislocation persistence | venues/relative_value.compute_dislocation_persistence | Proven start/sign reversal or explicit prehistory unknown |
| Signal lifecycle | app/crypto_terminal/tokenized_signal_lifecycle.py | 20 representations / 256 observations per representation / 60 events |
| Market Monitor V2 presentation | app/radar_ui/tokenized_monitor_v2.py | Existing product redaction and read projection; untouched |
| Deepstate execution history | app/crypto_terminal/deepstate_composition.py | Historical facts only, max 120, raw USDG/NVDA; NO current market approval |
| Canonical operator observation store | venues/store.VenueMarketStore | Constructor may initialize schema; NEVER constructed on source DB |
| R-LIVE surface and canonical last price | app/radar_rwa/r_live_service.py | Last historical price remains historical when original source evidence aged |
| Entitlement policy | Existing Crypto/Radar gating and API | No new gate; staging matrix requests all access combinations |

## Safety architecture

The tool tools/radar_tokenized_closeout_audit.py reads the source through an immutable **read-only SQLite URI**, takes a temporary SQLite snapshot, performs schema/integrity checks on that copy, and initializes VenueMarketStore **only against the copy**. A missing store, a symlink, an uncheckpointed nonempty WAL, an oversized store, an altered source fingerprint or an invalid schema is never accepted as clean. No network acquisition, collector startup, schema change or market write is part of audit logic.

A live WAL can make an immutable read omit data. That is a hard blocker: operations must provide a previously checkpointed and provenance-documented offline copy. For actual staging audit, verify the copy's origin and SHA separately (ops responsibility). A temporary audit copy is not additional observation history.

The tool reports:
- Observation existence, source and collection timestamps and missing source-clock counts.
- Source clock V2 versus historical/other observation counts.
- Read-only collector health.
- Canonical active representations, usable basis points, rejection reasons, own-history distribution and dislocation facts.
- Historical Deepstate count and normalization/current-execution restrictions.
- Exact evaluated Git HEAD when available; absence of Git provenance is explicitly null, **not** provenance PASS.
- Release gate remains NOT_ASSESSED_NO_DEPLOYMENT_EVIDENCE.

No fixed performance SLO is invented and no future price/source approval is implied.

## Offline benchmark (opt-in)

Reproduce with:

    python -m tools.bench_radar_v1_closeout --underlyings 10 --rows 64 --repeats 3
    python -m tools.bench_radar_v1_closeout --underlyings 60 --rows 256 --repeats 3

Both commands create disposable SYNTHETIC observations from exact committed registry identities. They never use an operator DB. The second command targets up to 60 ACTIVE underlyings, 256 observations per selected representation; actual selected count is reported rather than asserted. Signal lifecycle uses the existing max 20 representations, 256 observations each and 60 events. Deepstate composition preserves the 120-output cap.

Probe operations:

1. Tokenized Market Monitor composition.
2. Single-asset Relative Value read.
3. Canonical historical distribution and dislocation persistence.
4. Signal lifecycle composition.
5. Deepstate historical-only context.
6. Full offline closeout audit and snapshot cost.

Each operation reports 3 wall-clock values in milliseconds, range, spread, dataset size, and SQLite traced SELECT count where the store API exposes it. Audit snapshot opens its own connections; its trace count is explicitly null, never guessed.

**Observed timing baseline:** NOT MEASURED. The output of these commands becomes the baseline only after they are run in a representative, documented environment. The benchmark does not fail CI on wall time. Any N+1 or excessive scan finding requires a separate performance correction scoped to its owner rather than a broad optimization here.

## Local/CI verification recipe

Fast local checks:

    python -m compileall -q tools/radar_tokenized_closeout_audit.py tools/bench_radar_v1_closeout.py tests/test_radar_v1_closeout_audit.py tests/test_radar_v1_closeout_regression.py
    python -m pytest -q tests/test_radar_v1_closeout_audit.py tests/test_radar_v1_closeout_regression.py
    python -m pytest -q tests/test_tokenized_relative_value.py tests/test_tokenized_market_evidence_clocks.py tests/test_radar_r3_deepstate_composition.py tests/test_radar_tokenized_signal_lifecycle.py tests/test_radar_r4_tokenized_monitor_v2.py
    python tools/public_safety_scan.py

Additional collector/continuity gate:

    python -m pytest -q tests/test_opus_m7_collector_health.py tests/test_r_live_registry_continuity.py tests/test_radar_deepstate_nvda_market.py tests/test_tokenized_live_intelligence_v1.py

Full unsharded Public Safety, Governance Full History, Security/Compile, required Browser roles and exact-content authority are GitHub CI gates. A successful focused test is not merge approval. Real staging/runtime evidence is a separate later acceptance.

## Known measurement limitations

- The CLI reports only exact facts supported by the available persisted store. Absence of a collector table yields existing UNKNOWN/NEVER_RUN semantics.
- Current basis is not authenticated merely because a historical basis value exists.
- A 7-day canonical full-window read can still be expensive in a dense high-volume store. The CLI imposes source DB size and eligible universe bounds; further optimization needs a separate owner-reviewed change.
- No time series is interpolated or backfilled. Old source timestamps remain as stored.
- The local benchmark uses synthetic economic values solely for performance fixture construction; these values never enter Radar market production claims.
- SHA, test counts, real timings and UI screenshots cannot be entered into this document until independently executed and captured.
