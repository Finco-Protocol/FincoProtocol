# Third-Party Sources & Notices — Tokenized Markets registry seed

Provenance record for externally harvested data that seeds the FINCO
Tokenized Markets venue registry (PR 3a).  The normalized, committed
artifact is `finco_radar/venues/data/venue_registry_seed.json`, produced by
`tools/import_venue_registry_seed.py`.  Each imported row carries its
`source` and `source_ref` so external facts are never silently mixed with
FINCO-authored facts.

Imported at build time only — never fetched at application runtime.

| Source | Revision at import | What FINCO imports | License |
|---|---|---|---|
| `dicethedev/rwaimport-registry` (GitHub) | `a52ab346263f067b591ac9e936e687ee0291f12d` (main, 2026-10-02) | RWA dossiers `assets/<slug>/{asset,deployments}.json`: Robinhood Jersey representations (~195), Ondo Global Markets representations (~400), others (34, issuer classified from dossier `organizationRoles`) with chain / chainId / contract / decimals / deployment status | MIT |
| `xplowdie/rwa-registry` ("pegproof", GitHub) | `dabb99c82d16994bc546bd4c21159637f0b86776` (main, 2026-09-02) | Flat Robinhood Chain token mappings (`registry/data/robinhood-chain.json`, 192 rows: ticker / underlying / address / decimals / status) and the known-impostor list (`registry/data/known_impostors.json`, 6 entries: exact chain + contract deny/quarantine identity) | MIT (code), LICENSE-DATA.md for data |
| Official xStocks public API — `https://api.xstocks.fi/api/v2/public/assets` | live API, 13 pages / 1,271 assets at import (2026-10-02) | xStocks universe: symbol → `underlyingSymbol` / `underlyingIsin`, ISIN, per-network deployments (address, decimals), trading-halt state | public API; no SDK vendored |

What FINCO did NOT import: CoinGecko data as an xStocks identity authority
(explicitly avoided — official xStocks metadata wins), valuation/claims/
compliance dossier sections beyond identity+deployment facts, oracle feeds,
treasury addresses.

Runtime authority remains FINCO's: imported registry facts are seed
identity data, never live market evidence, and every representation row is
re-derived (quarantine / conflict / inactive) by
`finco_radar.venues.registry` at load time.
