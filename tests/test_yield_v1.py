from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from finco_yield.evidence_v1 import (
    YieldPostTradeReceiptV1,
    build_evidence,
    canonical_hash,
    canonical_json,
)
from finco_yield.execution import (
    ExecutionIntent,
    ExecutionValidationError,
    MAX_UINT256,
    build_direct_erc4626_deposit,
    build_pre_trade_evidence,
    validate_quote,
)
from finco_yield.explore import ExploreFilters, compare, explore
from finco_yield.freshness import evaluate_freshness
from finco_yield.onchain import Erc4626DirectObservation
from finco_yield.providers import (
    EnsoClient,
    ProviderError,
    ProviderValidationError,
    ZeroXClient,
)
from finco_yield.readiness import ChainReadinessState, robinhood_chain_readiness
from finco_yield.registry import (
    RegistryError,
    YieldSupportState,
    load_bundled_registry,
)
from finco_yield.schema import EvidenceConfidence, SourceReference, YieldObservation
from finco_yield.underwriting import NetApyAssumptions, position_net_apy, run_scenario
from finco_yield.web import router


WALLET = "0x3333333333333333333333333333333333333333"
OTHER = "0x4444444444444444444444444444444444444444"
ROUTER = "0x5555555555555555555555555555555555555555"
ALLOWANCE = "0x6666666666666666666666666666666666666666"


def _registry():
    return load_bundled_registry()


def _direct(binding, amount=1_000_000, asset=None, share=None, *, age_seconds=0, code_verified=True):
    now = datetime.now(timezone.utc)
    return Erc4626DirectObservation(
        chain_id=binding.chain_id,
        block_number=123,
        block_timestamp=now - timedelta(seconds=age_seconds),
        contract_address=binding.contract_address,
        asset_address=asset or binding.underlying_asset,
        share_token=share or binding.share_token,
        share_decimals=18,
        total_assets=10**12,
        total_supply=10**18,
        one_share_assets=1_000_000,
        one_asset_shares=1,
        preview_deposit_assets=amount,
        preview_deposit_shares=amount * 10**12,
        preview_redeem_shares=amount * 10**12,
        preview_redeem_assets=amount,
        code_verified=code_verified,
    )


def test_canonical_registry_unknown_uid_rejected():
    registry = _registry()
    opportunity = registry.all()[0]
    assert registry.resolve(opportunity.uid) == opportunity
    with pytest.raises(RegistryError):
        registry.canonical_binding("USDC")


def test_native_enriched_is_read_only_research_not_execution_authority():
    registry = _registry()
    for opportunity in registry.all():
        assert opportunity.source_type == EvidenceConfidence.NATIVE_ENRICHED
        assert opportunity.support_state == YieldSupportState.READ_ONLY_RESEARCH
        assert opportunity.block_number is None
        with pytest.raises(RegistryError):
            registry.execution_binding(opportunity.uid)


def test_execution_intent_cannot_define_economic_destination():
    intent = ExecutionIntent(_registry().all()[0].uid, 1, WALLET)
    for name in ("destination_contract", "share_token", "protocol", "underlying_asset"):
        assert not hasattr(intent, name)


def test_direct_plan_requires_block_bound_revalidation_and_minimal_approval():
    registry = _registry()
    opportunity = registry.all()[0]
    binding = registry.canonical_binding(opportunity.uid)
    intent = ExecutionIntent(opportunity.uid, 1_000_000, WALLET)

    plan = build_direct_erc4626_deposit(
        intent,
        registry=registry,
        direct_observation=_direct(binding),
        current_allowance=0,
        allowance_block_number=123,
    )

    assert plan.quote.destination_contract == binding.contract_address
    assert plan.quote.expected_output_token == binding.share_token
    assert plan.quote.receiver == WALLET.lower()
    assert plan.quote.authority_block_number == 123
    assert plan.approvals[0].amount == intent.amount
    assert not plan.approvals[0].unlimited
    assert plan.transactions[0].purpose == "EXACT_ERC20_APPROVAL"
    assert plan.transactions[-1].purpose == "ERC4626_DEPOSIT"
    assert plan.user_signable is False
    assert plan.protection_state == "UNPROTECTED_PREVIEW_ONLY"
    validate_quote(intent, plan, registry=registry)


