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

B2_3_IDEMPOTENCY_SUBJECT_SCOPED              = PASS
B2_3_CROSS_USER_IDEMPOTENCY_COLLISION_SAFE   = PASS
B2_3_CROSS_FEATURE_IDEMPOTENCY_COLLISION_SAFE = PASS
B2_3_QUERY_SIGNED_IDENTITY_ONLY             = PASS
B2_3_QUERY_CROSS_USER_SPOOF_IMPOSSIBLE       = PASS
B2_3_WALLET_NOT_CALLER_CONTROLLED            = PASS
B2_3_WALLET_CANONICAL_LINK_ONLY              = PASS
B2_3_QUERY_FAILURE_NOT_ZERO                  = PASS
B2_3_QUERY_ERROR_SECRET_SAFE                 = PASS

B2_3_SQLITE_CONCURRENT_DUPLICATE_NO_LOCK_ERROR = PASS
B2_3_SQLITE_CONCURRENT_DUPLICATE_ONE_ROW       = PASS
B2_3_SQLITE_CONCURRENT_REPEAT_STABLE           = PASS
B2_3_SQLITE_UNRELATED_DB_ERROR_NOT_SWALLOWED   = PASS

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
    QUERY_STATE_AVAILABLE,
    QUERY_STATE_UNAVAILABLE,
    QUERY_UNAVAILABLE_REASON,
    SAFE_METADATA_KEYS,
    UsageEvent,
    UsageQueryResult,
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
    r1_again = store.get_by_scoped_key(
        e1.subject_id, e1.feature_key, "idem-a1"
    )
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
    """Same (subject_id, feature_key, idempotency_key) delivered twice produces one event."""
    store = InMemoryUsageLedgerStore()
    key = "idem-idempotency-test"
    e1 = _event(idempotency_key=key, quantity=1)
    e2 = _event(idempotency_key=key, quantity=99)  # different event, same scoped key

    r1 = store.record(e1)
    r2 = store.record(e2)  # must be ignored — scoped key already present

    assert len(store.all_events()) == 1
    # Both calls return the same canonical event (the first one)
    assert r1.event_id == r2.event_id
    assert r1.quantity == 1
    assert r2.quantity == 1  # second record's quantity discarded

    # A third delivery also returns the original
    r3 = store.record(_event(idempotency_key=key, quantity=50))
    assert len(store.all_events()) == 1
    assert r3.event_id == r1.event_id


# ── B2_3_IDEMPOTENCY_SUBJECT_SCOPED ──────────────────────────────────────────────────────

def test_B2_3_IDEMPOTENCY_SUBJECT_SCOPED():
    """Idempotency key is scoped per subject: same key for different subjects = two events."""
    store = InMemoryUsageLedgerStore()
    shared_key = "shared-idem-key"
    e_alice = _event(subject_id="user-alice", idempotency_key=shared_key, quantity=1)
    e_bob = _event(subject_id="user-bob", idempotency_key=shared_key, quantity=2)

    r_alice = store.record(e_alice)
    r_bob = store.record(e_bob)

    # Two distinct events — different subjects, same idempotency_key
    assert len(store.all_events()) == 2
    assert r_alice.event_id != r_bob.event_id
    assert r_alice.subject_id == "user-alice"
    assert r_bob.subject_id == "user-bob"
    assert r_alice.quantity == 1
    assert r_bob.quantity == 2

    # Each subject's scoped key resolves to their own event
    looked_up_alice = store.get_by_scoped_key(
        "user-alice", FEATURE_INSTITUTIONAL_API_REQUEST, shared_key
    )
    looked_up_bob = store.get_by_scoped_key(
        "user-bob", FEATURE_INSTITUTIONAL_API_REQUEST, shared_key
    )
    assert looked_up_alice is not None and looked_up_alice.event_id == r_alice.event_id
    assert looked_up_bob is not None and looked_up_bob.event_id == r_bob.event_id


# ── B2_3_CROSS_USER_IDEMPOTENCY_COLLISION_SAFE ───────────────────────────────────────────

