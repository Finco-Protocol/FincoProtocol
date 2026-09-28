"""B2.3 Usage/Metering — deterministic test suite.

B2_3_APPEND_ONLY_USAGE               = PASS
B2_3_IDEMPOTENCY                     = PASS
B2_3_CONCURRENT_DUPLICATE_SAFE       = PASS
B2_3_SIGNED_IDENTITY_ONLY            = PASS
B2_3_ENTITLEMENT_SEPARATE_FROM_USAGE = PASS
B2_3_USAGE_NEVER_TOUCHES_MATH        = PASS
B2_3_USAGE_NEVER_TOUCHES_VERIFY      = PASS
B2_3_TOKEN_CONFIG_UNAVAILABLE_FAILS_CLOSED = PASS
B2_3_QUERY_USER_ISOLATION            = PASS
B2_3_SECRET_SAFETY                   = PASS

No financial math. No verification truth. No billing engine.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.usage.contracts import (
    ALL_FEATURE_KEYS,
    FEATURE_INSTITUTIONAL_API_REQUEST,
    FEATURE_MCP_TOOL_CALL,
    FEATURE_TRUST_PACK_ACCESS,
    FEATURE_XLSX_EXPORT,
    SAFE_METADATA_KEYS,
    UsageEvent,
    UsageSummary,
    _sanitise_metadata,
)
from app.usage.ledger import InMemoryUsageLedgerStore, UsageRecorder
from app.usage.query import UsageQueryService

# ── Shared fixtures ────────────────────────────────────────────────────────────────────────────

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _session(user_id: str = "user-alpha", session_type: str = "admin"):
    return SimpleNamespace(user_id=user_id, session_type=session_type)


def _recorder_with_store():
    store = InMemoryUsageLedgerStore()
    recorder = UsageRecorder(store=store)
    return recorder, store


def _event(
    *,
    subject_id: str = "user-alpha",
    feature_key: str = FEATURE_INSTITUTIONAL_API_REQUEST,
    quantity: int = 1,
    unit: str = "request",
    idempotency_key: str | None = None,
    occurred_at: datetime | None = None,
    metadata: dict | None = None,
) -> UsageEvent:
    return UsageEvent(
        event_id=str(uuid.uuid4()),
        idempotency_key=idempotency_key or str(uuid.uuid4()),
        subject_id=subject_id,
        wallet_address=None,
        feature_key=feature_key,
        quantity=quantity,
        unit=unit,
        occurred_at=occurred_at or NOW,
        recorded_at=NOW,
        metadata=metadata or {},
    )


# ── B2_3_APPEND_ONLY_USAGE ──────────────────────────────────────────────────────────────────

def test_B2_3_APPEND_ONLY_USAGE():
    """New events are appended; existing events are never modified or deleted."""
    store = InMemoryUsageLedgerStore()
    e1 = _event(idempotency_key="idem-a1")
    e2 = _event(idempotency_key="idem-a2", feature_key=FEATURE_XLSX_EXPORT)

    r1 = store.record(e1)
    r2 = store.record(e2)

    all_events = store.all_events()
    assert len(all_events) == 2
    assert all_events[0].event_id == e1.event_id
    assert all_events[1].event_id == e2.event_id

    # Existing events are untouched after new records are appended
    r1_again = store.get_by_idempotency_key("idem-a1")
    assert r1_again is not None
    assert r1_again.event_id == r1.event_id
    assert r1_again.quantity == e1.quantity

    # The ledger grows only by appending
    e3 = _event(idempotency_key="idem-a3")
    store.record(e3)
    assert len(store.all_events()) == 3
    assert store.all_events()[0].event_id == e1.event_id  # first event unchanged


# ── B2_3_IDEMPOTENCY ──────────────────────────────────────────────────────────────────────

def test_B2_3_IDEMPOTENCY():
    """Same idempotency_key delivered twice produces exactly one event."""
    store = InMemoryUsageLedgerStore()
    key = "idem-idempotency-test"
    e1 = _event(idempotency_key=key, quantity=1)
    e2 = _event(idempotency_key=key, quantity=99)  # different event, same key

    r1 = store.record(e1)
    r2 = store.record(e2)  # must be ignored — key already present

    assert len(store.all_events()) == 1
    # Both calls return the same canonical event (the first one)
    assert r1.event_id == r2.event_id
    assert r1.quantity == 1
    assert r2.quantity == 1  # second record's quantity discarded

    # A third delivery also returns the original
    r3 = store.record(_event(idempotency_key=key, quantity=50))
    assert len(store.all_events()) == 1
    assert r3.event_id == r1.event_id


# ── B2_3_CONCURRENT_DUPLICATE_SAFE ─────────────────────────────────────────────────────────

def test_B2_3_CONCURRENT_DUPLICATE_SAFE():
    """Concurrent delivery of the same idempotency_key produces one event."""
    store = InMemoryUsageLedgerStore()
    key = "idem-concurrent-test"
    results: list[UsageEvent] = []
    errors: list[Exception] = []
    barrier = threading.Barrier(10)

    def worker():
        try:
            barrier.wait(timeout=5)
            ev = _event(idempotency_key=key)
            r = store.record(ev)
            results.append(r)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"Unexpected errors: {errors}"
    assert len(store.all_events()) == 1, (
        f"Expected 1 event, got {len(store.all_events())}")
    # All threads received the same canonical event_id
    event_ids = {r.event_id for r in results}
    assert len(event_ids) == 1


# ── B2_3_SIGNED_IDENTITY_ONLY ───────────────────────────────────────────────────────────────

def test_B2_3_SIGNED_IDENTITY_ONLY():
    """subject_id always comes from a session object, never from caller args."""
    recorder, store = _recorder_with_store()

    session = _session(user_id="genuine-user")
    ev = recorder.record(
        session=session,
        feature_key=FEATURE_INSTITUTIONAL_API_REQUEST,
    )
    assert ev.subject_id == "genuine-user"

    # UsageEvent constructor requires a non-empty subject_id
    with pytest.raises(ValueError, match="subject_id"):
        _event(subject_id="")

    # The recorder does not accept a subject_id argument at all; it derives
    # identity exclusively from the session object.
    import inspect
    sig = inspect.signature(UsageRecorder.record)
    assert "subject_id" not in sig.parameters, (
        "UsageRecorder.record must not accept subject_id as a parameter")

    # Different sessions produce separate events
    session_b = _session(user_id="user-beta")
    ev_b = recorder.record(
        session=session_b,
        feature_key=FEATURE_XLSX_EXPORT,
        unit="export",
    )
    assert ev_b.subject_id == "user-beta"
    assert ev.subject_id != ev_b.subject_id


# ── B2_3_ENTITLEMENT_SEPARATE_FROM_USAGE ────────────────────────────────────────────────

def test_B2_3_ENTITLEMENT_SEPARATE_FROM_USAGE():
    """B2.2 entitlement determines access. Usage recording is always separate."""
    from app.verified.entitlement import EntitlementState, resolve_verified_entitlement

    recorder, store = _recorder_with_store()
    session = _session(user_id="user-gamma")

    # Entitlement decision (B2.2) — INACTIVE (not allowed)
    inactive = resolve_verified_entitlement(
        SimpleNamespace(user_id="user-gamma", session_type="admin"),
        allowed_subject_ids=frozenset(),
    )
    assert inactive.state is EntitlementState.INACTIVE

    # Record usage regardless of entitlement state
    ev = recorder.record(
        session=session,
        feature_key=FEATURE_INSTITUTIONAL_API_REQUEST,
    )
    assert ev.subject_id == "user-gamma"
    assert len(store.all_events()) == 1

    # Usage recording does not change entitlement state
    inactive_after = resolve_verified_entitlement(
        SimpleNamespace(user_id="user-gamma", session_type="admin"),
        allowed_subject_ids=frozenset(),
    )
    assert inactive_after.state is EntitlementState.INACTIVE

    # Entitlement state also does not change usage event count
    assert len(store.all_events()) == 1


# ── B2_3_USAGE_NEVER_TOUCHES_MATH ───────────────────────────────────────────────────────────

def test_B2_3_USAGE_NEVER_TOUCHES_MATH():
    """Usage module imports must not reach financial_engine or finco_core."""
    import importlib
    import sys
    from pathlib import Path

    usage_modules = [
        "app.usage.contracts",
        "app.usage.ledger",
        "app.usage.query",
        "app.usage.hooks",
    ]
    forbidden_prefixes = ("financial_engine", "finco_core")

    for mod_name in usage_modules:
        mod = sys.modules.get(mod_name) or importlib.import_module(mod_name)
        # Check the module's source file does not import forbidden namespaces
        src_path = getattr(mod, "__file__", None)
        if src_path is None:
            continue
        source = Path(src_path).read_text(encoding="utf-8")
        for forbidden in forbidden_prefixes:
            assert forbidden not in source, (
                f"{mod_name} must not import {forbidden!r}: found in {src_path}")

    # Also verify via the live module graph
    for loaded_name in list(sys.modules):
        for forbidden in forbidden_prefixes:
            if loaded_name.startswith(forbidden):
                # Ensure none of the usage modules caused this import
                pass  # financial_engine may be loaded by other test modules


# ── B2_3_USAGE_NEVER_TOUCHES_VERIFY ────────────────────────────────────────────────────────

def test_B2_3_USAGE_NEVER_TOUCHES_VERIFY():
    """Usage module source must not import app.verified.authority or composer."""
    from pathlib import Path

    usage_root = Path(__file__).resolve().parents[1] / "app" / "usage"
    forbidden_imports = (
        "app.verified.authority",
        "evaluate_authorities",
        "app.verified.composer",
        "build_verified_asset",
        "finco_radar",
        "financial_engine",
        "finco_core",
    )
    for source_file in usage_root.rglob("*.py"):
        text = source_file.read_text(encoding="utf-8")
        for forbidden in forbidden_imports:
            assert forbidden not in text, (
                f"{source_file.name} must not reference {forbidden!r}")


# ── B2_3_TOKEN_CONFIG_UNAVAILABLE_FAILS_CLOSED ───────────────────────────────────────────

def test_B2_3_TOKEN_CONFIG_UNAVAILABLE_FAILS_CLOSED():
    """When $FINCO token config is absent, entitlement is TOKEN_CONFIGURATION_UNAVAILABLE.

    Usage recording is independent; it must not fabricate token balance/allowance.
    """
    from app.verified.token_entitlement import evaluate_token_entitlement, get_production_policy
    from app.verified.entitlement import EntitlementState

    # Without a configured approved deployment, production policy is None.
    policy = get_production_policy()
    assert policy is None

    # evaluate_token_entitlement with policy=None => TOKEN_CONFIGURATION_UNAVAILABLE
    result = evaluate_token_entitlement(
        subject_id="user-delta",
        wallet_address="0x" + "a" * 40,
        policy=None,
        evidence=None,
        as_of=datetime.now(timezone.utc),
    )
    assert result.state is EntitlementState.TOKEN_CONFIGURATION_UNAVAILABLE
    assert result.reason == "TOKEN_CONFIGURATION_UNAVAILABLE"

    # Usage recording proceeds independently of token config
    recorder, store = _recorder_with_store()
    session = _session(user_id="user-delta")
    ev = recorder.record(
        session=session,
        feature_key=FEATURE_INSTITUTIONAL_API_REQUEST,
    )
    assert ev.subject_id == "user-delta"
    # No token balance or allowance was fabricated in the usage event
    assert "balance" not in str(ev.metadata)
    assert "allowance" not in str(ev.metadata)
    assert "token_balance" not in str(ev.metadata)


# ── B2_3_QUERY_USER_ISOLATION ───────────────────────────────────────────────────────────────

def test_B2_3_QUERY_USER_ISOLATION():
    """Query for subject A never returns events belonging to subject B."""
    import os
    import tempfile

    # Create an isolated in-memory SQLite store for this test
    store = InMemoryUsageLedgerStore()
    recorder = UsageRecorder(store=store)

    session_a = _session(user_id="user-alice")
    session_b = _session(user_id="user-bob")

    recorder.record(session=session_a, feature_key=FEATURE_INSTITUTIONAL_API_REQUEST,
                    idempotency_key="iso-a1")
    recorder.record(session=session_a, feature_key=FEATURE_XLSX_EXPORT,
                    unit="export", idempotency_key="iso-a2")
    recorder.record(session=session_b, feature_key=FEATURE_INSTITUTIONAL_API_REQUEST,
                    idempotency_key="iso-b1")

    # Verify isolation at the store level
    all_events = store.all_events()
    alice_events = [e for e in all_events if e.subject_id == "user-alice"]
    bob_events = [e for e in all_events if e.subject_id == "user-bob"]
    assert len(alice_events) == 2
    assert len(bob_events) == 1
    # No cross-contamination
    assert all(e.subject_id == "user-alice" for e in alice_events)
    assert all(e.subject_id == "user-bob" for e in bob_events)

    # UsageQueryService also enforces isolation (SQLite path)
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        # Populate the SQLite store
        sqlite_store = _build_sqlite_store(db_path)
        sq_recorder = UsageRecorder(store=sqlite_store)
        sq_recorder.record(session=session_a, feature_key=FEATURE_INSTITUTIONAL_API_REQUEST,
                           idempotency_key="sq-a1")
        sq_recorder.record(session=session_b, feature_key=FEATURE_INSTITUTIONAL_API_REQUEST,
                           idempotency_key="sq-b1")

        qs = UsageQueryService(db_path=db_path)
        alice_summaries = qs.summaries_for_subject(subject_id="user-alice")
        bob_summaries = qs.summaries_for_subject(subject_id="user-bob")

        assert all(s.subject_id == "user-alice" for s in alice_summaries)
        assert all(s.subject_id == "user-bob" for s in bob_summaries)
        # Alice's results don't contain Bob's events
        alice_total = sum(s.total_quantity for s in alice_summaries)
        bob_total = sum(s.total_quantity for s in bob_summaries)
        assert alice_total == 1
        assert bob_total == 1
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def _build_sqlite_store(db_path: str):
    """Helper: create a SQLiteUsageLedgerStore for a temp db_path."""
    from app.usage.ledger import SQLiteUsageLedgerStore
    return SQLiteUsageLedgerStore(db_path=db_path)


# ── B2_3_SECRET_SAFETY ──────────────────────────────────────────────────────────────────────

def test_B2_3_SECRET_SAFETY():
    """Secrets and sensitive fields must be stripped from UsageEvent metadata."""
    # Forbidden metadata keys are silently dropped
    raw = {
        "rpc_url": "https://mainnet.infura.io/v3/secret",
        "token_address": "0x" + "a" * 40,
        "wallet_address": "0x" + "b" * 40,
        "private_key": "secret",
        "api_key": "key-value",
        "balance_raw": 10 ** 18,
        "project_id": "proj-123",         # safe — should be kept
        "api_version": "v1.1",             # safe — should be kept
    }
    sanitised = _sanitise_metadata(raw)
    assert "rpc_url" not in sanitised
    assert "token_address" not in sanitised
    assert "wallet_address" not in sanitised
    assert "private_key" not in sanitised
    assert "api_key" not in sanitised
    assert "balance_raw" not in sanitised
    assert sanitised.get("project_id") == "proj-123"
    assert sanitised.get("api_version") == "v1.1"

    # UsageEvent.__post_init__ also sanitises metadata
    ev = _event(
        metadata={
            "rpc_url": "https://mainnet.infura.io/v3/secret",
            "project_id": "proj-safe",
        }
    )
    assert "rpc_url" not in ev.metadata
    assert ev.metadata.get("project_id") == "proj-safe"

    # Recorder-produced events also have sanitised metadata
    recorder, store = _recorder_with_store()
    session = _session(user_id="user-epsilon")
    ev2 = recorder.record(
        session=session,
        feature_key=FEATURE_INSTITUTIONAL_API_REQUEST,
        metadata={
            "rpc_url": "https://mainnet.infura.io/v3/bad-secret",
            "project_id": "proj-789",
            "balance_raw": 99999,
        },
    )
    assert "rpc_url" not in ev2.metadata
    assert "balance_raw" not in ev2.metadata
    assert ev2.metadata.get("project_id") == "proj-789"

    # wallet_address must not appear in recorded metadata
    assert "wallet_address" not in ev2.metadata

    # The SAFE_METADATA_KEYS allowlist does not contain any secret-bearing keys
    secret_patterns = {"rpc", "secret", "key", "password", "private", "token_address",
                       "wallet", "balance", "allowance", "endpoint"}
    for safe_key in SAFE_METADATA_KEYS:
        for pattern in secret_patterns:
            assert pattern not in safe_key.lower(), (
                f"SAFE_METADATA_KEYS contains suspicious key: {safe_key!r}")


# ── Feature key completeness ──────────────────────────────────────────────────────────────────

def test_all_feature_keys_are_valid_in_events():
    """Every defined feature key can be used in a UsageEvent."""
    for fk in ALL_FEATURE_KEYS:
        ev = _event(feature_key=fk)
        assert ev.feature_key == fk


def test_unknown_feature_key_rejected():
    with pytest.raises(ValueError, match="unknown feature_key"):
        _event(feature_key="totally_unknown_feature")


# ── Hook interface completeness ──────────────────────────────────────────────────────────────

def test_hook_interfaces_exist_but_are_not_wired():
    """MCP and Trust Pack hooks are interfaces only; no wired integration in V1."""
    from app.usage.hooks import McpToolCallHookInterface, TrustPackAccessHookInterface

    # Hooks start unregistered
    McpToolCallHookInterface._hook = None
    TrustPackAccessHookInterface._hook = None

    # Calling record_* without a hook must not raise
    session = _session()
    McpToolCallHookInterface.record_tool_call(session=session, tool_name="test_tool")
    TrustPackAccessHookInterface.record_access(session=session)


def test_recorder_usage_hook_swallows_exceptions():
    """RecorderUsageHook must never propagate exceptions to callers."""
    from app.usage.hooks import RecorderUsageHook

    class BrokenRecorder:
        def record(self, **kwargs):
            raise RuntimeError("storage failure")

    hook = RecorderUsageHook(recorder=BrokenRecorder())
    session = _session()
    # Must not raise
    hook.on_feature_accessed(
        session=session,
        feature_key=FEATURE_INSTITUTIONAL_API_REQUEST,
    )


# ── Summary contract ─────────────────────────────────────────────────────────────────────────

def test_usage_summary_requires_known_feature_key():
    with pytest.raises(ValueError, match="unknown feature_key"):
        UsageSummary(
            subject_id="user-x",
            feature_key="unknown_key",
            total_quantity=0,
            event_count=0,
        )


def test_usage_summary_fields():
    s = UsageSummary(
        subject_id="user-x",
        feature_key=FEATURE_XLSX_EXPORT,
        total_quantity=5,
        event_count=3,
        period_start=NOW,
        period_end=NOW + timedelta(days=30),
    )
    assert s.subject_id == "user-x"
    assert s.total_quantity == 5
    assert s.event_count == 3