def test_direct_plan_rejects_missing_code_or_stale_authority():
    registry = _registry()
    opportunity = registry.all()[0]
    binding = registry.canonical_binding(opportunity.uid)
    intent = ExecutionIntent(opportunity.uid, 1_000_000, WALLET)

    with pytest.raises(ExecutionValidationError, match="bytecode"):
        build_direct_erc4626_deposit(
            intent,
            registry=registry,
            direct_observation=_direct(binding, code_verified=False),
            current_allowance=0,
        )

    with pytest.raises(ExecutionValidationError, match="stale"):
        build_direct_erc4626_deposit(
            intent,
            registry=registry,
            direct_observation=_direct(binding, age_seconds=3600),
            current_allowance=0,
        )


def test_destination_underlying_share_substitution_rejected():
    registry = _registry()
    opportunity = registry.all()[0]
    binding = registry.canonical_binding(opportunity.uid)
    intent = ExecutionIntent(opportunity.uid, 1_000_000, WALLET)
    plan = build_direct_erc4626_deposit(
        intent,
        registry=registry,
        direct_observation=_direct(binding),
        current_allowance=intent.amount,
    )

    with pytest.raises(ExecutionValidationError):
        validate_quote(
            intent,
            replace(plan, quote=replace(plan.quote, destination_contract=OTHER)),
            registry=registry,
        )
    with pytest.raises(ExecutionValidationError):
        build_direct_erc4626_deposit(
            ExecutionIntent(opportunity.uid, 1_000_000, WALLET, funding_token=OTHER),
            registry=registry,
            direct_observation=_direct(binding),
            current_allowance=0,
        )
    with pytest.raises(ExecutionValidationError):
        validate_quote(
            intent,
            replace(plan, quote=replace(plan.quote, expected_output_token=OTHER)),
            registry=registry,
        )


def test_amount_chain_receiver_route_output_and_expiry_mutations_rejected():
    registry = _registry()
    opportunity = registry.all()[0]
    binding = registry.canonical_binding(opportunity.uid)
    intent = ExecutionIntent(opportunity.uid, 1_000_000, WALLET)
    plan = build_direct_erc4626_deposit(
        intent,
        registry=registry,
        direct_observation=_direct(binding),
        current_allowance=0,
    )
    mutations = [
        replace(plan, quote=replace(plan.quote, amount=2)),
        replace(plan, quote=replace(plan.quote, chain_id=999)),
        replace(plan, quote=replace(plan.quote, receiver=OTHER)),
        replace(plan, route=("TAMPER",)),
        replace(
            plan,
            quote=replace(
                plan.quote,
                expected_output=(plan.quote.expected_output or 0) + 1,
            ),
        ),
    ]
    for mutated in mutations:
        with pytest.raises(ExecutionValidationError):
            validate_quote(intent, mutated, registry=registry)

    with pytest.raises(ExecutionValidationError):
        validate_quote(
            intent,
            plan,
            registry=registry,
            now=plan.quote.expires_at + timedelta(seconds=1),
        )


def test_unlimited_approval_rejected():
    registry = _registry()
    opportunity = registry.all()[0]
    binding = registry.canonical_binding(opportunity.uid)
    intent = ExecutionIntent(opportunity.uid, 1_000_000, WALLET)
    plan = build_direct_erc4626_deposit(
        intent,
        registry=registry,
        direct_observation=_direct(binding),
        current_allowance=0,
    )
    bad = replace(plan.approvals[0], amount=MAX_UINT256, unlimited=True)
    with pytest.raises(ExecutionValidationError):
        validate_quote(
            intent,
            replace(plan, approvals=(bad,)),
            registry=registry,
        )