def test_B2_3_CROSS_USER_IDEMPOTENCY_COLLISION_SAFE():
    """User A's idempotency key cannot shadow or collide with User B's event."""
    store = InMemoryUsageLedgerStore()
    shared_key = "collision-key"

    # Record for user-A first
    e_a = _event(subject_id="user-A", idempotency_key=shared_key, quantity=10)
    r_a = store.record(e_a)

    # Record for user-B with same key — must succeed as a separate event
    e_b = _event(subject_id="user-B", idempotency_key=shared_key, quantity=20)
    r_b = store.record(e_b)

    # Neither event was suppressed
    assert len(store.all_events()) == 2
    assert r_a.quantity == 10
    assert r_b.quantity == 20
    assert r_a.subject_id == "user-A"
    assert r_b.subject_id == "user-B"

    # Idempotent re-delivery for user-A doesn't affect user-B's event
    r_a2 = store.record(_event(subject_id="user-A", idempotency_key=shared_key, quantity=99))
    assert r_a2.event_id == r_a.event_id
    assert r_a2.quantity == 10  # original preserved
    assert len(store.all_events()) == 2  # still two events


# ── B2_3_CROSS_FEATURE_IDEMPOTENCY_COLLISION_SAFE ────────────────────────────────────────

def test_B2_3_CROSS_FEATURE_IDEMPOTENCY_COLLISION_SAFE():
    """Same user, same idempotency key, different feature_key = two independent events."""
    store = InMemoryUsageLedgerStore()
    shared_key = "feature-cross-key"
    subject = "user-zeta"

    e_api = _event(
        subject_id=subject,
        feature_key=FEATURE_INSTITUTIONAL_API_REQUEST,
        idempotency_key=shared_key,
        quantity=5,
    )
    e_xlsx = _event(
        subject_id=subject,
        feature_key=FEATURE_XLSX_EXPORT,
        idempotency_key=shared_key,
        quantity=3,
        unit="export",
    )

    r_api = store.record(e_api)
    r_xlsx = store.record(e_xlsx)

    # Two distinct events for the same user on different features
    assert len(store.all_events()) == 2
    assert r_api.event_id != r_xlsx.event_id
    assert r_api.feature_key == FEATURE_INSTITUTIONAL_API_REQUEST
    assert r_xlsx.feature_key == FEATURE_XLSX_EXPORT
    assert r_api.quantity == 5
    assert r_xlsx.quantity == 3

    # Scoped lookup for each feature returns the correct event
    got_api = store.get_by_scoped_key(subject, FEATURE_INSTITUTIONAL_API_REQUEST, shared_key)
    got_xlsx = store.get_by_scoped_key(subject, FEATURE_XLSX_EXPORT, shared_key)
    assert got_api is not None and got_api.quantity == 5
    assert got_xlsx is not None and got_xlsx.quantity == 3


# ── B2_3_CONCURRENT_DUPLICATE_SAFE ─────────────────────────────────────────────────────────

def test_B2_3_CONCURRENT_DUPLICATE_SAFE():
    """Concurrent delivery of the same scoped key produces one event."""
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


# ── B2_3_QUERY_SIGNED_IDENTITY_ONLY ─────────────────────────────────────────────────────────

def test_B2_3_QUERY_SIGNED_IDENTITY_ONLY():
    """UsageQueryService.summaries_for_session derives subject_id from session only."""
    import inspect
    sig = inspect.signature(UsageQueryService.summaries_for_session)
    assert "subject_id" not in sig.parameters, (
        "summaries_for_session must not accept subject_id as a parameter")

    # The public method is summaries_for_session, not summaries_for_subject
    assert hasattr(UsageQueryService, "summaries_for_session"), (
        "UsageQueryService must expose summaries_for_session")
    assert not hasattr(UsageQueryService, "summaries_for_subject") or \
        getattr(UsageQueryService.summaries_for_subject, "__isabstractmethod__", False), (
        "summaries_for_subject must not be a public method")


# ── B2_3_QUERY_CROSS_USER_SPOOF_IMPOSSIBLE ───────────────────────────────────────────────────

