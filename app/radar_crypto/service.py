"""Read-only dashboard composition for Radar Crypto Overview."""
from __future__ import annotations

from datetime import datetime, timezone

from app.radar_crypto.coingecko import CoinGeckoCryptoProvider
from app.radar_crypto.contracts import CryptoObservation, CryptoSection, CryptoState
from app.radar_crypto.registry import SERIES, metrics_for_section

_SECTION_TITLES = {
    CryptoSection.MARKET_OVERVIEW: "Market Overview",
    CryptoSection.MAJOR_ASSETS: "Major Assets",
}


def _compact_usd(value: float) -> str:
    absolute = abs(value)
    if absolute >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f}T"
    if absolute >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if absolute >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    return f"${value:,.0f}"


def _display(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "usd_compact":
        return _compact_usd(value)
    if unit == "usd_price":
        return f"${value:,.2f}"
    if unit == "percent":
        return f"{value:.2f}%"
    if unit == "count":
        return f"{value:,.0f}"
    if unit == "ratio":
        return f"{value:.5f}"
    return f"{value:,.2f}"


def _change_display(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:+.2f}%"


def _binding_mismatch(definition, retrieved_at: datetime) -> CryptoObservation:
    return CryptoObservation(
        key=definition.key,
        state=CryptoState.UNAVAILABLE,
        value=None,
        change_24h=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source_endpoint=definition.source_endpoint,
        source_id=definition.source_id,
        publisher=definition.publisher,
        transport=definition.transport,
        reason="SOURCE_BINDING_MISMATCH",
    )


def _row(definition, observation: CryptoObservation) -> dict:
    return {
        "key": definition.key,
        "title": definition.title,
        "state": observation.state.value,
        "value": observation.value,
        "value_display": _display(observation.value, definition.unit),
        "change_24h": observation.change_24h,
        "change_24h_display": _change_display(observation.change_24h),
        "observed_at": observation.observed_at.isoformat() if observation.observed_at else None,
        "retrieved_at": observation.retrieved_at.isoformat(),
        "unit": definition.unit,
        "source_endpoint": definition.source_endpoint,
        "source_id": definition.source_id,
        "publisher": definition.publisher,
        "transport": definition.transport,
        "source_url": definition.source_url,
        "reason": observation.reason,
    }


class CryptoDashboardService:
    def __init__(self, provider=None) -> None:
        self.provider = provider or CoinGeckoCryptoProvider()

    def read_dashboard(self) -> dict:
        try:
            observations = self.provider.read_all(SERIES)
        except Exception as exc:  # injectable providers must fail closed too
            now = datetime.now(timezone.utc)
            observations = tuple(
                CryptoObservation(
                    key=definition.key,
                    state=CryptoState.UNAVAILABLE,
                    value=None,
                    change_24h=None,
                    observed_at=None,
                    retrieved_at=now,
                    source_endpoint=definition.source_endpoint,
                    source_id=definition.source_id,
                    publisher=definition.publisher,
                    transport=definition.transport,
                    reason=f"PROVIDER_READ_FAILED:{type(exc).__name__}",
                )
                for definition in SERIES
            )

        by_key: dict[str, CryptoObservation] = {}
        for definition, observation in zip(SERIES, observations):
            if (
                observation.key != definition.key
                or observation.source_endpoint != definition.source_endpoint
                or observation.source_id != definition.source_id
                or observation.publisher != definition.publisher
                or observation.transport != definition.transport
            ):
                observation = _binding_mismatch(definition, observation.retrieved_at)
            by_key[definition.key] = observation

        # Missing/duplicate provider rows are not allowed to become implicit data.
        for definition in SERIES:
            if definition.key not in by_key:
                by_key[definition.key] = _binding_mismatch(
                    definition, datetime.now(timezone.utc))

        sections = []
        for section in CryptoSection:
            definitions = metrics_for_section(section)
            rows = [_row(definition, by_key[definition.key]) for definition in definitions]
            sections.append({
                "key": section.value,
                "title": _SECTION_TITLES[section],
                "rows": rows,
            })

        states = [by_key[definition.key].state for definition in SERIES]
        fresh = sum(state is CryptoState.FRESH for state in states)
        stale = sum(state is CryptoState.STALE for state in states)
        unavailable = sum(state is CryptoState.UNAVAILABLE for state in states)
        overall = (
            "STALE" if stale else
            "PARTIAL" if fresh and unavailable else
            "FRESH" if fresh else
            "UNAVAILABLE"
        )
        return {
            "state": overall,
            "metric_count": len(SERIES),
            "fresh_count": fresh,
            "stale_count": stale,
            "unavailable_count": unavailable,
            "sections": sections,
        }
