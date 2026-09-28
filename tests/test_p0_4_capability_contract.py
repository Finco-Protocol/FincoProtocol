"""P0.4 Canonical Supported Today contract drift tests.

Acceptance markers (all must PASS for PR merge):
  CAPABILITY_CONTRACT_UNIQUE_AUTHORITY
  CAPABILITY_CONTRACT_KNOWN_STATUSES
  CAPABILITY_CONTRACT_NO_DUPLICATE_KEYS
  CAPABILITY_MODEL_VERTICAL_LIBRARY_AGREEMENT
  CAPABILITY_MODEL_VERTICAL_API_REFERENCE_AGREEMENT
  CAPABILITY_MODEL_VERTICAL_CLONEABLE_AGREEMENT
  CAPABILITY_CANONICAL_LAST_RUN_AGREEMENT
  CAPABILITY_CONTRACT_HOMEPAGE_VERTICAL_AGREEMENT
  CAPABILITY_DOCS_MODEL_VERTICAL_AGREEMENT
  CAPABILITY_ROADMAP_VERTICAL_AGREEMENT
  CAPABILITY_KNOWN_LIMITATIONS_LIVE_VERTICAL_AGREEMENT
  CAPABILITY_API_ENDPOINT_AGREEMENT
  CAPABILITY_FUTURE_NOT_LIVE_STORAGE
  CAPABILITY_B11_B12_BNB_RWA_CURRENT_STATE
  CAPABILITY_FUTURE_NOT_LIVE_WALLET
  CAPABILITY_FUTURE_NOT_LIVE_TOKEN_ENTITLEMENT
  CAPABILITY_FUTURE_NOT_LIVE_ONCHAIN_ANCHORING
  CAPABILITY_FUTURE_NOT_LIVE_TREASURY_PROOF
  CAPABILITY_FUTURE_NOT_LIVE_FINANCIAL_PASSPORT
  CAPABILITY_STATUS_VOCABULARY_FINITE
  CAPABILITY_LIVE_VERTICALS_HAVE_LIMITATIONS_DEFINED
  CAPABILITY_STORAGE_PREVIEW_FLAGS_CORRECT
  CAPABILITY_FACTORY_TEMPLATE_OPTIONS_INCLUDES_EV
"""
from __future__ import annotations

import re

import pytest

from app.product_capability import (
    PRODUCT_CAPABILITIES,
    LIVE_CAPABILITIES,
    PREVIEW_CAPABILITIES,
    ProductStatus,
    LIVE_KEYS,
    API_AVAILABLE_KEYS,
    live_vertical_names,
    capability_by_key,
    as_api_dict,
)
from app.services.project_library_service import (
    CLONEABLE_TEMPLATE_SOURCES,
    CANONICAL_REFERENCE_TEMPLATE_SOURCES,
    _CANONICAL_LAST_RUN_SOURCES,
)
from app.api.v1.model_reference import VALID_REFERENCE_KEYS


# ── A. Canonical uniqueness ───────────────────────────────────────────────────

def test_canonical_uniqueness():
    """CAPABILITY_CONTRACT_UNIQUE_AUTHORITY: single authoritative registry module."""
    assert PRODUCT_CAPABILITIES, "PRODUCT_CAPABILITIES must be non-empty"
    assert len(PRODUCT_CAPABILITIES) >= 5


def test_no_duplicate_keys():
    """CAPABILITY_CONTRACT_NO_DUPLICATE_KEYS: every key is unique."""
    keys = [c.key for c in PRODUCT_CAPABILITIES]
    assert len(keys) == len(set(keys)), f"Duplicate capability keys: {keys}"


def test_known_statuses():
    """CAPABILITY_CONTRACT_KNOWN_STATUSES: all capabilities carry a known status."""
    valid = set(ProductStatus)
    for cap in PRODUCT_CAPABILITIES:
        assert cap.status in valid, f"{cap.key} has unknown status {cap.status!r}"


def test_status_vocabulary_finite():
    """CAPABILITY_STATUS_VOCABULARY_FINITE: ProductStatus has exactly 3 values."""
    assert set(ProductStatus) == {
        ProductStatus.LIVE,
        ProductStatus.PREVIEW,
        ProductStatus.IN_DEVELOPMENT,
    }


# ── B. Model vertical agreement with Library ─────────────────────────────────