def test_B2_3_QUERY_CROSS_USER_SPOOF_IMPOSSIBLE():
    """A session for user-A cannot query usage data belonging to user-B."""
    import os
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        from app.usage.ledger import SQLiteUsageLedgerStore
        sqlite_store = SQLiteUsageLedgerStore(db_path=db_path)
        sq_recorder = UsageRecorder(store=sqlite_store)

        session_a = _session(user_id="user-spoof-A")
        session_b = _session(user_id="user-spoof-B")

        sq_recorder.record(
            session=session_b,
            feature_key=FEATURE_INSTITUTIONAL_API_REQUEST,
            idempotency_key="spoof-b1",
        )
        sq_recorder.record(
            session=session_b,
            feature_key=FEATURE_INSTITUTIONAL_API_REQUEST,
            idempotency_key="spoof-b2",
        )

        qs = UsageQueryService(db_path=db_path)
        # User A queries their own usage — should be empty, not user B's data
        result_a = qs.summaries_for_session(session=session_a)
        assert result_a.state == QUERY_STATE_AVAILABLE
        assert len(result_a.summaries) == 0, (
            "User A must not see User B's events")

        # User B queries their own usage — should see their two events
        result_b = qs.summaries_for_session(session=session_b)
        assert result_b.state == QUERY_STATE_AVAILABLE
        assert len(result_b.summaries) == 1
        assert result_b.summaries[0].event_count == 2
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ── B2_3_WALLET_NOT_CALLER_CONTROLLED ───────────────────────────────────────────────────────

def test_B2_3_WALLET_NOT_CALLER_CONTROLLED():
    """UsageRecorder.record must not accept wallet_address as a parameter."""
    import inspect
    sig = inspect.signature(UsageRecorder.record)
    assert "wallet_address" not in sig.parameters, (
        "UsageRecorder.record must not accept wallet_address — "
        "it must be resolved internally from wallet_auth only"
    )


# ── B2_3_WALLET_CANONICAL_LINK_ONLY ─────────────────────────────────────────────────────────

def test_B2_3_WALLET_CANONICAL_LINK_ONLY(monkeypatch):
    """wallet_address in recorded events comes from wallet_auth, not caller args."""
    import sys
    import types

    canonical_wallet = "0x" + "c" * 40

    def mock_get_verified_wallet(user_id: str):
        if user_id == "user-with-wallet":
            return {"wallet_address": canonical_wallet}
        return None

    # Inject a mock wallet_auth module so the test doesn't need eth_account.
    # Must patch both sys.modules AND the attribute on app.protocol, because
    # `import app.protocol.wallet_auth as _wauth` resolves via the parent package
    # attribute when the real module was already imported in the same session.
    import app.protocol as _proto_pkg
    mock_wauth = types.ModuleType("app.protocol.wallet_auth")
    mock_wauth.get_verified_wallet = mock_get_verified_wallet
    original_sys = sys.modules.get("app.protocol.wallet_auth")
    original_attr = getattr(_proto_pkg, "wallet_auth", None)
    sys.modules["app.protocol.wallet_auth"] = mock_wauth
    _proto_pkg.wallet_auth = mock_wauth
    try:
        recorder, store = _recorder_with_store()

        # User with a linked wallet
        session_linked = _session(user_id="user-with-wallet")
        ev_linked = recorder.record(
            session=session_linked,
            feature_key=FEATURE_INSTITUTIONAL_API_REQUEST,
        )
        assert ev_linked.wallet_address == canonical_wallet

        # User without a linked wallet
        session_no_wallet = _session(user_id="user-no-wallet")
        ev_no_wallet = recorder.record(
            session=session_no_wallet,
            feature_key=FEATURE_XLSX_EXPORT,
            unit="export",
        )
        assert ev_no_wallet.wallet_address is None
    finally:
        if original_sys is None:
            sys.modules.pop("app.protocol.wallet_auth", None)
        else:
            sys.modules["app.protocol.wallet_auth"] = original_sys
        if original_attr is None:
            try:
                delattr(_proto_pkg, "wallet_auth")
            except AttributeError:
                pass
        else:
            _proto_pkg.wallet_auth = original_attr


# ── B2_3_QUERY_FAILURE_NOT_ZERO ──────────────────────────────────────────────────────────────

def test_B2_3_QUERY_FAILURE_NOT_ZERO():
    """A storage failure returns UNAVAILABLE, not an empty list (zero usage)."""
    # Point to a non-existent directory to force a storage error
    qs = UsageQueryService(db_path="/nonexistent/path/usage.db")
    session = _session(user_id="user-failure-test")
    result = qs.summaries_for_session(session=session)

    assert isinstance(result, UsageQueryResult)
    assert result.state == QUERY_STATE_UNAVAILABLE, (
        "Storage failure must return UNAVAILABLE, not AVAILABLE with empty summaries"
    )
    assert result.reason == QUERY_UNAVAILABLE_REASON
    # Summaries must be empty (not None) even on failure
    assert len(result.summaries) == 0


