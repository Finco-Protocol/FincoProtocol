from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finco_yield.flags import execution_enabled, yield_enabled
from finco_yield.identity import YieldIdentity, canonical_address, yield_opportunity_uid
from finco_yield.ingestion import load_bundled_sample
from finco_yield.schema import ComponentState, ScenarioState, YieldObservation
from finco_yield.underwriting import decompose, run_scenario
from finco_yield.verify import YieldEvidenceRecord, sha256_canonical
from finco_yield.web import router


A = "0x1111111111111111111111111111111111111111"
B = "0x2222222222222222222222222222222222222222"


def test_flags_default_off(monkeypatch):
    monkeypatch.delenv("FINCO_YIELD_ENABLED", raising=False)
    monkeypatch.delenv("FINCO_YIELD_EXECUTION_ENABLED", raising=False)
    assert not yield_enabled()
    assert not execution_enabled()


def test_identity_exact_and_deterministic():
    x = YieldIdentity(8453, "Morpho", "morpho_vault", A, (B,), A)
    y = YieldIdentity(8453, "morpho", "morpho_vault", A, (B,), A)
    assert yield_opportunity_uid(x) == yield_opportunity_uid(y)
    assert yield_opportunity_uid(x) != yield_opportunity_uid(
        YieldIdentity(1, "morpho", "morpho_vault", A, (B,), A)
    )


@pytest.mark.parametrize("bad", ["USDC", "0x1234", "", None])
def test_no_symbol_fuzzy_identity(bad):
    with pytest.raises((ValueError, TypeError)):
        canonical_address(bad)


def test_missing_not_zero_and_component_math():
    assert YieldObservation(None, None).apy_total is None
    observation = YieldObservation(
        Decimal("100"),
        Decimal(".08"),
        Decimal(".05"),
        Decimal(".02"),
        Decimal(".01"),
        Decimal(".005"),
    )
    result = decompose(observation)
    assert result.state == ComponentState.AVAILABLE
    assert result.organic_share == Decimal(".75")
    assert result.reward_dependency == Decimal(".25")
    assert result.reward_off_apy == Decimal(".055")


def test_missing_components_and_not_modelled():
    observation = YieldObservation(Decimal("100"), Decimal(".08"))
    assert decompose(observation).state == ComponentState.COMPONENTS_UNAVAILABLE
    assert run_scenario("REWARDS_OFF", observation).state == ScenarioState.NOT_MODELLED


def test_scenarios():
    observation = YieldObservation(
        Decimal("100"),
        Decimal(".08"),
        Decimal(".05"),
        Decimal(".02"),
        Decimal(".01"),
    )
    assert run_scenario("REWARDS_OFF", observation).apy == Decimal(".06")
    assert run_scenario("REWARDS_MINUS_50", observation).apy == Decimal(".07")


def test_evidence_hash_determinism():
    assert sha256_canonical({"b": 2, "a": 1}) == sha256_canonical({"a": 1, "b": 2})
    record = YieldEvidenceRecord(
        "x", {"a": 1}, {"apy": ".04"}, {"days": 30}, {"out": ".03"}, "y0.1"
    )
    assert record.canonical_output_hash == record.canonical_output_hash


def test_live_sample_14_exact_native_enriched():
    rows = load_bundled_sample()
    assert len(rows) == 14
    assert {row["chain_id"] for row in rows} == {1, 8453}
    for row in rows:
        assert len(row["contract_address"]) == 42
        assert row["source_type"] == "NATIVE_ENRICHED"
        assert row["apy_base"] is None


def test_obsolete_prototype_route_is_explicit_tombstone(monkeypatch):
    monkeypatch.setenv("FINCO_YIELD_ENABLED", "1")
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get("/yield/prototype")
    assert response.status_code == 410
    assert "prototype route was removed" in response.text