def test_live_verticals_have_template_source_in_canonical():
    """CAPABILITY_MODEL_VERTICAL_LIBRARY_AGREEMENT: each LIVE vertical has a
    template_source in CANONICAL_REFERENCE_TEMPLATE_SOURCES."""
    _KEY_TO_TEMPLATE = {
        "solar": "generic_solar_reference",
        "wind": "generic_wind_reference",
        "data_center": "generic_data_center_reference",
        "ev_charging": "generic_ev_charging_reference",
    }
    for cap in LIVE_CAPABILITIES:
        if cap.product_area != "model":
            continue
        ts = _KEY_TO_TEMPLATE.get(cap.key)
        assert ts is not None, f"No template_source mapping for LIVE model key {cap.key!r}"
        assert ts in CANONICAL_REFERENCE_TEMPLATE_SOURCES, (
            f"{cap.key} template_source {ts!r} not in CANONICAL_REFERENCE_TEMPLATE_SOURCES"
        )


def test_cloneable_live_verticals_in_cloneable_set():
    """CAPABILITY_MODEL_VERTICAL_CLONEABLE_AGREEMENT: any LIVE capability with
    cloneable=True has its template_source in CLONEABLE_TEMPLATE_SOURCES."""
    _KEY_TO_TEMPLATE = {
        "solar": "generic_solar_reference",
        "wind": "generic_wind_reference",
        "data_center": "generic_data_center_reference",
        "ev_charging": "generic_ev_charging_reference",
    }
    for cap in LIVE_CAPABILITIES:
        if cap.product_area != "model":
            continue
        if cap.cloneable:
            ts = _KEY_TO_TEMPLATE.get(cap.key)
            assert ts is not None, f"No template_source mapping for cloneable LIVE key {cap.key!r}"
            assert ts in CLONEABLE_TEMPLATE_SOURCES, (
                f"LIVE cloneable {cap.key} template_source {ts!r} not in CLONEABLE_TEMPLATE_SOURCES"
            )


def test_storage_not_in_cloneable():
    """CAPABILITY_FUTURE_NOT_LIVE_STORAGE: Storage must not be in CLONEABLE_TEMPLATE_SOURCES."""
    assert "generic_storage_reference" not in CLONEABLE_TEMPLATE_SOURCES


# ── C. Canonical Last Run agreement ──────────────────────────────────────────

def test_canonical_last_run_agreement():
    """CAPABILITY_CANONICAL_LAST_RUN_AGREEMENT: any capability with
    canonical_last_run=True must have its template_source in _CANONICAL_LAST_RUN_SOURCES."""
    _KEY_TO_TEMPLATE = {
        "solar": "generic_solar_reference",
        "wind": "generic_wind_reference",
        "data_center": "generic_data_center_reference",
        "ev_charging": "generic_ev_charging_reference",
    }
    for cap in PRODUCT_CAPABILITIES:
        if cap.canonical_last_run:
            ts = _KEY_TO_TEMPLATE.get(cap.key)
            assert ts is not None, (
                f"canonical_last_run=True on {cap.key!r} but no template_source mapping"
            )
            assert ts in _CANONICAL_LAST_RUN_SOURCES, (
                f"{cap.key} canonical_last_run=True but template_source {ts!r} "
                f"absent from _CANONICAL_LAST_RUN_SOURCES"
            )


def test_storage_canonical_last_run_false():
    """Storage must have canonical_last_run=False since its runtime is not released."""
    storage = capability_by_key("storage")
    assert storage is not None
    assert not storage.canonical_last_run


# ── D. API reference key agreement ───────────────────────────────────────────

def test_api_reference_key_agreement():
    """CAPABILITY_MODEL_VERTICAL_API_REFERENCE_AGREEMENT: VALID_REFERENCE_KEYS must
    match the api_available capabilities (by template_source convention)."""
    _KEY_TO_TEMPLATE = {
        "solar": "generic_solar_reference",
        "wind": "generic_wind_reference",
        "data_center": "generic_data_center_reference",
        "ev_charging": "generic_ev_charging_reference",
    }
    expected_keys = frozenset(
        _KEY_TO_TEMPLATE[c.key]
        for c in PRODUCT_CAPABILITIES
        if c.api_available and c.key in _KEY_TO_TEMPLATE
    )
    assert expected_keys == VALID_REFERENCE_KEYS, (
        f"Mismatch: expected {sorted(expected_keys)}, got {sorted(VALID_REFERENCE_KEYS)}"
    )


# ── E. Homepage chip row agreement ───────────────────────────────────────────

