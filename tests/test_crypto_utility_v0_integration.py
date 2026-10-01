"""Cross-branch integration tests for FINCO Crypto Utility V0 Agent D."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import os
import tempfile

import pytest


def _actual(resource, verdict, reason, *, balance=None, chain_id=None, token=None):
    from app.protocol.entitlement_evaluator import ResourceAccessDecision
    return ResourceAccessDecision(
        resource_key=resource,
        decision=verdict,
        reason_code=reason,
        access_mode="FINCO_HOLDER" if resource != "yield.basic" else "PUBLIC",
        wallet_address="0x" + "11" * 20,
        chain_id=chain_id,
        token_address=token,
        entitlement_state="ACTIVE" if getattr(verdict, "value", verdict) == "ALLOW" else None,
        observed_balance=balance,
        minimum_balance=None,
        observed_at=datetime.now(timezone.utc) if balance is not None else None,
    )


def test_actual_agent_a_enum_and_dataclass_map_into_agent_c():
    """Regression: str(Decision.ALLOW) is not used as canonical normalization."""
    from app.crypto_access import (
        RESOURCE_DISPLAY,
        RESOURCE_LOCKED,
        RESOURCE_NOT_ACTIVATED,
        RESOURCE_UNLOCKED,
        YIELD_HISTORY,
        present_resource,
    )
    from app.protocol.entitlement_evaluator import Decision

    allow = present_resource(
        RESOURCE_DISPLAY[YIELD_HISTORY],
        _actual(YIELD_HISTORY, Decision.ALLOW, "BALANCE_AT_OR_ABOVE_THRESHOLD"),
    )
    deny = present_resource(
        RESOURCE_DISPLAY[YIELD_HISTORY],
        _actual(YIELD_HISTORY, Decision.DENY, "BALANCE_BELOW_THRESHOLD"),
    )
    inactive = present_resource(
        RESOURCE_DISPLAY[YIELD_HISTORY],
        _actual(YIELD_HISTORY, Decision.INACTIVE, "TOKEN_GATING_OFF"),
    )
    assert allow["state"] == RESOURCE_UNLOCKED
    assert deny["state"] == RESOURCE_LOCKED
    assert inactive["state"] == RESOURCE_NOT_ACTIVATED


def test_actual_agent_a_balance_zero_is_presented_only_with_identity():
    from app.crypto_access import RESOURCE_DISPLAY, YIELD_HISTORY, present_resource
    from app.protocol.entitlement_evaluator import Decision
    token = "0x" + "ab" * 20
    view = present_resource(
        RESOURCE_DISPLAY[YIELD_HISTORY],
        _actual(
            YIELD_HISTORY,
            Decision.DENY,
            "BALANCE_BELOW_THRESHOLD",
            balance=Decimal(0),
            chain_id=8453,
            token=token,
        ),
    )
    assert view["balance"] == {
        "observed_balance": "0",
        "chain_id": 8453,
        "token_address": token,
    }
    assert "minimum_balance" not in view


@pytest.fixture()
def client(monkeypatch):
    os.environ["FINCO_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "integration.db")
    from app.persistence import db
    db.DB_PATH = os.environ["FINCO_DB_PATH"]
    db.init_db()
    monkeypatch.setenv("FINCO_YIELD_ENABLED", "1")
    monkeypatch.delenv("FINCO_TOKEN_GATING_ENABLED", raising=False)
    monkeypatch.delenv("FINCO_ENTITLEMENT_POLICIES_JSON", raising=False)

    from fastapi.testclient import TestClient
    import main_web
    from app.auth import COOKIE_NAME, create_session_token
    c = TestClient(main_web.app)
    c.cookies.update({COOKIE_NAME: create_session_token(
        user_id="integration-user", username="integration")})
    return c


def test_access_json_consumes_actual_agent_a_decisions(client, monkeypatch):
    """The route calls Agent A once and passes decisions to C; C does not evaluate token truth."""
    from app.protocol import entitlement_evaluator as ev
    from app.protocol.entitlement_evaluator import Decision
    calls = []

    async def fake_all(wallet, **kw):
        calls.append(wallet)
        return {
            "yield.basic": _actual("yield.basic", Decision.ALLOW, "PUBLIC_RESOURCE"),
            "yield.history": _actual("yield.history", Decision.INACTIVE, "TOKEN_GATING_OFF"),
            "yield.advanced_compare": _actual(
                "yield.advanced_compare", Decision.DENY, "BALANCE_BELOW_THRESHOLD"),
            "yield.alerts": _actual("yield.alerts", Decision.INACTIVE, "POLICY_DISABLED"),
            "yield.execution_preflight": _actual(
                "yield.execution_preflight", Decision.DENY, "RPC_UNAVAILABLE"),
        }

    monkeypatch.setattr(ev, "evaluate_all_resources", fake_all)
    r = client.get("/yield/access.json")
    assert r.status_code == 200
    body = r.json()
    assert len(calls) == 1
    assert body["resources"]["yield.basic"]["state"] == "PUBLIC"
    assert body["resources"]["yield.history"]["state"] == "NOT_ACTIVATED"
    assert body["resources"]["yield.advanced_compare"]["state"] == "LOCKED"
    assert body["resources"]["yield.alerts"]["state"] == "NOT_ACTIVATED"
    assert body["resources"]["yield.execution_preflight"]["state"] == "UNAVAILABLE"


def test_presentation_module_has_no_token_or_rpc_evaluator():
    import inspect
    from app import crypto_access
    source = inspect.getsource(crypto_access)
    for banned in (
        "evaluate_resource_access",
        "evaluate_all_resources",
        "evaluate_token_entitlement",
        "P4ReadOnlyBalanceProvider",
        "get_production_policy",
        "FINCO_TOKEN_RPC_URL",
    ):
        assert banned not in source


def test_default_agent_a_bundle_is_inactive_for_holder_resources():
    """Canonical production defaults: code existence alone activates nothing."""
    import asyncio
    from app.protocol.entitlement_evaluator import Decision, NO_WALLET, evaluate_all_resources
    decisions = asyncio.run(evaluate_all_resources(NO_WALLET, environ={}))
    assert decisions["yield.basic"].decision is Decision.ALLOW
    for key in (
        "yield.history", "yield.advanced_compare", "yield.alerts", "yield.execution_preflight",
    ):
        assert decisions[key].decision is Decision.INACTIVE
        assert decisions[key].reason_code == "TOKEN_GATING_OFF"
        assert decisions[key].observed_balance is None
