"""FINCO Equity fundamentals ingestion CLI.

Usage:
    python -m app.equity.equity_fundamentals_ingest <stage> [options]

Stages:
    universe     discover Robinhood Chain stock-token universe (1 HTTP call)
    profiles     company profiles for all mapped active tickers
    financials   financial statements (TTM/annual/quarterly)
    dividends    dividend history
    splits       split history
    seed         universe + AAPL/NVDA/MSFT end-to-end (bootstrap verification)
    all          universe + all stages for the full universe

Environment:
    MASSIVE_API_KEY   required for Massive stages (never logged)
    FINCO_EQUITY_DB_PATH  optional SQLite path override

Properties: idempotent, checkpointed (resumable), paced at ~4 req/min with
retry/backoff on 429/5xx/network errors, and one failed ticker never aborts
the universe.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import repository as repo
from .db import connect
from .providers.massive_legacy import (
    MassiveLegacyClient,
    MassiveLegacyError,
    normalize_company_profile,
    normalize_dividends,
    normalize_financials,
    normalize_splits,
    scrub_secrets,
)
from .universe import fetch_universe

logger = logging.getLogger("app.equity.ingest")

PROFILE_REFRESH_DAYS = 14  # profiles re-fetch when older than this (7-30 day band)
SEED_TICKERS = ["AAPL", "NVDA", "MSFT"]


def _client() -> MassiveLegacyClient:
    try:
        return MassiveLegacyClient()
    except MassiveLegacyError as exc:
        logger.error("cannot start Massive client: %s", exc)
        raise SystemExit(2)


def _run_ticker_stage(
    conn,
    client: MassiveLegacyClient,
    stage: str,
    ticker: str,
    *,
    skip_if_fresh: bool = True,
) -> str:
    """Run one ticker/stage; returns status: done | skipped | failed."""
    run_key = f"{stage}:{ticker}"
    row = repo.checkpoint_get(conn, run_key)
    if row is not None and row["status"] == "done" and skip_if_fresh:
        return "skipped"

    try:
        if stage == "profiles":
            if skip_if_fresh:
                freshness = repo.profile_freshness(conn, ticker)
                if freshness is not None:
                    age = datetime.now(timezone.utc) - datetime.fromisoformat(freshness)
                    if age < timedelta(days=PROFILE_REFRESH_DAYS):
                        repo.checkpoint_set(conn, run_key, stage, ticker, "done",
                                            "profile fresh")
                        return "skipped"
            raw = client.company_profile(ticker)
            repo.upsert_profile(conn, normalize_company_profile(raw), raw)
        elif stage == "financials":
            if skip_if_fresh and repo.has_snapshots(conn, ticker):
                repo.checkpoint_set(conn, run_key, stage, ticker, "done", "has data")
                return "skipped"
            raw = client.financials(ticker)
            repo.upsert_snapshots(conn, normalize_financials(raw, ticker), raw)
        elif stage == "dividends":
            raw = client.dividends(ticker)
            repo.upsert_dividends(conn, normalize_dividends(raw, ticker))
        elif stage == "splits":
            raw = client.splits(ticker)
            repo.upsert_splits(conn, normalize_splits(raw, ticker), raw)
        else:
            raise ValueError(f"unknown stage {stage}")
    except MassiveLegacyError as exc:
        repo.checkpoint_set(conn, run_key, stage, ticker, "failed", scrub_secrets(str(exc)))
        logger.warning("ticker %s failed stage %s: %s", ticker, stage, exc)
        return "failed"
    except Exception as exc:  # noqa: BLE001 — universe must not abort
        repo.checkpoint_set(conn, run_key, stage, ticker, "failed", scrub_secrets(str(exc)))
        logger.warning("ticker %s failed stage %s: %s", ticker, stage, exc)
        return "failed"

    repo.checkpoint_set(conn, run_key, stage, ticker, "done")
    return "done"


def stage_universe(conn) -> dict:
    snapshot = fetch_universe()
    for asset in snapshot.assets:
        repo.upsert_asset(conn, asset)
    disappeared = repo.mark_disappeared_inactive(
        conn, [a.robinhood_token_symbol for a in snapshot.assets]
    )
    repo.checkpoint_set(conn, "universe:registry", "universe", None, "done",
                        f"{len(snapshot.assets)} assets, {disappeared} deactivations")
    logger.info("universe: %d assets (%d disappeared -> inactive)",
                len(snapshot.assets), disappeared)
    return {"discovered": len(snapshot.assets), "deactivated": disappeared}


def _tickers(conn, only: Optional[list[str]]) -> list[str]:
    if only:
        return only
    return repo.active_tickers(conn)


def _run_stage(conn, client, stage: str, tickers: list[str], stats: dict,
               *, skip_if_fresh: bool = True) -> None:
    for ticker in tickers:
        status = _run_ticker_stage(conn, client, stage, ticker,
                                   skip_if_fresh=skip_if_fresh)
        stats[status] = stats.get(status, 0) + 1
        conn.commit()
    logger.info("stage %s: %s", stage, stats)


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="FINCO Equity fundamentals ingestion")
    parser.add_argument(
        "stage",
        choices=["universe", "profiles", "financials", "dividends", "splits",
                 "seed", "all"],
    )
    parser.add_argument("--tickers", nargs="*", help="restrict to these tickers")
    parser.add_argument("--limit", type=int, default=0,
                        help="process at most N tickers per Massive stage")
    parser.add_argument("--force", action="store_true",
                        help="re-ingest even if fresh (still hash-idempotent)")
    args = parser.parse_args(argv)

    with connect() as conn:
        if args.stage in ("universe", "seed", "all"):
            stage_universe(conn)

        if args.stage == "universe":
            return 0

        tickers = _tickers(conn, args.tickers)
        if args.stage == "seed":
            tickers = SEED_TICKERS
        if args.limit:
            tickers = tickers[: args.limit]

        client = _client()
        stages = (
            ["profiles", "financials", "dividends", "splits"]
            if args.stage in ("seed", "all")
            else [args.stage]
        )
        summary: dict[str, dict] = {}
        for stage in stages:
            stats: dict = {}
            _run_stage(conn, client, stage, tickers, stats, skip_if_fresh=not args.force)
            summary[stage] = stats
        print(json.dumps({
            "tickers": len(tickers),
            "api_calls": client.request_count,
            "summary": summary,
        }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