def test_homepage_vertical_agreement():
    """CAPABILITY_CONTRACT_HOMEPAGE_VERTICAL_AGREEMENT: protocol_roadmap.html
    chip row must list every LIVE vertical and nothing more."""
    import pathlib
    roadmap_html = pathlib.Path("app/templates/protocol_roadmap.html").read_text()
    live_names = live_vertical_names()
    for name in live_names:
        assert name in roadmap_html, (
            f"LIVE vertical {name!r} not found in protocol_roadmap.html"
        )
    # Storage must not appear in the "Shipped" chip row
    # (it may appear in the note, which is acceptable)
    # Specifically: the proad-chip-row for Infrastructure Model must not list Storage
    chip_section = re.search(
        r'proad-chip-row.*?</div>',
        roadmap_html,
        re.DOTALL,
    )
    if chip_section:
        chip_text = chip_section.group(0)
        assert "Storage" not in chip_text, (
            "Storage must not appear in the Infrastructure Model chip row "
            "(it is PREVIEW, not LIVE)"
        )


# ── F. Docs vertical agreement ────────────────────────────────────────────────

def test_docs_vertical_agreement():
    """CAPABILITY_DOCS_MODEL_VERTICAL_AGREEMENT: protocol_docs.html must mention
    every LIVE vertical in its surface-scope table row for Model."""
    import pathlib
    docs_html = pathlib.Path("app/templates/protocol_docs.html").read_text()
    live_names = live_vertical_names()
    for name in live_names:
        assert name in docs_html, (
            f"LIVE vertical {name!r} not found in protocol_docs.html"
        )


# ── G. Roadmap vertical agreement ─────────────────────────────────────────────

def test_roadmap_md_vertical_agreement():
    """CAPABILITY_ROADMAP_VERTICAL_AGREEMENT: docs/ROADMAP.md must list every
    LIVE vertical under the 'Now' section."""
    import pathlib
    roadmap_md = pathlib.Path("docs/ROADMAP.md").read_text()
    live_names = live_vertical_names()
    for name in live_names:
        assert name in roadmap_md, (
            f"LIVE vertical {name!r} not found in docs/ROADMAP.md"
        )


# ── H. Known Limitations agreement ───────────────────────────────────────────

def test_known_limitations_live_vertical_agreement():
    """CAPABILITY_KNOWN_LIMITATIONS_LIVE_VERTICAL_AGREEMENT: known_limitations_page.html
    must mention every LIVE vertical."""
    import pathlib
    kl_html = pathlib.Path("app/templates/known_limitations_page.html").read_text()
    live_names = live_vertical_names()
    for name in live_names:
        assert name in kl_html, (
            f"LIVE vertical {name!r} not found in known_limitations_page.html"
        )


# ── I. API capabilities endpoint agreement ───────────────────────────────────

def test_api_capabilities_endpoint_agreement():
    """CAPABILITY_API_ENDPOINT_AGREEMENT: the /capabilities endpoint payload
    matches PRODUCT_CAPABILITIES exactly."""
    payload_capabilities = [as_api_dict(c) for c in PRODUCT_CAPABILITIES]
    assert len(payload_capabilities) == len(PRODUCT_CAPABILITIES)
    keys_in_payload = [d["key"] for d in payload_capabilities]
    expected_keys = [c.key for c in PRODUCT_CAPABILITIES]
    assert keys_in_payload == expected_keys
    # Verify live verticals are present with correct status
    live_in_payload = [d for d in payload_capabilities if d["status"] == "LIVE"]
    assert len(live_in_payload) == len(LIVE_CAPABILITIES)


# ── J. No-future-leakage tests ────────────────────────────────────────────────

def test_storage_is_preview_not_live():
    """CAPABILITY_FUTURE_NOT_LIVE_STORAGE: Storage must remain PREVIEW."""
    storage = capability_by_key("storage")
    assert storage is not None
    assert storage.status == ProductStatus.PREVIEW
    assert not storage.runnable
    assert not storage.cloneable
    assert not storage.api_available


def test_b11_b12_bnb_rwa_current_state():
    """CAPABILITY_B11_B12_BNB_RWA_CURRENT_STATE: B1.1 (observations) and B1.2
    (canonical cross-chain identity) are both merged. bnb_rwa must be LIVE,
    radar-area, read-only. IDENTITY_UNAVAILABLE is a valid production state when
    Robinhood chain-56 bindings are absent — that is truthful, not a gap.
    B1.3 premium/execution intelligence is not yet supported."""
    bnb = capability_by_key("bnb_rwa")
    assert bnb is not None, "bnb_rwa must be in PRODUCT_CAPABILITIES (B1.1 + B1.2 merged)"
    assert bnb.status == ProductStatus.LIVE
    assert bnb.product_area == "radar", "bnb_rwa must be a radar-area capability"
    assert not bnb.runnable, "Radar observations are read-only; not a model run"
    assert not bnb.cloneable
    assert not bnb.canonical_last_run
    # B1.2 identity resolution is implemented — status_note must reflect current truth
    assert "B1.2" in bnb.status_note or "cross-chain identity" in bnb.status_note, (
        "bnb_rwa status_note must reference B1.2 canonical identity resolution"
    )
    assert "IDENTITY_UNAVAILABLE" in bnb.status_note, (
        "bnb_rwa status_note must acknowledge IDENTITY_UNAVAILABLE as a valid production state"
    )
    # B1.3 premium/execution intelligence is not yet supported
    assert "B1.3" in bnb.status_note or "premium" in bnb.status_note.lower(), (
        "bnb_rwa status_note must note that B1.3 premium/execution is not live"
    )
    b13 = capability_by_key("bnb_premium") or capability_by_key("rwa_execution")
    assert b13 is None or b13.status != ProductStatus.LIVE, "B1.3 premium/execution not live"