def test_freshness_stale_future_and_direct_block_identity():
    now = datetime.now(timezone.utc)
    assert (
        evaluate_freshness(
            SourceReference(
                EvidenceConfidence.NATIVE_ENRICHED,
                "x",
                now - timedelta(hours=2),
            ),
            now=now,
        ).state
        == "STALE"
    )
    assert (
        evaluate_freshness(
            SourceReference(
                EvidenceConfidence.NATIVE_ENRICHED,
                "x",
                now + timedelta(minutes=10),
            ),
            now=now,
        ).state
        == "FUTURE_TIMESTAMP"
    )
    assert (
        evaluate_freshness(
            SourceReference(EvidenceConfidence.DIRECT_ONCHAIN, "x", now),
            now=now,
        ).state
        == "INVALID"
    )


def test_evidence_canonicalization_decimal_and_timezone():
    assert canonical_hash({"x": Decimal("1.0")}) == canonical_hash({"x": Decimal("1.00")})
    a = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    b = datetime(2025, 12, 31, 19, 0, tzinfo=timezone(timedelta(hours=-5)))
    assert canonical_json({"t": a}) == canonical_json({"t": b})


def test_typed_yield_evidence_and_pretrade_are_deterministic():
    registry = _registry()
    opportunity = registry.all()[0]
    evidence1 = build_evidence(opportunity)
    evidence2 = build_evidence(opportunity)
    assert evidence1.schema_version == "YIELD_EVIDENCE_V1"
    assert evidence1.canonical_input_hash == evidence2.canonical_input_hash
    assert evidence1.canonical_output_hash == evidence2.canonical_output_hash

    binding = registry.canonical_binding(opportunity.uid)
    intent = ExecutionIntent(opportunity.uid, 1_000_000, WALLET)
    plan = build_direct_erc4626_deposit(
        intent,
        registry=registry,
        direct_observation=_direct(binding),
        current_allowance=intent.amount,
    )
    pre = build_pre_trade_evidence(evidence1, plan)
    assert pre.opportunity_uid == opportunity.uid
    assert pre.route_hash == plan.quote.route_hash
    assert len(pre.record_hash) == 64


def test_net_apy_unavailable_unless_all_explicit_costs_exist():
    observation = YieldObservation(Decimal("100"), Decimal(".05"))
    missing = position_net_apy(
        observation,
        NetApyAssumptions(
            Decimal("1000"),
            30,
            Decimal("1"),
            Decimal("1"),
            Decimal("0"),
            None,
            Decimal("0"),
            Decimal("0"),
        ),
    )
    assert missing.state == "NET_APY_UNAVAILABLE"
    assert missing.net_apy is None

    full = position_net_apy(
        observation,
        NetApyAssumptions(
            Decimal("1000"),
            365,
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
            Decimal("1"),
        ),
    )
    assert full.state == "AVAILABLE"
    assert full.net_apy == Decimal(".044")


def test_unsupported_causal_scenarios_are_not_modelled():
    observation = YieldObservation(Decimal("100"), Decimal(".05"))
    for name in ("UTILIZATION_SHIFT", "ASSET_DEPEG", "LIQUIDITY_COMPRESSION"):
        assert run_scenario(name, observation).state.value == "NOT_MODELLED"


def test_explore_filters_and_compare_are_neutral():
    registry = _registry()
    opportunity = registry.all()[0]
    rows = explore(
        registry,
        filters=ExploreFilters(
            chain_id=opportunity.chain_id,
            asset=opportunity.underlying_symbol,
            minimum_tvl_usd=Decimal("1"),
        ),
    )
    assert opportunity in rows
    comp = compare(registry, [opportunity.uid])
    assert comp[0].opportunity_uid == opportunity.uid
    with pytest.raises(ValueError):
        compare(registry, [])
    with pytest.raises(ValueError):
        compare(registry, [opportunity.uid, opportunity.uid])


