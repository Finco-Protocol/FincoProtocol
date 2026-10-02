"""Deterministic Tokenized-Markets registry seed importer (build-time tool).

Fetches the three reviewed external seed sources ONCE at development/build
time and writes the normalized, diffable FINCO seed artifact:

    finco_radar/venues/data/venue_registry_seed.json

Sources (recorded per row with origin + revision):
  A. dicethedev/rwaimport-registry  (dossiers: asset.json + deployments.json)
  B. xplowdie/rwa-registry          (flat Robinhood Chain mappings + impostors)
  C. official xStocks public API    (asset universe + deployments)

The application NEVER fetches these at page-load time: the committed seed
artifact is the runtime input (see finco_radar.venues.seed_loader).

Usage:
    python tools/import_venue_registry_seed.py [--output PATH]

The output is deterministic: rows are canonically sorted, keys sorted, and
every imported fact carries its source origin.  Re-running against the same
source revisions yields a byte-identical artifact.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

RWAIMPORT_REPO = "dicethedev/rwaimport-registry"
RWAIMPORT_REF = "a52ab346263f067b591ac9e936e687ee0291f12d"
XPLOWDIE_REPO = "xplowdie/rwa-registry"
XPLOWDIE_REF = "dabb99c82d16994bc546bd4c21159637f0b86776"
XSTOCKS_ASSETS_URL = "https://api.xstocks.fi/api/v2/public/assets"

SEED_SCHEMA_VERSION = "FINCO_VENUE_REGISTRY_SEED_V1"

# chain/network name → canonical network key (exact; unknown stays verbatim-lower)
NETWORK_CANON = {
    "robinhood-chain": "robinhood-chain",
    "robinhood chain": "robinhood-chain",
    "ethereum": "ethereum",
    "solana": "solana",
    "arbitrum": "arbitrum",
    "arbitrum one": "arbitrum",
    "mantle": "mantle",
    "base": "base",
    "bsc": "bnb",
    "bnb": "bnb",
    "bnb smart chain": "bnb",
    "polygon": "polygon",
    "avalanche": "avalanche",
    "optimism": "optimism",
    "ton": "ton",
}


def _get_json(url: str, *, timeout: float = 30.0):
    request = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "finco-venue-seed-importer/1.0",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _network_key(name) -> str | None:
    if not isinstance(name, str) or not name.strip():
        return None
    lowered = name.strip().lower()
    return NETWORK_CANON.get(lowered, lowered.replace(" ", "-"))


def _platform_from_slug(slug: str, dossier: dict) -> str:
    """Platform/issuer classification from the dossier itself (not the slug)."""
    lowered = slug.lower()
    if lowered.startswith("robinhood-"):
        return "robinhood"
    roles = dossier.get("organizationRoles") or []
    for role in roles:
        org = str(role.get("organizationId", "")).lower()
        if "robinhood" in org:
            return "robinhood"
        if "ondo" in org:
            return "ondo"
        if "wisdomtree" in org:
            return "wisdomtree"
    name = str(dossier.get("name", "")).lower()
    if "ondo" in name:
        return "ondo"
    if "wisdomtree" in name:
        return "wisdomtree"
    return "other"


def _fetch_dossier(slug: str) -> dict | None:
    """Fetch one rwaimport dossier (asset.json + deployments.json)."""
    base = (f"https://raw.githubusercontent.com/{RWAIMPORT_REPO}/{RWAIMPORT_REF}"
            f"/assets/{slug}")
    try:
        asset = _get_json(f"{base}/asset.json")
        deployments = _get_json(f"{base}/deployments.json")
    except Exception:  # noqa: BLE001 — build-time import: skip unreachable dossier
        return None
    return {"slug": slug, "asset": asset, "deployments": deployments}


def _fetch_rwaimport_dossiers() -> tuple[list[dict], int]:
    tree = _get_json(
        f"https://api.github.com/repos/{RWAIMPORT_REPO}/git/trees/{RWAIMPORT_REF}"
        "?recursive=1")
    paths = [t["path"] for t in tree.get("tree", [])
             if t.get("type") == "blob" and t["path"].endswith("/asset.json")
             and t["path"].startswith("assets/")]
    slugs = sorted(p.split("/")[1] for p in paths if len(p.split("/")) == 3)
    dossiers: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        for result in pool.map(_fetch_dossier, slugs):
            if result is not None:
                dossiers.append(result)
    return dossiers, len(slugs)


def _normalize_dossier(dossier: dict) -> list[dict]:
    """One dossier → underlying + representation rows (per deployment)."""
    asset = dossier.get("asset") or {}
    deployments = dossier.get("deployments") or []
    if not isinstance(deployments, list):
        deployments = []
    platform = _platform_from_slug(dossier["slug"], asset)
    symbol = asset.get("symbol")
    underlying_id = asset.get("underlyingId")
    if not isinstance(symbol, str) or not symbol.strip():
        return []
    rows = []
    if deployments:
        for deployment in deployments:
            address = deployment.get("address")
            if not isinstance(address, str) or not address:
                continue
            rows.append({
                "kind": "representation",
                "platform": platform,
                "representation_symbol": symbol,
                "underlying_symbol": (
                    str(underlying_id).removeprefix("equity-").upper()
                    if isinstance(underlying_id, str) and underlying_id
                    else None),
                "underlying_ref": underlying_id,
                "network": _network_key(deployment.get("chain")),
                "chain_id": deployment.get("chainId")
                if isinstance(deployment.get("chainId"), int) else None,
                "contract_address": address.lower(),
                "decimals": deployment.get("decimals")
                if isinstance(deployment.get("decimals"), int) else None,
                "deployment_status": deployment.get("status"),
                "name": asset.get("name"),
                "instrument_type": asset.get("instrumentType"),
                "source": "rwaimport-registry",
                "source_ref": (
                    f"{RWAIMPORT_REPO}@{RWAIMPORT_REF[:12]}#assets/{dossier['slug']}"),
            })
    else:
        rows.append({
            "kind": "representation",
            "platform": platform,
            "representation_symbol": symbol,
            "underlying_symbol": (
                str(underlying_id).removeprefix("equity-").upper()
                if isinstance(underlying_id, str) and underlying_id else None),
            "underlying_ref": underlying_id,
            "network": None,
            "chain_id": None,
            "contract_address": None,
            "decimals": None,
            "deployment_status": None,
            "name": asset.get("name"),
            "instrument_type": asset.get("instrumentType"),
            "source": "rwaimport-registry",
            "source_ref": (
                f"{RWAIMPORT_REPO}@{RWAIMPORT_REF[:12]}#assets/{dossier['slug']}"),
        })
    return rows


def _normalize_xplowdie(registry_rows: list[dict]) -> list[dict]:
    rows = []
    for entry in registry_rows:
        if not isinstance(entry, dict):
            continue
        address = entry.get("address")
        if not isinstance(address, str) or not address:
            continue
        rows.append({
            "kind": "representation",
            "platform": str(entry.get("issuer") or "robinhood").lower(),
            "representation_symbol": entry.get("ticker"),
            "underlying_symbol": entry.get("underlying") or entry.get("ticker"),
            "underlying_ref": None,
            "network": "robinhood-chain",
            "chain_id": entry.get("chain_id")
            if isinstance(entry.get("chain_id"), int) else None,
            "contract_address": address.lower(),
            "decimals": entry.get("decimals")
            if isinstance(entry.get("decimals"), int) else None,
            "deployment_status": entry.get("status"),
            "name": entry.get("name"),
            "instrument_type": "tokenized-equity",
            "source": "xplowdie-rwa-registry",
            "source_ref": f"{XPLOWDIE_REPO}@{XPLOWDIE_REF[:12]}#registry/data/robinhood-chain.json",
        })
    return rows


def _normalize_impostors(entries: list) -> list[dict]:
    rows = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        address = entry.get("address")
        if not isinstance(address, str) or not address:
            continue
        rows.append({
            "kind": "quarantine",
            "network": _network_key(entry.get("chain_id")),
            "chain_id": entry.get("chain_id")
            if isinstance(entry.get("chain_id"), int) else None,
            "contract_address": address.lower(),
            "mimics": entry.get("mimics"),
            "classification": entry.get("classification") or "impostor",
            "evidence": entry.get("evidence"),
            "source": "xplowdie-rwa-registry",
            "source_ref": f"{XPLOWDIE_REPO}@{XPLOWDIE_REF[:12]}#registry/data/known_impostors.json",
        })
    return rows


def _fetch_xstocks_universe() -> tuple[list[dict], int]:
    """Deterministic pagination over the official xStocks assets endpoint."""
    universe: list[dict] = []
    page = 0
    while True:
        payload = _get_json(f"{XSTOCKS_ASSETS_URL}?page={page}")
        nodes = payload.get("nodes")
        if not isinstance(nodes, list):
            break
        universe.extend(nodes)
        meta = payload.get("page") or {}
        if not meta.get("hasNextPage"):
            break
        page += 1
    return universe, page + 1


def _normalize_xstocks(nodes: list[dict]) -> list[dict]:
    rows = []
    for node in nodes:
        symbol = node.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            continue
        underlying = node.get("underlying") or {}
        halted = node.get("isTradingHalted")
        if not isinstance(halted, bool):
            halted = (node.get("trading") or {}).get("isTradingHalted")
        base = {
            "kind": "representation",
            "platform": "xstocks",
            "representation_symbol": symbol,
            "underlying_symbol": node.get("underlyingSymbol")
            or underlying.get("symbol"),
            "underlying_ref": node.get("underlyingSymbol"),
            "underlying_isin": node.get("underlyingIsin")
            or underlying.get("isin"),
            "isin": node.get("isin"),
            "trading_halted": halted if isinstance(halted, bool) else None,
            "source": "xstocks-official-api",
            "source_ref": XSTOCKS_ASSETS_URL,
        }
        # xStocks deploys every asset on a uniform multi-chain matrix, so the
        # seed keeps ONE row per asset with the exact deployment list embedded
        # (structured, deterministic) — exact contract lookup expands it.
        deployments = node.get("deployments") or []
        embedded = []
        if isinstance(deployments, list):
            for deployment in deployments:
                address = deployment.get("address")
                if not isinstance(address, str) or not address:
                    continue
                embedded.append({
                    "network": _network_key(deployment.get("network")),
                    "contract_address": address.lower(),
                    "decimals": deployment.get("decimals")
                    if isinstance(deployment.get("decimals"), int) else None,
                })
        embedded.sort(key=lambda d: (d["network"], d["contract_address"]))
        row = dict(base)
        row.update({
            "network": None,
            "chain_id": None,
            "contract_address": None,
            "decimals": None,
            "deployment_status": None,
            "name": node.get("name"),
            "instrument_type": "xstock",
            "deployments": embedded,
        })
        rows.append(row)
    return rows


def build_seed() -> dict:
    dossiers, dossier_total = _fetch_rwaimport_dossiers()
    dossier_rows: list[dict] = []
    for dossier in dossiers:
        dossier_rows.extend(_normalize_dossier(dossier))

    xplowdie_registry = _get_json(
        f"https://raw.githubusercontent.com/{XPLOWDIE_REPO}/{XPLOWDIE_REF}"
        "/registry/data/robinhood-chain.json")
    xplowdie_impostors = _get_json(
        f"https://raw.githubusercontent.com/{XPLOWDIE_REPO}/{XPLOWDIE_REF}"
        "/registry/data/known_impostors.json")

    xstocks_nodes, xstocks_pages = _fetch_xstocks_universe()
    xstocks_rows = _normalize_xstocks(xstocks_nodes)

    representations = (
        dossier_rows
        + _normalize_xplowdie(xplowdie_registry if isinstance(xplowdie_registry, list) else [])
        + xstocks_rows
    )
    representations = [r for r in representations
                       if isinstance(r.get("representation_symbol"), str)
                       and r["representation_symbol"].strip()]
    representations.sort(key=lambda r: (
        r["source"], r["platform"], str(r["representation_symbol"]).upper(),
        str(r["network"]), str(r["contract_address"])))
    # exact-duplicate dedupe (same source + contract + symbol): keep first
    seen = set()
    deduped = []
    for row in representations:
        key = (row["source"], row.get("contract_address"),
               row["representation_symbol"].upper(), row.get("network"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    quarantines = _normalize_impostors(
        xplowdie_impostors if isinstance(xplowdie_impostors, list) else [])
    quarantines.sort(key=lambda q: (str(q["contract_address"]), str(q["network"])))

    underlyings = {}
    for row in deduped:
        symbol = row.get("underlying_symbol")
        if not symbol:
            continue
        key = str(symbol).upper()
        entry = underlyings.setdefault(key, {
            "kind": "underlying",
            "canonical_symbol": key,
            "underlying_isin": None,
            "underlying_name": None,
            "sources": [],
        })
        isin = row.get("underlying_isin")
        if isin and not entry["underlying_isin"]:
            entry["underlying_isin"] = isin
        if row.get("source") not in entry["sources"]:
            entry["sources"].append(row["source"])
    underlyings_list = sorted(underlyings.values(),
                              key=lambda u: u["canonical_symbol"])

    return {
        "schema_version": SEED_SCHEMA_VERSION,
        "generated_from": {
            "rwaimport_registry": {
                "repo": RWAIMPORT_REPO, "revision": RWAIMPORT_REF,
                "dossiers_seen": dossier_total,
                "dossiers_imported": len(dossiers),
            },
            "xplowdie_rwa_registry": {
                "repo": XPLOWDIE_REPO, "revision": XPLOWDIE_REF,
            },
            "xstocks_official_api": {
                "url": XSTOCKS_ASSETS_URL, "pages": xstocks_pages,
                "assets": len(xstocks_nodes),
            },
        },
        "underlyings": underlyings_list,
        "representations": deduped,
        "quarantines": quarantines,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",
                        default=str(REPO / "finco_radar/venues/data/venue_registry_seed.json"))
    parser.add_argument("--allow-partial", action="store_true",
                        help="development-only: keep a smaller seed when "
                             "pinned-source dossiers fail to fetch (the "
                             "committed artifact must normally be complete)")
    args = parser.parse_args()

    seed = build_seed()
    generated = seed["generated_from"]["rwaimport_registry"]
    if (generated["dossiers_imported"] != generated["dossiers_seen"]
            and not args.allow_partial):
        print(f"FAIL-CLOSED: requested {generated['dossiers_seen']} dossiers "
              f"but imported {generated['dossiers_imported']}; transient "
              "source failures must not silently shrink the reviewed seed. "
              "Re-run, or pass --allow-partial for development-only use.",
              file=sys.stderr)
        return 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(seed, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(f"underlyings={len(seed['underlyings'])} "
          f"representations={len(seed['representations'])} "
          f"quarantines={len(seed['quarantines'])} -> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