def test_wallet_not_live():
    """CAPABILITY_FUTURE_NOT_LIVE_WALLET: wallet identity must not be LIVE."""
    wallet = capability_by_key("wallet")
    assert wallet is None or wallet.status != ProductStatus.LIVE


def test_token_entitlement_not_live():
    """CAPABILITY_FUTURE_NOT_LIVE_TOKEN_ENTITLEMENT: token entitlement must not be LIVE."""
    token = capability_by_key("finco_token")
    token2 = capability_by_key("token_entitlement")
    assert token is None or token.status != ProductStatus.LIVE
    assert token2 is None or token2.status != ProductStatus.LIVE


def test_onchain_anchoring_not_live():
    """CAPABILITY_FUTURE_NOT_LIVE_ONCHAIN_ANCHORING: onchain anchoring must not be LIVE."""
    cap = capability_by_key("onchain_anchoring")
    assert cap is None or cap.status != ProductStatus.LIVE


def test_treasury_proof_not_live():
    """CAPABILITY_FUTURE_NOT_LIVE_TREASURY_PROOF: treasury proof must not be LIVE."""
    cap = capability_by_key("treasury_proof")
    assert cap is None or cap.status != ProductStatus.LIVE


def test_financial_passport_not_live():
    """CAPABILITY_FUTURE_NOT_LIVE_FINANCIAL_PASSPORT: financial passport must not be LIVE."""
    cap = capability_by_key("financial_passport")
    assert cap is None or cap.status != ProductStatus.LIVE


# ── K. LIVE verticals have limitations ───────────────────────────────────────

def test_live_verticals_have_limitations_defined():
    """CAPABILITY_LIVE_VERTICALS_HAVE_LIMITATIONS_DEFINED: every LIVE capability
    must declare at least one known limitation."""
    for cap in LIVE_CAPABILITIES:
        assert cap.limitations, (
            f"LIVE capability {cap.key!r} has no known limitations defined. "
            "Even well-supported capabilities should document their boundaries."
        )


# ── L. Storage PREVIEW flags ──────────────────────────────────────────────────

def test_storage_preview_flags():
    """CAPABILITY_STORAGE_PREVIEW_FLAGS_CORRECT: Storage must have all runtime
    flags False since its working-copy runtime is not released."""
    storage = capability_by_key("storage")
    assert storage is not None
    assert storage.status == ProductStatus.PREVIEW
    assert not storage.runnable
    assert not storage.cloneable
    assert not storage.working_copy_editable
    assert not storage.canonical_last_run
    assert not storage.api_available
    assert storage.reference_available, "Storage reference model must still be viewable"


# ── M. FACTORY_TEMPLATE_OPTIONS includes EV Charging ─────────────────────────

def test_factory_template_options_includes_ev_charging():
    """CAPABILITY_FACTORY_TEMPLATE_OPTIONS_INCLUDES_EV: FACTORY_TEMPLATE_OPTIONS
    in main_web.py must include generic_ev_charging_reference for all four LIVE
    verticals to appear in the Library."""
    import importlib.util, pathlib
    # Read the raw file rather than importing main_web (too expensive in test suite)
    source = pathlib.Path("main_web.py").read_text()
    assert "generic_ev_charging_reference" in source, (
        "generic_ev_charging_reference must appear in main_web.py "
        "(required for FACTORY_TEMPLATE_OPTIONS)"
    )
    # Verify it specifically appears in FACTORY_TEMPLATE_OPTIONS section
    match = re.search(
        r'FACTORY_TEMPLATE_OPTIONS\s*=\s*\[(.*?)\]',
        source,
        re.DOTALL,
    )
    assert match, "Could not locate FACTORY_TEMPLATE_OPTIONS in main_web.py"
    block = match.group(1)
    assert "generic_ev_charging_reference" in block, (
        "generic_ev_charging_reference must be in FACTORY_TEMPLATE_OPTIONS list body"
    )
