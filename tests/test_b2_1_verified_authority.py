"""Deterministic B2.1 authority fixtures; no fixture is a production asset."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.radar_rwa.bnb_contracts import BnbRwaMarketObservation
from app.verified.authority import (
    ModelMarketRunBinding, VerificationPolicy, VerifiedAuthorityBundle,
    evaluate_authorities,
)
from app.verified.entitlement import EntitlementState, resolve_verified_entitlement
from finco_radar.assets.contracts import AssetKey
from finco_radar.authority.contracts import (
    AuthoritySnapshot, AuthorityState, BasisPointQuantity, ExecutionGap,
    ExecutionLayer, ReferenceLayer,
)
from finco_radar.authority.cross_chain import CrossChainIdentityBinding
from finco_radar.tokenization_premium.contracts import (
    TokenizationPremiumObservation, TokenizationPremiumStatus,
)


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
UID = "0x" + "a" * 64
OTHER_UID = "0x" + "b" * 64
KEY = AssetKey(56, "0x" + "1" * 40)
OTHER_KEY = AssetKey(56, "0x" + "2" * 40)
POLICY = VerificationPolicy(approved_binding_sources=frozenset({"TEST_ATTESTATION"}))
CERT = {
    "certificate_digest_sha256": "c" * 64,
    "identity": {"composite_hash": "d" * 64},
}


def _bundle():
    binding = ModelMarketRunBinding(
        "fixture_asset", "fixture_project", "c" * 64, "d" * 64,
        UID, KEY, "fixture-evidence-1", "TEST_ATTESTATION", NOW,
    )
    identity = CrossChainIdentityBinding(
        AuthorityState.AVAILABLE, KEY, UID, (KEY,),
        "ROBINHOOD_STOCK_TOKEN_ASSETS_API:LIVE", NOW, None,
    )
    market = BnbRwaMarketObservation(
        provider_id="fixture-provider-id", symbol="TEST", name="Fixture",
        asset_key=KEY, deployment_reason=None, observed_at=NOW,
        state=AuthorityState.AVAILABLE, price_usd=Decimal("12.5"),
        market_cap_usd=None, volume_24h_usd=None, price_change_24h_pct=None,
        circulating_supply=None, total_supply=None, unavailable_fields=(),
    )
    underlying = ReferenceLayer(
        AuthorityState.AVAILABLE, UID, KEY, "underlying", Decimal("10"),
        "TEST_REFERENCE", NOW,
    )
    token = ReferenceLayer(
        AuthorityState.AVAILABLE, UID, KEY, "independent token reference",
        Decimal("12"), "TEST_TOKEN_REFERENCE", NOW,
    )
    premium_quantity = BasisPointQuantity(
        AuthorityState.AVAILABLE, Decimal("2000"), Decimal("12"),
        Decimal("10"), "TEST_ONLY", ("TEST_REFERENCE", "TEST_TOKEN_REFERENCE"),
        (NOW, NOW),
    )
    execution = ExecutionLayer(
        AuthorityState.UNAVAILABLE, KEY, None, None, None, None, None,
        None, None, None, "NO_EXECUTION_QUOTE",
    )
    gap = ExecutionGap(AuthorityState.UNAVAILABLE, None, None, None,
                       "UNAVAILABLE", "NO_EXECUTION_QUOTE")
    radar = AuthoritySnapshot(UID, KEY, "ROBINHOOD_STOCK_TOKEN_ASSETS_API:LIVE",
                              NOW, underlying, token, premium_quantity, execution, gap)
    p2 = TokenizationPremiumObservation(
        status=TokenizationPremiumStatus.TOKENIZATION_PREMIUM_OK,
        underlying_raw_bid_usd_per_share=Decimal("9"),
        underlying_raw_ask_usd_per_share=Decimal("11"),
        underlying_raw_mid_usd_per_share=Decimal("10"),
        current_multiplier=Decimal("1"),
        underlying_token_basis_usd_per_token=Decimal("10"),
        buy_execution_price_usd_per_token=Decimal("12"),
        sell_execution_price_usd_per_token=Decimal("12"),
        execution_mid_price_usd_per_token=Decimal("12"),
        tokenization_premium_bps=Decimal("2000"),
        buy_execution_premium_bps=Decimal("2000"),
        sell_execution_premium_bps=Decimal("2000"),
        reference_observed_at=NOW, buy_quote_observed_at=NOW,
        sell_quote_observed_at=NOW,
    )
    return VerifiedAuthorityBundle(binding, identity, market, radar, p2)


def _result(bundle, *, as_of=NOW, policy=POLICY, certificate=CERT):
    return evaluate_authorities(
        asset_id="fixture_asset", project_code="fixture_project",
        certificate=certificate, bundle=bundle, as_of=as_of, policy=policy,
    )


def test_complete_fixture_is_verified_and_deterministic():
    bundle = _bundle()
    assert _result(bundle) == ("VERIFIED", None)
    assert _result(bundle) == _result(bundle)


def test_complete_fixture_through_canonical_certificate_and_composer():
    from app.verified.composer import build_verified_asset
    from app.verified.contracts import VerifiedAssetDefinition, VerifiedAssetStatus
    from app.verify.run_certificate import verify_certificate_digest

    asset = VerifiedAssetDefinition(asset_id="fixture_asset", display_name="Fixture",
                                    asset_type="Test", template_source="fixture_project",
                                    description="Test only")
    project = SimpleNamespace(project_code="fixture_project", project_name="Fixture")
    ws = SimpleNamespace(
        any_run_committed=True, last_runtime_at=NOW,
        last_runtime_origin="canonical_reference", last_runtime_snapshot_id="snapshot-1",
        last_runtime_composite_hash="d" * 64, last_runtime_scenario_id=None,
        last_runtime_identity={"engine_version": "fixture-engine", "scenario_name": "Base"},
        last_runtime_summary={"project_irr": 0.1}, last_runtime_snapshot={"input": 1},
        last_financial_statements={}, last_debt_schedule={}, last_tax_schedule={},
        last_distribution_schedule={}, last_sponsor_schedule={},
    )
    model_only = build_verified_asset(asset, project, ws)
    certificate = model_only["certificate"]
    assert verify_certificate_digest(certificate)
    bundle = _bundle()
    bundle = replace(bundle, binding=replace(
        bundle.binding, certificate_digest_sha256=certificate["certificate_digest_sha256"],
    ))
    verified = build_verified_asset(asset, project, ws, authority_bundle=bundle,
                                    as_of=NOW, verification_policy=POLICY)
    assert verified["status"] is VerifiedAssetStatus.VERIFIED
    assert verified["verify"]["certificate_id"] == certificate["certificate_id"]
    assert verified["evidence"]["run_certificate_digest_sha256"] == certificate["certificate_digest_sha256"]
    assert verified["identity"]["economic_asset_uid"] == UID
    assert verified["market_observation"]["provider"] == "CoinGecko"


def test_model_only_without_explicit_economic_binding():
    assert _result(None) == ("MODEL_ONLY", "MODEL_MARKET_BINDING_UNAVAILABLE")


def test_wrong_run_or_evidence_digest_fails_closed():
    bundle = _bundle()
    bad = replace(bundle, binding=replace(bundle.binding, certificate_digest_sha256="e" * 64))
    assert _result(bad)[0] == "IDENTITY_MISMATCH"


def test_wrong_economic_uid_and_conflicting_identity_fail_closed():
    bundle = _bundle()
    conflicting = replace(bundle, identity=replace(bundle.identity, economic_asset_uid=OTHER_UID))
    assert _result(conflicting)[0] == "IDENTITY_MISMATCH"
    conflicting_radar = replace(bundle, radar=replace(bundle.radar, economic_asset_uid=OTHER_UID))
    assert _result(conflicting_radar)[0] == "IDENTITY_MISMATCH"


def test_wrong_deployment_fails_closed_even_with_same_symbol():
    bundle = _bundle()
    changed = replace(bundle, market=replace(bundle.market, asset_key=OTHER_KEY))
    assert _result(changed) == ("IDENTITY_MISMATCH", "MARKET_DEPLOYMENT_MISMATCH")


def test_coingecko_only_or_unapproved_source_cannot_establish_identity():
    bundle = _bundle()
    no_registry = replace(bundle, identity=CrossChainIdentityBinding(
        AuthorityState.IDENTITY_UNAVAILABLE, KEY, None, (), None, None,
        "ROBINHOOD_REGISTRY_UNAVAILABLE",
    ))
    assert _result(no_registry)[0] == "MODEL_ONLY"
    unapproved = replace(bundle, binding=replace(bundle.binding, source="CoinGecko"))
    assert _result(unapproved)[0] == "MODEL_ONLY"


def test_stale_or_missing_market_observation_is_never_verified():
    bundle = _bundle()
    assert _result(bundle, as_of=NOW + timedelta(hours=2)) == ("STALE", "MARKET_STALE")
    missing = replace(bundle, market=replace(bundle.market, price_usd=None))
    assert _result(missing) == ("MODEL_ONLY", "MARKET_OBSERVATION_UNAVAILABLE")


def test_reference_and_premium_required_independently_of_execution():
    bundle = _bundle()
    missing_ref = replace(bundle, radar=replace(bundle.radar, token=replace(
        bundle.radar.token, state=AuthorityState.UNAVAILABLE)))
    assert _result(missing_ref)[0] == "MODEL_ONLY"
    missing_p2 = replace(bundle, premium=replace(
        bundle.premium, status=TokenizationPremiumStatus.TOKEN_MARKET_REFERENCE_UNAVAILABLE))
    assert _result(missing_p2)[0] == "MODEL_ONLY"
    assert _result(bundle)[0] == "VERIFIED"  # execution layer may remain unavailable


def test_missing_last_run_is_unavailable_in_canonical_composer():
    from app.verified.composer import build_verified_asset
    from app.verified.contracts import VerifiedAssetDefinition
    asset = VerifiedAssetDefinition(asset_id="fixture_asset", display_name="Fixture",
                                    asset_type="Test", template_source="fixture_project",
                                    description="Test only")
    ws = MagicMock()
    ws.any_run_committed = False
    ws.last_runtime_summary = {}
    ws.last_runtime_at = None
    ws.last_runtime_origin = None
    project = SimpleNamespace(project_code="fixture_project", project_name="Fixture")
    assert build_verified_asset(asset, project, ws, authority_bundle=_bundle(), as_of=NOW)["status"].value == "UNAVAILABLE"


def test_entitlement_isolation_and_production_registry_has_no_binding():
    from app.verified.asset_registry import list_asset_definitions
    active = resolve_verified_entitlement(
        SimpleNamespace(user_id="staff", session_type="admin"),
        allowed_subject_ids=frozenset({"staff"}),
    )
    inactive = resolve_verified_entitlement(
        SimpleNamespace(user_id="demo", session_type="demo"),
        allowed_subject_ids=frozenset({"demo"}),
    )
    assert active.state is EntitlementState.ACTIVE
    assert inactive.state is EntitlementState.INACTIVE
    assert _result(_bundle()) == _result(_bundle())  # entitlement is not an input
    assert all(not hasattr(asset, "economic_asset_uid") for asset in list_asset_definitions())
    assert len(list_asset_definitions()) == 2


def test_api_artifact_entitlement_and_public_truth(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import app.auth as auth
    import app.verified.entitlement as entitlement_module
    import app.verified.router as verified_router

    subject = SimpleNamespace(user_id="staff", session_type="admin")
    monkeypatch.setattr(auth, "resolve_request_session", lambda request: subject)
    monkeypatch.setattr(verified_router, "_load_verified_asset", lambda asset_id: {
        "found": True,
        "record": {
            "schema": "FINCO_VERIFIED_ASSET_V1", "asset_id": asset_id,
            "status": "VERIFIED", "verification": {"status": "VERIFIED", "reason": None},
            "model": {"headline_outputs": {"project_irr": 0.1}},
            "evidence": {"evidence_id": "fixture-evidence-1"},
            "identity": {"economic_asset_uid": UID},
            "market_observation": {"provider": "CoinGecko"},
            "certificate": CERT,
        },
    })
    allowed = set()
    monkeypatch.setattr(
        entitlement_module, "resolve_verified_entitlement",
        lambda session: resolve_verified_entitlement(
            session, allowed_subject_ids=frozenset(allowed)),
    )
    app = FastAPI()
    app.include_router(verified_router.router)
    client = TestClient(app)
    public_before = client.get("/verified/fixture_asset.json")
    assert public_before.status_code == 200
    assert public_before.json()["verification"]["status"] == "VERIFIED"
    assert public_before.json()["entitlement"]["state"] == "INACTIVE"
    assert "certificate" not in public_before.json()
    assert client.get("/verified/fixture_asset/dossier.json").status_code == 403
    allowed.add("staff")
    public_after = client.get("/verified/fixture_asset.json")
    assert public_after.json()["verification"] == public_before.json()["verification"]
    assert public_after.json()["model"] == public_before.json()["model"]
    assert public_after.json()["evidence"] == public_before.json()["evidence"]
    assert public_after.json()["identity"] == public_before.json()["identity"]
    assert public_after.json()["market_observation"] == public_before.json()["market_observation"]
    dossier = client.get("/verified/fixture_asset/dossier.json")
    assert dossier.status_code == 200
    assert dossier.json()["certificate"] == CERT


def test_verified_html_truth_and_entitlement_surface(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import app.auth as auth
    import app.verified.router as verified_router
    from app.verified.contracts import STATUS_DISPLAY, VerifiedAssetStatus

    monkeypatch.setattr(auth, "resolve_request_session", lambda request: SimpleNamespace(
        user_id="demo", session_type="demo"))
    record = {
        "asset_id": "generic_solar_reference",
        "display_name": "Generic Solar Reference",
        "asset_type": "Solar PPA",
        "description": "Reference model",
        "status": VerifiedAssetStatus.MODEL_ONLY,
        "status_display": STATUS_DISPLAY[VerifiedAssetStatus.MODEL_ONLY],
        "verification": {"status": "MODEL_ONLY", "reason": "MODEL_MARKET_BINDING_UNAVAILABLE"},
        "model": {"headline_outputs": {}, "last_runtime_at": NOW.isoformat(),
                  "last_runtime_origin": "canonical_reference"},
        "verify": None, "market": None, "evidence": None, "identity": None,
        "protocol": None, "error": None,
    }
    monkeypatch.setattr(verified_router, "_load_verified_asset", lambda asset_id: {
        "found": True, "record": record,
    })
    monkeypatch.setattr(verified_router, "_load_all_verified_assets", lambda: [record])
    app = FastAPI()
    app.include_router(verified_router.router)
    client = TestClient(app)
    detail = client.get("/verified/generic_solar_reference")
    assert detail.status_code == 200
    assert "MODEL_MARKET_BINDING_UNAVAILABLE" in detail.text
    assert "Dossier access" in detail.text
    assert "INACTIVE" in detail.text
    assert "Full evidence dossier" not in detail.text
    index = client.get("/verified")
    assert index.status_code == 200
    assert "0 VERIFIED" in index.text
