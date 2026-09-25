"""Canonical country/market options for FINCO Model project setup.

Single source of truth for country codes and display labels.
Used by registry.py (options), input_adapter.py (normalisation),
and nowhere else — DO NOT duplicate this mapping.
"""
from __future__ import annotations

# (iso_code, display_label) — order determines dropdown order.
# XA/XB/XC are pseudo-ISO codes for the three canonical FINCO synthetic-reference markets.
# XA = Solar reference (create_generic_solar_reference, jurisdiction XA-generic-mvp-v1)
# XB = Wind reference  (create_generic_wind_reference, jurisdiction XB-generic-mvp-v1)
# XC = Storage/BESS reference (create_generic_storage_reference, jurisdiction XC-generic-mvp-v1)
# XD = Data Center reference (create_generic_data_center_reference, generic synthetic market XD)
# Real country labels follow "Country Name (ISO)" convention; persisted value is always
# the canonical 2-char code.
COUNTRY_OPTIONS: tuple[tuple[str, str], ...] = (
    ("XA", "Generic / World — Solar (XA)"),
    ("XB", "Generic / World — Wind (XB)"),
    ("XC", "Generic / World — Storage (XC)"),
    ("XD", "Generic / World — Data Center (XD)"),
    ("AT", "Austria (AT)"),
    ("BE", "Belgium (BE)"),
    ("BG", "Bulgaria (BG)"),
    ("CA", "Canada (CA)"),
    ("CL", "Chile (CL)"),
    ("CN", "China (CN)"),
    ("CY", "Cyprus (CY)"),
    ("CZ", "Czechia (CZ)"),
    ("DK", "Denmark (DK)"),
    ("DE", "Germany (DE)"),
    ("ES", "Spain (ES)"),
    ("EE", "Estonia (EE)"),
    ("FI", "Finland (FI)"),
    ("FR", "France (FR)"),
    ("GB", "United Kingdom (GB)"),
    ("GR", "Greece (GR)"),
    ("HR", "Croatia (HR)"),
    ("HU", "Hungary (HU)"),
    ("IE", "Ireland (IE)"),
    ("IN", "India (IN)"),
    ("IS", "Iceland (IS)"),
    ("IL", "Israel (IL)"),
    ("IT", "Italy (IT)"),
    ("JP", "Japan (JP)"),
    ("KR", "South Korea (KR)"),
    ("LT", "Lithuania (LT)"),
    ("LU", "Luxembourg (LU)"),
    ("LV", "Latvia (LV)"),
    ("ME", "Montenegro (ME)"),
    ("MK", "North Macedonia (MK)"),
    ("MX", "Mexico (MX)"),
    ("NL", "Netherlands (NL)"),
    ("NO", "Norway (NO)"),
    ("NZ", "New Zealand (NZ)"),
    ("PL", "Poland (PL)"),
    ("PT", "Portugal (PT)"),
    ("RO", "Romania (RO)"),
    ("RS", "Serbia (RS)"),
    ("SA", "Saudi Arabia (SA)"),
    ("SG", "Singapore (SG)"),
    ("SI", "Slovenia (SI)"),
    ("SK", "Slovakia (SK)"),
    ("SE", "Sweden (SE)"),
    ("CH", "Switzerland (CH)"),
    ("TR", "Türkiye (TR)"),
    ("AE", "United Arab Emirates (AE)"),
    ("US", "United States (US)"),
    ("ZA", "South Africa (ZA)"),
    ("AR", "Argentina (AR)"),
    ("AU", "Australia (AU)"),
    ("BR", "Brazil (BR)"),
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
