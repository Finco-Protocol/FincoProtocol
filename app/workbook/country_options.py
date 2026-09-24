"""Canonical country/market options for FINCO Model project setup.

Single source of truth for country codes and display labels.
Used by registry.py (options), input_adapter.py (normalisation),
and nowhere else — DO NOT duplicate this mapping.
"""
from __future__ import annotations

# (iso_code, display_label) — order determines dropdown order.
# XA/XB/XC are pseudo-ISO codes for the Generic Market references.
COUNTRY_OPTIONS: tuple[tuple[str, str], ...] = (
    ("XA", "Generic Market A"),
    ("XB", "Generic Market B"),
    ("XC", "Generic Market C"),
    ("DE", "Germany"),
    ("ES", "Spain"),
    ("FR", "France"),
    ("GB", "United Kingdom"),
    ("HR", "HR"),
    ("IT", "Italy"),
    ("PL", "Poland"),
    ("RO", "Romania"),
    ("US", "United States"),
)

COUNTRY_CODES: tuple[str, ...] = tuple(code for code, _ in COUNTRY_OPTIONS)
COUNTRY_CODE_TO_LABEL: dict[str, str] = dict(COUNTRY_OPTIONS)

# Legacy free-text labels that may appear in pre-dropdown snapshots → canonical code.
_LEGACY_ALIASES: dict[str, str] = {
    "generic_market_a": "XA",
    "generic market a": "XA",
    "generic_market_b": "XB",
    "generic market b": "XB",
    "generic_market_c": "XC",
    "generic market c": "XC",
    # "hr"/"hrv" were previously mapped to XA (wrong); now map to HR.
    "hrv": "HR",
    "germany": "DE",
    "deutschland": "DE",
    "france": "FR",
    "spain": "ES",
    "espana": "ES",
    "italy": "IT",
    "italia": "IT",
    "poland": "PL",
    "polska": "PL",
    "romania": "RO",
    "uk": "GB",
    "united kingdom": "GB",
    "great britain": "GB",
    "united states": "US",
    "usa": "US",
}


def normalize_country_code(value: str) -> str:
    """Normalise a raw country string to a canonical 2-char code.

    Canonical dropdown values pass through unchanged.
    Legacy free-text labels are mapped via _LEGACY_ALIASES.
    Falls back to upper()[:2] for unknown but plausible 2-char codes.
    Defaults to "XA" for empty or unrecognisable input.
    """
    stripped = value.strip()
    if not stripped:
        return "XA"
    upper = stripped.upper()
    if upper in COUNTRY_CODE_TO_LABEL:
        return upper
    lower = stripped.lower()
    if lower in _LEGACY_ALIASES:
        return _LEGACY_ALIASES[lower]
    candidate = upper[:2]
    return candidate if len(candidate) == 2 else "XA"