def test_zero_x_normalization_requires_reviewed_targets(monkeypatch):
    monkeypatch.setenv("FINCO_YIELD_0X_APPROVAL_TARGETS_8453", ALLOWANCE)
    monkeypatch.setenv("FINCO_YIELD_0X_TRANSACTION_TARGETS_8453", ROUTER)
    client = ZeroXClient(api_key="x", client=object())
    opportunity = _registry().all()[0]
    quote = client.normalize(
        {
            "sellAmount": "100",
            "buyAmount": "95",
            "issues": {"allowance": {"spender": ALLOWANCE}},
            "transaction": {"to": ROUTER, "data": "0x12", "value": "0"},
        },
        chain_id=8453,
        sell_token=OTHER,
        buy_token=opportunity.underlying_address,
        sell_amount=100,
        taker=WALLET,
    )
    assert quote.provider == "0X_V2"
    assert quote.approval_target == ALLOWANCE.lower()
    with pytest.raises(ProviderValidationError):
        client.normalize(
            {"transaction": {"to": OTHER, "data": "0x12", "value": "0"}},
            chain_id=8453,
            sell_token=OTHER,
            buy_token=opportunity.underlying_address,
            sell_amount=100,
            taker=WALLET,
        )


def test_enso_normalization_requires_reviewed_target(monkeypatch):
    monkeypatch.setenv("FINCO_YIELD_ENSO_TRANSACTION_TARGETS_8453", ROUTER)
    client = EnsoClient(api_key="x", client=object())
    opportunity = _registry().all()[0]
    quote = client.normalize(
        {"tx": {"to": ROUTER, "data": "0xab", "value": "0"}, "amountOut": "123"},
        chain_id=8453,
        input_token=OTHER,
        output_token=opportunity.share_token,
        amount=100,
        receiver=WALLET,
    )
    assert quote.provider == "ENSO"
    with pytest.raises(ProviderValidationError):
        client.normalize(
            {"tx": {"to": OTHER, "data": "0xab", "value": "0"}},
            chain_id=8453,
            input_token=OTHER,
            output_token=opportunity.share_token,
            amount=100,
            receiver=WALLET,
        )


class _RaiseClient:
    def __init__(self, exc):
        self.exc = exc

    def get(self, *args, **kwargs):
        raise self.exc


class _Response:
    def __init__(self, status_code=200, payload=None, json_error=None):
        self.status_code = status_code
        self.payload = payload
        self.json_error = json_error

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("SECRET_RAW_PROVIDER_BODY api-key=do-not-leak")

    def json(self):
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class _ResponseClient:
    def __init__(self, response):
        self.response = response

    def get(self, *args, **kwargs):
        return self.response


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (401, "PROVIDER_AUTHENTICATION_FAILED"),
        (403, "PROVIDER_FORBIDDEN"),
        (429, "PROVIDER_RATE_LIMITED"),
        (500, "PROVIDER_UPSTREAM_UNAVAILABLE"),
        (503, "PROVIDER_UPSTREAM_UNAVAILABLE"),
    ],
)
def test_provider_http_failures_are_typed_and_redacted(status_code, expected_code):
    client = ZeroXClient(
        api_key="super-secret-api-key",
        client=_ResponseClient(_Response(status_code=status_code)),
    )
    with pytest.raises(ProviderError) as caught:
        client.quote(
            chain_id=8453,
            sell_token=OTHER,
            buy_token=ROUTER,
            sell_amount=100,
            taker=WALLET,
        )
    assert caught.value.code == expected_code
    text = str(caught.value)
    assert "SECRET_RAW_PROVIDER_BODY" not in text
    assert "super-secret-api-key" not in text
    assert "api-key" not in text