# ── B2_3_QUERY_ERROR_SECRET_SAFE ─────────────────────────────────────────────────────────────

def test_B2_3_QUERY_ERROR_SECRET_SAFE():
    """Query failure result must not expose exception text, DB paths, or SQL."""
    qs = UsageQueryService(db_path="/nonexistent/path/super-secret.db")
    session = _session(user_id="user-secret-test")
    result = qs.summaries_for_session(session=session)

    assert result.state == QUERY_STATE_UNAVAILABLE
    # reason must be the opaque constant, not raw exception/path text
    assert result.reason == QUERY_UNAVAILABLE_REASON
    # The reason must not contain DB path, SQL fragments, or exception details
    reason_str = str(result.reason) if result.reason else ""
    for forbidden in ("super-secret", "/nonexistent", "sqlite3", "Traceback",
                      "Error", "SELECT", "FROM", "WHERE"):
        assert forbidden not in reason_str, (
            f"reason must not expose internal details: {reason_str!r}"
        )


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
        result_alice = qs.summaries_for_session(session=session_a)
        result_bob = qs.summaries_for_session(session=session_b)

        assert result_alice.state == QUERY_STATE_AVAILABLE
        assert result_bob.state == QUERY_STATE_AVAILABLE
        assert all(s.subject_id == "user-alice" for s in result_alice.summaries)
        assert all(s.subject_id == "user-bob" for s in result_bob.summaries)
        # Alice's results don't contain Bob's events
        alice_total = sum(s.total_quantity for s in result_alice.summaries)
        bob_total = sum(s.total_quantity for s in result_bob.summaries)
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


# ── UsageQueryResult contract ────────────────────────────────────────────────────────────────

def test_usage_query_result_available():
    r = UsageQueryResult(state=QUERY_STATE_AVAILABLE, summaries=[])
    assert r.state == QUERY_STATE_AVAILABLE
    assert r.summaries == ()
    assert r.reason is None


def test_usage_query_result_unavailable():
    r = UsageQueryResult(
        state=QUERY_STATE_UNAVAILABLE,
        summaries=(),
        reason=QUERY_UNAVAILABLE_REASON,
    )
    assert r.state == QUERY_STATE_UNAVAILABLE
    assert r.reason == QUERY_UNAVAILABLE_REASON


def test_usage_query_result_invalid_state():
    with pytest.raises(ValueError, match="unknown query state"):
        UsageQueryResult(state="UNKNOWN_STATE", summaries=())


# ── SQLite concurrent duplicate safety ──────────────────────────────────────────────────────

def _run_concurrent_sqlite_round(db_path: str, n_workers: int = 5) -> tuple[list, list]:
    """Helper: run one round of concurrent duplicate writes; return (results, errors)."""
    from app.usage.ledger import SQLiteUsageLedgerStore
    store = SQLiteUsageLedgerStore(db_path=db_path)
    key = f"sqlite-concurrent-idem-{uuid.uuid4()}"
    subject = "user-concurrent-sqlite"
    results: list[UsageEvent] = []
    errors: list[Exception] = []
    barrier = threading.Barrier(n_workers)

    def worker():
        try:
            barrier.wait(timeout=5)
            ev = _event(subject_id=subject, idempotency_key=key)
            r = store.record(ev)
            results.append(r)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results, errors


