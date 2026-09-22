"""High-level equity fundamentals service for E1.

Entry points:
  get_equity_fundamentals(robinhood_token_symbol)
  get_equity_fundamentals_many(robinhood_token_symbols)

Deterministic against a fixed DB snapshot.
No Robinhood API calls.  No market prices.  No network I/O of any kind.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence, Tuple

from .config import (
    EquityDBModeError,  # noqa: F401 — re-exported for callers
    EquityDBNotConfiguredError,
    EquityDBNotFoundError,
    resolve_db_path,
    resolve_db_mode,
    validate_db_mode,
)
from .models import (
    AvailabilityState,
    EquityAssetIdentity,
    EquityCompanyHistoryBundle,
    EquityFundamentalsBundle,
    FinancialSnapshot,
    FundamentalsFreshness,
    CompanyProfile,
)
from .repository import EquityDBReadError, EquityFundamentalsRepository


# ── internal helpers ──────────────────────────────────────────────────────────

def _make_freshness(
    asset: Optional[EquityAssetIdentity],
    profile: Optional[CompanyProfile],
    ttm: Optional[FinancialSnapshot],
    quarterly: Optional[FinancialSnapshot],
    annual: Optional[FinancialSnapshot],
) -> FundamentalsFreshness:
    return FundamentalsFreshness(
        ttm_period_end=ttm.period_end if ttm else None,
        ttm_filing_date=ttm.filing_date if ttm else None,
        ttm_fetched_at=ttm.fetched_at if ttm else None,
        ttm_normalized_at=ttm.normalized_at if ttm else None,
        quarterly_period_end=quarterly.period_end if quarterly else None,
        quarterly_fetched_at=quarterly.fetched_at if quarterly else None,
        annual_period_end=annual.period_end if annual else None,
        annual_fetched_at=annual.fetched_at if annual else None,
        profile_fetched_at=profile.fetched_at if profile else None,
        asset_last_seen_at=asset.last_seen_at if asset else None,
    )


def _compute_availability(
    asset: Optional[EquityAssetIdentity],
    profile: Optional[CompanyProfile],
    ttm: Optional[FinancialSnapshot],
    quarterly: Optional[FinancialSnapshot],
    annual: Optional[FinancialSnapshot],
) -> AvailabilityState:
    if asset is None:
        return AvailabilityState.NOT_FOUND
    has_ttm = ttm is not None
    has_any_snapshot = has_ttm or quarterly is not None or annual is not None
    has_profile = profile is not None

    if has_profile and has_ttm:
        return AvailabilityState.AVAILABLE
    if has_profile or has_any_snapshot:
        return AvailabilityState.PARTIAL
    return AvailabilityState.NOT_AVAILABLE


def _unavailable_bundle(
    robinhood_token_symbol: str,
    state: AvailabilityState,
) -> EquityFundamentalsBundle:
    return EquityFundamentalsBundle(
        robinhood_token_symbol=robinhood_token_symbol,
        asset=None,
        company_profile=None,
        latest_ttm=None,
        latest_quarterly=None,
        latest_annual=None,
        recent_dividends=(),
        recent_splits=(),
        source_lineage_summary=(),
        availability=state,
        freshness=_make_freshness(None, None, None, None, None),
    )


# ── public API ────────────────────────────────────────────────────────────────

def get_equity_fundamentals(
    robinhood_token_symbol: str,
    *,
    db_path: Optional[Path] = None,
    db_mode: Optional[str] = None,
    dividends_limit: int = 20,
    splits_limit: int = 10,
    lineage_limit: int = 10,
) -> EquityFundamentalsBundle:
    """Resolve a Robinhood token to a full equity fundamentals bundle.

    ``db_path`` overrides the environment-variable path; pass it in tests.
    ``db_mode`` overrides FINCO_EQUITY_FUNDAMENTALS_DB_MODE; pass it in tests.
    When the DB is unconfigured or missing, returns SOURCE_UNAVAILABLE.
    When the token is unknown, returns NOT_FOUND.

    The bundle's robinhood_token_symbol is the canonical DB form, not the
    request casing.

    Deterministic: no network calls, no datetime.now() inside the result.

    Uses the same internal _build_one_bundle helper as get_equity_fundamentals_many
    so single and batch paths cannot drift.
    """
    # Validate mode before any DB access — programmer/config errors propagate immediately.
    # EquityDBModeError is NOT caught by the SOURCE_UNAVAILABLE handler below.
    if db_mode is not None:
        db_mode = validate_db_mode(db_mode)

    try:
        path = db_path if db_path is not None else resolve_db_path()
    except (EquityDBNotConfiguredError, EquityDBNotFoundError):
        return _unavailable_bundle(
            robinhood_token_symbol, AvailabilityState.SOURCE_UNAVAILABLE
        )

    mode = db_mode if db_mode is not None else resolve_db_mode()

    try:
        repo = EquityFundamentalsRepository(path, mode)
        with repo.read_session() as session:
            return _build_one_bundle(
                session, robinhood_token_symbol,
                dividends_limit, splits_limit, lineage_limit,
            )
    except EquityDBReadError:
        return _unavailable_bundle(
            robinhood_token_symbol, AvailabilityState.SOURCE_UNAVAILABLE
        )


def _build_one_bundle(
    session,
    symbol: str,
    dividends_limit: int,
    splits_limit: int,
    lineage_limit: int,
) -> EquityFundamentalsBundle:
    """Build one bundle within an already-open read session."""
    asset = session.get_asset(symbol)
    if asset is None:
        return _unavailable_bundle(symbol, AvailabilityState.NOT_FOUND)

    canonical_symbol = asset.robinhood_token_symbol
    ticker = asset.underlying_ticker
    profile = session.get_latest_profile(ticker)
    ttm = session.get_latest_snapshot(ticker, "ttm")
    quarterly = session.get_latest_snapshot(ticker, "quarterly")
    annual = session.get_latest_snapshot(ticker, "annual")
    dividends = session.get_dividends(ticker, limit=dividends_limit)
    splits = session.get_splits(ticker, limit=splits_limit)

    best_hash: Optional[str] = None
    for snap in (ttm, quarterly, annual):
        if snap is not None and snap.payload_hash:
            best_hash = snap.payload_hash
            break
    lineage = session.get_lineage(
        ticker, payload_hash=best_hash, limit=lineage_limit
    )
    return EquityFundamentalsBundle(
        robinhood_token_symbol=canonical_symbol,
        asset=asset,
        company_profile=profile,
        latest_ttm=ttm,
        latest_quarterly=quarterly,
        latest_annual=annual,
        recent_dividends=tuple(dividends),
        recent_splits=tuple(splits),
        source_lineage_summary=tuple(lineage),
        availability=_compute_availability(asset, profile, ttm, quarterly, annual),
        freshness=_make_freshness(asset, profile, ttm, quarterly, annual),
    )


def _unavailable_history_bundle(
    robinhood_token_symbol: str,
    state: AvailabilityState,
) -> EquityCompanyHistoryBundle:
    return EquityCompanyHistoryBundle(
        robinhood_token_symbol=robinhood_token_symbol,
        asset=None,
        company_profile=None,
        annual_history=(),
        quarterly_history=(),
        ttm_history=(),
        recent_dividends=(),
        recent_splits=(),
        source_lineage=(),
        availability=state,
        freshness=_make_freshness(None, None, None, None, None),
    )


def get_equity_company_history(
    robinhood_token_symbol: str,
    *,
    db_path: Optional[Path] = None,
    db_mode: Optional[str] = None,
    annual_limit: int = 5,
    quarterly_limit: int = 8,
    ttm_limit: int = 1,
    dividends_limit: int = 20,
    splits_limit: int = 10,
    lineage_limit: int = 10,
) -> EquityCompanyHistoryBundle:
    """Resolve a Robinhood token to a full company history bundle for E3 Terminal.

    One DB session: all financial history (annual, quarterly, TTM), profile,
    dividends, splits, and lineage are read from a single BEGIN DEFERRED
    transaction so all data is internally consistent.

    When the DB is unconfigured or missing, returns SOURCE_UNAVAILABLE.
    When the token is unknown, returns NOT_FOUND.

    No market prices.  No network I/O.  No Robinhood API calls.
    """
    if db_mode is not None:
        db_mode = validate_db_mode(db_mode)

    try:
        path = db_path if db_path is not None else resolve_db_path()
    except (EquityDBNotConfiguredError, EquityDBNotFoundError):
        return _unavailable_history_bundle(
            robinhood_token_symbol, AvailabilityState.SOURCE_UNAVAILABLE
        )

    mode = db_mode if db_mode is not None else resolve_db_mode()

    try:
        repo = EquityFundamentalsRepository(path, mode)
        with repo.read_session() as session:
            asset = session.get_asset(robinhood_token_symbol)
            if asset is None:
                return _unavailable_history_bundle(
                    robinhood_token_symbol, AvailabilityState.NOT_FOUND
                )

            canonical_symbol = asset.robinhood_token_symbol
            ticker = asset.underlying_ticker
            profile = session.get_latest_profile(ticker)
            annual_history = tuple(
                session.get_financial_history(ticker, "annual", limit=annual_limit)
            )
            quarterly_history = tuple(
                session.get_financial_history(ticker, "quarterly", limit=quarterly_limit)
            )
            ttm_history = tuple(
                session.get_financial_history(ticker, "ttm", limit=ttm_limit)
            )
            dividends = session.get_dividends(ticker, limit=dividends_limit)
            splits = session.get_splits(ticker, limit=splits_limit)

            # Lineage: use best hash from TTM, then quarterly, then annual.
            best_ttm = ttm_history[0] if ttm_history else None
            best_quarterly = quarterly_history[0] if quarterly_history else None
            best_annual = annual_history[0] if annual_history else None
            best_hash: Optional[str] = None
            for snap in (best_ttm, best_quarterly, best_annual):
                if snap is not None and snap.payload_hash:
                    best_hash = snap.payload_hash
                    break
            lineage = session.get_lineage(
                ticker, payload_hash=best_hash, limit=lineage_limit
            )

            # Availability: reuse _compute_availability with the latest snapshots.
            latest_ttm = best_ttm
            latest_quarterly = best_quarterly
            latest_annual = best_annual
            availability = _compute_availability(
                asset, profile, latest_ttm, latest_quarterly, latest_annual
            )
            freshness = _make_freshness(
                asset, profile, latest_ttm, latest_quarterly, latest_annual
            )

            return EquityCompanyHistoryBundle(
                robinhood_token_symbol=canonical_symbol,
                asset=asset,
                company_profile=profile,
                annual_history=annual_history,
                quarterly_history=quarterly_history,
                ttm_history=ttm_history,
                recent_dividends=tuple(dividends),
                recent_splits=tuple(splits),
                source_lineage=tuple(lineage),
                availability=availability,
                freshness=freshness,
            )
    except EquityDBReadError:
        return _unavailable_history_bundle(
            robinhood_token_symbol, AvailabilityState.SOURCE_UNAVAILABLE
        )


def get_equity_fundamentals_many(
    robinhood_token_symbols: Sequence[str],
    *,
    db_path: Optional[Path] = None,
    db_mode: Optional[str] = None,
    dividends_limit: int = 20,
    splits_limit: int = 10,
    lineage_limit: int = 10,
) -> Tuple[EquityFundamentalsBundle, ...]:
    """Resolve multiple Robinhood tokens to equity fundamentals bundles.

    One DB configuration resolution, one repository, one read_session,
    one BEGIN DEFERRED snapshot — all requested symbols read from that
    same SQLite snapshot.

    Preserves the input ordering.  Duplicates receive independent results.
    Unknown symbol → NOT_FOUND bundle in its position.

    Raises EquityDBModeError for bad mode (propagates to caller).
    Returns SOURCE_UNAVAILABLE bundles for all positions on DB errors.
    """
    if not robinhood_token_symbols:
        return ()

    if db_mode is not None:
        db_mode = validate_db_mode(db_mode)

    try:
        path = db_path if db_path is not None else resolve_db_path()
    except (EquityDBNotConfiguredError, EquityDBNotFoundError):
        return tuple(
            _unavailable_bundle(sym, AvailabilityState.SOURCE_UNAVAILABLE)
            for sym in robinhood_token_symbols
        )

    mode = db_mode if db_mode is not None else resolve_db_mode()

    try:
        repo = EquityFundamentalsRepository(path, mode)
        with repo.read_session() as session:
            return tuple(
                _build_one_bundle(
                    session, sym,
                    dividends_limit, splits_limit, lineage_limit,
                )
                for sym in robinhood_token_symbols
            )
    except EquityDBReadError:
        return tuple(
            _unavailable_bundle(sym, AvailabilityState.SOURCE_UNAVAILABLE)
            for sym in robinhood_token_symbols
        )