def test_provider_timeout_and_connect_failures_are_redacted():
    request = httpx.Request("GET", "https://api.example.invalid/?secret=LEAK")
    failures = [
        (httpx.ReadTimeout("SECRET_TIMEOUT", request=request), "PROVIDER_TIMEOUT"),
        (httpx.ConnectError("SECRET_DNS", request=request), "PROVIDER_NETWORK_ERROR"),
    ]
    for exc, code in failures:
        client = EnsoClient(api_key="super-secret-api-key", client=_RaiseClient(exc))
        with pytest.raises(ProviderError) as caught:
            client.route(
                chain_id=8453,
                input_token=OTHER,
                output_token=ROUTER,
                amount=100,
                sender=WALLET,
                receiver=WALLET,
            )
        assert caught.value.code == code
        text = str(caught.value)
        assert "SECRET_" not in text
        assert "super-secret-api-key" not in text
        assert "example.invalid" not in text


def test_provider_malformed_json_is_typed_and_redacted():
    client = ZeroXClient(
        api_key="super-secret-api-key",
        client=_ResponseClient(
            _Response(
                status_code=200,
                json_error=ValueError("SECRET_PROVIDER_BODY super-secret-api-key"),
            )
        ),
    )
    with pytest.raises(ProviderError) as caught:
        client.quote(
            chain_id=8453,
            sell_token=OTHER,
            buy_token=ROUTER,
            sell_amount=100,
            taker=WALLET,
        )
    assert caught.value.code == "PROVIDER_MALFORMED_JSON"
    assert "SECRET_PROVIDER_BODY" not in str(caught.value)
    assert "super-secret-api-key" not in str(caught.value)


def test_post_trade_receipt_design_and_robinhood_partial():
    receipt = YieldPostTradeReceiptV1(
        "0x" + "ab" * 32,
        123,
        "yld_x",
        "v1",
        100,
        95,
        96,
        Decimal("10"),
        datetime.now(timezone.utc),
    )
    assert len(receipt.receipt_hash) == 64
    readiness = robinhood_chain_readiness()
    assert readiness.chain_id == 4663
    assert readiness.state == ChainReadinessState.PARTIAL
    assert "authoritative Enso chain 4663 support" in readiness.unproven


def test_no_private_key_sign_or_broadcast_api():
    import finco_yield.execution as execution

    names = set(dir(execution))
    assert "private_key" not in names
    assert "sign" not in names
    assert "broadcast" not in names


def test_web_feature_flags_and_prototype_tombstone(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    monkeypatch.delenv("FINCO_YIELD_ENABLED", raising=False)
    # V1 contract: with the runtime OFF the primary /yield entry is a truthful, data-free disabled shell
    # (evaluated at request time); no opportunity/registry data is served and every data route stays 404.
    uid = _registry().all()[0].uid
    off = client.get("/yield")
    assert off.status_code == 200
    assert 'data-yield-runtime-state="disabled"' in off.text
    assert "Evidence-backed DeFi opportunities" not in off.text
    assert uid not in off.text
    for path in ("/yield/compare", "/yield/monitor", "/yield/access.json", "/yield/watchlist.json",
                 f"/yield/{uid}", f"/yield/{uid}/history.json", f"/yield/{uid}/evidence.json"):
        assert client.get(path).status_code == 404, path
    assert client.post(f"/yield/{uid}/plan", data={"amount": "1"}).status_code == 404

    monkeypatch.setenv("FINCO_YIELD_ENABLED", "1")
    response = client.get("/yield")
    assert response.status_code == 200
    assert "Evidence-backed DeFi opportunities" in response.text
    assert "does not rank a winner" in response.text

    prototype = client.get("/yield/prototype")
    assert prototype.status_code == 410

    monkeypatch.delenv("FINCO_YIELD_EXECUTION_ENABLED", raising=False)
    uid = _registry().all()[0].uid
    plan = client.post(f"/yield/{uid}/plan", data={"amount": "1"})
    assert plan.json()["code"] == "EXECUTION_DISABLED"