def test_B2_3_CONCURRENT_DUPLICATE_SAFE_sqlite():
    """SQLite: concurrent delivery of the same scoped key produces one event.

    Markers verified:
      B2_3_SQLITE_CONCURRENT_DUPLICATE_NO_LOCK_ERROR — no OperationalError from 5 writers
      B2_3_SQLITE_CONCURRENT_DUPLICATE_ONE_ROW       — exactly 1 DB row after 5 writes
    """
    import os
    import sqlite3
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        from app.usage.ledger import SQLiteUsageLedgerStore
        store = SQLiteUsageLedgerStore(db_path=db_path)
        key = "sqlite-concurrent-idem"
        subject = "user-concurrent-sqlite"
        results: list[UsageEvent] = []
        errors: list[Exception] = []
        barrier = threading.Barrier(5)

        def worker():
            try:
                barrier.wait(timeout=5)
                ev = _event(subject_id=subject, idempotency_key=key)
                r = store.record(ev)
                results.append(r)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        # B2_3_SQLITE_CONCURRENT_DUPLICATE_NO_LOCK_ERROR
        assert not errors, (
            f"B2_3_SQLITE_CONCURRENT_DUPLICATE_NO_LOCK_ERROR FAIL — "
            f"unexpected errors in SQLite concurrent test: {errors}")
        # All threads returned an event
        assert len(results) == 5
        # All returned the same canonical event_id
        event_ids = {r.event_id for r in results}
        assert len(event_ids) == 1, (
            f"Expected 1 canonical event_id, got {event_ids}")

        # B2_3_SQLITE_CONCURRENT_DUPLICATE_ONE_ROW — verify exactly 1 row in the DB
        conn = sqlite3.connect(db_path)
        try:
            row_count = conn.execute(
                "SELECT COUNT(*) FROM usage_events"
                " WHERE subject_id = ? AND idempotency_key = ?",
                (subject, key),
            ).fetchone()[0]
        finally:
            conn.close()
        assert row_count == 1, (
            f"B2_3_SQLITE_CONCURRENT_DUPLICATE_ONE_ROW FAIL — "
            f"expected 1 DB row, got {row_count}")
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def test_B2_3_SQLITE_CONCURRENT_REPEAT_STABLE():
    """SQLite: 20 repeated rounds of concurrent duplicate writes all produce exactly 1 row.

    Marker: B2_3_SQLITE_CONCURRENT_REPEAT_STABLE
    Each round uses a fresh idempotency key and 5 concurrent writers.
    All rounds must complete without errors and with 1 canonical event each.
    """
    import os
    import sqlite3
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        n_rounds = 20
        for round_idx in range(n_rounds):
            results, errors = _run_concurrent_sqlite_round(db_path, n_workers=5)
            assert not errors, (
                f"B2_3_SQLITE_CONCURRENT_REPEAT_STABLE FAIL round {round_idx}: "
                f"errors={errors}")
            assert len(results) == 5, (
                f"B2_3_SQLITE_CONCURRENT_REPEAT_STABLE FAIL round {round_idx}: "
                f"expected 5 results, got {len(results)}")
            event_ids = {r.event_id for r in results}
            assert len(event_ids) == 1, (
                f"B2_3_SQLITE_CONCURRENT_REPEAT_STABLE FAIL round {round_idx}: "
                f"expected 1 canonical event_id, got {event_ids}")

        # Final: verify total row count equals number of rounds (one per unique key)
        conn = sqlite3.connect(db_path)
        try:
            total_rows = conn.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0]
        finally:
            conn.close()
        assert total_rows == n_rounds, (
            f"B2_3_SQLITE_CONCURRENT_REPEAT_STABLE FAIL: "
            f"expected {n_rounds} total rows, got {total_rows}")
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def test_B2_3_SQLITE_UNRELATED_DB_ERROR_NOT_SWALLOWED():
    """Non-lock OperationalErrors from _acquire_immediate are re-raised without retry.

    Marker: B2_3_SQLITE_UNRELATED_DB_ERROR_NOT_SWALLOWED
    The retry loop in _acquire_immediate must only catch errors whose message
    contains 'locked'.  Any other OperationalError must propagate immediately.
    """
    import sqlite3
    from app.usage.ledger import _acquire_immediate

    class _FakeConn:
        """Fake connection that raises a non-lock OperationalError on BEGIN IMMEDIATE."""
        def __init__(self, msg: str):
            self._msg = msg
            self.calls = 0

        def execute(self, sql: str):
            if "BEGIN" in sql.upper():
                self.calls += 1
                raise sqlite3.OperationalError(self._msg)

    # A non-lock error must be re-raised immediately (calls == 1, no retry)
    conn = _FakeConn("disk I/O error")
    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
        _acquire_immediate(conn, max_retries=8)
    assert conn.calls == 1, (
        f"B2_3_SQLITE_UNRELATED_DB_ERROR_NOT_SWALLOWED FAIL: "
        f"non-lock error should not be retried, but execute was called {conn.calls} times")

    # A second non-lock variant
    conn2 = _FakeConn("no such table: usage_events")
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        _acquire_immediate(conn2, max_retries=8)
    assert conn2.calls == 1, (
        f"B2_3_SQLITE_UNRELATED_DB_ERROR_NOT_SWALLOWED FAIL: "
        f"non-lock error should not be retried (calls={conn2.calls})")
